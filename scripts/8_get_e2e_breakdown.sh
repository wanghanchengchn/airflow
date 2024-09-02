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

# if [ "$DAG_NAME" = "dag_w1_d1" ]
# then
#     worker1="$(kubectl -n airflow get pods | grep worker-dag-w1-d1- | awk '{print $1}' | head -n 1)"
#     kubectl -n airflow logs "$worker1" user-container | sed -r "s/\x1B\[([0-9]{1,3}(;[0-9]{1,3})*)?[mGK]//g" > "$log_dir"/log_worker1.log
#     python scripts/10_merge_logs.py "$log_dir"/log_scheduler.log "$log_dir"/log_worker1.log -o "$log_dir"/merged_output.log
# fi

# if [ "$DAG_NAME" = "dag_w1_d2" ]
# then
#     worker1="$(kubectl -n airflow get pods | grep worker-dag-w1-d2- | awk '{print $1}' | head -n 1)"
#     worker2="$(kubectl -n airflow get pods | grep worker-dag-w1-d2- | awk '{print $1}' | sed -n '2p')"
#     kubectl -n airflow logs "$worker1" user-container | sed -r "s/\x1B\[([0-9]{1,3}(;[0-9]{1,3})*)?[mGK]//g" > "$log_dir"/log_worker1.log
#     kubectl -n airflow logs "$worker2" user-container | sed -r "s/\x1B\[([0-9]{1,3}(;[0-9]{1,3})*)?[mGK]//g" > "$log_dir"/log_worker2.log
#     python scripts/10_merge_logs.py "$log_dir"/log_scheduler.log "$log_dir"/log_worker1.log "$log_dir"/log_worker2.log -o "$log_dir"/merged_output.log
# fi

# if [ "$DAG_NAME" = "dag_w1_d4" ]
# then
#     worker1="$(kubectl -n airflow get pods | grep worker-dag-w1-d4- | awk '{print $1}' | head -n 1)"
#     worker2="$(kubectl -n airflow get pods | grep worker-dag-w1-d4- | awk '{print $1}' | sed -n '2p')"
#     worker3="$(kubectl -n airflow get pods | grep worker-dag-w1-d4- | awk '{print $1}' | sed -n '3p')"
#     worker4="$(kubectl -n airflow get pods | grep worker-dag-w1-d4- | awk '{print $1}' | sed -n '4p')"
#     kubectl -n airflow logs "$worker1" user-container | sed -r "s/\x1B\[([0-9]{1,3}(;[0-9]{1,3})*)?[mGK]//g" > "$log_dir"/log_worker1.log
#     kubectl -n airflow logs "$worker2" user-container | sed -r "s/\x1B\[([0-9]{1,3}(;[0-9]{1,3})*)?[mGK]//g" > "$log_dir"/log_worker2.log
#     kubectl -n airflow logs "$worker3" user-container | sed -r "s/\x1B\[([0-9]{1,3}(;[0-9]{1,3})*)?[mGK]//g" > "$log_dir"/log_worker3.log
#     kubectl -n airflow logs "$worker4" user-container | sed -r "s/\x1B\[([0-9]{1,3}(;[0-9]{1,3})*)?[mGK]//g" > "$log_dir"/log_worker4.log
#     python scripts/10_merge_logs.py "$log_dir"/log_scheduler.log "$log_dir"/log_worker1.log "$log_dir"/log_worker2.log "$log_dir"/log_worker3.log "$log_dir"/log_worker4.log -o "$log_dir"/merged_output.log
# fi

# if [ "$DAG_NAME" = "dag_w1_d8" ]
# then
#     worker1="$(kubectl -n airflow get pods | grep worker-dag-w1-d8- | awk '{print $1}' | head -n 1)"
#     worker2="$(kubectl -n airflow get pods | grep worker-dag-w1-d8- | awk '{print $1}' | sed -n '2p')"
#     worker3="$(kubectl -n airflow get pods | grep worker-dag-w1-d8- | awk '{print $1}' | sed -n '3p')"
#     worker4="$(kubectl -n airflow get pods | grep worker-dag-w1-d8- | awk '{print $1}' | sed -n '4p')"
#     worker5="$(kubectl -n airflow get pods | grep worker-dag-w1-d8- | awk '{print $1}' | sed -n '5p')"
#     worker6="$(kubectl -n airflow get pods | grep worker-dag-w1-d8- | awk '{print $1}' | sed -n '6p')"
#     worker7="$(kubectl -n airflow get pods | grep worker-dag-w1-d8- | awk '{print $1}' | sed -n '7p')"
#     worker8="$(kubectl -n airflow get pods | grep worker-dag-w1-d8- | awk '{print $1}' | sed -n '8p')"
#     kubectl -n airflow logs "$worker1" user-container | sed -r "s/\x1B\[([0-9]{1,3}(;[0-9]{1,3})*)?[mGK]//g" > "$log_dir"/log_worker1.log
#     kubectl -n airflow logs "$worker2" user-container | sed -r "s/\x1B\[([0-9]{1,3}(;[0-9]{1,3})*)?[mGK]//g" > "$log_dir"/log_worker2.log
#     kubectl -n airflow logs "$worker3" user-container | sed -r "s/\x1B\[([0-9]{1,3}(;[0-9]{1,3})*)?[mGK]//g" > "$log_dir"/log_worker3.log
#     kubectl -n airflow logs "$worker4" user-container | sed -r "s/\x1B\[([0-9]{1,3}(;[0-9]{1,3})*)?[mGK]//g" > "$log_dir"/log_worker4.log
#     kubectl -n airflow logs "$worker5" user-container | sed -r "s/\x1B\[([0-9]{1,3}(;[0-9]{1,3})*)?[mGK]//g" > "$log_dir"/log_worker5.log
#     kubectl -n airflow logs "$worker6" user-container | sed -r "s/\x1B\[([0-9]{1,3}(;[0-9]{1,3})*)?[mGK]//g" > "$log_dir"/log_worker6.log
#     kubectl -n airflow logs "$worker7" user-container | sed -r "s/\x1B\[([0-9]{1,3}(;[0-9]{1,3})*)?[mGK]//g" > "$log_dir"/log_worker7.log
#     kubectl -n airflow logs "$worker8" user-container | sed -r "s/\x1B\[([0-9]{1,3}(;[0-9]{1,3})*)?[mGK]//g" > "$log_dir"/log_worker8.log
#     python scripts/10_merge_logs.py "$log_dir"/log_scheduler.log "$log_dir"/log_worker1.log "$log_dir"/log_worker2.log "$log_dir"/log_worker3.log "$log_dir"/log_worker4.log "$log_dir"/log_worker5.log "$log_dir"/log_worker6.log "$log_dir"/log_worker7.log "$log_dir"/log_worker8.log -o "$log_dir"/merged_output.log
# fi

# if [ "$DAG_NAME" = "dag_w1_d16" ]
# then 
#     worker1="$(kubectl -n airflow get pods | grep worker-dag-w1-d16- | awk '{print $1}' | head -n 1)"
#     worker2="$(kubectl -n airflow get pods | grep worker-dag-w1-d16- | awk '{print $1}' | sed -n '2p')"
#     worker3="$(kubectl -n airflow get pods | grep worker-dag-w1-d16- | awk '{print $1}' | sed -n '3p')"
#     worker4="$(kubectl -n airflow get pods | grep worker-dag-w1-d16- | awk '{print $1}' | sed -n '4p')"
#     worker5="$(kubectl -n airflow get pods | grep worker-dag-w1-d16- | awk '{print $1}' | sed -n '5p')"
#     worker6="$(kubectl -n airflow get pods | grep worker-dag-w1-d16- | awk '{print $1}' | sed -n '6p')"
#     worker7="$(kubectl -n airflow get pods | grep worker-dag-w1-d16- | awk '{print $1}' | sed -n '7p')"
#     worker8="$(kubectl -n airflow get pods | grep worker-dag-w1-d16- | awk '{print $1}' | sed -n '8p')"
#     worker9="$(kubectl -n airflow get pods | grep worker-dag-w1-d16- | awk '{print $1}' | sed -n '9p')"
#     worker10="$(kubectl -n airflow get pods | grep worker-dag-w1-d16- | awk '{print $1}' | sed -n '10p')"
#     worker11="$(kubectl -n airflow get pods | grep worker-dag-w1-d16- | awk '{print $1}' | sed -n '11p')"
#     worker12="$(kubectl -n airflow get pods | grep worker-dag-w1-d16- | awk '{print $1}' | sed -n '12p')"
#     worker13="$(kubectl -n airflow get pods | grep worker-dag-w1-d16- | awk '{print $1}' | sed -n '13p')"
#     worker14="$(kubectl -n airflow get pods | grep worker-dag-w1-d16- | awk '{print $1}' | sed -n '14p')"
#     worker15="$(kubectl -n airflow get pods | grep worker-dag-w1-d16- | awk '{print $1}' | sed -n '15p')"
#     worker16="$(kubectl -n airflow get pods | grep worker-dag-w1-d16- | awk '{print $1}' | sed -n '16p')"
#     kubectl -n airflow logs "$worker1" user-container | sed -r "s/\x1B\[([0-9]{1,3}(;[0-9]{1,3})*)?[mGK]//g" > "$log_dir"/log_worker1.log
#     kubectl -n airflow logs "$worker2" user-container | sed -r "s/\x1B\[([0-9]{1,3}(;[0-9]{1,3})*)?[mGK]//g" > "$log_dir"/log_worker2.log
#     kubectl -n airflow logs "$worker3" user-container | sed -r "s/\x1B\[([0-9]{1,3}(;[0-9]{1,3})*)?[mGK]//g" > "$log_dir"/log_worker3.log
#     kubectl -n airflow logs "$worker4" user-container | sed -r "s/\x1B\[([0-9]{1,3}(;[0-9]{1,3})*)?[mGK]//g" > "$log_dir"/log_worker4.log
#     kubectl -n airflow logs "$worker5" user-container | sed -r "s/\x1B\[([0-9]{1,3}(;[0-9]{1,3})*)?[mGK]//g" > "$log_dir"/log_worker5.log
#     kubectl -n airflow logs "$worker6" user-container | sed -r "s/\x1B\[([0-9]{1,3}(;[0-9]{1,3})*)?[mGK]//g" > "$log_dir"/log_worker6.log
#     kubectl -n airflow logs "$worker7" user-container | sed -r "s/\x1B\[([0-9]{1,3}(;[0-9]{1,3})*)?[mGK]//g" > "$log_dir"/log_worker7.log
#     kubectl -n airflow logs "$worker8" user-container | sed -r "s/\x1B\[([0-9]{1,3}(;[0-9]{1,3})*)?[mGK]//g" > "$log_dir"/log_worker8.log
#     kubectl -n airflow logs "$worker9" user-container | sed -r "s/\x1B\[([0-9]{1,3}(;[0-9]{1,3})*)?[mGK]//g" > "$log_dir"/log_worker9.log
#     kubectl -n airflow logs "$worker10" user-container | sed -r "s/\x1B\[([0-9]{1,3}(;[0-9]{1,3})*)?[mGK]//g" > "$log_dir"/log_worker10.log
#     kubectl -n airflow logs "$worker11" user-container | sed -r "s/\x1B\[([0-9]{1,3}(;[0-9]{1,3})*)?[mGK]//g" > "$log_dir"/log_worker11.log
#     kubectl -n airflow logs "$worker12" user-container | sed -r "s/\x1B\[([0-9]{1,3}(;[0-9]{1,3})*)?[mGK]//g" > "$log_dir"/log_worker12.log
#     kubectl -n airflow logs "$worker13" user-container | sed -r "s/\x1B\[([0-9]{1,3}(;[0-9]{1,3})*)?[mGK]//g" > "$log_dir"/log_worker13.log
#     kubectl -n airflow logs "$worker14" user-container | sed -r "s/\x1B\[([0-9]{1,3}(;[0-9]{1,3})*)?[mGK]//g" > "$log_dir"/log_worker14.log
#     kubectl -n airflow logs "$worker15" user-container | sed -r "s/\x1B\[([0-9]{1,3}(;[0-9]{1,3})*)?[mGK]//g" > "$log_dir"/log_worker15.log
#     kubectl -n airflow logs "$worker16" user-container | sed -r "s/\x1B\[([0-9]{1,3}(;[0-9]{1,3})*)?[mGK]//g" > "$log_dir"/log_worker16.log
#     python scripts/10_merge_logs.py "$log_dir"/log_scheduler.log "$log_dir"/log_worker1.log "$log_dir"/log_worker2.log "$log_dir"/log_worker3.log "$log_dir"/log_worker4.log "$log_dir"/log_worker5.log "$log_dir"/log_worker6.log "$log_dir"/log_worker7.log "$log_dir"/log_worker8.log "$log_dir"/log_worker9.log "$log_dir"/log_worker10.log "$log_dir"/log_worker11.log "$log_dir"/log_worker12.log "$log_dir"/log_worker13.log "$log_dir"/log_worker14.log "$log_dir"/log_worker15.log "$log_dir"/log_worker16.log -o "$log_dir"/merged_output.log
# fi

################################################################################################################


echo " "
echo "7_process_e2e_latency"
cat "$log_dir"/log_whc_e2e_latency.log | python scripts/7_process_e2e_latency.py $REPETITION 2         # 有几组？每组有2行

echo " "
echo "9_process_e2e_breakdown.py"
grep WHC_E2E_BREAKDOWN "$log_dir"/merged_output.log > "$log_dir"/log_whc_e2e_breakdown.log
cat "$log_dir"/log_whc_e2e_breakdown.log | python scripts/9_process_e2e_breakdown.py $REPETITION $LINES_PER_GROUP  # 有几组？每组有2 + 4 * d行