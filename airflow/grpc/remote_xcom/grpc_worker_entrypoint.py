import json
from typing import *
from concurrent import futures
import os
import pathlib
import grpc
import pickle
import logging
import argparse
import pendulum
from time import perf_counter
# from  argparse import ArgumentParser
from airflow.utils.cli import get_dag
from airflow.utils.dates import timezone
from airflow.cli import cli_parser
from airflow.cli.commands import task_command

from airflow.grpc.remote_xcom.protobufs import remote_xcom_pb2, remote_xcom_pb2_grpc

log = logging.getLogger(__name__)

class InvokeWorker(remote_xcom_pb2_grpc.TaskRunServicer):
    def __init__(self) -> None:
        log.info(f"init_start")
        super().__init__()
        self.parser = cli_parser.get_parser()
        dag_id = os.getenv("AIRFLOW_DAG_ID")
        task_id = os.getenv("AIRFLOW_TASK_ID")
        self.dag = get_dag(f"DAGS_FOLDER/{dag_id}.py", dag_id)
        self.task = self.dag.get_task(task_id=task_id)
        log.info(f"init_finish")
        
    def HandleTask(self, request, context):
        log.info(f"Received job !")
        args = request.args
        log.info(f"args: {args}")
        start_time = perf_counter()
        args = self.parser.parse_args(args[1:])
        log.info(f"parsed_args: {args}, dag: {self.dag}, task: {self.task}")
        task_command.task_run(args, dag = self.dag, task=self.task)       
        end_time = perf_counter()
        response = pickle.dumps({"execution_time": end_time-start_time})
        return remote_xcom_pb2.task_reply(timing = response)


def serve(port: int):
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    remote_xcom_pb2_grpc.add_TaskRunServicer_to_server(InvokeWorker(),server)
    server.add_insecure_port(f'[::]:{port}')
    log.info(f"start worker server at port [{port}]")
    server.start()
    server.wait_for_termination()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('-p', '--port', type=int, default=8081)
    args = parser.parse_args()
    serve(args.port)
