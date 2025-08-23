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
import subprocess
import shutil

# # 设置环境变量来抑制 gRPC fork 警告
# os.environ["GRPC_ENABLE_FORK_SUPPORT"] = "1"


####
# 这是ExCamera的函数，运行方法是：./scripts/8_get_e2e_breakdown.sh 1 "dag_w1_d17" 160 16


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


size_generators = {"test": (18, 6), "small": (30, 6), "large": (60, 6)}


def buckets_count():
    return (1, 1)


def generate_input(size, benchmarks_bucket, input_buckets, output_buckets):
    num_frames, batch_size = size_generators[size]

    # for small size
    new_vid_segs = [
        "00000000.y4m",
        "00000001.y4m",
        "00000002.y4m",
        "00000003.y4m",
        "00000004.y4m",
        "00000005.y4m",
        "00000006.y4m",
        "00000007.y4m",
        "00000008.y4m",
        "00000009.y4m",
        "00000010.y4m",
        "00000011.y4m",
        "00000012.y4m",
        "00000013.y4m",
        "00000014.y4m",
        "00000015.y4m",
        "00000016.y4m",
        "00000017.y4m",
        "00000018.y4m",
        "00000019.y4m",
        "00000020.y4m",
        "00000021.y4m",
        "00000022.y4m",
        "00000023.y4m",
        "00000024.y4m",
        "00000025.y4m",
        "00000026.y4m",
        "00000027.y4m",
        "00000028.y4m",
        "00000029.y4m",
    ]

    return {
        "segments": new_vid_segs,
        "benchmark_bucket": benchmarks_bucket,
        "input_bucket": input_buckets[0],
        "output_bucket": output_buckets[0],
        "batch_size": batch_size,
        "quality": 1,
    }


def chunks(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


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


VPXENC = "/tmp/vpxenc --ivf --codec=vp8 --good --cpu-used=0 --end-usage=cq --min-q=0 --max-q=63 --cq-level={quality} --buf-initial-sz=10000 --buf-optimal-sz=20000 --buf-sz=40000 --undershoot-pct=100 --passes=2 --auto-alt-ref=1 --threads=1 --token-parts=0 --tune=ssim --target-bitrate=4294967295 -o {output}.ivf {input}.y4m"
TERMINATE_CHUNK = "/tmp/xc-terminate-chunk {input}.ivf {output}.ivf"
XC_DUMP_0 = "/tmp/xc-dump {input}.ivf {output}.state"


def download_bin(benchmark_bucket, bucket, name, dest_dir):
    client = storage.get_instance()
    path = os.path.join(dest_dir, name)
    if not os.path.exists(path):
        client.download(benchmark_bucket, bucket + "/" + name, path)
        os.system(f"chmod +x {path} > /dev/null 2>&1")


def upload_files(benchmark_bucket, bucket, paths, prefix):
    client = storage.get_instance()
    for path in paths:
        file = os.path.basename(path)
        file = prefix + file
        logging.info("WHCWHC: Uploading %s to %s", file, path)
        client.upload(benchmark_bucket, bucket + "/" + file, path, unique_name=False)


def run(cmd):
    try:
        # 使用 os.system 避免 gRPC fork 警告，并重定向输出到 /dev/null
        silent_cmd = f"{cmd} > /dev/null 2>&1"
        exit_code = os.system(silent_cmd)
        if exit_code != 0:
            logger = logging.getLogger()
            logger.error(f"Error when executing command: {cmd}, exit code: {exit_code}")
            raise subprocess.CalledProcessError(exit_code, cmd)
        return b""  # os.system 不返回输出，但保持兼容性
    except Exception as e:
        logger = logging.getLogger()
        logger.error(f"Error when executing command: {cmd}\n{str(e)}")
        raise e


def encode(segs, data_dir, quality):
    files = []

    for idx, name in enumerate(segs):
        input_path = os.path.join(data_dir, name)
        output_path = os.path.join(data_dir, f"{name}-vpxenc")
        cmd = VPXENC.format(quality=quality, input=input_path, output=output_path)
        run(cmd)

        input_path = output_path
        output = name if idx == 0 else f"{name}-0"
        output_path = os.path.join(data_dir, output)
        cmd = TERMINATE_CHUNK.format(input=input_path, output=output_path)
        run(cmd)
        files.append(output_path + ".ivf")

        input_path = output_path
        output_path = os.path.join(data_dir, f"{name}-0")
        cmd = XC_DUMP_0.format(input=input_path, output=output_path)
        run(cmd)
        files.append(output_path + ".state")

    return files


XC_ENC_FIRST_FRAME = "/tmp/xc-enc -W -w 0.75 -i y4m -o {output}.ivf -r -I {source_state}.state -p {input_pred}.ivf {extra} {input}.y4m"


def prev_seg_name(seg):
    idx = int(seg) - 1
    assert idx >= 0
    return "{:08d}".format(idx)


def reencode_first_frame(segs, data_dir, dry_run=False):
    input_paths = []
    output_paths = []
    for idx in range(1, len(segs)):
        name = segs[idx]
        input_path = os.path.join(data_dir, name)
        output_path = input_path if idx == 1 else f"{input_path}-1"
        source_state_path = os.path.join(data_dir, prev_seg_name(name)) + "-0"
        output_state_path = f"{input_path}-1.state"
        extra = f"-O {output_state_path}" if idx == 1 else ""
        input_pred_path = f"{input_path}-0"

        cmd = XC_ENC_FIRST_FRAME.format(
            input=input_path,
            output=output_path,
            source_state=source_state_path,
            extra=extra,
            input_pred=input_pred_path,
        )
        if not dry_run:
            run(cmd)

        input_paths.append(input_path + ".y4m")
        input_paths.append(source_state_path + ".state")
        input_paths.append(input_pred_path + ".ivf")

        output_paths.append(output_path + ".ivf")
        if idx == 1:
            output_paths.append(output_state_path)

    return input_paths, output_paths


XC_ENC_REBASE = "/tmp/xc-enc -W -w 0.75 -i y4m -o {output}.ivf -r -I {source_state}.state -p {input_pred}.ivf -S {pred_state}.state {extra} {input}.y4m"


def rebase(segs, data_dir, dry_run=False):
    input_paths = []
    output_paths = []

    for idx in range(2, len(segs)):
        name = segs[idx]
        input_path = os.path.join(data_dir, name)
        prev_input_path = os.path.join(data_dir, prev_seg_name(name))
        source_state_path = f"{prev_input_path}-1"
        output_state_path = f"{input_path}-1.state"
        extra = f"-O {output_state_path}" if idx != len(segs) - 1 else ""
        input_pred_path = f"{input_path}-1"
        pred_state_path = f"{prev_input_path}-0"

        cmd = XC_ENC_REBASE.format(
            output=input_path,
            input=input_path,
            source_state=source_state_path,
            extra=extra,
            input_pred=input_pred_path,
            pred_state=pred_state_path,
        )
        if not dry_run:
            run(cmd)

        input_paths.append(input_path + ".y4m")
        input_paths.append(source_state_path + ".state")
        input_paths.append(input_pred_path + ".ivf")
        input_paths.append(pred_state_path + ".state")

        output_paths.append(input_path + ".ivf")
        if idx != len(segs) - 1:
            output_paths.append(output_state_path)

    return input_paths, output_paths


@dag(
    schedule_interval=None,
    start_date=pendulum.datetime(2021, 1, 1, tz="UTC"),
    catchup=False,
    is_paused_upon_creation=False,
)
def dag_w1_d17():
    @task
    @timing
    def func_1_1(event):
        logging.info("======= begin: func_1_1 execution =======")

        segs = chunks(event["segments"], event["batch_size"])
        input_bucket = event["input_bucket"]
        output_bucket = event["output_bucket"]
        benchmark_bucket = event["benchmark_bucket"]
        quality = event["quality"]

        return {
            "segments": [
                {
                    "prefix": str(uuid.uuid4().int & (1 << 64) - 1)[:8],
                    "segments": ss,
                    "quality": quality,
                    "input_bucket": input_bucket,
                    "output_bucket": output_bucket,
                    "benchmark_bucket": benchmark_bucket,
                }
                for idx, ss in enumerate(segs)
            ]
        }

    @task
    @timing
    def func_1_2(
        upstream_output_func_1_1,
        dag_id: str = "dag_w1_d17",
        upstream_task_id: str = "func_1_1",
        task_name: str = "func_1_2",
        enable_optimization: bool = True,
    ):
        logging.info("======= func_1_2 execution =======")

        event = upstream_output_func_1_1["segments"][0]

        client = storage.get_instance()

        input_bucket = event["input_bucket"]
        output_bucket = event["output_bucket"]
        benchmark_bucket = event["benchmark_bucket"]
        segs = event["segments"]
        quality = event["quality"]
        prefix = event["prefix"]

        tmp_dir = "/tmp"
        download_bin(benchmark_bucket, input_bucket, "vpxenc", tmp_dir)
        download_bin(benchmark_bucket, input_bucket, "xc-terminate-chunk", tmp_dir)
        download_bin(benchmark_bucket, input_bucket, "xc-dump", tmp_dir)

        data_dir = os.path.join(tmp_dir, str(uuid.uuid4()))
        os.makedirs(data_dir, exist_ok=True)
        for seg in segs:
            path = os.path.join(data_dir, seg)
            client.download(benchmark_bucket, input_bucket + "/" + seg, path)

        segs = [os.path.splitext(seg)[0] for seg in segs]
        output_paths = encode(segs, data_dir, quality)
        upload_files(benchmark_bucket, output_bucket, output_paths, prefix)

        shutil.rmtree(data_dir)

        return upstream_output_func_1_1

    @task
    @timing
    def func_1_3(
        upstream_output_func_1_2,
        dag_id: str = "dag_w1_d17",
        upstream_task_id: str = "func_1_2",
        task_name: str = "func_1_3",
        enable_optimization: bool = True,
    ):
        logging.info("======= func_1_3 execution =======")

        event = upstream_output_func_1_2["segments"][0]

        client = storage.get_instance()

        input_bucket = event["input_bucket"]
        output_bucket = event["output_bucket"]
        benchmark_bucket = event["benchmark_bucket"]
        segs = event["segments"]
        segs = [os.path.splitext(seg)[0] for seg in segs]
        prefix = event["prefix"]

        tmp_dir = "/tmp"
        download_bin(benchmark_bucket, input_bucket, "xc-enc", tmp_dir)

        data_dir = os.path.join(tmp_dir, str(uuid.uuid4()))
        os.makedirs(data_dir, exist_ok=True)
        input_paths, _ = reencode_first_frame(segs, data_dir, dry_run=True)
        for path in input_paths:
            file = os.path.basename(path)

            if ".y4m" in file:
                client.download(benchmark_bucket, input_bucket + "/" + file, path)
            else:
                file = prefix + file
                client.download(benchmark_bucket, output_bucket + "/" + file, path)

        _, output_paths = reencode_first_frame(segs, data_dir)
        upload_files(benchmark_bucket, output_bucket, output_paths, prefix)

        shutil.rmtree(data_dir)

        return upstream_output_func_1_2

    @task
    @timing
    def func_1_4(
        upstream_output_func_1_3,
        dag_id: str = "dag_w1_d17",
        upstream_task_id: str = "func_1_3",
        task_name: str = "func_1_4",
        enable_optimization: bool = True,
    ):
        logging.info("======= func_1_4 execution =======")

        event = upstream_output_func_1_3["segments"][0]

        client = storage.get_instance()

        input_bucket = event["input_bucket"]
        output_bucket = event["output_bucket"]
        benchmark_bucket = event["benchmark_bucket"]
        segs = event["segments"]
        segs = [os.path.splitext(seg)[0] for seg in segs]
        prefix = event["prefix"]

        tmp_dir = "/tmp"
        download_bin(benchmark_bucket, input_bucket, "xc-enc", tmp_dir)

        data_dir = os.path.join(tmp_dir, str(uuid.uuid4()))
        os.makedirs(data_dir, exist_ok=True)

        input_paths, _ = rebase(segs, data_dir, dry_run=True)

        for path in input_paths:
            file = os.path.basename(path)

            try:
                if ".y4m" in file:
                    client.download(benchmark_bucket, input_bucket + '/' + file, path)
                else:
                    file = prefix + file
                    client.download(benchmark_bucket, output_bucket + '/' + file, path)
            except:
                # -1.state is generated by rebase itself
                if not "-1.state" in file:
                    raise

        _, output_paths = rebase(segs, data_dir)

        logging.info("WHCWHC: final upload")
        upload_files(benchmark_bucket, output_bucket, output_paths, prefix)

        shutil.rmtree(data_dir)

        return upstream_output_func_1_3

    @task
    @timing
    def func_1_5(
        upstream_output_func_1_1,
        dag_id: str = "dag_w1_d17",
        upstream_task_id: str = "func_1_4",
        task_name: str = "func_1_5",
        enable_optimization: bool = True,
    ):
        logging.info("======= func_1_5 execution =======")

        event = upstream_output_func_1_1["segments"][1]

        client = storage.get_instance()

        input_bucket = event["input_bucket"]
        output_bucket = event["output_bucket"]
        benchmark_bucket = event["benchmark_bucket"]
        segs = event["segments"]
        quality = event["quality"]
        prefix = event["prefix"]

        tmp_dir = "/tmp"
        download_bin(benchmark_bucket, input_bucket, "vpxenc", tmp_dir)
        download_bin(benchmark_bucket, input_bucket, "xc-terminate-chunk", tmp_dir)
        download_bin(benchmark_bucket, input_bucket, "xc-dump", tmp_dir)

        data_dir = os.path.join(tmp_dir, str(uuid.uuid4()))
        os.makedirs(data_dir, exist_ok=True)
        for seg in segs:
            path = os.path.join(data_dir, seg)
            client.download(benchmark_bucket, input_bucket + "/" + seg, path)

        segs = [os.path.splitext(seg)[0] for seg in segs]
        output_paths = encode(segs, data_dir, quality)
        upload_files(benchmark_bucket, output_bucket, output_paths, prefix)

        shutil.rmtree(data_dir)

        return upstream_output_func_1_1

    @task
    @timing
    def func_1_6(
        upstream_output_func_1_5,
        dag_id: str = "dag_w1_d17",
        upstream_task_id: str = "func_1_5",
        task_name: str = "func_1_6",
        enable_optimization: bool = True,
    ):
        logging.info("======= func_1_6 execution =======")

        event = upstream_output_func_1_5["segments"][1]

        client = storage.get_instance()

        input_bucket = event["input_bucket"]
        output_bucket = event["output_bucket"]
        benchmark_bucket = event["benchmark_bucket"]
        segs = event["segments"]
        segs = [os.path.splitext(seg)[0] for seg in segs]
        prefix = event["prefix"]

        tmp_dir = "/tmp"
        download_bin(benchmark_bucket, input_bucket, "xc-enc", tmp_dir)

        data_dir = os.path.join(tmp_dir, str(uuid.uuid4()))
        os.makedirs(data_dir, exist_ok=True)
        input_paths, _ = reencode_first_frame(segs, data_dir, dry_run=True)
        for path in input_paths:
            file = os.path.basename(path)

            if ".y4m" in file:
                client.download(benchmark_bucket, input_bucket + "/" + file, path)
            else:
                file = prefix + file
                client.download(benchmark_bucket, output_bucket + "/" + file, path)

        _, output_paths = reencode_first_frame(segs, data_dir)
        upload_files(benchmark_bucket, output_bucket, output_paths, prefix)

        shutil.rmtree(data_dir)

        return upstream_output_func_1_5

    @task
    @timing
    def func_1_7(
        upstream_output_func_1_6,
        dag_id: str = "dag_w1_d17",
        upstream_task_id: str = "func_1_6",
        task_name: str = "func_1_7",
        enable_optimization: bool = True,
    ):
        logging.info("======= func_1_7 execution =======")

        event = upstream_output_func_1_6["segments"][1]

        client = storage.get_instance()

        input_bucket = event["input_bucket"]
        output_bucket = event["output_bucket"]
        benchmark_bucket = event["benchmark_bucket"]
        segs = event["segments"]
        segs = [os.path.splitext(seg)[0] for seg in segs]
        prefix = event["prefix"]

        tmp_dir = "/tmp"
        download_bin(benchmark_bucket, input_bucket, "xc-enc", tmp_dir)

        data_dir = os.path.join(tmp_dir, str(uuid.uuid4()))
        os.makedirs(data_dir, exist_ok=True)

        input_paths, _ = rebase(segs, data_dir, dry_run=True)

        for path in input_paths:
            file = os.path.basename(path)

            try:
                if ".y4m" in file:
                    client.download(benchmark_bucket, input_bucket + '/' + file, path)
                else:
                    file = prefix + file
                    client.download(benchmark_bucket, output_bucket + '/' + file, path)
            except:
                # -1.state is generated by rebase itself
                if not "-1.state" in file:
                    raise

        _, output_paths = rebase(segs, data_dir)

        logging.info("WHCWHC: final upload")
        upload_files(benchmark_bucket, output_bucket, output_paths, prefix)

        shutil.rmtree(data_dir)

        return upstream_output_func_1_6

    @task
    @timing
    def func_1_8(
        upstream_output_func_1_1,
        dag_id: str = "dag_w1_d17",
        upstream_task_id: str = "func_1_7",
        task_name: str = "func_1_8",
        enable_optimization: bool = True,
    ):
        logging.info("======= func_1_8 execution =======")

        event = upstream_output_func_1_1["segments"][2]

        client = storage.get_instance()

        input_bucket = event["input_bucket"]
        output_bucket = event["output_bucket"]
        benchmark_bucket = event["benchmark_bucket"]
        segs = event["segments"]
        quality = event["quality"]
        prefix = event["prefix"]

        tmp_dir = "/tmp"
        download_bin(benchmark_bucket, input_bucket, "vpxenc", tmp_dir)
        download_bin(benchmark_bucket, input_bucket, "xc-terminate-chunk", tmp_dir)
        download_bin(benchmark_bucket, input_bucket, "xc-dump", tmp_dir)

        data_dir = os.path.join(tmp_dir, str(uuid.uuid4()))
        os.makedirs(data_dir, exist_ok=True)
        for seg in segs:
            path = os.path.join(data_dir, seg)
            client.download(benchmark_bucket, input_bucket + "/" + seg, path)

        segs = [os.path.splitext(seg)[0] for seg in segs]
        output_paths = encode(segs, data_dir, quality)
        upload_files(benchmark_bucket, output_bucket, output_paths, prefix)

        shutil.rmtree(data_dir)

        return upstream_output_func_1_1

    @task
    @timing
    def func_1_9(
        upstream_output_func_1_8,
        dag_id: str = "dag_w1_d17",
        upstream_task_id: str = "func_1_8",
        task_name: str = "func_1_9",
        enable_optimization: bool = True,
    ):
        logging.info("======= func_1_9 execution =======")

        event = upstream_output_func_1_8["segments"][2]

        client = storage.get_instance()

        input_bucket = event["input_bucket"]
        output_bucket = event["output_bucket"]
        benchmark_bucket = event["benchmark_bucket"]
        segs = event["segments"]
        segs = [os.path.splitext(seg)[0] for seg in segs]
        prefix = event["prefix"]

        tmp_dir = "/tmp"
        download_bin(benchmark_bucket, input_bucket, "xc-enc", tmp_dir)

        data_dir = os.path.join(tmp_dir, str(uuid.uuid4()))
        os.makedirs(data_dir, exist_ok=True)
        input_paths, _ = reencode_first_frame(segs, data_dir, dry_run=True)
        for path in input_paths:
            file = os.path.basename(path)

            if ".y4m" in file:
                client.download(benchmark_bucket, input_bucket + "/" + file, path)
            else:
                file = prefix + file
                client.download(benchmark_bucket, output_bucket + "/" + file, path)

        _, output_paths = reencode_first_frame(segs, data_dir)
        upload_files(benchmark_bucket, output_bucket, output_paths, prefix)

        shutil.rmtree(data_dir)

        return upstream_output_func_1_8

    @task
    @timing
    def func_1_10(
        upstream_output_func_1_9,
        dag_id: str = "dag_w1_d17",
        upstream_task_id: str = "func_1_9",
        task_name: str = "func_1_10",
        enable_optimization: bool = True,
    ):
        logging.info("======= func_1_10 execution =======")

        event = upstream_output_func_1_9["segments"][2]

        client = storage.get_instance()

        input_bucket = event["input_bucket"]
        output_bucket = event["output_bucket"]
        benchmark_bucket = event["benchmark_bucket"]
        segs = event["segments"]
        segs = [os.path.splitext(seg)[0] for seg in segs]
        prefix = event["prefix"]

        tmp_dir = "/tmp"
        download_bin(benchmark_bucket, input_bucket, "xc-enc", tmp_dir)

        data_dir = os.path.join(tmp_dir, str(uuid.uuid4()))
        os.makedirs(data_dir, exist_ok=True)

        input_paths, _ = rebase(segs, data_dir, dry_run=True)

        for path in input_paths:
            file = os.path.basename(path)

            try:
                if ".y4m" in file:
                    client.download(benchmark_bucket, input_bucket + '/' + file, path)
                else:
                    file = prefix + file
                    client.download(benchmark_bucket, output_bucket + '/' + file, path)
            except:
                # -1.state is generated by rebase itself
                if not "-1.state" in file:
                    raise

        _, output_paths = rebase(segs, data_dir)

        logging.info("WHCWHC: final upload")
        upload_files(benchmark_bucket, output_bucket, output_paths, prefix)

        shutil.rmtree(data_dir)

        return upstream_output_func_1_9

    @task
    @timing
    def func_1_11(
        upstream_output_func_1_1,
        dag_id: str = "dag_w1_d17",
        upstream_task_id: str = "func_1_10",
        task_name: str = "func_1_11",
        enable_optimization: bool = True,
    ):
        logging.info("======= func_1_11 execution =======")

        event = upstream_output_func_1_1["segments"][3]

        client = storage.get_instance()

        input_bucket = event["input_bucket"]
        output_bucket = event["output_bucket"]
        benchmark_bucket = event["benchmark_bucket"]
        segs = event["segments"]
        quality = event["quality"]
        prefix = event["prefix"]

        tmp_dir = "/tmp"
        download_bin(benchmark_bucket, input_bucket, "vpxenc", tmp_dir)
        download_bin(benchmark_bucket, input_bucket, "xc-terminate-chunk", tmp_dir)
        download_bin(benchmark_bucket, input_bucket, "xc-dump", tmp_dir)

        data_dir = os.path.join(tmp_dir, str(uuid.uuid4()))
        os.makedirs(data_dir, exist_ok=True)
        for seg in segs:
            path = os.path.join(data_dir, seg)
            client.download(benchmark_bucket, input_bucket + "/" + seg, path)

        segs = [os.path.splitext(seg)[0] for seg in segs]
        output_paths = encode(segs, data_dir, quality)
        upload_files(benchmark_bucket, output_bucket, output_paths, prefix)

        shutil.rmtree(data_dir)

        return upstream_output_func_1_1

    @task
    @timing
    def func_1_12(
        upstream_output_func_1_11,
        dag_id: str = "dag_w1_d17",
        upstream_task_id: str = "func_1_11",
        task_name: str = "func_1_12",
        enable_optimization: bool = True,
    ):
        logging.info("======= func_1_12 execution =======")
        
        event = upstream_output_func_1_11["segments"][3]

        client = storage.get_instance()

        input_bucket = event["input_bucket"]
        output_bucket = event["output_bucket"]
        benchmark_bucket = event["benchmark_bucket"]
        segs = event["segments"]
        segs = [os.path.splitext(seg)[0] for seg in segs]
        prefix = event["prefix"]

        tmp_dir = "/tmp"
        download_bin(benchmark_bucket, input_bucket, "xc-enc", tmp_dir)

        data_dir = os.path.join(tmp_dir, str(uuid.uuid4()))
        os.makedirs(data_dir, exist_ok=True)
        input_paths, _ = reencode_first_frame(segs, data_dir, dry_run=True)
        for path in input_paths:
            file = os.path.basename(path)

            if ".y4m" in file:
                client.download(benchmark_bucket, input_bucket + "/" + file, path)
            else:
                file = prefix + file
                client.download(benchmark_bucket, output_bucket + "/" + file, path)

        _, output_paths = reencode_first_frame(segs, data_dir)
        upload_files(benchmark_bucket, output_bucket, output_paths, prefix)

        shutil.rmtree(data_dir)

        return upstream_output_func_1_11

    @task
    @timing
    def func_1_13(
        upstream_output_func_1_12,
        dag_id: str = "dag_w1_d17",
        upstream_task_id: str = "func_1_12",
        task_name: str = "func_1_13",
        enable_optimization: bool = True,
    ):
        logging.info("======= func_1_13 execution =======")

        event = upstream_output_func_1_12["segments"][3]

        client = storage.get_instance()

        input_bucket = event["input_bucket"]
        output_bucket = event["output_bucket"]
        benchmark_bucket = event["benchmark_bucket"]
        segs = event["segments"]
        segs = [os.path.splitext(seg)[0] for seg in segs]
        prefix = event["prefix"]

        tmp_dir = "/tmp"
        download_bin(benchmark_bucket, input_bucket, "xc-enc", tmp_dir)

        data_dir = os.path.join(tmp_dir, str(uuid.uuid4()))
        os.makedirs(data_dir, exist_ok=True)

        input_paths, _ = rebase(segs, data_dir, dry_run=True)

        for path in input_paths:
            file = os.path.basename(path)

            try:
                if ".y4m" in file:
                    client.download(benchmark_bucket, input_bucket + '/' + file, path)
                else:
                    file = prefix + file
                    client.download(benchmark_bucket, output_bucket + '/' + file, path)
            except:
                # -1.state is generated by rebase itself
                if not "-1.state" in file:
                    raise

        _, output_paths = rebase(segs, data_dir)

        logging.info("WHCWHC: final upload")
        upload_files(benchmark_bucket, output_bucket, output_paths, prefix)

        shutil.rmtree(data_dir)

        return upstream_output_func_1_12

    @task
    @timing
    def func_1_14(
        upstream_output_func_1_1,
        dag_id: str = "dag_w1_d17",
        upstream_task_id: str = "func_1_13",
        task_name: str = "func_1_14",
        enable_optimization: bool = True,
    ):
        logging.info("======= func_1_14 execution =======")

        event = upstream_output_func_1_1["segments"][4]

        client = storage.get_instance()

        input_bucket = event["input_bucket"]
        output_bucket = event["output_bucket"]
        benchmark_bucket = event["benchmark_bucket"]
        segs = event["segments"]
        quality = event["quality"]
        prefix = event["prefix"]

        tmp_dir = "/tmp"
        download_bin(benchmark_bucket, input_bucket, "vpxenc", tmp_dir)
        download_bin(benchmark_bucket, input_bucket, "xc-terminate-chunk", tmp_dir)
        download_bin(benchmark_bucket, input_bucket, "xc-dump", tmp_dir)

        data_dir = os.path.join(tmp_dir, str(uuid.uuid4()))
        os.makedirs(data_dir, exist_ok=True)
        for seg in segs:
            path = os.path.join(data_dir, seg)
            client.download(benchmark_bucket, input_bucket + "/" + seg, path)

        segs = [os.path.splitext(seg)[0] for seg in segs]
        output_paths = encode(segs, data_dir, quality)
        upload_files(benchmark_bucket, output_bucket, output_paths, prefix)

        shutil.rmtree(data_dir)

        return upstream_output_func_1_1

    @task
    @timing
    def func_1_15(
        upstream_output_func_1_14,
        dag_id: str = "dag_w1_d17",
        upstream_task_id: str = "func_1_14",
        task_name: str = "func_1_15",
        enable_optimization: bool = True,
    ):
        logging.info("======= func_1_15 execution =======")

        event = upstream_output_func_1_14["segments"][4]

        client = storage.get_instance()

        input_bucket = event["input_bucket"]
        output_bucket = event["output_bucket"]
        benchmark_bucket = event["benchmark_bucket"]
        segs = event["segments"]
        segs = [os.path.splitext(seg)[0] for seg in segs]
        prefix = event["prefix"]

        tmp_dir = "/tmp"
        download_bin(benchmark_bucket, input_bucket, "xc-enc", tmp_dir)

        data_dir = os.path.join(tmp_dir, str(uuid.uuid4()))
        os.makedirs(data_dir, exist_ok=True)
        input_paths, _ = reencode_first_frame(segs, data_dir, dry_run=True)
        for path in input_paths:
            file = os.path.basename(path)

            if ".y4m" in file:
                client.download(benchmark_bucket, input_bucket + "/" + file, path)
            else:
                file = prefix + file
                client.download(benchmark_bucket, output_bucket + "/" + file, path)

        _, output_paths = reencode_first_frame(segs, data_dir)
        upload_files(benchmark_bucket, output_bucket, output_paths, prefix)

        shutil.rmtree(data_dir)

        return upstream_output_func_1_14

    @task
    @timing
    def func_1_16(
        upstream_output_func_1_15,
        dag_id: str = "dag_w1_d17",
        upstream_task_id: str = "func_1_15",
        task_name: str = "func_1_16",
        enable_optimization: bool = True,
    ):
        logging.info("======= func_1_16 execution =======")

        event = upstream_output_func_1_15["segments"][4]

        client = storage.get_instance()

        input_bucket = event["input_bucket"]
        output_bucket = event["output_bucket"]
        benchmark_bucket = event["benchmark_bucket"]
        segs = event["segments"]
        segs = [os.path.splitext(seg)[0] for seg in segs]
        prefix = event["prefix"]

        tmp_dir = "/tmp"
        download_bin(benchmark_bucket, input_bucket, "xc-enc", tmp_dir)

        data_dir = os.path.join(tmp_dir, str(uuid.uuid4()))
        os.makedirs(data_dir, exist_ok=True)

        input_paths, _ = rebase(segs, data_dir, dry_run=True)

        for path in input_paths:
            file = os.path.basename(path)

            try:
                if ".y4m" in file:
                    client.download(benchmark_bucket, input_bucket + '/' + file, path)
                else:
                    file = prefix + file
                    client.download(benchmark_bucket, output_bucket + '/' + file, path)
            except:
                # -1.state is generated by rebase itself
                if not "-1.state" in file:
                    raise

        _, output_paths = rebase(segs, data_dir)

        logging.info("WHCWHC: final upload")
        upload_files(benchmark_bucket, output_bucket, output_paths, prefix)

        shutil.rmtree(data_dir)

        return upstream_output_func_1_15


    # DAG execution with optimization control
    _enable_optimization = False

    func_1_1_output = func_1_1(
        event=generate_input(
            size="small",
            benchmarks_bucket="sebs-benchmarks-bucket-20250917",
            input_buckets=["benchmarks/680-excamera"],
            output_buckets=["benchmarks/680-excamera"],
        )
    )

    func_1_2_output = func_1_2(
        upstream_output_func_1_1=func_1_1_output,
        dag_id="dag_w1_d17",
        upstream_task_id="func_1_1",
        task_name="func_1_2",
        enable_optimization=_enable_optimization,
    )
    func_1_3_output = func_1_3(
        upstream_output_func_1_2=func_1_2_output,
        dag_id="dag_w1_d17",
        upstream_task_id="func_1_1",
        task_name="func_1_3",
        enable_optimization=_enable_optimization,
    )
    func_1_4_output = func_1_4(
        upstream_output_func_1_3=func_1_3_output,
        dag_id="dag_w1_d17",
        upstream_task_id="func_1_1",
        task_name="func_1_4",
        enable_optimization=_enable_optimization,
    )
    func_1_5_output = func_1_5(
        upstream_output_func_1_1=func_1_1_output,
        dag_id="dag_w1_d17",
        upstream_task_id="func_1_4",
        task_name="func_1_5",
        enable_optimization=_enable_optimization,
    )
    func_1_6_output = func_1_6(
        upstream_output_func_1_5=func_1_5_output,
        dag_id="dag_w1_d17",
        upstream_task_id="func_1_5",
        task_name="func_1_6",
        enable_optimization=_enable_optimization,
    )
    func_1_7_output = func_1_7(
        upstream_output_func_1_6=func_1_6_output,
        dag_id="dag_w1_d17",
        upstream_task_id="func_1_5",
        task_name="func_1_7",
        enable_optimization=_enable_optimization,
    )
    func_1_8_output = func_1_8(
        upstream_output_func_1_1=func_1_1_output,
        dag_id="dag_w1_d17",
        upstream_task_id="func_1_5",
        task_name="func_1_8",
        enable_optimization=_enable_optimization,
    )
    func_1_9_output = func_1_9(
        upstream_output_func_1_8=func_1_8_output,
        dag_id="dag_w1_d17",
        upstream_task_id="func_1_5",
        task_name="func_1_9",
        enable_optimization=_enable_optimization,
    )
    func_1_10_output = func_1_10(
        upstream_output_func_1_9=func_1_9_output,
        dag_id="dag_w1_d17",
        upstream_task_id="func_1_5",
        task_name="func_1_10",
        enable_optimization=_enable_optimization,
    )
    func_1_11_output = func_1_11(
        upstream_output_func_1_1=func_1_1_output,
        dag_id="dag_w1_d17",
        upstream_task_id="func_1_5",
        task_name="func_1_11",
        enable_optimization=_enable_optimization,
    )
    func_1_12_output = func_1_12(
        upstream_output_func_1_11=func_1_11_output,
        dag_id="dag_w1_d17",
        upstream_task_id="func_1_5",
        task_name="func_1_12",
        enable_optimization=_enable_optimization,
    )
    func_1_13_output = func_1_13(
        upstream_output_func_1_12=func_1_12_output,
        dag_id="dag_w1_d17",
        upstream_task_id="func_1_5",
        task_name="func_1_13",
        enable_optimization=_enable_optimization,
    )
    func_1_14_output = func_1_14(
        upstream_output_func_1_1=func_1_1_output,
        dag_id="dag_w1_d17",
        upstream_task_id="func_1_5",
        task_name="func_1_14",
        enable_optimization=_enable_optimization,
    )
    func_1_15_output = func_1_15(
        upstream_output_func_1_14=func_1_14_output,
        dag_id="dag_w1_d17",
        upstream_task_id="func_1_5",
        task_name="func_1_15",
        enable_optimization=_enable_optimization,
    )
    func_1_16_output = func_1_16(
        upstream_output_func_1_15=func_1_15_output,
        dag_id="dag_w1_d17",
        upstream_task_id="func_1_5",
        task_name="func_1_16",
        enable_optimization=_enable_optimization,
    )


# execute dag
etl_dag = dag_w1_d17()