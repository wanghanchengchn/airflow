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


class nosql:

    instance: Optional["nosql"] = None

    def __init__(self):
        session = boto3.Session(
            aws_access_key_id="<WHC_AWS_KEY>",
            aws_secret_access_key="<WHC_AWS_SECRET>",
            region_name="us-east-1",
        )

        self.client = session.resource("dynamodb")
        self._tables = {}

    # Based on: https://github.com/boto/boto3/issues/369#issuecomment-157205696
    def _remove_decimals(self, data: dict) -> Union[dict, list, int, float]:

        if isinstance(data, list):
            return [self._remove_decimals(x) for x in data]
        elif isinstance(data, dict):
            return {k: self._remove_decimals(v) for k, v in data.items()}
        elif isinstance(data, Decimal):
            if data.as_integer_ratio()[1] == 1:
                return int(data)
            else:
                return float(data)
        else:
            return data

    def _get_table(self, table_name: str):

        if table_name not in self._tables:

            env_name = f"NOSQL_STORAGE_TABLE_{table_name}"

            if env_name in environ:
                aws_name = environ[env_name]
            else:
                # 如果没有环境变量，直接使用table_name作为AWS表名
                aws_name = table_name

            self._tables[table_name] = self.client.Table(aws_name)

        return self._tables[table_name]

    def insert(
        self,
        table_name: str,
        primary_key: Tuple[str, str],
        secondary_key: Tuple[str, str],
        data: dict,
    ):
        for key in (primary_key, secondary_key):
            data[key[0]] = key[1]

        self._get_table(table_name).put_item(Item=data)

    def get(self, table_name: str, primary_key: Tuple[str, str], secondary_key: Tuple[str, str]) -> dict:

        data = {}
        for key in (primary_key, secondary_key):
            data[key[0]] = key[1]

        res = self._get_table(table_name).get_item(Key=data)
        return self._remove_decimals(res["Item"])

    def update(
        self,
        table_name: str,
        primary_key: Tuple[str, str],
        secondary_key: Tuple[str, str],
        updates: dict,
    ):

        key_data = {}
        for key in (primary_key, secondary_key):
            key_data[key[0]] = key[1]

        update_expression = "SET "
        update_values = {}
        update_names = {}

        # We use attribute names because DynamoDB reserves some keywords, like 'status'
        for key, value in updates.items():

            update_expression += f" #{key}_name = :{key}_value, "
            update_values[f":{key}_value"] = value
            update_names[f"#{key}_name"] = key

        update_expression = update_expression[:-2]

        self._get_table(table_name).update_item(
            Key=key_data,
            UpdateExpression=update_expression,
            ExpressionAttributeValues=update_values,
            ExpressionAttributeNames=update_names,
        )

    def query(self, table_name: str, primary_key: Tuple[str, str], _: str) -> List[dict]:

        res = self._get_table(table_name).query(
            KeyConditionExpression=f"{primary_key[0]} = :keyvalue",
            ExpressionAttributeValues={":keyvalue": primary_key[1]},
        )["Items"]
        return self._remove_decimals(res)

    def delete(self, table_name: str, primary_key: Tuple[str, str], secondary_key: Tuple[str, str]):
        data = {}
        for key in (primary_key, secondary_key):
            data[key[0]] = key[1]

        self._get_table(table_name).delete_item(Key=data)

    @staticmethod
    def get_instance():
        if nosql.instance is None:
            nosql.instance = nosql()
        return nosql.instance


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


def generate_input(data_dir, size, benchmarks_bucket, input_buckets, output_buckets, upload_func, nosql_func):
    input_config = {}

    # test - invoke a single trip, succeed
    # small - fail in the middle
    # large - fail at the last step

    trip_details = {
        "flight_depart": "ZRH",
        "flight_arrive": "KTW",
        "flight_date": "2020-08-22T13:00:00",
        "hotel_stars": "3",
        "hotel_nights": "3",
        "hotel_distance": "1500",
        "hotel_price_max": "150",
        "rental_class": "compact",
        "rental_price_max": "100",
        "rental_duration": 3,
        "rental_requests": ["full_tank", "CDW", "assistance"],
    }

    size_results = {
        "test": {"result": "success"},
        "small": {"result": "failure", "reason": "hotel"},
        "large": {"result": "failure", "reason": "confirm"},
    }

    trip_details["expected_result"] = size_results[size]
    trip_details["request-id"] = str(uuid.uuid4().hex)

    return trip_details


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
    return generate_input(None, "test", None, None, None, None, None)  # 默认值


def execute_parallel_tasks(tasks):
    """并行执行多个任务"""
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(func, *args) for func, args in tasks]
        results = [future.result() for future in futures]
        return results


@dag(
    schedule_interval=None,
    start_date=pendulum.datetime(2021, 1, 1, tz="UTC"),
    catchup=False,
    is_paused_upon_creation=False,
)
def dag_w1_d7():
    @task
    @timing
    def func_1_1(event):
        logging.info("======= func_1_1 execution start =======")

        nosql_client = nosql.get_instance()
        nosql_table_name = "hotel_booking"

        expected_result = event["expected_result"]
        if expected_result["result"] == "failure" and expected_result["reason"] == "hotel":
            raise RuntimeError("Failed to book the hotel!")

        # We start with the hotel
        trip_id = str(uuid.uuid4().hex)
        hotel_booking_id = event["request-id"]

        # Simulate return from a service
        hotel_price = "130"
        hotel_name = "BestEver Hotel"

        nosql_client.insert(
            nosql_table_name,
            ("trip_id", trip_id),
            ("booking_id", hotel_booking_id),
            {
                **{key: event[key] for key in event.keys() if key.startswith("hotel_")},
                "hotel_price": hotel_price,
                "hotel_name": hotel_name,
                "status": "pending",
            },
        )

        logging.info("======= func_1_1 execution end =======")

        return {"trip_id": trip_id, "booking_id": hotel_booking_id, **event}

    @task
    @timing
    def func_1_2(
        func_1_1_output,
        dag_id: str = "dag_w1_d7",
        upstream_task_id: str = "func_1_1",
        task_name: str = "func_1_2",
        enable_optimization: bool = True,
    ):
        current_run_id = get_current_task_run_id(dag_id, task_name)

        if enable_optimization:
            # 数据平面优化模式：并行获取上游数据和建立数据库连接
            tasks = [
                (get_upstream_task_value, (dag_id, task_name, current_run_id, upstream_task_id)),
                (nosql.get_instance, ()),
            ]

            # 并行执行任务
            upstream_output, nosql_client = execute_parallel_tasks(tasks)
        else:
            # 普通模式：串行执行
            upstream_output = get_upstream_task_value(dag_id, task_name, current_run_id, upstream_task_id)
            nosql_client = nosql.get_instance()

        logging.info("======= func_1_2 execution start =======")

        event = upstream_output

        nosql_table_name = "car_rentals"

        expected_result = event["expected_result"]
        if expected_result["result"] == "failure" and expected_result["reason"] == "rental":
            raise RuntimeError("Failed to rent a car!")

        # We start with the hotel
        trip_id = event["trip_id"]
        rental_id = event["request-id"]

        # Simulate return from a service
        car_price = "125"
        car_name = "Fiat 126P"

        nosql_client.insert(
            nosql_table_name,
            ("trip_id", trip_id),
            ("rental_id", rental_id),
            {
                **{key: event[key] for key in event.keys() if key.startswith("rental_")},
                "rental_price": car_price,
                "rental_name": car_name,
                "status": "pending",
            },
        )

        logging.info("======= func_1_2 execution end =======")

        return {"trip_id": trip_id, "rental_id": rental_id, **event}

    @task
    @timing
    def func_1_3(
        func_1_2_output,
        dag_id: str = "dag_w1_d7",
        upstream_task_id: str = "func_1_2",
        task_name: str = "func_1_3",
        enable_optimization: bool = True,
    ):
        current_run_id = get_current_task_run_id(dag_id, task_name)

        if enable_optimization:
            # 数据平面优化模式：并行获取上游数据和建立数据库连接
            tasks = [
                (get_upstream_task_value, (dag_id, task_name, current_run_id, upstream_task_id)),
                (nosql.get_instance, ()),
            ]

            # 并行执行任务
            upstream_output, nosql_client = execute_parallel_tasks(tasks)
            logging.info("WHC: nosql_client: %s", nosql_client)
        else:
            # 普通模式：串行执行
            upstream_output = get_upstream_task_value(dag_id, task_name, current_run_id, upstream_task_id)
            nosql_client = nosql.get_instance()
            logging.info("WHC: nosql_client: %s", nosql_client)

        logging.info("======= func_1_3 execution start =======")

        event = upstream_output

        nosql_table_name = "flights"

        expected_result = event["expected_result"]
        if expected_result["result"] == "failure" and expected_result["reason"] == "flight":
            raise RuntimeError("Failed to book a flight!")

        # We start with the hotel
        trip_id = event["trip_id"]
        flight_id = event["request-id"]

        # Simulate return from a service
        flight_price = "1000"
        flight_connections = ["WAW"]
        flight_duration = "4h30m"

        nosql_client.insert(
            nosql_table_name,
            ("trip_id", trip_id),
            ("flight_id", flight_id),
            {
                **{key: event[key] for key in event.keys() if key.startswith("flight_")},
                "price": flight_price,
                "connections": flight_connections,
                "duration": flight_duration,
                "status": "pending",
            },
        )

        logging.info("======= func_1_3 execution end =======")

        return {"trip_id": trip_id, "flight_id": flight_id, **event}

    @task
    @timing
    def func_1_4(
        func_1_3_output,
        dag_id: str = "dag_w1_d7",
        upstream_task_id: str = "func_1_3",
        task_name: str = "func_1_4",
        enable_optimization: bool = True,
    ):
        current_run_id = get_current_task_run_id(dag_id, task_name)

        if enable_optimization:
            # 数据平面优化模式：并行获取上游数据和建立数据库连接
            tasks = [
                (get_upstream_task_value, (dag_id, task_name, current_run_id, upstream_task_id)),
                (nosql.get_instance, ()),
            ]

            # 并行执行任务
            upstream_output, nosql_client = execute_parallel_tasks(tasks)
        else:
            # 普通模式：串行执行
            upstream_output = get_upstream_task_value(dag_id, task_name, current_run_id, upstream_task_id)
            nosql_client = nosql.get_instance()

        logging.info("======= func_1_4 execution start =======")

        event = upstream_output

        expected_result = event["expected_result"]
        if expected_result["result"] == "failure" and expected_result["reason"] == "confirm":
            raise RuntimeError("Failed to confirm the booking!")

        trip_id = event["trip_id"]

        # Confirm flight
        nosql_table_name = "flights"
        flight_id = event["flight_id"]
        nosql_client.update(
            nosql_table_name,
            ("trip_id", trip_id),
            ("flight_id", flight_id),
            {"status": "booked"},
        )

        # Confirm car rental
        nosql_table_name = "car_rentals"
        nosql_client.update(
            nosql_table_name,
            ("trip_id", trip_id),
            ("rental_id", event["rental_id"]),
            {"status": "booked"},
        )

        # Confirm hotel booking
        nosql_table_name = "hotel_booking"
        nosql_client.update(
            nosql_table_name,
            ("trip_id", trip_id),
            ("booking_id", event["booking_id"]),
            {"status": "booked"},
        )

        logging.info("======= func_1_4 execution end =======")

        return {"trip_id": trip_id, **event}

    @task
    @timing
    def func_1_5(
        func_1_4_output,
        dag_id: str = "dag_w1_d7",
        upstream_task_id: str = "func_1_4",
        task_name: str = "func_1_5",
        enable_optimization: bool = True,
    ):
        current_run_id = get_current_task_run_id(dag_id, task_name)

        if enable_optimization:
            # 数据平面优化模式：并行获取上游数据和建立数据库连接
            tasks = [
                (get_upstream_task_value, (dag_id, task_name, current_run_id, upstream_task_id)),
                (nosql.get_instance, ()),
            ]

            # 并行执行任务
            upstream_output, nosql_client = execute_parallel_tasks(tasks)
        else:
            # 普通模式：串行执行
            upstream_output = get_upstream_task_value(dag_id, task_name, current_run_id, upstream_task_id)
            nosql_client = nosql.get_instance()

        logging.info("======= func_1_5 execution start =======")

        event = upstream_output

        trip_id = event["trip_id"]

        # Confirm flight
        nosql_table_name = "flights"
        flight_id = event["flight_id"]
        nosql_client.delete(nosql_table_name, ("trip_id", trip_id), ("flight_id", flight_id))

        event.pop("flight_id")

        logging.info("======= func_1_5 execution end =======")

        return event

    @task
    @timing
    def func_1_6(
        func_1_5_output,
        dag_id: str = "dag_w1_d7",
        upstream_task_id: str = "func_1_5",
        task_name: str = "func_1_6",
        enable_optimization: bool = True,
    ):
        current_run_id = get_current_task_run_id(dag_id, task_name)

        if enable_optimization:
            # 数据平面优化模式：并行获取上游数据和建立数据库连接
            tasks = [
                (get_upstream_task_value, (dag_id, task_name, current_run_id, upstream_task_id)),
                (nosql.get_instance, ()),
            ]

            # 并行执行任务
            upstream_output, nosql_client = execute_parallel_tasks(tasks)
        else:
            # 普通模式：串行执行
            upstream_output = get_upstream_task_value(dag_id, task_name, current_run_id, upstream_task_id)
            nosql_client = nosql.get_instance()

        logging.info("======= func_1_6 execution start =======")

        event = upstream_output

        trip_id = event["trip_id"]

        # Confirm flight
        nosql_table_name = "car_rentals"
        rental_id = event["rental_id"]
        nosql_client.delete(nosql_table_name, ("trip_id", trip_id), ("rental_id", rental_id))

        event.pop("rental_id")

        logging.info("======= func_1_6 execution end =======")

        return event

    @task
    @timing
    def func_1_7(
        func_1_6_output,
        dag_id: str = "dag_w1_d7",
        upstream_task_id: str = "func_1_6",
        task_name: str = "func_1_7",
        enable_optimization: bool = True,
    ):
        current_run_id = get_current_task_run_id(dag_id, task_name)

        if enable_optimization:
            # 数据平面优化模式：并行获取上游数据和建立数据库连接
            tasks = [
                (get_upstream_task_value, (dag_id, task_name, current_run_id, upstream_task_id)),
                (nosql.get_instance, ()),
            ]

            # 并行执行任务
            upstream_output, nosql_client = execute_parallel_tasks(tasks)
        else:
            # 普通模式：串行执行
            upstream_output = get_upstream_task_value(dag_id, task_name, current_run_id, upstream_task_id)
            nosql_client = nosql.get_instance()

        logging.info("======= func_1_7 execution start=======")

        event = upstream_output

        trip_id = event["trip_id"]

        # Confirm flight
        nosql_table_name = "hotel_booking"
        booking_id = event["booking_id"]
        nosql_client.delete(nosql_table_name, ("trip_id", trip_id), ("booking_id", booking_id))

        logging.info("======= func_1_7 execution end =======")

        return {"trip_id": trip_id, "status": "failure"}

    # DAG execution with optimization control
    _enable_optimization = False

    func_1_1_output = func_1_1(event=generate_input(None, "test", None, None, None, None, None))
    func_1_2_output = func_1_2(
        func_1_1_output=func_1_1_output,
        dag_id="dag_w1_d7",
        upstream_task_id="func_1_1",
        task_name="func_1_2",
        enable_optimization=_enable_optimization,
    )
    func_1_3_output = func_1_3(
        func_1_2_output=func_1_2_output,
        dag_id="dag_w1_d7",
        upstream_task_id="func_1_2",
        task_name="func_1_3",
        enable_optimization=_enable_optimization,
    )
    func_1_4_output = func_1_4(
        func_1_3_output=func_1_3_output,
        dag_id="dag_w1_d7",
        upstream_task_id="func_1_3",
        task_name="func_1_4",
        enable_optimization=_enable_optimization,
    )
    func_1_5_output = func_1_5(
        func_1_4_output=func_1_4_output,
        dag_id="dag_w1_d7",
        upstream_task_id="func_1_4",
        task_name="func_1_5",
        enable_optimization=_enable_optimization,
    )
    func_1_6_output = func_1_6(
        func_1_5_output=func_1_5_output,
        dag_id="dag_w1_d7",
        upstream_task_id="func_1_5",
        task_name="func_1_6",
        enable_optimization=_enable_optimization,
    )
    func_1_7_output = func_1_7(
        func_1_6_output=func_1_6_output,
        dag_id="dag_w1_d7",
        upstream_task_id="func_1_6",
        task_name="func_1_7",
        enable_optimization=_enable_optimization,
    )


# execute dag
etl_dag = dag_w1_d7()