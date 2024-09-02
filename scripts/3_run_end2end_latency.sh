sudo truncate -s 0 /var/log/pods/airflow_airflow-scheduler-*_*/scheduler/0.log
sudo truncate -s 0 /var/log/pods/airflow_airflow-worker-dag-w1-d2-func-1-1-00001-*_*/user-container/0.log
sudo truncate -s 0 /var/log/pods/airflow_airflow-worker-dag-w1-d2-func-1-2-00001-*_*/user-container/0.log

# sudo truncate -s 0 /var/log/pods/airflow_airflow-worker-dag-w1-d4-func-1-1-00001-*_*/user-container/0.log
# sudo truncate -s 0 /var/log/pods/airflow_airflow-worker-dag-w1-d4-func-1-2-00001-*_*/user-container/0.log
# sudo truncate -s 0 /var/log/pods/airflow_airflow-worker-dag-w1-d4-func-1-3-00001-*_*/user-container/0.log
# sudo truncate -s 0 /var/log/pods/airflow_airflow-worker-dag-w1-d4-func-1-4-00001-*_*/user-container/0.log

log_dir=./benchmark/"$(date +%s)"
mkdir -p "$log_dir"
kubectl port-forward svc/airflow-webserver 8080:8080 --namespace airflow 1>/dev/null 2>&1 &

for i in $(seq 1 1)
do
    python ./workflow-gateway/main.py "dag_w1_d2"
    sleep 30
done

scheduler="$(kubectl -n airflow get pods | grep scheduler | awk '{print $1}')"
worker1="$(kubectl -n airflow get pods | grep worker-dag-w1-d2- | awk '{print $1}' | head -n 1)"
worker2="$(kubectl -n airflow get pods | grep worker-dag-w1-d2- | awk '{print $1}' | sed -n '2p')"

# worker1="$(kubectl -n airflow get pods | grep worker-dag-w1-d4- | awk '{print $1}' | head -n 1)"
# worker2="$(kubectl -n airflow get pods | grep worker-dag-w1-d4- | awk '{print $1}' | sed -n '2p')"
# worker3="$(kubectl -n airflow get pods | grep worker-dag-w1-d4- | awk '{print $1}' | sed -n '3p')"
# worker4="$(kubectl -n airflow get pods | grep worker-dag-w1-d4- | awk '{print $1}' | sed -n '4p')"

kubectl -n airflow logs "$scheduler" scheduler | grep TIMING > "$log_dir"/log_timing.log
kubectl -n airflow logs "$scheduler" scheduler | grep WHC > "$log_dir"/log_whc.log
kubectl -n airflow logs "$scheduler" scheduler | grep WHCIMP > "$log_dir"/log_whcimp.log
kubectl -n airflow logs "$scheduler" scheduler > "$log_dir"/log_scheduler.log

kubectl -n airflow logs "$worker1" user-container | sed -r "s/\x1B\[([0-9]{1,3}(;[0-9]{1,3})*)?[mGK]//g" > "$log_dir"/log_worker1.log
kubectl -n airflow logs "$worker2" user-container | sed -r "s/\x1B\[([0-9]{1,3}(;[0-9]{1,3})*)?[mGK]//g" > "$log_dir"/log_worker2.log
# kubectl -n airflow logs "$worker3" user-container | sed -r "s/\x1B\[([0-9]{1,3}(;[0-9]{1,3})*)?[mGK]//g" > "$log_dir"/log_worker3.log
# kubectl -n airflow logs "$worker4" user-container | sed -r "s/\x1B\[([0-9]{1,3}(;[0-9]{1,3})*)?[mGK]//g" > "$log_dir"/log_worker4.log

echo " "
echo "4_process_end2end_latency"
cat "$log_dir"/log_whcimp.log | python scripts/4_process_end2end_latency.py 1 5

echo " "
echo "5_process_task_duration_get_min"
cat "$log_dir"/log_timing.log | python scripts/5_process_task_duration.py 1 4 1

echo " "
echo "5_process_task_duration"
cat "$log_dir"/log_timing.log | python scripts/5_process_task_duration.py 1 4 0