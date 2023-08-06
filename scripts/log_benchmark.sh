if pgrep -xf "kubectl port-forward svc/airflow-webserver 8080:8080 --namespace airflow" > /dev/null; then
    pgrep -xf "kubectl port-forward svc/airflow-webserver 8080:8080 --namespace airflow" | xargs kill -9
    echo "Airflow Webserver portforwarding cleared"
fi
helm uninstall -n airflow airflow
kn service delete --all -n airflow
kubectl delete namespace airflow
kubectl delete -f configs/volumes.yaml
sudo rm -rf /mnt/data*/*

./scripts/build_knative_yamls.sh
./scripts/update_images.sh
./scripts/setup_airflow.sh

# Get Logs
log_dir=./benchmark/"$(date +%s)"
mkdir -p "$log_dir"
kubectl port-forward svc/airflow-webserver 8080:8080 --namespace airflow 2>&1 >/dev/null &
sleep 3
python ./workflow-gateway/main.py
sleep 3
scheduler="$(kubectl -n airflow get pods | grep scheduler | awk '{print $1}')"
kubectl -n airflow logs "$scheduler" scheduler | grep TIMING > "$log_dir"/log_timing.log
kubectl -n airflow logs "$scheduler" scheduler > "$log_dir"/log_scheduler.log
producer="$(kubectl -n airflow get pods | grep get-date | awk '{print $1}')"
kubectl -n airflow logs "$producer" user-container > "$log_dir"/log_producer.log
consumer="$(kubectl -n airflow get pods | grep save-date | awk '{print $1}')"
kubectl -n airflow logs "$consumer" user-container > "$log_dir"/log_consumer.log