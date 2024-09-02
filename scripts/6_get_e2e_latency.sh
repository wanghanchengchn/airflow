REPETITION=2
DAG_NAME="dag_w1_d2"

sudo truncate -s 0 /var/log/pods/airflow_airflow-scheduler-*_*/scheduler/0.log

log_dir=./benchmark/"$(date +%s)"
mkdir -p "$log_dir"
kubectl port-forward svc/airflow-webserver 8080:8080 --namespace airflow 1>/dev/null 2>&1 &

for i in $(seq 1 $REPETITION)
do
    python ./workflow-gateway/main.py "$DAG_NAME"
    sleep 10
done

scheduler="$(kubectl -n airflow get pods | grep scheduler | awk '{print $1}')"

kubectl -n airflow logs "$scheduler" scheduler | grep WHC_E2E_LATENCY > "$log_dir"/log_whc_e2e_latency.log
kubectl -n airflow logs "$scheduler" scheduler | grep TIMING > "$log_dir"/log_timing.log
kubectl -n airflow logs "$scheduler" scheduler > "$log_dir"/log_scheduler.log

echo " "
echo "7_process_e2e_latency"
cat "$log_dir"/log_whc_e2e_latency.log | python scripts/7_process_e2e_latency.py $REPETITION 2      # 有几组？每组有2行