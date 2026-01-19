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

# echo "Deploying dag_w1_d4"
# ./scripts/deploy_workflow.sh dag_w1_d4

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

# echo "Deploying dag_w64_d3"
# ./scripts/deploy_workflow.sh dag_w64_d3

# echo "Deploying dag_w128_d3"
# ./scripts/deploy_workflow.sh dag_w128_d3

echo "Deploying dag_w256_d3"
./scripts/deploy_workflow.sh dag_w256_d3

# echo "Deploying dag_w512_d3"
# ./scripts/deploy_workflow.sh dag_w512_d3

# echo "Deploying dag_w1024_d3"
# ./scripts/deploy_workflow.sh dag_w1024_d3

# echo "Deploying dag_w2048_d3"
# ./scripts/deploy_workflow.sh dag_w2048_d3

# echo "Deploying dag_w4096_d3"
# ./scripts/deploy_workflow.sh dag_w4096_d3


# ./scripts/8_get_e2e_breakdown.sh 1 "dag_w32_d3" 40 34
# ./scripts/8_get_e2e_breakdown.sh 1 "dag_w64_d3" 40 66
# ./scripts/8_get_e2e_breakdown.sh 1 "dag_w128_d3" 40 130
# ./scripts/8_get_e2e_breakdown.sh 1 "dag_w256_d3" 40 258
# ./scripts/8_get_e2e_breakdown.sh 1 "dag_w512_d3" 40 514
# ./scripts/8_get_e2e_breakdown.sh 1 "dag_w1024_d3" 40 1026
# ./scripts/8_get_e2e_breakdown.sh 1 "dag_w2048_d3" 40 2050
# ./scripts/8_get_e2e_breakdown.sh 1 "dag_w4096_d3" 40 4098
