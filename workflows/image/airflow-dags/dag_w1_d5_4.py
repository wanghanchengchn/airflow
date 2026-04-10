from math import log
import pendulum
from airflow.decorators import dag, task
import logging
from functools import wraps
from time import time
import time as t_module
from airflow.models import TaskInstance
from airflow.settings import Session
from concurrent.futures import ThreadPoolExecutor, TimeoutError, wait, FIRST_COMPLETED
import uuid
import copy
from typing import Dict, Any, Tuple, Optional, Union, List
from decimal import Decimal
from os import environ
import boto3
import os
import io
import cv2

#### 
# 这是vid的函数，运行方法是：./scripts/8_get_e2e_breakdown.sh 1 "dag_w1_d5_4" 40 4

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


size_generators = {
    "test" : (3, 10, "video_test.mp4"),
    "small": (10, 5, "video_small.mp4"),
    "large": (1000, 3, "video_large.mp4"),
}


def buckets_count():
    return (1, 1)


def generate_input(size, benchmarks_bucket, input_buckets, output_buckets):
    n_frames, batch_size, video_name = size_generators[size]
    files = ["frozen_inference_graph.pb", "faster_rcnn_resnet50_coco_2018_01_28.pbtxt", video_name]

    return {
        "video": video_name,
        "n_frames": n_frames,
        "batch_size": batch_size,
        "frames_bucket": output_buckets[0],
        "benchmark_bucket": benchmarks_bucket,
        "input_bucket": input_buckets[0],
        "model_weights": files[0],
        "model_config": files[1]
    }


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
            's3',
            region_name="us-east-1",
            aws_access_key_id="<WHC_AWS_KEY>",
            aws_secret_access_key="<WHC_AWS_SECRET>"
        )

    @staticmethod
    def unique_name(name):
        name, extension = os.path.splitext(name)
        return '{name}.{random}{extension}'.format(
                    name=name,
                    extension=extension,
                    random=str(uuid.uuid4()).split('-')[0]
                )

    def upload(self, bucket, file, filepath, unique_name = True):
        incr_io_env_file(filepath, "STORAGE_UPLOAD_BYTES")

        key_name = storage.unique_name(file) if unique_name else file
        self.client.upload_file(filepath, bucket, key_name)
        return key_name

    def download(self, bucket, file, filepath):
        self.client.download_file(bucket, file, filepath)
        incr_io_env_file(filepath, "STORAGE_DOWNLOAD_BYTES")

    def download_directory(self, bucket, prefix, path):
        objects = self.client.list_objects_v2(Bucket=bucket, Prefix=prefix)
        for obj in objects['Contents']:
            file_name = obj['Key']
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
        resp = self.client.get_object(Bucket=bucket, Key=file, Range='bytes={}-{}'.format(start_byte, stop_byte))
        return resp['Body'].read().decode('utf-8')

    def list_directory(self, bucket, prefix):
        objects = self.client.list_objects_v2(Bucket=bucket, Prefix=prefix)
        for obj in objects['Contents']:
            yield obj['Key']

    def get_instance():
        if storage.instance is None:
            storage.instance = storage()
        return storage.instance


def chunks(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


def load_video(benchmark_bucket, bucket, blob, dest_dir):
    client = storage.get_instance()

    path = os.path.join(dest_dir, blob)
    client.download(benchmark_bucket, bucket + '/' + blob, path)
    return path


def decode_video(path, n_frames, dest_dir):
    vidcap = cv2.VideoCapture(path)
    success, img = vidcap.read()
    img_paths = []
    while success and len(img_paths) < n_frames:
        img_path = os.path.join(dest_dir, f"frame{len(img_paths)}.jpg")
        img_paths.append(img_path)
        cv2.imwrite(img_path, img)
        success, img = vidcap.read()

    return img_paths


def upload_imgs(benchmark_bucket, bucket, paths):
    client = storage.get_instance()

    for path in paths:
        name = os.path.basename(path)
        yield client.upload(benchmark_bucket, bucket + '/' + name, path)


labels = ["person", "bicycle", "car", "motorcycle",
"airplane", "bus", "train", "truck", "boat", "traffic light", "fire hydrant",
"stop sign", "parking meter", "bench", "bird", "cat", "dog", "horse",
"sheep", "cow", "elephant", "bear", "zebra", "giraffe", "backpack",
"umbrella", "handbag", "tie", "suitcase", "frisbee", "skis",
"snowboard", "sports ball", "kite", "baseball bat", "baseball glove", "skateboard",
"surfboard", "tennis racket", "bottle", "wine glass", "cup", "fork", "knife",
"spoon", "bowl", "banana", "apple", "sandwich", "orange", "broccoli", "carrot", "hot dog",
"pizza", "donut", "cake", "chair", "couch", "potted plant", "bed", "dining table",
"toilet", "tv", "laptop", "mouse", "remote", "keyboard",
"cell phone", "microwave", "oven", "toaster", "sink", "refrigerator",
"book", "clock", "vase", "scissors", "teddy bear", "hair drier", "toothbrush" ]


def load_model(bucket, weights_blob, config_blob, dest_dir):
    client = storage.get_instance()

    weights_path = os.path.join(dest_dir, "model.weights")
    client.download(bucket, weights_blob, weights_path)

    config_path = os.path.join(dest_dir, "model.config")
    client.download(bucket, config_blob, config_path)

    net = cv2.dnn.readNetFromTensorflow(weights_path, config_path)
    return net


def load_frames(benchmark_bucket, bucket, blobs, dest_dir):
    client = storage.get_instance()

    for blob in blobs:
        stripped_blob = blob.replace(bucket + '/', '')
        path = os.path.join(dest_dir, stripped_blob)
        client.download(benchmark_bucket, blob, path)
        yield cv2.imread(path)


def detect(net, img):
    rows = img.shape[0]
    cols = img.shape[1]
    img = cv2.dnn.blobFromImage(img, size=(300, 300), swapRB=True, crop=False)
    net.setInput(img)
    out = net.forward()

    preds = []
    for detection in out[0,0,:,:]:
        score = float(detection[2])
        if score > 0.5:
            class_id = int(detection[1])
            preds.append({
                "class": labels[class_id],
                "score": score
            })

    return preds


@dag(
    schedule_interval=None,
    start_date=pendulum.datetime(2021, 1, 1, tz="UTC"),
    catchup=False,
    is_paused_upon_creation=False,
)
def dag_w1_d5_4():
    @task
    @timing
    def func_1_1(event):
        logging.info("======= func_1_1 execution start =======")

        vid_blob = event["video"]
        n_frames = event["n_frames"]
        batch_size = event["batch_size"]
        frames_bucket = event["frames_bucket"]
        input_bucket = event["input_bucket"]
        benchmark_bucket = event["benchmark_bucket"]

        tmp_dir = os.path.join("/tmp", str(uuid.uuid4()))
        os.makedirs(tmp_dir, exist_ok=True)

        vid_path = load_video(benchmark_bucket, input_bucket, vid_blob, tmp_dir)
        img_paths = decode_video(vid_path, n_frames, tmp_dir)
        paths = list(upload_imgs(benchmark_bucket, frames_bucket, img_paths))
        frames = list(chunks(paths, batch_size))

        logging.info("======= func_1_1 execution end =======")

        return {
            "frames": [{
                "frames_bucket": frames_bucket,
                "frames": fs,
                "benchmark_bucket": benchmark_bucket,
                "model_bucket": input_bucket,
                "model_config": event["model_config"],
                "model_weights": event["model_weights"]
            } for fs in frames]
        }

    @task
    @timing
    def func_1_2(
        upstream_output_func_1_1,
        dag_id: str = "dag_w1_d5_4",
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
                (load_model, ("sebs-benchmarks-bucket-20250917", "benchmarks/650-vid/frozen_inference_graph.pb", "benchmarks/650-vid/faster_rcnn_resnet50_coco_2018_01_28.pbtxt", "/tmp")),
            ]

            # 并行执行任务
            upstream_output, net = execute_parallel_tasks(tasks)
        else:
            # 普通模式：串行执行
            upstream_output = get_upstream_task_value(dag_id, task_name, current_run_id, upstream_task_id)
            net = load_model("sebs-benchmarks-bucket-20250917", "benchmarks/650-vid/frozen_inference_graph.pb", "benchmarks/650-vid/faster_rcnn_resnet50_coco_2018_01_28.pbtxt", "/tmp")

        logging.info("======= func_1_2 execution start =======")

        event = upstream_output["frames"][0]

        tmp_dir = "/tmp"

        benchmark_bucket = event["benchmark_bucket"]

        frames = list(load_frames(benchmark_bucket, event["frames_bucket"], event["frames"], tmp_dir))

        preds = [detect(net, frame) for frame in frames]

        frames_names = event["frames"]
        frames_names = [x.split(".")[0] for x in event["frames"]]

        preds = {f"{frames_names[idx]}": dets for idx, dets in enumerate(preds)}

        logging.info("======= func_1_2 execution end =======")

        return preds

    @task
    @timing
    def func_1_3(
        upstream_output_func_1_1,
        dag_id: str = "dag_w1_d5_4",
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
                (load_model, ("sebs-benchmarks-bucket-20250917", "benchmarks/650-vid/frozen_inference_graph.pb", "benchmarks/650-vid/faster_rcnn_resnet50_coco_2018_01_28.pbtxt", "/tmp")),
            ]

            # 并行执行任务
            upstream_output, net = execute_parallel_tasks(tasks)
        else:
            # 普通模式：串行执行
            upstream_output = get_upstream_task_value(dag_id, task_name, current_run_id, upstream_task_id)
            net = load_model("sebs-benchmarks-bucket-20250917", "benchmarks/650-vid/frozen_inference_graph.pb", "benchmarks/650-vid/faster_rcnn_resnet50_coco_2018_01_28.pbtxt", "/tmp")

        logging.info("======= func_1_3 execution start =======")
        
        event = upstream_output["frames"][1]

        tmp_dir = "/tmp"

        benchmark_bucket = event["benchmark_bucket"]

        frames = list(load_frames(benchmark_bucket, event["frames_bucket"], event["frames"], tmp_dir))

        preds = [detect(net, frame) for frame in frames]

        frames_names = event["frames"]
        frames_names = [x.split(".")[0] for x in event["frames"]]

        preds = {f"{frames_names[idx]}": dets for idx, dets in enumerate(preds)}

        logging.info(f"WHC: preds: {preds}")

        logging.info("======= func_1_3 execution end =======")

        return preds

    @task
    @timing
    def func_1_4(
        upstream_output_func_1_2,
        upstream_output_func_1_3,
        dag_id: str = "dag_w1_d5_4",
        upstream_task_id: str = "func_1_3",
        task_name: str = "func_1_4",
        enable_optimization: bool = True,
        run_id: str = "{{ run_id }}",
    ): 
        current_run_id = run_id

        if enable_optimization:
            # 数据平面优化模式：并行获取上游数据和建立数据库连接
            tasks = [
                (get_upstream_task_value, (dag_id, task_name, current_run_id, "func_1_2")),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, "func_1_3")),
            ]

            # 并行执行任务
            upstream_output_func_1_2, upstream_output_func_1_3 = execute_parallel_tasks(tasks)
        else:
            # 普通模式：串行执行
            upstream_output_func_1_2 = get_upstream_task_value(dag_id, task_name, current_run_id, "func_1_2")
            upstream_output_func_1_3 = get_upstream_task_value(dag_id, task_name, current_run_id, "func_1_3")

        logging.info("======= func_1_4 execution start =======")

        logs = {}

        for frame_name, detections in upstream_output_func_1_2.items():
            logs[frame_name] = detections

        for frame_name, detections in upstream_output_func_1_3.items():
            logs[frame_name] = detections

        logging.info(f"WHC: logs: {logs}")

        logging.info("======= func_1_4 execution end =======")

        return logs
        
    
    # DAG execution with optimization control
    _enable_optimization = True

    func_1_1_output = func_1_1(event=generate_input(size="small", benchmarks_bucket="sebs-benchmarks-bucket-20250917", input_buckets=["benchmarks/650-vid"], output_buckets=["benchmarks/650-vid"]))

    func_1_2_output = func_1_2(
        upstream_output_func_1_1=func_1_1_output,
        dag_id="dag_w1_d5_4",
        upstream_task_id="func_1_1",
        task_name="func_1_2",
        enable_optimization=_enable_optimization,
        run_id="{{ run_id }}",
    )
    func_1_3_output = func_1_3(
        upstream_output_func_1_1=func_1_1_output,
        dag_id="dag_w1_d5_4",
        upstream_task_id="func_1_1",
        task_name="func_1_3",
        enable_optimization=_enable_optimization,
        run_id="{{ run_id }}",
    )
    func_1_4_output = func_1_4(
        upstream_output_func_1_2=func_1_2_output,
        upstream_output_func_1_3=func_1_3_output,
        dag_id="dag_w1_d5_4",
        upstream_task_id="func_1_3",
        task_name="func_1_4",
        enable_optimization=_enable_optimization,
        run_id="{{ run_id }}",
    )


# execute dag
etl_dag = dag_w1_d5_4()
