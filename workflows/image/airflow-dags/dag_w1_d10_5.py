from pickle import NONE
import pendulum
from airflow.decorators import dag, task
import logging
from functools import wraps
from time import sleep, time
import time as t_module
from airflow.models import TaskInstance
from airflow.settings import Session
from concurrent.futures import ThreadPoolExecutor, TimeoutError, wait, FIRST_COMPLETED
import uuid
import copy
from typing import Dict, Any, Tuple, Optional, Union, List
from decimal import Decimal
from os import environ
import os
import io
import random
import boto3


####
# 这是mapreduce的函数，运行方法是：./scripts/8_get_e2e_breakdown.sh 1 "dag_w1_d10_5" 40 10


# by Jonathan Prieto-Cubides https://stackoverflow.com/questions/1622943/timeit-versus-timing-decorator
def timing(f):
    @wraps(f)
    def wrap(*args, **kw):
        ts = time()
        result = f(*args, **kw)
        te = time()
        logging.info(
            "func:%r args:[%r, %r] took: %f sec. Start: %f, End: %f" % (f.__name__, args, kw, te - ts, ts, te)
        )
        return result

    return wrap


def get_current_task_run_id(dag_id, task_id):
    """获取指定任务的当前run_id"""
    session = Session()
    try:
        current_task = (
            session.query(TaskInstance)
            .filter(TaskInstance.dag_id == dag_id, TaskInstance.task_id == task_id)
            .order_by(TaskInstance.start_date.desc())
            .first()
        )

        if not current_task:
            raise ValueError(f"Cannot find current task instance for {dag_id}.{task_id}")

        return current_task.run_id
    finally:
        session.close()


def get_upstream_task_value(dag_id, task_id, run_id, upstream_task_id, max_retries=10000, retry_delay=0.1):
    """获取上游任务的XCom值"""
    for attempt in range(max_retries):
        session = Session()
        try:
            upstream_task = (
                session.query(TaskInstance)
                .filter(
                    TaskInstance.dag_id == dag_id,
                    TaskInstance.task_id == upstream_task_id,
                    TaskInstance.run_id == run_id,
                )
                .first()
            )

            if upstream_task:
                value = upstream_task.xcom_pull(task_ids=upstream_task_id)
                if value is not None:
                    logging.info(f"WHC: get upstream value: {value}")
                    return value
            logging.info(f"Attempt {attempt + 1}/{max_retries}: Waiting for upstream XCom...")
            t_module.sleep(retry_delay)
        except Exception as e:
            logging.info(f"Error getting upstream value: {str(e)}")
        finally:
            session.close()

    logging.info("Max retries reached, using default value")
    return None  # 默认值


def execute_parallel_tasks(tasks):
    """并行执行多个任务"""
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(func, *args) for func, args in tasks]
        results = [future.result() for future in futures]
        return results


size_generators = {"test": (50, 3), "small": (1000, 3), "large": (100000, 3)}


def buckets_count():
    return (1, 1)


def generate_input(size, benchmarks_bucket, input_buckets, output_buckets):
    mult, n_mappers = size_generators[size]
    words = ["cat", "dog", "bird", "horse", "pig"]
    lst = mult * words
    random.shuffle(lst)

    list_name = "words"

    return {
        "benchmark_bucket": benchmarks_bucket,
        "words_bucket": input_buckets[0],
        "words": list_name,
        "n_mappers": n_mappers,
        "output_bucket": output_buckets[0],
    }


def chunks(lst, n):
    m = int(len(lst) / n)
    for i in range(n - 1):
        yield lst[i * m : i * m + m]
    tail = lst[(n - 1) * m :]
    if len(tail) > 0:
        yield tail


def count_words(lst):
    index = dict()
    for word in lst:
        if len(word) == 0:
            continue

        val = index.get(word, 0)
        index[word] = val + 1

    return index


def incr_io_env_file(filepath, key):
    stats = os.stat(filepath)
    incr_io_env(stats.st_size, key)


def incr_io_env(val, key):
    cnt = int(os.getenv(key, "0"))
    os.environ[key] = str(cnt + val)


class storage:
    instance = None
    client = None

    def __init__(self):
        self.client = boto3.client(
            "s3",
            region_name="us-east-1",
            aws_access_key_id="<WHC_AWS_KEY>",
            aws_secret_access_key="<WHC_AWS_SECRET>",
        )

    @staticmethod
    def unique_name(name):
        name, extension = os.path.splitext(name)
        return "{name}.{random}{extension}".format(
            name=name, extension=extension, random=str(uuid.uuid4()).split("-")[0]
        )

    def upload(self, bucket, file, filepath, unique_name=True):
        incr_io_env_file(filepath, "STORAGE_UPLOAD_BYTES")

        key_name = storage.unique_name(file) if unique_name else file
        self.client.upload_file(filepath, bucket, key_name)
        return key_name

    def download(self, bucket, file, filepath):
        self.client.download_file(bucket, file, filepath)
        incr_io_env_file(filepath, "STORAGE_DOWNLOAD_BYTES")

    def download_directory(self, bucket, prefix, path):
        objects = self.client.list_objects_v2(Bucket=bucket, Prefix=prefix)
        for obj in objects["Contents"]:
            file_name = obj["Key"]
            path_to_file = os.path.dirname(file_name)
            os.makedirs(os.path.join(path, path_to_file), exist_ok=True)
            self.download(bucket, file_name, os.path.join(path, file_name))
            incr_io_env_file(os.path.join(path, file_name), "STORAGE_DOWNLOAD_BYTES")

    def upload_stream(self, bucket, file, data):
        size = data.seek(0, 2)
        incr_io_env(size, "STORAGE_UPLOAD_BYTES")
        data.seek(0)
        key_name = storage.unique_name(file)
        self.client.upload_fileobj(data, bucket, key_name)
        return key_name

    def download_stream(self, bucket, file):
        data = io.BytesIO()
        self.client.download_fileobj(bucket, file, data)
        incr_io_env(data.tell(), "STORAGE_DOWNLOAD_BYTES")
        return data.getbuffer()

    def download_within_range(self, bucket, file, start_byte, stop_byte):
        resp = self.client.get_object(
            Bucket=bucket, Key=file, Range="bytes={}-{}".format(start_byte, stop_byte)
        )
        return resp["Body"].read().decode("utf-8")

    def list_directory(self, bucket, prefix):
        objects = self.client.list_objects_v2(Bucket=bucket, Prefix=prefix)
        for obj in objects["Contents"]:
            yield obj["Key"]

    def get_instance():
        if storage.instance is None:
            storage.instance = storage()
        return storage.instance


@dag(
    schedule_interval=None,
    start_date=pendulum.datetime(2021, 1, 1, tz="UTC"),
    catchup=False,
    is_paused_upon_creation=False,
)
def dag_w1_d10_5():
    @task
    @timing
    def func_1_1(event):
        logging.info("======= func_1_1 execution start =======")

        benchmark_bucket = event["benchmark_bucket"]
        words_bucket = event["words_bucket"]
        words_blob = event["words"]
        words_path = os.path.join("/tmp", "words.txt")

        client = storage.get_instance()
        client.download(benchmark_bucket, words_bucket + "/" + words_blob, words_path)
        with open(words_path, "r") as f:
            list = f.read().split("\n")
        os.remove(words_path)

        n_mappers = event["n_mappers"]
        output_bucket = event["output_bucket"]
        map_lists = chunks(list, n_mappers)
        blobs = []

        for chunk in map_lists:
            name = str(uuid.uuid4())[:8]
            data = io.BytesIO()
            data.writelines((val + "\n").encode("utf-8") for val in chunk)
            data.seek(0)

            name = client.upload_stream(benchmark_bucket, output_bucket + "/" + name, data)
            stripped_name = name.replace(output_bucket + "/", "")
            blobs.append(stripped_name)

        prefix = str(uuid.uuid4())[:8]
        lst = [
            {"benchmark_bucket": benchmark_bucket, "bucket": output_bucket, "blob": b, "prefix": prefix}
            for b in blobs
        ]

        logging.info("======= func_1_1 execution end =======")

        return {"list": lst}

    @task
    @timing
    def func_1_2(
        upstream_output_func_1_1,
        dag_id: str = "dag_w1_d10_5",
        upstream_task_id: str = "func_1_1",
        task_name: str = "func_1_2",
        enable_optimization: bool = True,
        run_id: str = "{{ run_id }}",
    ):
        current_run_id = run_id

        if enable_optimization:
            # 数据平面优化模式：并行获取上游数据和建立数据库连接
            tasks = [
                (get_upstream_task_value, (dag_id, task_name, current_run_id, upstream_task_id)),
                (storage.get_instance, ()),
            ]

            # 并行执行任务
            upstream_output, client = execute_parallel_tasks(tasks)
        else:
            # 普通模式：串行执行
            upstream_output = get_upstream_task_value(dag_id, task_name, current_run_id, upstream_task_id)
            client = storage.get_instance()

        logging.info("======= func_1_2 execution start =======")

        event = upstream_output["list"][0]

        benchmark_bucket = event["benchmark_bucket"]
        bucket = event["bucket"]
        blob = event["blob"]
        prefix = event["prefix"]

        my_buffer = client.download_stream(benchmark_bucket, bucket + "/" + blob)
        words = bytes(my_buffer).decode("utf-8").split("\n")

        index = count_words(words)
        for word, count in index.items():
            data = io.BytesIO()
            data.write(str(count).encode("utf-8"))
            data.seek(0)

            # client.upload_stream(benchmark_bucket, os.path.join(bucket, prefix, word, blob), data)
            client.upload_stream(benchmark_bucket, os.path.join(prefix, word, blob), data)

        logging.info("======= func_1_2 execution end =======")

        return upstream_output

    @task
    @timing
    def func_1_3(
        upstream_output_func_1_1,
        dag_id: str = "dag_w1_d10_5",
        upstream_task_id: str = "func_1_1",
        task_name: str = "func_1_3",
        enable_optimization: bool = True,
        run_id: str = "{{ run_id }}",
    ):
        current_run_id = run_id

        if enable_optimization:
            # 数据平面优化模式：并行获取上游数据和建立数据库连接
            tasks = [
                (get_upstream_task_value, (dag_id, task_name, current_run_id, upstream_task_id)),
                (storage.get_instance, ()),
            ]

            # 并行执行任务
            upstream_output, client = execute_parallel_tasks(tasks)
        else:
            # 普通模式：串行执行
            upstream_output = get_upstream_task_value(dag_id, task_name, current_run_id, upstream_task_id)
            client = storage.get_instance()

        logging.info("======= func_1_3 execution start =======")

        event = upstream_output["list"][1]
        benchmark_bucket = event["benchmark_bucket"]
        bucket = event["bucket"]
        blob = event["blob"]
        prefix = event["prefix"]

        my_buffer = client.download_stream(benchmark_bucket, bucket + "/" + blob)
        words = bytes(my_buffer).decode("utf-8").split("\n")

        index = count_words(words)
        for word, count in index.items():
            data = io.BytesIO()
            data.write(str(count).encode("utf-8"))
            data.seek(0)

            # client.upload_stream(benchmark_bucket, os.path.join(bucket, prefix, word, blob), data)
            client.upload_stream(benchmark_bucket, os.path.join(prefix, word, blob), data)

        logging.info("======= func_1_3 execution end =======")

        return upstream_output

    @task
    @timing
    def func_1_4(
        upstream_output_func_1_1,
        dag_id: str = "dag_w1_d10_5",
        upstream_task_id: str = "func_1_1",
        task_name: str = "func_1_4",
        enable_optimization: bool = True,
        run_id: str = "{{ run_id }}",
    ):
        current_run_id = run_id

        if enable_optimization:
            # 数据平面优化模式：并行获取上游数据和建立数据库连接
            tasks = [
                (get_upstream_task_value, (dag_id, task_name, current_run_id, upstream_task_id)),
                (storage.get_instance, ()),
            ]

            # 并行执行任务
            upstream_output, client = execute_parallel_tasks(tasks)
        else:
            # 普通模式：串行执行
            upstream_output = get_upstream_task_value(dag_id, task_name, current_run_id, upstream_task_id)
            client = storage.get_instance()

        logging.info("======= func_1_4 execution start =======")

        event = upstream_output["list"][2]
        benchmark_bucket = event["benchmark_bucket"]
        bucket = event["bucket"]
        blob = event["blob"]
        prefix = event["prefix"]

        my_buffer = client.download_stream(benchmark_bucket, bucket + "/" + blob)
        words = bytes(my_buffer).decode("utf-8").split("\n")

        index = count_words(words)
        for word, count in index.items():
            data = io.BytesIO()
            data.write(str(count).encode("utf-8"))
            data.seek(0)

            # client.upload_stream(benchmark_bucket, os.path.join(bucket, prefix, word, blob), data)
            client.upload_stream(benchmark_bucket, os.path.join(prefix, word, blob), data)

        logging.info("======= func_1_4 execution end =======")

        return upstream_output

    @task
    @timing
    def func_1_5(
        upstream_output_func_1_2,
        upstream_output_func_1_3,
        upstream_output_func_1_4,
        dag_id: str = "dag_w1_d10_5",
        upstream_task_id: str = "func_1_4",
        task_name: str = "func_1_5",
        enable_optimization: bool = True,
        run_id: str = "{{ run_id }}",
    ):
        current_run_id = run_id

        if enable_optimization:
            # 数据平面优化模式：并行获取上游数据和建立数据库连接
            tasks = [
                (get_upstream_task_value, (dag_id, task_name, current_run_id, upstream_task_id)),
                (storage.get_instance, ()),
            ]

            # 并行执行任务
            upstream_output, client = execute_parallel_tasks(tasks)
        else:
            # 普通模式：串行执行
            upstream_output = get_upstream_task_value(dag_id, task_name, current_run_id, upstream_task_id)
            client = storage.get_instance()

        logging.info("======= func_1_5 execution start =======")

        event = upstream_output

        lst = event["list"]
        benchmark_bucket = lst[0]["benchmark_bucket"]
        bucket = lst[0]["bucket"]
        prefix = lst[0]["prefix"]

        dirs = client.list_directory(benchmark_bucket, prefix)
        dirs = [p.split(os.sep)[1] for p in dirs]
        dirs = list(set(dirs))
        lst = [
            {
                "bucket": benchmark_bucket,
                # "dir": os.path.join(bucket, prefix, path)
                # TODO add word here.
                "dir": os.path.join(prefix, path),
                # "dir": os.path.join(bucket, prefix)
            }
            for path in dirs
        ]

        logging.info("======= func_1_5 execution end =======")

        return {"list": lst}

    @task
    @timing
    def func_1_6(
        upstream_output_func_1_5,
        dag_id: str = "dag_w1_d10_5",
        upstream_task_id: str = "func_1_5",
        task_name: str = "func_1_6",
        enable_optimization: bool = True,
        run_id: str = "{{ run_id }}",
    ):
        current_run_id = run_id

        if enable_optimization:
            # 数据平面优化模式：并行获取上游数据和建立数据库连接
            tasks = [
                (get_upstream_task_value, (dag_id, task_name, current_run_id, upstream_task_id)),
                (storage.get_instance, ()),
            ]

            # 并行执行任务
            upstream_output, client = execute_parallel_tasks(tasks)
        else:
            # 普通模式：串行执行
            upstream_output = get_upstream_task_value(dag_id, task_name, current_run_id, upstream_task_id)
            client = storage.get_instance()
        
        logging.info("======= func_1_6 execution start =======")

        event = upstream_output["list"][0]

        bucket = event["bucket"]
        path = event["dir"]

        count = 0
        # each blob is one word.
        # for blob in client.list_directory(bucket, path):
        for blob in client.list_directory(bucket, path):
            my_buffer = client.download_stream(bucket, blob)
            count += int(bytes(my_buffer).decode("utf-8"))
            # count += int(my_buffer.getvalue().decode("utf-8"))

        logging.info(f"WHC: word: {os.path.basename(path)}")
        logging.info(f"WHC: count: {count}")

        logging.info("======= func_1_6 execution end =======")

        return {"word": os.path.basename(path), "count": count}

    @task
    @timing
    def func_1_7(
        upstream_output_func_1_5,
        dag_id: str = "dag_w1_d10_5",
        upstream_task_id: str = "func_1_5",
        task_name: str = "func_1_7",
        enable_optimization: bool = True,
        run_id: str = "{{ run_id }}",
    ):
        current_run_id = run_id

        if enable_optimization:
            # 数据平面优化模式：并行获取上游数据和建立数据库连接
            tasks = [
                (get_upstream_task_value, (dag_id, task_name, current_run_id, upstream_task_id)),
                (storage.get_instance, ()),
            ]

            # 并行执行任务
            upstream_output, client = execute_parallel_tasks(tasks)
        else:
            # 普通模式：串行执行
            upstream_output = get_upstream_task_value(dag_id, task_name, current_run_id, upstream_task_id)
            client = storage.get_instance()

        logging.info("======= func_1_7 execution start =======")

        event = upstream_output["list"][1]

        bucket = event["bucket"]
        path = event["dir"]

        count = 0
        # each blob is one word.
        # for blob in client.list_directory(bucket, path):
        for blob in client.list_directory(bucket, path):
            my_buffer = client.download_stream(bucket, blob)
            count += int(bytes(my_buffer).decode("utf-8"))
            # count += int(my_buffer.getvalue().decode("utf-8"))

        logging.info(f"WHC: word: {os.path.basename(path)}")
        logging.info(f"WHC: count: {count}")

        logging.info("======= func_1_7 execution end =======")

        return {"word": os.path.basename(path), "count": count}

    @task
    @timing
    def func_1_8(
        upstream_output_func_1_5,
        dag_id: str = "dag_w1_d10_5",
        upstream_task_id: str = "func_1_5",
        task_name: str = "func_1_8",
        enable_optimization: bool = True,
        run_id: str = "{{ run_id }}",
    ):
        current_run_id = run_id

        if enable_optimization:
            # 数据平面优化模式：并行获取上游数据和建立数据库连接
            tasks = [
                (get_upstream_task_value, (dag_id, task_name, current_run_id, upstream_task_id)),
                (storage.get_instance, ()),
            ]

            # 并行执行任务
            upstream_output, client = execute_parallel_tasks(tasks)
        else:
            # 普通模式：串行执行
            upstream_output = get_upstream_task_value(dag_id, task_name, current_run_id, upstream_task_id)
            client = storage.get_instance()

        logging.info("======= func_1_8 execution start =======")

        event = upstream_output["list"][2]

        bucket = event["bucket"]
        path = event["dir"]

        count = 0
        # each blob is one word.
        # for blob in client.list_directory(bucket, path):
        for blob in client.list_directory(bucket, path):
            my_buffer = client.download_stream(bucket, blob)
            count += int(bytes(my_buffer).decode("utf-8"))
            # count += int(my_buffer.getvalue().decode("utf-8"))

        logging.info(f"WHC: word: {os.path.basename(path)}")
        logging.info(f"WHC: count: {count}")

        logging.info("======= func_1_8 execution end =======")

        return {"word": os.path.basename(path), "count": count}

    @task
    @timing
    def func_1_9(
        upstream_output_func_1_5,
        dag_id: str = "dag_w1_d10_5",
        upstream_task_id: str = "func_1_5",
        task_name: str = "func_1_9",
        enable_optimization: bool = True,
        run_id: str = "{{ run_id }}",
    ):
        current_run_id = run_id

        if enable_optimization:
            # 数据平面优化模式：并行获取上游数据和建立数据库连接
            tasks = [
                (get_upstream_task_value, (dag_id, task_name, current_run_id, upstream_task_id)),
                (storage.get_instance, ()),
            ]

            # 并行执行任务
            upstream_output, client = execute_parallel_tasks(tasks)
        else:
            # 普通模式：串行执行
            upstream_output = get_upstream_task_value(dag_id, task_name, current_run_id, upstream_task_id)
            client = storage.get_instance()

        logging.info("======= func_1_9 execution start =======")

        event = upstream_output["list"][3]

        bucket = event["bucket"]
        path = event["dir"]

        count = 0
        # each blob is one word.
        # for blob in client.list_directory(bucket, path):
        for blob in client.list_directory(bucket, path):
            my_buffer = client.download_stream(bucket, blob)
            count += int(bytes(my_buffer).decode("utf-8"))
            # count += int(my_buffer.getvalue().decode("utf-8"))

        logging.info(f"WHC: word: {os.path.basename(path)}")
        logging.info(f"WHC: count: {count}")

        logging.info("======= func_1_9 execution end =======")

        return {"word": os.path.basename(path), "count": count}

    @task
    @timing
    def func_1_10(
        upstream_output_func_1_5,
        dag_id: str = "dag_w1_d10_5",
        upstream_task_id: str = "func_1_5",
        task_name: str = "func_1_10",
        enable_optimization: bool = True,
        run_id: str = "{{ run_id }}",
    ):
        current_run_id = run_id

        if enable_optimization:
            # 数据平面优化模式：并行获取上游数据和建立数据库连接
            tasks = [
                (get_upstream_task_value, (dag_id, task_name, current_run_id, upstream_task_id)),
                (storage.get_instance, ()),
            ]

            # 并行执行任务
            upstream_output, client = execute_parallel_tasks(tasks)
        else:
            # 普通模式：串行执行
            upstream_output = get_upstream_task_value(dag_id, task_name, current_run_id, upstream_task_id)
            client = storage.get_instance()

        logging.info("======= func_1_10 execution start =======")

        event = upstream_output["list"][4]

        bucket = event["bucket"]
        path = event["dir"]

        count = 0
        # each blob is one word.
        # for blob in client.list_directory(bucket, path):
        for blob in client.list_directory(bucket, path):
            my_buffer = client.download_stream(bucket, blob)
            count += int(bytes(my_buffer).decode("utf-8"))
            # count += int(my_buffer.getvalue().decode("utf-8"))

        logging.info(f"WHC: word: {os.path.basename(path)}")
        logging.info(f"WHC: count: {count}")

        logging.info("======= func_1_10 execution end =======")

        return {"word": os.path.basename(path), "count": count}

    # DAG execution with optimization control
    _enable_optimization = False

    func_1_1_output = func_1_1(
        event=generate_input(
            size="large",
            benchmarks_bucket="sebs-benchmarks-bucket-20250917",
            input_buckets=["benchmarks/660-map-reduce"],
            output_buckets=["benchmarks/660-map-reduce"],
        )
    )

    func_1_2_output = func_1_2(
        upstream_output_func_1_1=func_1_1_output,
        dag_id="dag_w1_d10_5",
        upstream_task_id="func_1_1",
        task_name="func_1_2",
        enable_optimization=_enable_optimization,
        run_id="{{ run_id }}",
    )
    func_1_3_output = func_1_3(
        upstream_output_func_1_1=func_1_1_output,
        dag_id="dag_w1_d10_5",
        upstream_task_id="func_1_1",
        task_name="func_1_3",
        enable_optimization=_enable_optimization,
        run_id="{{ run_id }}",
    )
    func_1_4_output = func_1_4(
        upstream_output_func_1_1=func_1_1_output,
        dag_id="dag_w1_d10_5",
        upstream_task_id="func_1_1",
        task_name="func_1_4",
        enable_optimization=_enable_optimization,
        run_id="{{ run_id }}",
    )
    func_1_5_output = func_1_5(
        upstream_output_func_1_2=func_1_2_output,
        upstream_output_func_1_3=func_1_3_output,
        upstream_output_func_1_4=func_1_4_output,
        dag_id="dag_w1_d10_5",
        upstream_task_id="func_1_4",
        task_name="func_1_5",
        enable_optimization=_enable_optimization,
        run_id="{{ run_id }}",
    )
    func_1_6_output = func_1_6(
        upstream_output_func_1_5=func_1_5_output,
        dag_id="dag_w1_d10_5",
        upstream_task_id="func_1_5",
        task_name="func_1_6",
        enable_optimization=_enable_optimization,
        run_id="{{ run_id }}",
    )
    func_1_7_output = func_1_7(
        upstream_output_func_1_5=func_1_5_output,
        dag_id="dag_w1_d10_5",
        upstream_task_id="func_1_5",
        task_name="func_1_7",
        enable_optimization=_enable_optimization,
        run_id="{{ run_id }}",
    )
    func_1_8_output = func_1_8(
        upstream_output_func_1_5=func_1_5_output,
        dag_id="dag_w1_d10_5",
        upstream_task_id="func_1_5",
        task_name="func_1_8",
        enable_optimization=_enable_optimization,
        run_id="{{ run_id }}",
    )
    func_1_9_output = func_1_9(
        upstream_output_func_1_5=func_1_5_output,
        dag_id="dag_w1_d10_5",
        upstream_task_id="func_1_5",
        task_name="func_1_9",
        enable_optimization=_enable_optimization,
        run_id="{{ run_id }}",
    )
    func_1_10_output = func_1_10(
        upstream_output_func_1_5=func_1_5_output,
        dag_id="dag_w1_d10_5",
        upstream_task_id="func_1_5",
        task_name="func_1_10",
        enable_optimization=_enable_optimization,
        run_id="{{ run_id }}",
    )


# execute dag
etl_dag = dag_w1_d10_5()
