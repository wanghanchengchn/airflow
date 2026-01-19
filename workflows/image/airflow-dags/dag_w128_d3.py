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
    with ThreadPoolExecutor(max_workers=300) as executor:
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
def dag_w128_d3():
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
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_2',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_3',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_4(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_4',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_5(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_5',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_6(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_6',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_7(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_7',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_8(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_8',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_9(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_9',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_10(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_10',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_11(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_11',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_12(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_12',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_13(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_13',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_14(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_14',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_15(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_15',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_16(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_16',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_17(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_17',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_18(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_18',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_19(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_19',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_20(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_20',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_21(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_21',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_22(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_22',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_23(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_23',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_24(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_24',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_25(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_25',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_26(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_26',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_27(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_27',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_28(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_28',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_29(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_29',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_30(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_30',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_31(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_31',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_32(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_32',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_33(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_33',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_34(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_34',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_35(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_35',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_36(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_36',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_37(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_37',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_38(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_38',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_39(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_39',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_40(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_40',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_41(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_41',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_42(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_42',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_43(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_43',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_44(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_44',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_45(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_45',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_46(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_46',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_47(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_47',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_48(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_48',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_49(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_49',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_50(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_50',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_51(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_51',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_52(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_52',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_53(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_53',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_54(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_54',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_55(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_55',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_56(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_56',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_57(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_57',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_58(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_58',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_59(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_59',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_60(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_60',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_61(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_61',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_62(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_62',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_63(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_63',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_64(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_64',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_65(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_65',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_66(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_66',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_67(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_67',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_68(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_68',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_69(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_69',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_70(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_70',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_71(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_71',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_72(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_72',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_73(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_73',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_74(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_74',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_75(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_75',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_76(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_76',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_77(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_77',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_78(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_78',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_79(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_79',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_80(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_80',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_81(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_81',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_82(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_82',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_83(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_83',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_84(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_84',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_85(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_85',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_86(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_86',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_87(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_87',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_88(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_88',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_89(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_89',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_90(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_90',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_91(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_91',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_92(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_92',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_93(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_93',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_94(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_94',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_95(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_95',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_96(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_96',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_97(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_97',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_98(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_98',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_99(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_99',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_100(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_100',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_101(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_101',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_102(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_102',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_103(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_103',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_104(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_104',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_105(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_105',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_106(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_106',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_107(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_107',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_108(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_108',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_109(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_109',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_110(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_110',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_111(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_111',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_112(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_112',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_113(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_113',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_114(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_114',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_115(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_115',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_116(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_116',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_117(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_117',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_118(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_118',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_119(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_119',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_120(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_120',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_121(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_121',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_122(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_122',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_123(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_123',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_124(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_124',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_125(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_125',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_126(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_126',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_127(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_127',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_128(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_128',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_129(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_129',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
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
    def func_1_130(
        sleep_time_ms_1: int,
        sleep_time_ms_2: int,
        sleep_time_ms_3: int,
        sleep_time_ms_4: int,
        sleep_time_ms_5: int,
        sleep_time_ms_6: int,
        sleep_time_ms_7: int,
        sleep_time_ms_8: int,
        sleep_time_ms_9: int,
        sleep_time_ms_10: int,
        sleep_time_ms_11: int,
        sleep_time_ms_12: int,
        sleep_time_ms_13: int,
        sleep_time_ms_14: int,
        sleep_time_ms_15: int,
        sleep_time_ms_16: int,
        sleep_time_ms_17: int,
        sleep_time_ms_18: int,
        sleep_time_ms_19: int,
        sleep_time_ms_20: int,
        sleep_time_ms_21: int,
        sleep_time_ms_22: int,
        sleep_time_ms_23: int,
        sleep_time_ms_24: int,
        sleep_time_ms_25: int,
        sleep_time_ms_26: int,
        sleep_time_ms_27: int,
        sleep_time_ms_28: int,
        sleep_time_ms_29: int,
        sleep_time_ms_30: int,
        sleep_time_ms_31: int,
        sleep_time_ms_32: int,
        sleep_time_ms_33: int,
        sleep_time_ms_34: int,
        sleep_time_ms_35: int,
        sleep_time_ms_36: int,
        sleep_time_ms_37: int,
        sleep_time_ms_38: int,
        sleep_time_ms_39: int,
        sleep_time_ms_40: int,
        sleep_time_ms_41: int,
        sleep_time_ms_42: int,
        sleep_time_ms_43: int,
        sleep_time_ms_44: int,
        sleep_time_ms_45: int,
        sleep_time_ms_46: int,
        sleep_time_ms_47: int,
        sleep_time_ms_48: int,
        sleep_time_ms_49: int,
        sleep_time_ms_50: int,
        sleep_time_ms_51: int,
        sleep_time_ms_52: int,
        sleep_time_ms_53: int,
        sleep_time_ms_54: int,
        sleep_time_ms_55: int,
        sleep_time_ms_56: int,
        sleep_time_ms_57: int,
        sleep_time_ms_58: int,
        sleep_time_ms_59: int,
        sleep_time_ms_60: int,
        sleep_time_ms_61: int,
        sleep_time_ms_62: int,
        sleep_time_ms_63: int,
        sleep_time_ms_64: int,
        sleep_time_ms_65: int,
        sleep_time_ms_66: int,
        sleep_time_ms_67: int,
        sleep_time_ms_68: int,
        sleep_time_ms_69: int,
        sleep_time_ms_70: int,
        sleep_time_ms_71: int,
        sleep_time_ms_72: int,
        sleep_time_ms_73: int,
        sleep_time_ms_74: int,
        sleep_time_ms_75: int,
        sleep_time_ms_76: int,
        sleep_time_ms_77: int,
        sleep_time_ms_78: int,
        sleep_time_ms_79: int,
        sleep_time_ms_80: int,
        sleep_time_ms_81: int,
        sleep_time_ms_82: int,
        sleep_time_ms_83: int,
        sleep_time_ms_84: int,
        sleep_time_ms_85: int,
        sleep_time_ms_86: int,
        sleep_time_ms_87: int,
        sleep_time_ms_88: int,
        sleep_time_ms_89: int,
        sleep_time_ms_90: int,
        sleep_time_ms_91: int,
        sleep_time_ms_92: int,
        sleep_time_ms_93: int,
        sleep_time_ms_94: int,
        sleep_time_ms_95: int,
        sleep_time_ms_96: int,
        sleep_time_ms_97: int,
        sleep_time_ms_98: int,
        sleep_time_ms_99: int,
        sleep_time_ms_100: int,
        sleep_time_ms_101: int,
        sleep_time_ms_102: int,
        sleep_time_ms_103: int,
        sleep_time_ms_104: int,
        sleep_time_ms_105: int,
        sleep_time_ms_106: int,
        sleep_time_ms_107: int,
        sleep_time_ms_108: int,
        sleep_time_ms_109: int,
        sleep_time_ms_110: int,
        sleep_time_ms_111: int,
        sleep_time_ms_112: int,
        sleep_time_ms_113: int,
        sleep_time_ms_114: int,
        sleep_time_ms_115: int,
        sleep_time_ms_116: int,
        sleep_time_ms_117: int,
        sleep_time_ms_118: int,
        sleep_time_ms_119: int,
        sleep_time_ms_120: int,
        sleep_time_ms_121: int,
        sleep_time_ms_122: int,
        sleep_time_ms_123: int,
        sleep_time_ms_124: int,
        sleep_time_ms_125: int,
        sleep_time_ms_126: int,
        sleep_time_ms_127: int,
        sleep_time_ms_128: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w128_d3',
        upstream_task_id: str = 'func_1_129',
        task_name: str = 'func_1_130',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w128_d3'
            upstream_task_id: 上游任务ID，默认'func_1_129'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
        current_run_id = get_current_task_run_id(dag_id, task_name)

        if enable_optimization:
            tasks = [
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_2')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_3')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_4')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_5')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_6')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_7')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_8')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_9')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_10')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_11')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_12')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_13')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_14')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_15')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_16')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_17')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_18')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_19')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_20')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_21')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_22')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_23')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_24')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_25')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_26')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_27')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_28')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_29')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_30')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_31')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_32')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_33')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_34')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_35')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_36')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_37')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_38')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_39')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_40')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_41')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_42')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_43')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_44')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_45')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_46')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_47')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_48')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_49')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_50')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_51')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_52')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_53')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_54')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_55')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_56')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_57')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_58')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_59')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_60')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_61')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_62')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_63')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_64')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_65')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_66')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_67')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_68')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_69')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_70')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_71')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_72')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_73')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_74')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_75')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_76')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_77')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_78')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_79')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_80')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_81')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_82')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_83')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_84')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_85')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_86')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_87')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_88')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_89')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_90')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_91')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_92')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_93')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_94')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_95')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_96')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_97')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_98')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_99')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_100')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_101')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_102')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_103')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_104')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_105')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_106')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_107')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_108')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_109')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_110')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_111')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_112')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_113')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_114')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_115')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_116')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_117')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_118')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_119')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_120')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_121')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_122')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_123')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_124')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_125')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_126')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_127')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_128')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_129')),
                (fixed_sleep_task, (fixed_sleep_seconds, f"{task_name}_partA"))
            ]
            
            # 并行执行任务
            sleep_time_ms_1, sleep_time_ms_2, sleep_time_ms_3, sleep_time_ms_4, sleep_time_ms_5, sleep_time_ms_6, sleep_time_ms_7, sleep_time_ms_8, sleep_time_ms_9, sleep_time_ms_10, sleep_time_ms_11, sleep_time_ms_12, sleep_time_ms_13, sleep_time_ms_14, sleep_time_ms_15, sleep_time_ms_16, sleep_time_ms_17, sleep_time_ms_18, sleep_time_ms_19, sleep_time_ms_20, sleep_time_ms_21, sleep_time_ms_22, sleep_time_ms_23, sleep_time_ms_24, sleep_time_ms_25, sleep_time_ms_26, sleep_time_ms_27, sleep_time_ms_28, sleep_time_ms_29, sleep_time_ms_30, sleep_time_ms_31, sleep_time_ms_32, sleep_time_ms_33, sleep_time_ms_34, sleep_time_ms_35, sleep_time_ms_36, sleep_time_ms_37, sleep_time_ms_38, sleep_time_ms_39, sleep_time_ms_40, sleep_time_ms_41, sleep_time_ms_42, sleep_time_ms_43, sleep_time_ms_44, sleep_time_ms_45, sleep_time_ms_46, sleep_time_ms_47, sleep_time_ms_48, sleep_time_ms_49, sleep_time_ms_50, sleep_time_ms_51, sleep_time_ms_52, sleep_time_ms_53, sleep_time_ms_54, sleep_time_ms_55, sleep_time_ms_56, sleep_time_ms_57, sleep_time_ms_58, sleep_time_ms_59, sleep_time_ms_60, sleep_time_ms_61, sleep_time_ms_62, sleep_time_ms_63, sleep_time_ms_64, sleep_time_ms_65, sleep_time_ms_66, sleep_time_ms_67, sleep_time_ms_68, sleep_time_ms_69, sleep_time_ms_70, sleep_time_ms_71, sleep_time_ms_72, sleep_time_ms_73, sleep_time_ms_74, sleep_time_ms_75, sleep_time_ms_76, sleep_time_ms_77, sleep_time_ms_78, sleep_time_ms_79, sleep_time_ms_80, sleep_time_ms_81, sleep_time_ms_82, sleep_time_ms_83, sleep_time_ms_84, sleep_time_ms_85, sleep_time_ms_86, sleep_time_ms_87, sleep_time_ms_88, sleep_time_ms_89, sleep_time_ms_90, sleep_time_ms_91, sleep_time_ms_92, sleep_time_ms_93, sleep_time_ms_94, sleep_time_ms_95, sleep_time_ms_96, sleep_time_ms_97, sleep_time_ms_98, sleep_time_ms_99, sleep_time_ms_100, sleep_time_ms_101, sleep_time_ms_102, sleep_time_ms_103, sleep_time_ms_104, sleep_time_ms_105, sleep_time_ms_106, sleep_time_ms_107, sleep_time_ms_108, sleep_time_ms_109, sleep_time_ms_110, sleep_time_ms_111, sleep_time_ms_112, sleep_time_ms_113, sleep_time_ms_114, sleep_time_ms_115, sleep_time_ms_116, sleep_time_ms_117, sleep_time_ms_118, sleep_time_ms_119, sleep_time_ms_120, sleep_time_ms_121, sleep_time_ms_122, sleep_time_ms_123, sleep_time_ms_124, sleep_time_ms_125, sleep_time_ms_126, sleep_time_ms_127, sleep_time_ms_128, _ = execute_parallel_tasks(tasks)

            sleep_time_ms = max(sleep_time_ms_1, sleep_time_ms_2, sleep_time_ms_3, sleep_time_ms_4, sleep_time_ms_5, sleep_time_ms_6, sleep_time_ms_7, sleep_time_ms_8, sleep_time_ms_9, sleep_time_ms_10, sleep_time_ms_11, sleep_time_ms_12, sleep_time_ms_13, sleep_time_ms_14, sleep_time_ms_15, sleep_time_ms_16, sleep_time_ms_17, sleep_time_ms_18, sleep_time_ms_19, sleep_time_ms_20, sleep_time_ms_21, sleep_time_ms_22, sleep_time_ms_23, sleep_time_ms_24, sleep_time_ms_25, sleep_time_ms_26, sleep_time_ms_27, sleep_time_ms_28, sleep_time_ms_29, sleep_time_ms_30, sleep_time_ms_31, sleep_time_ms_32, sleep_time_ms_33, sleep_time_ms_34, sleep_time_ms_35, sleep_time_ms_36, sleep_time_ms_37, sleep_time_ms_38, sleep_time_ms_39, sleep_time_ms_40, sleep_time_ms_41, sleep_time_ms_42, sleep_time_ms_43, sleep_time_ms_44, sleep_time_ms_45, sleep_time_ms_46, sleep_time_ms_47, sleep_time_ms_48, sleep_time_ms_49, sleep_time_ms_50, sleep_time_ms_51, sleep_time_ms_52, sleep_time_ms_53, sleep_time_ms_54, sleep_time_ms_55, sleep_time_ms_56, sleep_time_ms_57, sleep_time_ms_58, sleep_time_ms_59, sleep_time_ms_60, sleep_time_ms_61, sleep_time_ms_62, sleep_time_ms_63, sleep_time_ms_64, sleep_time_ms_65, sleep_time_ms_66, sleep_time_ms_67, sleep_time_ms_68, sleep_time_ms_69, sleep_time_ms_70, sleep_time_ms_71, sleep_time_ms_72, sleep_time_ms_73, sleep_time_ms_74, sleep_time_ms_75, sleep_time_ms_76, sleep_time_ms_77, sleep_time_ms_78, sleep_time_ms_79, sleep_time_ms_80, sleep_time_ms_81, sleep_time_ms_82, sleep_time_ms_83, sleep_time_ms_84, sleep_time_ms_85, sleep_time_ms_86, sleep_time_ms_87, sleep_time_ms_88, sleep_time_ms_89, sleep_time_ms_90, sleep_time_ms_91, sleep_time_ms_92, sleep_time_ms_93, sleep_time_ms_94, sleep_time_ms_95, sleep_time_ms_96, sleep_time_ms_97, sleep_time_ms_98, sleep_time_ms_99, sleep_time_ms_100, sleep_time_ms_101, sleep_time_ms_102, sleep_time_ms_103, sleep_time_ms_104, sleep_time_ms_105, sleep_time_ms_106, sleep_time_ms_107, sleep_time_ms_108, sleep_time_ms_109, sleep_time_ms_110, sleep_time_ms_111, sleep_time_ms_112, sleep_time_ms_113, sleep_time_ms_114, sleep_time_ms_115, sleep_time_ms_116, sleep_time_ms_117, sleep_time_ms_118, sleep_time_ms_119, sleep_time_ms_120, sleep_time_ms_121, sleep_time_ms_122, sleep_time_ms_123, sleep_time_ms_124, sleep_time_ms_125, sleep_time_ms_126, sleep_time_ms_127, sleep_time_ms_128)

            logging.info(f"WHC IMP IMP IMP: sleep_time_ms: {sleep_time_ms} sleep_time_ms_1: {sleep_time_ms_1} sleep_time_ms_2: {sleep_time_ms_2} sleep_time_ms_3: {sleep_time_ms_3} sleep_time_ms_4: {sleep_time_ms_4} sleep_time_ms_5: {sleep_time_ms_5} sleep_time_ms_6: {sleep_time_ms_6} sleep_time_ms_7: {sleep_time_ms_7} sleep_time_ms_8: {sleep_time_ms_8} sleep_time_ms_9: {sleep_time_ms_9} sleep_time_ms_10: {sleep_time_ms_10} sleep_time_ms_11: {sleep_time_ms_11} sleep_time_ms_12: {sleep_time_ms_12} sleep_time_ms_13: {sleep_time_ms_13} sleep_time_ms_14: {sleep_time_ms_14} sleep_time_ms_15: {sleep_time_ms_15} sleep_time_ms_16: {sleep_time_ms_16} sleep_time_ms_17: {sleep_time_ms_17} sleep_time_ms_18: {sleep_time_ms_18} sleep_time_ms_19: {sleep_time_ms_19} sleep_time_ms_20: {sleep_time_ms_20} sleep_time_ms_21: {sleep_time_ms_21} sleep_time_ms_22: {sleep_time_ms_22} sleep_time_ms_23: {sleep_time_ms_23} sleep_time_ms_24: {sleep_time_ms_24} sleep_time_ms_25: {sleep_time_ms_25} sleep_time_ms_26: {sleep_time_ms_26} sleep_time_ms_27: {sleep_time_ms_27} sleep_time_ms_28: {sleep_time_ms_28} sleep_time_ms_29: {sleep_time_ms_29} sleep_time_ms_30: {sleep_time_ms_30} sleep_time_ms_31: {sleep_time_ms_31} sleep_time_ms_32: {sleep_time_ms_32} sleep_time_ms_33: {sleep_time_ms_33} sleep_time_ms_34: {sleep_time_ms_34} sleep_time_ms_35: {sleep_time_ms_35} sleep_time_ms_36: {sleep_time_ms_36} sleep_time_ms_37: {sleep_time_ms_37} sleep_time_ms_38: {sleep_time_ms_38} sleep_time_ms_39: {sleep_time_ms_39} sleep_time_ms_40: {sleep_time_ms_40} sleep_time_ms_41: {sleep_time_ms_41} sleep_time_ms_42: {sleep_time_ms_42} sleep_time_ms_43: {sleep_time_ms_43} sleep_time_ms_44: {sleep_time_ms_44} sleep_time_ms_45: {sleep_time_ms_45} sleep_time_ms_46: {sleep_time_ms_46} sleep_time_ms_47: {sleep_time_ms_47} sleep_time_ms_48: {sleep_time_ms_48} sleep_time_ms_49: {sleep_time_ms_49} sleep_time_ms_50: {sleep_time_ms_50} sleep_time_ms_51: {sleep_time_ms_51} sleep_time_ms_52: {sleep_time_ms_52} sleep_time_ms_53: {sleep_time_ms_53} sleep_time_ms_54: {sleep_time_ms_54} sleep_time_ms_55: {sleep_time_ms_55} sleep_time_ms_56: {sleep_time_ms_56} sleep_time_ms_57: {sleep_time_ms_57} sleep_time_ms_58: {sleep_time_ms_58} sleep_time_ms_59: {sleep_time_ms_59} sleep_time_ms_60: {sleep_time_ms_60} sleep_time_ms_61: {sleep_time_ms_61} sleep_time_ms_62: {sleep_time_ms_62} sleep_time_ms_63: {sleep_time_ms_63} sleep_time_ms_64: {sleep_time_ms_64} sleep_time_ms_65: {sleep_time_ms_65} sleep_time_ms_66: {sleep_time_ms_66} sleep_time_ms_67: {sleep_time_ms_67} sleep_time_ms_68: {sleep_time_ms_68} sleep_time_ms_69: {sleep_time_ms_69} sleep_time_ms_70: {sleep_time_ms_70} sleep_time_ms_71: {sleep_time_ms_71} sleep_time_ms_72: {sleep_time_ms_72} sleep_time_ms_73: {sleep_time_ms_73} sleep_time_ms_74: {sleep_time_ms_74} sleep_time_ms_75: {sleep_time_ms_75} sleep_time_ms_76: {sleep_time_ms_76} sleep_time_ms_77: {sleep_time_ms_77} sleep_time_ms_78: {sleep_time_ms_78} sleep_time_ms_79: {sleep_time_ms_79} sleep_time_ms_80: {sleep_time_ms_80} sleep_time_ms_81: {sleep_time_ms_81} sleep_time_ms_82: {sleep_time_ms_82} sleep_time_ms_83: {sleep_time_ms_83} sleep_time_ms_84: {sleep_time_ms_84} sleep_time_ms_85: {sleep_time_ms_85} sleep_time_ms_86: {sleep_time_ms_86} sleep_time_ms_87: {sleep_time_ms_87} sleep_time_ms_88: {sleep_time_ms_88} sleep_time_ms_89: {sleep_time_ms_89} sleep_time_ms_90: {sleep_time_ms_90} sleep_time_ms_91: {sleep_time_ms_91} sleep_time_ms_92: {sleep_time_ms_92} sleep_time_ms_93: {sleep_time_ms_93} sleep_time_ms_94: {sleep_time_ms_94} sleep_time_ms_95: {sleep_time_ms_95} sleep_time_ms_96: {sleep_time_ms_96} sleep_time_ms_97: {sleep_time_ms_97} sleep_time_ms_98: {sleep_time_ms_98} sleep_time_ms_99: {sleep_time_ms_99} sleep_time_ms_100: {sleep_time_ms_100} sleep_time_ms_101: {sleep_time_ms_101} sleep_time_ms_102: {sleep_time_ms_102} sleep_time_ms_103: {sleep_time_ms_103} sleep_time_ms_104: {sleep_time_ms_104} sleep_time_ms_105: {sleep_time_ms_105} sleep_time_ms_106: {sleep_time_ms_106} sleep_time_ms_107: {sleep_time_ms_107} sleep_time_ms_108: {sleep_time_ms_108} sleep_time_ms_109: {sleep_time_ms_109} sleep_time_ms_110: {sleep_time_ms_110} sleep_time_ms_111: {sleep_time_ms_111} sleep_time_ms_112: {sleep_time_ms_112} sleep_time_ms_113: {sleep_time_ms_113} sleep_time_ms_114: {sleep_time_ms_114} sleep_time_ms_115: {sleep_time_ms_115} sleep_time_ms_116: {sleep_time_ms_116} sleep_time_ms_117: {sleep_time_ms_117} sleep_time_ms_118: {sleep_time_ms_118} sleep_time_ms_119: {sleep_time_ms_119} sleep_time_ms_120: {sleep_time_ms_120} sleep_time_ms_121: {sleep_time_ms_121} sleep_time_ms_122: {sleep_time_ms_122} sleep_time_ms_123: {sleep_time_ms_123} sleep_time_ms_124: {sleep_time_ms_124} sleep_time_ms_125: {sleep_time_ms_125} sleep_time_ms_126: {sleep_time_ms_126} sleep_time_ms_127: {sleep_time_ms_127} sleep_time_ms_128: {sleep_time_ms_128}")

            # 执行最后的sleep，使用优化比例
            return dynamic_sleep_task(
                sleep_time_ms=sleep_time_ms,
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


    # specify data flow
    sleep_time_ms = 5000
    _enable_optimization = True

    func_1_1_output = func_1_1(sleep_time_ms = sleep_time_ms, dynamic_ratio=1, task_name='func_1_1')

    func_1_2_output = func_1_2(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_2', enable_optimization=_enable_optimization)

    func_1_3_output = func_1_3(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_3', enable_optimization=_enable_optimization)

    func_1_4_output = func_1_4(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_4', enable_optimization=_enable_optimization)

    func_1_5_output = func_1_5(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_5', enable_optimization=_enable_optimization)

    func_1_6_output = func_1_6(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_6', enable_optimization=_enable_optimization)

    func_1_7_output = func_1_7(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_7', enable_optimization=_enable_optimization)

    func_1_8_output = func_1_8(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_8', enable_optimization=_enable_optimization)

    func_1_9_output = func_1_9(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_9', enable_optimization=_enable_optimization)

    func_1_10_output = func_1_10(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_10', enable_optimization=_enable_optimization)

    func_1_11_output = func_1_11(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_11', enable_optimization=_enable_optimization)

    func_1_12_output = func_1_12(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_12', enable_optimization=_enable_optimization)

    func_1_13_output = func_1_13(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_13', enable_optimization=_enable_optimization)

    func_1_14_output = func_1_14(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_14', enable_optimization=_enable_optimization)

    func_1_15_output = func_1_15(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_15', enable_optimization=_enable_optimization)

    func_1_16_output = func_1_16(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_16', enable_optimization=_enable_optimization)

    func_1_17_output = func_1_17(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_17', enable_optimization=_enable_optimization)

    func_1_18_output = func_1_18(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_18', enable_optimization=_enable_optimization)

    func_1_19_output = func_1_19(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_19', enable_optimization=_enable_optimization)

    func_1_20_output = func_1_20(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_20', enable_optimization=_enable_optimization)

    func_1_21_output = func_1_21(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_21', enable_optimization=_enable_optimization)

    func_1_22_output = func_1_22(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_22', enable_optimization=_enable_optimization)

    func_1_23_output = func_1_23(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_23', enable_optimization=_enable_optimization)

    func_1_24_output = func_1_24(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_24', enable_optimization=_enable_optimization)

    func_1_25_output = func_1_25(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_25', enable_optimization=_enable_optimization)

    func_1_26_output = func_1_26(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_26', enable_optimization=_enable_optimization)

    func_1_27_output = func_1_27(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_27', enable_optimization=_enable_optimization)

    func_1_28_output = func_1_28(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_28', enable_optimization=_enable_optimization)

    func_1_29_output = func_1_29(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_29', enable_optimization=_enable_optimization)

    func_1_30_output = func_1_30(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_30', enable_optimization=_enable_optimization)

    func_1_31_output = func_1_31(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_31', enable_optimization=_enable_optimization)

    func_1_32_output = func_1_32(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_32', enable_optimization=_enable_optimization)

    func_1_33_output = func_1_33(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_33', enable_optimization=_enable_optimization)

    func_1_34_output = func_1_34(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_34', enable_optimization=_enable_optimization)

    func_1_35_output = func_1_35(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_35', enable_optimization=_enable_optimization)

    func_1_36_output = func_1_36(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_36', enable_optimization=_enable_optimization)

    func_1_37_output = func_1_37(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_37', enable_optimization=_enable_optimization)

    func_1_38_output = func_1_38(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_38', enable_optimization=_enable_optimization)

    func_1_39_output = func_1_39(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_39', enable_optimization=_enable_optimization)

    func_1_40_output = func_1_40(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_40', enable_optimization=_enable_optimization)

    func_1_41_output = func_1_41(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_41', enable_optimization=_enable_optimization)

    func_1_42_output = func_1_42(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_42', enable_optimization=_enable_optimization)

    func_1_43_output = func_1_43(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_43', enable_optimization=_enable_optimization)

    func_1_44_output = func_1_44(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_44', enable_optimization=_enable_optimization)

    func_1_45_output = func_1_45(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_45', enable_optimization=_enable_optimization)

    func_1_46_output = func_1_46(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_46', enable_optimization=_enable_optimization)

    func_1_47_output = func_1_47(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_47', enable_optimization=_enable_optimization)

    func_1_48_output = func_1_48(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_48', enable_optimization=_enable_optimization)

    func_1_49_output = func_1_49(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_49', enable_optimization=_enable_optimization)

    func_1_50_output = func_1_50(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_50', enable_optimization=_enable_optimization)

    func_1_51_output = func_1_51(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_51', enable_optimization=_enable_optimization)

    func_1_52_output = func_1_52(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_52', enable_optimization=_enable_optimization)

    func_1_53_output = func_1_53(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_53', enable_optimization=_enable_optimization)

    func_1_54_output = func_1_54(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_54', enable_optimization=_enable_optimization)

    func_1_55_output = func_1_55(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_55', enable_optimization=_enable_optimization)

    func_1_56_output = func_1_56(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_56', enable_optimization=_enable_optimization)

    func_1_57_output = func_1_57(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_57', enable_optimization=_enable_optimization)

    func_1_58_output = func_1_58(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_58', enable_optimization=_enable_optimization)

    func_1_59_output = func_1_59(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_59', enable_optimization=_enable_optimization)

    func_1_60_output = func_1_60(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_60', enable_optimization=_enable_optimization)

    func_1_61_output = func_1_61(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_61', enable_optimization=_enable_optimization)

    func_1_62_output = func_1_62(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_62', enable_optimization=_enable_optimization)

    func_1_63_output = func_1_63(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_63', enable_optimization=_enable_optimization)

    func_1_64_output = func_1_64(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_64', enable_optimization=_enable_optimization)

    func_1_65_output = func_1_65(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_65', enable_optimization=_enable_optimization)

    func_1_66_output = func_1_66(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_66', enable_optimization=_enable_optimization)

    func_1_67_output = func_1_67(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_67', enable_optimization=_enable_optimization)

    func_1_68_output = func_1_68(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_68', enable_optimization=_enable_optimization)

    func_1_69_output = func_1_69(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_69', enable_optimization=_enable_optimization)

    func_1_70_output = func_1_70(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_70', enable_optimization=_enable_optimization)

    func_1_71_output = func_1_71(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_71', enable_optimization=_enable_optimization)

    func_1_72_output = func_1_72(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_72', enable_optimization=_enable_optimization)

    func_1_73_output = func_1_73(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_73', enable_optimization=_enable_optimization)

    func_1_74_output = func_1_74(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_74', enable_optimization=_enable_optimization)

    func_1_75_output = func_1_75(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_75', enable_optimization=_enable_optimization)

    func_1_76_output = func_1_76(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_76', enable_optimization=_enable_optimization)

    func_1_77_output = func_1_77(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_77', enable_optimization=_enable_optimization)

    func_1_78_output = func_1_78(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_78', enable_optimization=_enable_optimization)

    func_1_79_output = func_1_79(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_79', enable_optimization=_enable_optimization)

    func_1_80_output = func_1_80(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_80', enable_optimization=_enable_optimization)

    func_1_81_output = func_1_81(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_81', enable_optimization=_enable_optimization)

    func_1_82_output = func_1_82(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_82', enable_optimization=_enable_optimization)

    func_1_83_output = func_1_83(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_83', enable_optimization=_enable_optimization)

    func_1_84_output = func_1_84(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_84', enable_optimization=_enable_optimization)

    func_1_85_output = func_1_85(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_85', enable_optimization=_enable_optimization)

    func_1_86_output = func_1_86(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_86', enable_optimization=_enable_optimization)

    func_1_87_output = func_1_87(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_87', enable_optimization=_enable_optimization)

    func_1_88_output = func_1_88(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_88', enable_optimization=_enable_optimization)

    func_1_89_output = func_1_89(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_89', enable_optimization=_enable_optimization)

    func_1_90_output = func_1_90(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_90', enable_optimization=_enable_optimization)

    func_1_91_output = func_1_91(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_91', enable_optimization=_enable_optimization)

    func_1_92_output = func_1_92(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_92', enable_optimization=_enable_optimization)

    func_1_93_output = func_1_93(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_93', enable_optimization=_enable_optimization)

    func_1_94_output = func_1_94(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_94', enable_optimization=_enable_optimization)

    func_1_95_output = func_1_95(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_95', enable_optimization=_enable_optimization)

    func_1_96_output = func_1_96(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_96', enable_optimization=_enable_optimization)

    func_1_97_output = func_1_97(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_97', enable_optimization=_enable_optimization)

    func_1_98_output = func_1_98(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_98', enable_optimization=_enable_optimization)

    func_1_99_output = func_1_99(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_99', enable_optimization=_enable_optimization)

    func_1_100_output = func_1_100(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_100', enable_optimization=_enable_optimization)

    func_1_101_output = func_1_101(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_101', enable_optimization=_enable_optimization)

    func_1_102_output = func_1_102(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_102', enable_optimization=_enable_optimization)

    func_1_103_output = func_1_103(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_103', enable_optimization=_enable_optimization)

    func_1_104_output = func_1_104(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_104', enable_optimization=_enable_optimization)

    func_1_105_output = func_1_105(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_105', enable_optimization=_enable_optimization)

    func_1_106_output = func_1_106(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_106', enable_optimization=_enable_optimization)

    func_1_107_output = func_1_107(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_107', enable_optimization=_enable_optimization)

    func_1_108_output = func_1_108(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_108', enable_optimization=_enable_optimization)

    func_1_109_output = func_1_109(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_109', enable_optimization=_enable_optimization)

    func_1_110_output = func_1_110(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_110', enable_optimization=_enable_optimization)

    func_1_111_output = func_1_111(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_111', enable_optimization=_enable_optimization)

    func_1_112_output = func_1_112(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_112', enable_optimization=_enable_optimization)

    func_1_113_output = func_1_113(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_113', enable_optimization=_enable_optimization)

    func_1_114_output = func_1_114(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_114', enable_optimization=_enable_optimization)

    func_1_115_output = func_1_115(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_115', enable_optimization=_enable_optimization)

    func_1_116_output = func_1_116(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_116', enable_optimization=_enable_optimization)

    func_1_117_output = func_1_117(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_117', enable_optimization=_enable_optimization)

    func_1_118_output = func_1_118(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_118', enable_optimization=_enable_optimization)

    func_1_119_output = func_1_119(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_119', enable_optimization=_enable_optimization)

    func_1_120_output = func_1_120(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_120', enable_optimization=_enable_optimization)

    func_1_121_output = func_1_121(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_121', enable_optimization=_enable_optimization)

    func_1_122_output = func_1_122(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_122', enable_optimization=_enable_optimization)

    func_1_123_output = func_1_123(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_123', enable_optimization=_enable_optimization)

    func_1_124_output = func_1_124(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_124', enable_optimization=_enable_optimization)

    func_1_125_output = func_1_125(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_125', enable_optimization=_enable_optimization)

    func_1_126_output = func_1_126(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_126', enable_optimization=_enable_optimization)

    func_1_127_output = func_1_127(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_127', enable_optimization=_enable_optimization)

    func_1_128_output = func_1_128(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_128', enable_optimization=_enable_optimization)

    func_1_129_output = func_1_129(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_1', task_name='func_1_129', enable_optimization=_enable_optimization)

    func_1_130_output = func_1_130(sleep_time_ms_1 = func_1_2_output, sleep_time_ms_2 = func_1_3_output, sleep_time_ms_3 = func_1_4_output, sleep_time_ms_4 = func_1_5_output, sleep_time_ms_5 = func_1_6_output, sleep_time_ms_6 = func_1_7_output, sleep_time_ms_7 = func_1_8_output, sleep_time_ms_8 = func_1_9_output, sleep_time_ms_9 = func_1_10_output, sleep_time_ms_10 = func_1_11_output, sleep_time_ms_11 = func_1_12_output, sleep_time_ms_12 = func_1_13_output, sleep_time_ms_13 = func_1_14_output, sleep_time_ms_14 = func_1_15_output, sleep_time_ms_15 = func_1_16_output, sleep_time_ms_16 = func_1_17_output, sleep_time_ms_17 = func_1_18_output, sleep_time_ms_18 = func_1_19_output, sleep_time_ms_19 = func_1_20_output, sleep_time_ms_20 = func_1_21_output, sleep_time_ms_21 = func_1_22_output, sleep_time_ms_22 = func_1_23_output, sleep_time_ms_23 = func_1_24_output, sleep_time_ms_24 = func_1_25_output, sleep_time_ms_25 = func_1_26_output, sleep_time_ms_26 = func_1_27_output, sleep_time_ms_27 = func_1_28_output, sleep_time_ms_28 = func_1_29_output, sleep_time_ms_29 = func_1_30_output, sleep_time_ms_30 = func_1_31_output, sleep_time_ms_31 = func_1_32_output, sleep_time_ms_32 = func_1_33_output, sleep_time_ms_33 = func_1_34_output, sleep_time_ms_34 = func_1_35_output, sleep_time_ms_35 = func_1_36_output, sleep_time_ms_36 = func_1_37_output, sleep_time_ms_37 = func_1_38_output, sleep_time_ms_38 = func_1_39_output, sleep_time_ms_39 = func_1_40_output, sleep_time_ms_40 = func_1_41_output, sleep_time_ms_41 = func_1_42_output, sleep_time_ms_42 = func_1_43_output, sleep_time_ms_43 = func_1_44_output, sleep_time_ms_44 = func_1_45_output, sleep_time_ms_45 = func_1_46_output, sleep_time_ms_46 = func_1_47_output, sleep_time_ms_47 = func_1_48_output, sleep_time_ms_48 = func_1_49_output, sleep_time_ms_49 = func_1_50_output, sleep_time_ms_50 = func_1_51_output, sleep_time_ms_51 = func_1_52_output, sleep_time_ms_52 = func_1_53_output, sleep_time_ms_53 = func_1_54_output, sleep_time_ms_54 = func_1_55_output, sleep_time_ms_55 = func_1_56_output, sleep_time_ms_56 = func_1_57_output, sleep_time_ms_57 = func_1_58_output, sleep_time_ms_58 = func_1_59_output, sleep_time_ms_59 = func_1_60_output, sleep_time_ms_60 = func_1_61_output, sleep_time_ms_61 = func_1_62_output, sleep_time_ms_62 = func_1_63_output, sleep_time_ms_63 = func_1_64_output, sleep_time_ms_64 = func_1_65_output, sleep_time_ms_65 = func_1_66_output, sleep_time_ms_66 = func_1_67_output, sleep_time_ms_67 = func_1_68_output, sleep_time_ms_68 = func_1_69_output, sleep_time_ms_69 = func_1_70_output, sleep_time_ms_70 = func_1_71_output, sleep_time_ms_71 = func_1_72_output, sleep_time_ms_72 = func_1_73_output, sleep_time_ms_73 = func_1_74_output, sleep_time_ms_74 = func_1_75_output, sleep_time_ms_75 = func_1_76_output, sleep_time_ms_76 = func_1_77_output, sleep_time_ms_77 = func_1_78_output, sleep_time_ms_78 = func_1_79_output, sleep_time_ms_79 = func_1_80_output, sleep_time_ms_80 = func_1_81_output, sleep_time_ms_81 = func_1_82_output, sleep_time_ms_82 = func_1_83_output, sleep_time_ms_83 = func_1_84_output, sleep_time_ms_84 = func_1_85_output, sleep_time_ms_85 = func_1_86_output, sleep_time_ms_86 = func_1_87_output, sleep_time_ms_87 = func_1_88_output, sleep_time_ms_88 = func_1_89_output, sleep_time_ms_89 = func_1_90_output, sleep_time_ms_90 = func_1_91_output, sleep_time_ms_91 = func_1_92_output, sleep_time_ms_92 = func_1_93_output, sleep_time_ms_93 = func_1_94_output, sleep_time_ms_94 = func_1_95_output, sleep_time_ms_95 = func_1_96_output, sleep_time_ms_96 = func_1_97_output, sleep_time_ms_97 = func_1_98_output, sleep_time_ms_98 = func_1_99_output, sleep_time_ms_99 = func_1_100_output, sleep_time_ms_100 = func_1_101_output, sleep_time_ms_101 = func_1_102_output, sleep_time_ms_102 = func_1_103_output, sleep_time_ms_103 = func_1_104_output, sleep_time_ms_104 = func_1_105_output, sleep_time_ms_105 = func_1_106_output, sleep_time_ms_106 = func_1_107_output, sleep_time_ms_107 = func_1_108_output, sleep_time_ms_108 = func_1_109_output, sleep_time_ms_109 = func_1_110_output, sleep_time_ms_110 = func_1_111_output, sleep_time_ms_111 = func_1_112_output, sleep_time_ms_112 = func_1_113_output, sleep_time_ms_113 = func_1_114_output, sleep_time_ms_114 = func_1_115_output, sleep_time_ms_115 = func_1_116_output, sleep_time_ms_116 = func_1_117_output, sleep_time_ms_117 = func_1_118_output, sleep_time_ms_118 = func_1_119_output, sleep_time_ms_119 = func_1_120_output, sleep_time_ms_120 = func_1_121_output, sleep_time_ms_121 = func_1_122_output, sleep_time_ms_122 = func_1_123_output, sleep_time_ms_123 = func_1_124_output, sleep_time_ms_124 = func_1_125_output, sleep_time_ms_125 = func_1_126_output, sleep_time_ms_126 = func_1_127_output, sleep_time_ms_127 = func_1_128_output, sleep_time_ms_128 = func_1_129_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w128_d3', upstream_task_id='func_1_129', task_name='func_1_130', enable_optimization=_enable_optimization)

# execute dag
etl_dag = dag_w128_d3()
