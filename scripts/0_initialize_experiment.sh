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

# echo "Deploying dag_w1_d5"
# ./scripts/deploy_workflow.sh dag_w1_d5

# echo "Deploying dag_w1_d7"
# ./scripts/deploy_workflow.sh dag_w1_d7

# echo "Deploying dag_w1_d10"
# ./scripts/deploy_workflow.sh dag_w1_d10

# echo "Deploying dag_w1_d17"
# ./scripts/deploy_workflow.sh dag_w1_d17

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

# echo "Deploying dag_w256_d3"
# ./scripts/deploy_workflow.sh dag_w256_d3


# # production trace
# echo "Deploying dag_w1_d5_1"
# ./scripts/deploy_workflow.sh dag_w1_d5_1

# echo "Deploying dag_w1_d5_2"
# ./scripts/deploy_workflow.sh dag_w1_d5_2

# echo "Deploying dag_w1_d5_3"
# ./scripts/deploy_workflow.sh dag_w1_d5_3

# echo "Deploying dag_w1_d5_4"
# ./scripts/deploy_workflow.sh dag_w1_d5_4

# echo "Deploying dag_w1_d5_5"
# ./scripts/deploy_workflow.sh dag_w1_d5_5

# echo "Deploying dag_w1_d7_1"
# ./scripts/deploy_workflow.sh dag_w1_d7_1

# echo "Deploying dag_w1_d7_2"
# ./scripts/deploy_workflow.sh dag_w1_d7_2

# echo "Deploying dag_w1_d7_3"
# ./scripts/deploy_workflow.sh dag_w1_d7_3

# echo "Deploying dag_w1_d7_4"
# ./scripts/deploy_workflow.sh dag_w1_d7_4

# echo "Deploying dag_w1_d7_5"
# ./scripts/deploy_workflow.sh dag_w1_d7_5

# echo "Deploying dag_w1_d10_1"
# ./scripts/deploy_workflow.sh dag_w1_d10_1

# echo "Deploying dag_w1_d10_2"
# ./scripts/deploy_workflow.sh dag_w1_d10_2

# echo "Deploying dag_w1_d10_3"
# ./scripts/deploy_workflow.sh dag_w1_d10_3

# echo "Deploying dag_w1_d10_4"
# ./scripts/deploy_workflow.sh dag_w1_d10_4

# echo "Deploying dag_w1_d10_5"
# ./scripts/deploy_workflow.sh dag_w1_d10_5

# echo "Deploying dag_w1_d17_1"
# ./scripts/deploy_workflow.sh dag_w1_d17_1

# echo "Deploying dag_w1_d17_2"
# ./scripts/deploy_workflow.sh dag_w1_d17_2

# echo "Deploying dag_w1_d17_3"
# ./scripts/deploy_workflow.sh dag_w1_d17_3

# echo "Deploying dag_w1_d17_4"
# ./scripts/deploy_workflow.sh dag_w1_d17_4

# echo "Deploying dag_w1_d17_5"
# ./scripts/deploy_workflow.sh dag_w1_d17_5