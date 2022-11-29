# Knative workflows via Apache Airflow

This fork of Apache Airflow executes DAGs similarly to the Kubernetes Executor
shipped with stock Apache Airflow.
However, instead of creating and deleting Kubernetes pods to execute tasks,
it uses Knative services.

These Knative services must be created ahead of time.
However, due to how Knative works, this does not mean that a worker pod is
running constantly.
Instead, Knative creates/scales/deletes the pods automatically as needed.
Moreover, instead of looking up task arguments in the database used by Airflow,
this fork directly sends them in the RPC to the Knative services
Likewise, the HTTP response by the Knative services includes the return value
of the task.

## Setting up and running an example
First, set up a cluster of one or more nodes with the `stock-only` configuration
as described in
[vHive Quickstart](https://github.com/vhive-serverless/vHive/blob/main/docs/quickstart_guide.md).
Do not start vHive, as it is not needed.
The relevant commands for a single-node cluster are reproduced here.

```bash
git clone --depth=1 https://github.com/vhive-serverless/vhive.git
cd vhive
mkdir -p /tmp/vhive-logs
./scripts/cloudlab/setup_node.sh stock-only  # this might print errors, ignore them
```

The `setup_node.sh` script might print some errors, don't worry about them and continue.

```bash
sudo screen -d -m containerd
./scripts/cluster/create_one_node_cluster.sh stock-only
cd ..
```

Now, the Kubernetes cluster and Knative should be ready.
It is time to deploy this fork of airflow with the following commands:
```bash
git clone --single-branch --branch integrate-knative --depth 1 git@github.com:eth-easl/airflow.git
cd airflow
./scripts/setup_airflow.sh
```

The script will create the namespace `airflow` and deploy all resources to
that namespace.

After running the setup script, airflow should be up and running.
Verify by running `kubectl -n airflow get pods`, the output should look similar
to what is shown below.
```
airflow-create-user-jw7t8                                         0/1     Completed     1          2m23s
airflow-postgresql-0                                              1/1     Running       0          2m23s
airflow-run-airflow-migrations-xldsv                              0/1     Completed     0          2m23s
airflow-scheduler-cdcc9b98b-dqkrn                                 2/2     Running       0          2m23s
airflow-statsd-59895f6c69-p4rbg                                   1/1     Running       0          2m23s
airflow-triggerer-7d5f6d85b8-6pptm                                1/1     Running       0          2m23s
airflow-webserver-5c58849cd9-mvkgx                                1/1     Running       0          2m23s
```

You can also check that the Knative services are ready with
`kn service list -n airflow`.
Again, the output should look similar to this.
```
NAME                                           URL                                                                                  LATEST                                               AGE     CONDITIONS   READY   REASON
airflow-avg-worker-distributed-compute-count   http://airflow-avg-worker-distributed-compute-count.airflow.192.168.1.240.sslip.io   airflow-avg-worker-distributed-compute-count-00001   5m58s   3 OK / 3     True
airflow-avg-worker-distributed-compute-sum     http://airflow-avg-worker-distributed-compute-sum.airflow.192.168.1.240.sslip.io     airflow-avg-worker-distributed-compute-sum-00001     5m50s   3 OK / 3     True
airflow-avg-worker-distributed-do-avg          http://airflow-avg-worker-distributed-do-avg.airflow.192.168.1.240.sslip.io          airflow-avg-worker-distributed-do-avg-00001          5m39s   3 OK / 3     True
airflow-avg-worker-distributed-extract         http://airflow-avg-worker-distributed-extract.airflow.192.168.1.240.sslip.io         airflow-avg-worker-distributed-extract-00001         5m28s   3 OK / 3     True
airflow-workflow-gateway                       http://airflow-workflow-gateway.airflow.192.168.1.240.sslip.io                       airflow-workflow-gateway-00001                       5m23s   3 OK / 3     True
```


Now all that's left to do is to deploy and run a workflow.
```bash
GATEWAY_URL="$(kn service list -o json -n airflow | jq -r '.items[] | select(.metadata.name=="airflow-workflow-gateway").status.url')"
curl -u admin:admin -X POST -H 'application/json' --data '{"input": [1,2,3,4]}' "$GATEWAY_URL"/runWorkflow/compute_avg_distributed
```
Running the workflow will take some time (~20s) but if all went well, it should return
`{"output":2.5}`.
The reason it takes so long for a simple computation is that the
workflow is artificially split into small steps, and each of them must
start a Knative service.


## Deploying new workflows
A workflow (Apache Airflow also calls them DAGs) consists of the following files:
- A python file that defines the DAG using [Airflow Taskflow](https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/taskflow.html).
- YAML files that define the Knative services for each function in the workflow.

Examples can be found in the [workflows](workflows) directory.
For instance, [avg_distributed.py](workflows/image/airflow-dags/avg_distributed.py) contains
a workflow that computes the average of its inputs.
The corresponding YAML files that define the Knative services for each
function in the workflow can be found in [workflows/avg_distributed](workflows/avg_distributed).

Since the DAGs are baked into the function and airflow images, it is a bit tedious
to deploy new DAGs.
However, the below step-by-step guide should make it easier.
1. Place your python workflow file in `workflows/image/airflow-dags`
2. Run `scripts/update_images.sh`. This will build two images: `airflow` and `airflow-worker`.
3. Tag and push these images, e.g.
   ```bash
   docker tag airflow:latest ghcr.io/jonamuen/airflow:latest
   docker tag airflow-worker:latest ghcr.io/jonamuen/airflow-worker:latest
   docker push ghcr.io/jonamuen/airflow:latest
   docker push ghcr.io/jonamuen/airflow-worker:latest
   ```
   Don't forget to adjust the registry.
4. If you previously followed the setup guide above, run
   ```bash
   kubectl delete namespace airflow
   ```
   This removes the namespace `airflow` and all resources in that namespace.
   It might take a while.
5. Modify `configs/values.yaml` to point to your new image, i.e. replace references
   to `ghcr.io/jonamuen/airflow` with the name of your `airflow` image.
   Also adjust the tag if needed.
6. Adjust the template for Knative services in [workflows/knative\_yaml\_builder/knative\_service\_template.yaml](workflows/knative_yaml_builder/knative_service_template.yaml) to point to your `airflow-worker` image.
   Then run `scripts/build_knative_yamls.sh`.
   This will generate Knative service definitions in [workflows/knative\_yamls](workflows/knative_yamls) for
   all dags in `workflows/image/airflow-dags`.
7. Run `scripts/setup_airflow.sh`.
8. Run `scripts/deploy_workflow.sh dag_id`, replacing `dag_id` with the id of your dag.
   Look in `workflows/knative\_yamls` if you are not sure what the id of your dag is.
9. Airflow should now be up and running (check with `kubectl -n airflow get pods`)
   and a Knative service for each function of your workflow should be available,
   which can be verified with `kn service list -n airflow`.
10. Execute your dag with
    ```bash
    DAG_ID="<dag_id>"
    GATEWAY_URL="$(kn service list -o json -n airflow | jq -r '.items[] | select(.metadata.name=="airflow-workflow-gateway").status.url')"
    curl -u admin:admin -X POST -H 'application/json' --data '{"input": [1,2,3,4]}' "$GATEWAY_URL"/runWorkflow/"$DAG_ID"
    ```
    Make sure to replace `<dag_id>` with the id of your DAG.
    Modify the `--data` parameter as needed.

### Sending input to workflows
To send input (i.e. arguments of the root function) to a workflow, you must send
them under the `"input"` key to the `/runWorkflow/<dag_id>` endpoint.
Set up the root function to accept a single argument `params`.
The input data you sent will then be accessible via `params["data"]`.

Example: If you send `{"input": "foo"}` to `/runWorkflow/<dag_id>`, then
`params["data"] == "foo"` in the first function of your workflow.

### Debugging
If you started a workflow, but it is crashing or does not terminate, you might
need to inspect the logs.
The most likely place to find useful information are the logs of Airflow's scheduler,
which can be accessed as shown below.
```bash
scheduler="$(kubectl -n airflow get pods | grep scheduler)"
kubectl -n airflog logs "$scheduler" scheduler
```

If you need access to the logs of a function, you will need to find its pod id
with `kubectl -n airflow get pods`.
Then `kubectl -n airflow logs <pod_id> user-container` will give you the
logs of the webserver that handles function invocations.
To get the logs of the function execution, you can open a shell in the pod with
```bash
kubectl -n airflow exec <pod_id> -- bash
```
and then navigate to the `./logs` directory.

Airflow's web interface might also be helpful.
You can expose it at `http://localhost:8080` with the below command.
Log in with username `admin` and password `admin`.
```bash
screen -d -m kubectl -n airflow port-forward deployment/airflow-webserver 8080:8080
```

The last component that might be worth checking is the `workflow-gateway`.
Since it is a Knative service, you will need to find its pod id with
```bash
kubectl -n airflow get pods
```
Since it is a Knative service, there will only be a pod if there were recent
requests to it.
With the pod id, run
```bash
kubectl -n airflow logs <pod_id>
```
