import pendulum
from airflow.decorators import dag, task
import logging
from functools import wraps
from time import time
import time as t_module
from airflow.models import TaskInstance
from airflow.settings import Session
from concurrent.futures import ThreadPoolExecutor, TimeoutError, wait, FIRST_COMPLETED
from typing import Optional, Union, Tuple

# by Jonathan Prieto-Cubides https://stackoverflow.com/questions/1622943/timeit-versus-timing-decorator
def timing(f):
    @wraps(f)
    def wrap(*args, **kw):
        ts = time()
        result = f(*args, **kw)
        te = time()
        logging.info('func:%r args:[%r, %r] took: %f sec. Start: %f, End: %f' % (f.__name__, args, kw, te-ts, ts, te))
        return result
    return wrap

def get_current_task_run_id(dag_id, task_id):
    """获取指定任务的当前run_id"""
    session = Session()
    try:
        current_task = session.query(TaskInstance).filter(
            TaskInstance.dag_id == dag_id,
            TaskInstance.task_id == task_id
        ).order_by(TaskInstance.start_date.desc()).first()
        
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
            upstream_task = session.query(TaskInstance).filter(
                TaskInstance.dag_id == dag_id,
                TaskInstance.task_id == upstream_task_id,
                TaskInstance.run_id == run_id
            ).first()
            
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
    return 5000  # 默认值

def execute_parallel_tasks(tasks):
    """并行执行多个任务
    
    Args:
        tasks: 包含多个(task_func, args)元组的列表
    Returns:
        返回所有任务的结果列表
    """
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(func, *args) for func, args in tasks]
        results = [future.result() for future in futures]
        return results

def fixed_sleep_task(sleep_seconds=2.5, task_name="fixed_sleep"):
    """固定时间的睡眠任务
    
    Args:
        sleep_seconds: 睡眠时间（秒）
        task_name: 任务名称，用于日志
    Returns:
        True
    """
    logging.info(f"start {task_name} sleep {sleep_seconds}")
    t_module.sleep(sleep_seconds)
    logging.info(f"end {task_name} sleep {sleep_seconds}")
    return True

def dynamic_sleep_task(sleep_time_ms, dynamic_ratio=1, task_name="dynamic_sleep"):
    """动态时间的睡眠任务
    
    Args:
        sleep_time_ms: 睡眠时间（毫秒）
        dynamic_ratio: 时间优化比例
        task_name: 任务名称，用于日志
    Returns:
        sleep_time_ms
    """
    sleep_seconds = (sleep_time_ms / 1000) * dynamic_ratio
    logging.info(f"{task_name}: sleep_time_ms={sleep_time_ms}, sleep_seconds={sleep_seconds}")
    logging.info(f"WHC IMP IMP IMP: sleep_seconds: {sleep_seconds}")
    t_module.sleep(sleep_seconds)
    return sleep_time_ms

@dag(
    schedule_interval=None,
    start_date=pendulum.datetime(2021, 1, 1, tz="UTC"),
    catchup=False,
    is_paused_upon_creation=False)
def dag_w1_d3():
    @task
    @timing
    def func_1_1(
        sleep_time_ms: int,
        dynamic_ratio: float = 1,
        task_name: str = "func_1_1"
    ) -> int:
        """执行一个动态睡眠任务
        
        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            dynamic_ratio: 时间优化比例，默认为1（不优化时间）
            task_name: 任务名称，用于日志
        Returns:
            sleep_time_ms: 输入的睡眠时间
        """
        return dynamic_sleep_task(
            sleep_time_ms=sleep_time_ms,
            dynamic_ratio=dynamic_ratio,
            task_name=task_name
        )

    @task
    @timing
    def func_1_2(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w1_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_2',
        enable_optimization: bool = True,
        branch_id: int = 0
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w1_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认False
            branch_id: 并行分支ID，用于Dynamic Task Mapping区分不同实例
        Returns:
            int: 从上游任务获取的睡眠时间
        """
        logging.info(f"Executing branch {branch_id} of {task_name}")
        current_run_id = get_current_task_run_id(dag_id, task_name)

        if enable_optimization:
            # 数据平面优化模式
            tasks = [
                (get_upstream_task_value, (dag_id, task_name, current_run_id, upstream_task_id)),
                (fixed_sleep_task, (fixed_sleep_seconds, f"{task_name}_partA"))
            ]
            
            # 并行执行任务
            sleep_time_ms_from_db, _ = execute_parallel_tasks(tasks)
            
            # 执行最后的sleep，使用优化比例
            return dynamic_sleep_task(
                sleep_time_ms=sleep_time_ms_from_db,
                dynamic_ratio=dynamic_ratio,
                task_name=f"{task_name}_partB"
            )
        else:
            # 普通模式：串行执行
            sleep_time_ms = get_upstream_task_value(dag_id, task_name, current_run_id, upstream_task_id)
            
            return dynamic_sleep_task(
                sleep_time_ms=sleep_time_ms,
                dynamic_ratio=1,
                task_name=task_name
            )


    @task
    @timing
    def func_1_3(
        sleep_time_ms_list: list,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w1_d3',
        task_name: str = 'func_1_3',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务，支持多个上游输入（Fan-in）

        Args:
            sleep_time_ms_list: 上游任务的睡眠时间列表（毫秒），自动从上游并行任务收集
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w1_d3'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认False
        Returns:
            int: 使用第一个上游任务的睡眠时间（或者可以是求和/平均等聚合逻辑）
        """
        logging.info(f"Fan-in: Received {len(sleep_time_ms_list)} inputs from {len(sleep_time_ms_list)} parallel tasks")
        logging.info(f"Upstream values: {sleep_time_ms_list}")
        
        # 聚合逻辑：这里使用第一个值，你可以改成求和、平均、最大值等
        sleep_time_ms = sleep_time_ms_list[0] if sleep_time_ms_list else 5000
        
        current_run_id = get_current_task_run_id(dag_id, task_name)

        if enable_optimization:
            # 数据平面优化模式
            # 在fan-in场景下，直接使用聚合后的值
            tasks = [
                (lambda: sleep_time_ms, ()),
                (fixed_sleep_task, (fixed_sleep_seconds, f"{task_name}_partA"))
            ]
            
            # 并行执行任务
            sleep_time_ms_from_calc, _ = execute_parallel_tasks(tasks)
            
            # 执行最后的sleep，使用优化比例
            return dynamic_sleep_task(
                sleep_time_ms=sleep_time_ms_from_calc,
                dynamic_ratio=dynamic_ratio,
                task_name=f"{task_name}_partB"
            )
        else:
            # 普通模式：使用传入的sleep_time_ms
            return dynamic_sleep_task(
                sleep_time_ms=sleep_time_ms,
                dynamic_ratio=1,
                task_name=task_name
            )

    # specify data flow with default values
    sleep_time_ms = 5000
    _enable_optimization = False
    
    # 定义并行分支数量 - 可以轻松改成512或任意数量！
    num_parallel_branches = 32  # 改成512就能创建512个并行任务！

    # Step 1: 第一个任务
    func_1_1_output = func_1_1(sleep_time_ms = sleep_time_ms, dynamic_ratio=1, task_name='func_1_1')
    
    # Step 2: Fan-out - 使用.expand()自动创建N个并行的func_1_2实例
    # 这会创建 func_1_2[0], func_1_2[1], ..., func_1_2[N-1]
    # 所有实例都映射到同一个Knative Service: dag_w1_d3-func_1_2.yaml
    parallel_outputs = func_1_2.partial(
        sleep_time_ms=func_1_1_output,
        fixed_sleep_seconds=(sleep_time_ms / 1000) / 2,
        dynamic_ratio=0.5,
        dag_id='dag_w1_d3',
        upstream_task_id='func_1_1',
        task_name='func_1_2',
        enable_optimization=_enable_optimization
    ).expand(
        branch_id=list(range(num_parallel_branches))
    )
    
    # Step 3: Fan-in - func_1_3 自动收集所有并行任务的输出
    # Airflow会自动将parallel_outputs转换为列表传给func_1_3
    func_1_3(
        sleep_time_ms_list=parallel_outputs,
        fixed_sleep_seconds=(sleep_time_ms / 1000) / 2,
        dynamic_ratio=0.5,
        dag_id='dag_w1_d3',
        task_name='func_1_3',
        enable_optimization=_enable_optimization
    )

# execute dag
etl_dag = dag_w1_d3()
