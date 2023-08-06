import uuid
from time import sleep, perf_counter

import airflow_client.client
from airflow_client.client.api import config_api, dag_api, dag_run_api
from airflow_client.client.model.dag_run import DAGRun

from airflow_client.client.api import x_com_api
from airflow_client.client.model.x_com_collection import XComCollection
from airflow_client.client.model.error import Error

import json
from contextlib import suppress
# The client must use the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.
#
# In case of the basic authentication below, make sure that Airflow is
# configured also with the basic_auth as backend additionally to regular session backend needed
# by the UI. In the `[api]` section of your `airflow.cfg` set:
#
# auth_backend = airflow.api.auth.backend.session,airflow.api.auth.backend.basic_auth
#
# Make sure that your user/name are configured properly - using the user/password that has admin
# privileges in Airflow

# Configure HTTP basic authorization: Basic

# Make sure in the [core] section, the  `load_examples` config is set to True in your airflow.cfg
# or AIRFLOW__CORE__LOAD_EXAMPLES environment variable set to True

# Enter a context with an instance of the API client

def get_dag_list(api_client):
    errors = False

    print('[blue]Getting DAG list')
    dag_api_instance = dag_api.DAGApi(api_client)
    try:
        api_response = dag_api_instance.get_dags()
        print(api_response)
    except airflow_client.client.OpenApiException as e:
        print("[red]Exception when calling DagAPI->get_dags: %s\n" % e)
        errors = True
    else:
        print('[green]Getting DAG list successful')


def trigger_dag(api_client, DAG_ID):

    print('[blue]Triggering a DAG run')
    dag_run_api_instance = dag_run_api.DAGRunApi(api_client)
    try:
        # Create a DAGRun object (no dag_id should be specified because it is read-only property of DAGRun)
        # dag_run id is generated randomly to allow multiple executions of the script
        dag_run = DAGRun(
            dag_run_id='manual_' + uuid.uuid4().hex,
        )
        api_response = dag_run_api_instance.post_dag_run(DAG_ID, dag_run)
        print(api_response)
        return api_response
    except airflow_client.client.exceptions.OpenApiException as e:
        print("[red]Exception when calling DAGRunAPI->post_dag_run: %s\n" % e)
        errors = True

def get_xcom_values(api_client, dag_id, run_id, task_id):
    prod_id, cons_id = task_id
    api_instance = x_com_api.XComApi(api_client)
    while True:
        try: 
            xcom_return_value_producer = api_instance.get_xcom_entry(dag_id, run_id, prod_id, 'return_value')
            xcom_return_value_consumer = api_instance.get_xcom_entry(dag_id, run_id, cons_id, 'return_value')
        except Exception as e:
            print(f"no result: {e.status}", end="\r")
            sleep(0.1)
        else: 
            got_result_time = perf_counter()
            print(f"producer: {xcom_return_value_producer}")
            print(f"consumer: {xcom_return_value_consumer}")
            
            return got_result_time

def main():
    configuration = airflow_client.client.Configuration(
    host="http://localhost:8080/api/v1",
    username='admin',
    password='admin', 
    )
    dag_id = "benchmark_w8_d3"
    api_client = airflow_client.client.ApiClient(configuration)
    start_trigger = perf_counter()
    response = trigger_dag(api_client, dag_id)
    finish_trigger = perf_counter()
    
    run_id = response['dag_run_id']
    prod_id = 'extract'
    cons_id = 'do_sum'
    
    got_result_time = get_xcom_values(api_client, dag_id, run_id, [prod_id, cons_id])
    
    print(f"trigger_time: {finish_trigger - start_trigger}")
    print(f"exec_and_retrieve: {got_result_time - finish_trigger}")

    
if __name__ == "__main__":
    main()