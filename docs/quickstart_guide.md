## Quick start guide

### Infrastructure Setup
First, we will set up a **single node** with vHive `stock-only` configuration.

To set up hardware infrastructure, refer to `CloudLab Deployment Notes` in
[vHive Quickstart](https://github.com/vhive-serverless/vHive/blob/main/docs/quickstart_guide.md#3-cloudlab-deployment-notes). You only need to rent 1-node.

To set up software infrastructure, clone this Airflow repository and run commands below. 

[setup_infrastructure.sh](../scripts/setup_infrastructure.sh) will setup Knative using vHive framework. For those who already have a working cluster can skip this script.

```bash
git clone https://github.com/vhive-serverless/airflow.git
./airflow/scripts/setup_infrastructure.sh
```

[setup_tools.sh](../scripts/setup_tools.sh) will install packages needed.
These aditional packages include: Docker, Airflow Python Client, gRPC Tools, and K9S

```bash
./airflow/scripts/setup_tools.sh
```

### Example Deployment

When `setup_infrastructure.sh` and `setup_tools.sh` are finished, run script below.

```bash
cd airflow
./scripts/quickstart_script.sh
```

[quickstart_script.sh](../scripts/quickstart_script.sh) deploys airflow using helm chart, and run a sample dag [avg_distributed.py](../workflows/image/airflow-dags/avg_distributed.py) twice to show cold start and warm start latency difference. The dag run trigger will return this result:

```bash
Triggering a DAG run:
dag_id: compute_avg_distributed
dag_run_id: manual_1cfa7678ab1b461b8326015b232667d9
```

And after a few seconds, result will be pulled from Database. 
```bash
Execution Result:
  extract:
    dag_id: compute_avg_distributed
    task_id: extract
    value: [1, 2, 3, 4]
  count:
    dag_id: compute_avg_distributed
    task_id: compute_count
    value: 4
  sum:
    dag_id: compute_avg_distributed
    task_id: compute_sum
    value: 10.0
  average:
    dag_id: compute_avg_distributed
    task_id: do_avg
    value: 2.5

End-to-end Latency: 45.3 second
```

End-to-end latency is measured with Airflow-webserver HTTP response time. 


```bash
TIMING: {"function": "worker_execution", "times": [2.935269741999946], ...
TIMING: {"function": "executor_async_task", "times": [1696967251.981217, 1696967251.981461, 1696967261.053331, 1696967261.054357],
"timestamp_annotations": ["function_entry", "before_post_request", "after_post_request", "function_exit"], ...
```

You can retrieve per-task worker and scheduler execution time by viewing the log of scheduler pod using `k9s`
Also the quickstart script will automatically dump pods logs in benchmark folder.

---
For warm start, same result will be returned with much shorter execution time and latency

```bash
End-to-end Latency: 4.96 second
```

```bash
TIMING: {"function": "worker_execution", "times": [0.5060419100009312], ...
TIMING: {"function": "executor_async_task", "times": [1696967299.870403, 1696967299.8705447, 1696967300.411216, 1696967300.412098],
"timestamp_annotations": ["function_entry", "before_post_request", "after_post_request", "function_exit"], ...
