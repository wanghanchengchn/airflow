REPETITION=$1
DAG_NAME=$2
SLEEP_TIME=$3
DAG_D=$4

LINES_PER_GROUP=$((2 + 4 * DAG_D))

################################################################################################################
sudo truncate -s 0 /var/log/pods/airflow_airflow-scheduler-*_*/scheduler/0.log

for func in $(seq 1 $DAG_D)
do
    sudo truncate -s 0 /var/log/pods/airflow_airflow-worker-dag-w1-d${DAG_D}-func-1-${func}-00001-*_*/user-container/0.log
done

################################################################################################################

log_dir=./benchmark/"$(date +%s)"
mkdir -p "$log_dir"
kubectl port-forward svc/airflow-webserver 8080:8080 --namespace airflow 1>/dev/null 2>&1 &

for i in $(seq 1 $REPETITION)
do
    python ./workflow-gateway/main.py "$DAG_NAME"
    sleep $SLEEP_TIME
done

scheduler="$(kubectl -n airflow get pods | grep scheduler | awk '{print $1}')"

kubectl -n airflow logs "$scheduler" scheduler | grep WHC_E2E_LATENCY > "$log_dir"/log_whc_e2e_latency.log
kubectl -n airflow logs "$scheduler" scheduler > "$log_dir"/log_scheduler.log

cat "$log_dir"/log_scheduler.log | grep "WHCIMP: TIMING:" > "$log_dir"/log_whc_timing.log


################################################################################################################


worker_logs=""

for i in $(seq 1 $DAG_D)
do
    worker="$(kubectl -n airflow get pods | grep worker-dag-w1-d${DAG_D}- | awk '{print $1}' | sed -n "${i}p")"
    kubectl -n airflow logs "$worker" user-container | sed -r "s/\x1B\[([0-9]{1,3}(;[0-9]{1,3})*)?[mGK]//g" > "$log_dir"/log_worker${i}.log
    worker_logs+=" $log_dir/log_worker${i}.log"
done

echo $worker_logs

python scripts/10_merge_logs.py "$log_dir"/log_scheduler.log $worker_logs -o "$log_dir"/merged_output.log

################################################################################################################


echo " "
echo "7_process_e2e_latency"
cat "$log_dir"/log_whc_e2e_latency.log | python scripts/7_process_e2e_latency.py $REPETITION 2         # 有几组？每组有2行

echo " "
echo "9_process_e2e_breakdown.py"
grep WHC_E2E_BREAKDOWN "$log_dir"/merged_output.log > "$log_dir"/log_whc_e2e_breakdown.log
cat "$log_dir"/log_whc_e2e_breakdown.log | python scripts/9_process_e2e_breakdown.py $REPETITION $LINES_PER_GROUP  # 有几组？每组有2 + 4 * d行