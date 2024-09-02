sudo truncate -s 0 /var/log/pods/airflow_airflow-scheduler-*_*/scheduler/0.log

log_dir=./benchmark/"$(date +%s)"
mkdir -p "$log_dir"
kubectl port-forward svc/airflow-webserver 8080:8080 --namespace airflow 1>/dev/null 2>&1 &

for i in $(seq 1 10)
do
    python ./workflow-gateway/main.py
    sleep 100
done

scheduler="$(kubectl -n airflow get pods | grep scheduler | awk '{print $1}')"
kubectl -n airflow logs "$scheduler" scheduler | grep TIMING > "$log_dir"/log_timing.log
kubectl -n airflow logs "$scheduler" scheduler | grep WHC > "$log_dir"/log_whc.log
kubectl -n airflow logs "$scheduler" scheduler | grep WHCIMP > "$log_dir"/log_whcimp.log
kubectl -n airflow logs "$scheduler" scheduler > "$log_dir"/log_scheduler.log

cat "$log_dir"/log_whcimp.log | python scripts/2_process_end2end_latency.py