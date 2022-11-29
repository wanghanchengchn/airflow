from typing import *
from concurrent import futures
import grpc
import pickle
import argparse
import logging

from airflow.grpc.remote_xcom.protobufs import remote_xcom_pb2, remote_xcom_pb2_grpc

        
def get_target(server, port):
    prefix = 'http://'
    server = server[len(prefix):] if server.startswith(prefix) else server
    print(server)
    return f'{server}:{port}'

def invoke_task(target: str, args):
    target = get_target(target, 80)
    with grpc.insecure_channel(target) as channel:
        stub = remote_xcom_pb2_grpc.TaskRunStub(channel)
        task = remote_xcom_pb2.task_invoke(
            args = args, 
        )
        response = stub.HandleTask(task)
    return response
    
if __name__ == '__main__':
    print(f"not designed to be used as server")
