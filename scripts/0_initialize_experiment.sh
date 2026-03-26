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

# echo "Deploying dag_w1_d17"
# ./scripts/deploy_workflow.sh dag_w1_d17

# echo "Deploying dag_w1_d5"
# ./scripts/deploy_workflow.sh dag_w1_d5

# echo "Deploying dag_w1_d7"
# ./scripts/deploy_workflow.sh dag_w1_d7

# echo "Deploying dag_w1_d10"
# ./scripts/deploy_workflow.sh dag_w1_d10

# echo "Deploying dag_w1_d2"
# ./scripts/deploy_workflow.sh dag_w1_d2

echo "Deploying dag_w1_d4"
./scripts/deploy_workflow.sh dag_w1_d4

# echo "Deploying dag_w1_d8"
# ./scripts/deploy_workflow.sh dag_w1_d8

# echo "Deploying dag_w1_d16"
# ./scripts/deploy_workflow.sh dag_w1_d16

# echo "Deploying dag_w1_d32"
# ./scripts/deploy_workflow.sh dag_w1_d32

# echo "Deploying dag_w1_d3"
# ./scripts/deploy_workflow.sh dag_w1_d3

# echo "Deploying dag_w2_d3"
# ./scripts/deploy_workflow.sh dag_w2_d3

# echo "Deploying dag_w4_d3"
# ./scripts/deploy_workflow.sh dag_w4_d3

# echo "Deploying dag_w8_d3"
# ./scripts/deploy_workflow.sh dag_w8_d3

# echo "Deploying dag_w16_d3"
# ./scripts/deploy_workflow.sh dag_w16_d3

# echo "Deploying dag_w32_d3"
# ./scripts/deploy_workflow.sh dag_w32_d3


# ./scripts/8_get_e2e_breakdown.sh 1 "dag_w32_d3" 40 34
