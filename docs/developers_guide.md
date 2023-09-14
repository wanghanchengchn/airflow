## Airflow-vHive developer's guide
To deploy new workflow and apply changes to the Airflow components, you need to set your own container registry.

After changing the registry, you should 

## Changing container registry
```
configs/values.yaml
scripts/update_images.sh
workflows/knative_yaml_builder/knative_service_template.yaml
```
Change container registry in files above to your prefered one.

## Deploying new workflows
A workflow (Apache Airflow also calls them DAGs) consists of the following files:
- A python file that defines the DAG using [Airflow Taskflow](https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/taskflow.html).
- YAML files that define the Knative services for each function in the workflow.

Examples can be found in the [workflows](workflows) directory.
For instance, [xcom_dag.py](workflows/image/airflow-dags/xcpom_dag.py) contains
a workflow that pass current time value generated at producer function to consumer function.
The corresponding YAML files that define the Knative services for each
function in the workflow can be found in [workflows/knative_yams/xcom_dag](workflows/knative_yams/xcom_dag).

Since the DAGs are baked into the function and airflow images, it is a bit tedious
to deploy new DAGs.
However, the below step-by-step guide should make it easier.
1. Place your python workflow file in `workflows/image/airflow-dags`
2. Run `scripts/install_airflow.sh`. It will automatically clean up previous environment, rebuild knative worker yamls, and deploy airflow and knative workers with up to date DAGs.
3. Run `scripts/deploy_workflow.sh dag_id`, replacing `dag_id` with the id of your dag.
   Look in `workflows/knative_yamls` if you are not sure what the id of your dag is.
4. Execute your dag with
    ```bash
    python workflow-gateway/main.py
    ```
   Make sure to replace dag name and task name in the `main.py` to the ones you are triggering. 
   Also, check out [Airflow Python Client](https://github.com/apache/airflow-client-python) repository to add features that you might want for the python airflow client.

## Debugging
If you started a workflow, but it is crashing or does not terminate, you might
need to inspect the logs.
The most likely place to find useful information are the logs of Airflow's scheduler,
which can be accessed with [k9s](https://k9scli.io/) we installed while running above script.

If you need access to the logs of a function, you will need to find its pod id with kubectl -n airflow get pods. Then kubectl -n airflow logs <pod_id> user-container will give you the logs of the webserver that handles function invocations. To get the logs of the function execution, you can open a shell in the pod with
``` bash
kubectl -n airflow exec <pod_id> -- bash
```
and then navigate to the ./logs directory.

Airflow's web interface might also be helpful. Webserver is already exposed at http://localhost:8080. Log in with username admin and password admin.

## Logging
Running `./scripts/log_benchmark.sh` will reinstall entire Airflow with updated images, run a workflow, and store worker logs as text files in designated folder.
Or you can run script below to only get logs from worker directly.
```bash
log_dir=./benchmark/"$(date +%s)"
mkdir -p "$log_dir"
target="$(kubectl -n airflow get pods | grep "$target" | awk '{print $1}')"
kubectl -n airflow logs "$target" user-container > "$log_dir"/log_"$target".log
```