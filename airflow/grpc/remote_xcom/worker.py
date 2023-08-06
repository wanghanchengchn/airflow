from typing import *
from concurrent import futures
import os
import pathlib
import grpc
import pickle
import argparse
import logging

from airflow.grpc.remote_xcom.protobufs  import remote_xcom_pb2, remote_xcom_pb2_grpc

log = logging.getLogger()


class InvokeWorker(remote_xcom_pb2_grpc.TaskRunServicer):
    def HandleTask(self, request, context):
        print(f"Received job !")
        args = request.args
        annotations =  pickle.loads(request.annotations)
        xcoms = pickle.loads(request.xcoms)
        print(f"args: {args}, annotations: {annotations}, xcoms: {xcoms}")
        
        response = [10, 10, 10, 10]
        print(f"response: {response}")
        return remote_xcom_pb2.task_reply(xcoms = pickle.dumps(response))


def serve(port: int):
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    remote_xcom_pb2_grpc.add_TaskRunServicer_to_server(InvokeWorker(),server)
    server.add_insecure_port(f'[::]:{port}')
    print(f"start worker server at port [{port}]")
    server.start()
    server.wait_for_termination()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('-p', '--port', type=int, default=8080)
    args = parser.parse_args()
    serve(args.port)