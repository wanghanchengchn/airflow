# remove k8s and helm environment set up by previous installation
if pgrep -xf "kubectl port-forward svc/airflow-webserver 8080:8080 --namespace airflow" > /dev/null; then
    pgrep -xf "kubectl port-forward svc/airflow-webserver 8080:8080 --namespace airflow" | xargs kill -9
    echo "Airflow Webserver portforwarding cleared"
fi
echo "Cleaning up Airflow"
helm uninstall -n airflow airflow
kn service delete --all -n airflow
kubectl delete namespace airflow
kubectl delete -f configs/volumes.yaml
sudo rm -rf /mnt/data*/*

# update knative yamls, rebuild worker image and deploy airflow using helm
echo "Setting up Airflow"
./scripts/build_knative_yamls.sh
./scripts/setup_airflow.sh

echo "Deploying dag_w1_d1"
./scripts/deploy_workflow.sh dag_w1_d1

echo "Deploying dag_w1_d2"
./scripts/deploy_workflow.sh dag_w1_d2

echo "Deploying dag_w1_d4"
./scripts/deploy_workflow.sh dag_w1_d4

echo "Deploying dag_w1_d8"
./scripts/deploy_workflow.sh dag_w1_d8

echo "Deploying dag_w1_d16"
./scripts/deploy_workflow.sh dag_w1_d16

echo "Deploying dag_w1_d32"
./scripts/deploy_workflow.sh dag_w1_d32