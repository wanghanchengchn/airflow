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
def dag_w256_d3():
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_2',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_3',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_4',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_5',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_6',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_7',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_8',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_9',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_10',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_11',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_12',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_13',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_14',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_15',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_16',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_17',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_18',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_19',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_20',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_21',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_22',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_23',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_24',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_25',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_26',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_27',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_28',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_29',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_30',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_31',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_32',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_33',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_34',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_35',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_36',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_37',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_38',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_39',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_40',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_41',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_42',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_43',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_44',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_45',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_46',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_47',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_48',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_49',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_50',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_51',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_52',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_53',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_54',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_55',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_56',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_57',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_58',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_59',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_60',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_61',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_62',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_63',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_64',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_65',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_66',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_67',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_68',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_69',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_70',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_71',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_72',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_73',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_74',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_75',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_76',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_77',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_78',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_79',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_80',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_81',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_82',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_83',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_84',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_85',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_86',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_87',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_88',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_89',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_90',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_91',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_92',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_93',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_94',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_95',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_96',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_97',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_98',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_99',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_100',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_101',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_102',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_103',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_104',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_105',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_106',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_107',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_108',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_109',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_110',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_111',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_112',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_113',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_114',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_115',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_116',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_117',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_118',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_119',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_120',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_121',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_122',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_123',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_124',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_125',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_126',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_127',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_128',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_129',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_130',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_131(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_131',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_132(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_132',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_133(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_133',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_134(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_134',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_135(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_135',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_136(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_136',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_137(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_137',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_138(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_138',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_139(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_139',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_140(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_140',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_141(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_141',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_142(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_142',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_143(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_143',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_144(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_144',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_145(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_145',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_146(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_146',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_147(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_147',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_148(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_148',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_149(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_149',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_150(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_150',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_151(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_151',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_152(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_152',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_153(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_153',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_154(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_154',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_155(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_155',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_156(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_156',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_157(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_157',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_158(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_158',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_159(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_159',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_160(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_160',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_161(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_161',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_162(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_162',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_163(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_163',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_164(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_164',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_165(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_165',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_166(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_166',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_167(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_167',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_168(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_168',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_169(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_169',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_170(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_170',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_171(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_171',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_172(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_172',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_173(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_173',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_174(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_174',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_175(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_175',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_176(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_176',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_177(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_177',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_178(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_178',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_179(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_179',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_180(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_180',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_181(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_181',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_182(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_182',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_183(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_183',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_184(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_184',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_185(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_185',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_186(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_186',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_187(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_187',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_188(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_188',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_189(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_189',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_190(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_190',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_191(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_191',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_192(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_192',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_193(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_193',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_194(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_194',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_195(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_195',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_196(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_196',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_197(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_197',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_198(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_198',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_199(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_199',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_200(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_200',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_201(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_201',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_202(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_202',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_203(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_203',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_204(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_204',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_205(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_205',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_206(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_206',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_207(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_207',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_208(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_208',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_209(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_209',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_210(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_210',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_211(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_211',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_212(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_212',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_213(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_213',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_214(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_214',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_215(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_215',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_216(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_216',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_217(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_217',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_218(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_218',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_219(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_219',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_220(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_220',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_221(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_221',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_222(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_222',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_223(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_223',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_224(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_224',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_225(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_225',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_226(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_226',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_227(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_227',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_228(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_228',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_229(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_229',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_230(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_230',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_231(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_231',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_232(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_232',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_233(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_233',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_234(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_234',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_235(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_235',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_236(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_236',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_237(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_237',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_238(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_238',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_239(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_239',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_240(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_240',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_241(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_241',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_242(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_242',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_243(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_243',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_244(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_244',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_245(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_245',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_246(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_246',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_247(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_247',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_248(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_248',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_249(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_249',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_250(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_250',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_251(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_251',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_252(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_252',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_253(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_253',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_254(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_254',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_255(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_255',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_256(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_256',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_257(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_257',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
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
    def func_1_258(
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
        sleep_time_ms_129: int,
        sleep_time_ms_130: int,
        sleep_time_ms_131: int,
        sleep_time_ms_132: int,
        sleep_time_ms_133: int,
        sleep_time_ms_134: int,
        sleep_time_ms_135: int,
        sleep_time_ms_136: int,
        sleep_time_ms_137: int,
        sleep_time_ms_138: int,
        sleep_time_ms_139: int,
        sleep_time_ms_140: int,
        sleep_time_ms_141: int,
        sleep_time_ms_142: int,
        sleep_time_ms_143: int,
        sleep_time_ms_144: int,
        sleep_time_ms_145: int,
        sleep_time_ms_146: int,
        sleep_time_ms_147: int,
        sleep_time_ms_148: int,
        sleep_time_ms_149: int,
        sleep_time_ms_150: int,
        sleep_time_ms_151: int,
        sleep_time_ms_152: int,
        sleep_time_ms_153: int,
        sleep_time_ms_154: int,
        sleep_time_ms_155: int,
        sleep_time_ms_156: int,
        sleep_time_ms_157: int,
        sleep_time_ms_158: int,
        sleep_time_ms_159: int,
        sleep_time_ms_160: int,
        sleep_time_ms_161: int,
        sleep_time_ms_162: int,
        sleep_time_ms_163: int,
        sleep_time_ms_164: int,
        sleep_time_ms_165: int,
        sleep_time_ms_166: int,
        sleep_time_ms_167: int,
        sleep_time_ms_168: int,
        sleep_time_ms_169: int,
        sleep_time_ms_170: int,
        sleep_time_ms_171: int,
        sleep_time_ms_172: int,
        sleep_time_ms_173: int,
        sleep_time_ms_174: int,
        sleep_time_ms_175: int,
        sleep_time_ms_176: int,
        sleep_time_ms_177: int,
        sleep_time_ms_178: int,
        sleep_time_ms_179: int,
        sleep_time_ms_180: int,
        sleep_time_ms_181: int,
        sleep_time_ms_182: int,
        sleep_time_ms_183: int,
        sleep_time_ms_184: int,
        sleep_time_ms_185: int,
        sleep_time_ms_186: int,
        sleep_time_ms_187: int,
        sleep_time_ms_188: int,
        sleep_time_ms_189: int,
        sleep_time_ms_190: int,
        sleep_time_ms_191: int,
        sleep_time_ms_192: int,
        sleep_time_ms_193: int,
        sleep_time_ms_194: int,
        sleep_time_ms_195: int,
        sleep_time_ms_196: int,
        sleep_time_ms_197: int,
        sleep_time_ms_198: int,
        sleep_time_ms_199: int,
        sleep_time_ms_200: int,
        sleep_time_ms_201: int,
        sleep_time_ms_202: int,
        sleep_time_ms_203: int,
        sleep_time_ms_204: int,
        sleep_time_ms_205: int,
        sleep_time_ms_206: int,
        sleep_time_ms_207: int,
        sleep_time_ms_208: int,
        sleep_time_ms_209: int,
        sleep_time_ms_210: int,
        sleep_time_ms_211: int,
        sleep_time_ms_212: int,
        sleep_time_ms_213: int,
        sleep_time_ms_214: int,
        sleep_time_ms_215: int,
        sleep_time_ms_216: int,
        sleep_time_ms_217: int,
        sleep_time_ms_218: int,
        sleep_time_ms_219: int,
        sleep_time_ms_220: int,
        sleep_time_ms_221: int,
        sleep_time_ms_222: int,
        sleep_time_ms_223: int,
        sleep_time_ms_224: int,
        sleep_time_ms_225: int,
        sleep_time_ms_226: int,
        sleep_time_ms_227: int,
        sleep_time_ms_228: int,
        sleep_time_ms_229: int,
        sleep_time_ms_230: int,
        sleep_time_ms_231: int,
        sleep_time_ms_232: int,
        sleep_time_ms_233: int,
        sleep_time_ms_234: int,
        sleep_time_ms_235: int,
        sleep_time_ms_236: int,
        sleep_time_ms_237: int,
        sleep_time_ms_238: int,
        sleep_time_ms_239: int,
        sleep_time_ms_240: int,
        sleep_time_ms_241: int,
        sleep_time_ms_242: int,
        sleep_time_ms_243: int,
        sleep_time_ms_244: int,
        sleep_time_ms_245: int,
        sleep_time_ms_246: int,
        sleep_time_ms_247: int,
        sleep_time_ms_248: int,
        sleep_time_ms_249: int,
        sleep_time_ms_250: int,
        sleep_time_ms_251: int,
        sleep_time_ms_252: int,
        sleep_time_ms_253: int,
        sleep_time_ms_254: int,
        sleep_time_ms_255: int,
        sleep_time_ms_256: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w256_d3',
        upstream_task_id: str = 'func_1_257',
        task_name: str = 'func_1_258',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w256_d3'
            upstream_task_id: 上游任务ID，默认'func_1_257'
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
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_130')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_131')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_132')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_133')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_134')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_135')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_136')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_137')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_138')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_139')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_140')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_141')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_142')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_143')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_144')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_145')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_146')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_147')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_148')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_149')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_150')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_151')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_152')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_153')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_154')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_155')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_156')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_157')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_158')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_159')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_160')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_161')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_162')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_163')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_164')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_165')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_166')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_167')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_168')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_169')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_170')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_171')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_172')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_173')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_174')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_175')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_176')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_177')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_178')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_179')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_180')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_181')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_182')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_183')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_184')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_185')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_186')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_187')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_188')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_189')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_190')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_191')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_192')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_193')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_194')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_195')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_196')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_197')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_198')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_199')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_200')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_201')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_202')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_203')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_204')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_205')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_206')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_207')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_208')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_209')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_210')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_211')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_212')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_213')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_214')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_215')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_216')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_217')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_218')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_219')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_220')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_221')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_222')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_223')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_224')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_225')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_226')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_227')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_228')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_229')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_230')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_231')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_232')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_233')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_234')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_235')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_236')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_237')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_238')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_239')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_240')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_241')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_242')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_243')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_244')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_245')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_246')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_247')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_248')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_249')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_250')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_251')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_252')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_253')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_254')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_255')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_256')),
                (get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_257')),
                (fixed_sleep_task, (fixed_sleep_seconds, f"{task_name}_partA"))
            ]
            
            # 并行执行任务
            sleep_time_ms_1, sleep_time_ms_2, sleep_time_ms_3, sleep_time_ms_4, sleep_time_ms_5, sleep_time_ms_6, sleep_time_ms_7, sleep_time_ms_8, sleep_time_ms_9, sleep_time_ms_10, sleep_time_ms_11, sleep_time_ms_12, sleep_time_ms_13, sleep_time_ms_14, sleep_time_ms_15, sleep_time_ms_16, sleep_time_ms_17, sleep_time_ms_18, sleep_time_ms_19, sleep_time_ms_20, sleep_time_ms_21, sleep_time_ms_22, sleep_time_ms_23, sleep_time_ms_24, sleep_time_ms_25, sleep_time_ms_26, sleep_time_ms_27, sleep_time_ms_28, sleep_time_ms_29, sleep_time_ms_30, sleep_time_ms_31, sleep_time_ms_32, sleep_time_ms_33, sleep_time_ms_34, sleep_time_ms_35, sleep_time_ms_36, sleep_time_ms_37, sleep_time_ms_38, sleep_time_ms_39, sleep_time_ms_40, sleep_time_ms_41, sleep_time_ms_42, sleep_time_ms_43, sleep_time_ms_44, sleep_time_ms_45, sleep_time_ms_46, sleep_time_ms_47, sleep_time_ms_48, sleep_time_ms_49, sleep_time_ms_50, sleep_time_ms_51, sleep_time_ms_52, sleep_time_ms_53, sleep_time_ms_54, sleep_time_ms_55, sleep_time_ms_56, sleep_time_ms_57, sleep_time_ms_58, sleep_time_ms_59, sleep_time_ms_60, sleep_time_ms_61, sleep_time_ms_62, sleep_time_ms_63, sleep_time_ms_64, sleep_time_ms_65, sleep_time_ms_66, sleep_time_ms_67, sleep_time_ms_68, sleep_time_ms_69, sleep_time_ms_70, sleep_time_ms_71, sleep_time_ms_72, sleep_time_ms_73, sleep_time_ms_74, sleep_time_ms_75, sleep_time_ms_76, sleep_time_ms_77, sleep_time_ms_78, sleep_time_ms_79, sleep_time_ms_80, sleep_time_ms_81, sleep_time_ms_82, sleep_time_ms_83, sleep_time_ms_84, sleep_time_ms_85, sleep_time_ms_86, sleep_time_ms_87, sleep_time_ms_88, sleep_time_ms_89, sleep_time_ms_90, sleep_time_ms_91, sleep_time_ms_92, sleep_time_ms_93, sleep_time_ms_94, sleep_time_ms_95, sleep_time_ms_96, sleep_time_ms_97, sleep_time_ms_98, sleep_time_ms_99, sleep_time_ms_100, sleep_time_ms_101, sleep_time_ms_102, sleep_time_ms_103, sleep_time_ms_104, sleep_time_ms_105, sleep_time_ms_106, sleep_time_ms_107, sleep_time_ms_108, sleep_time_ms_109, sleep_time_ms_110, sleep_time_ms_111, sleep_time_ms_112, sleep_time_ms_113, sleep_time_ms_114, sleep_time_ms_115, sleep_time_ms_116, sleep_time_ms_117, sleep_time_ms_118, sleep_time_ms_119, sleep_time_ms_120, sleep_time_ms_121, sleep_time_ms_122, sleep_time_ms_123, sleep_time_ms_124, sleep_time_ms_125, sleep_time_ms_126, sleep_time_ms_127, sleep_time_ms_128, sleep_time_ms_129, sleep_time_ms_130, sleep_time_ms_131, sleep_time_ms_132, sleep_time_ms_133, sleep_time_ms_134, sleep_time_ms_135, sleep_time_ms_136, sleep_time_ms_137, sleep_time_ms_138, sleep_time_ms_139, sleep_time_ms_140, sleep_time_ms_141, sleep_time_ms_142, sleep_time_ms_143, sleep_time_ms_144, sleep_time_ms_145, sleep_time_ms_146, sleep_time_ms_147, sleep_time_ms_148, sleep_time_ms_149, sleep_time_ms_150, sleep_time_ms_151, sleep_time_ms_152, sleep_time_ms_153, sleep_time_ms_154, sleep_time_ms_155, sleep_time_ms_156, sleep_time_ms_157, sleep_time_ms_158, sleep_time_ms_159, sleep_time_ms_160, sleep_time_ms_161, sleep_time_ms_162, sleep_time_ms_163, sleep_time_ms_164, sleep_time_ms_165, sleep_time_ms_166, sleep_time_ms_167, sleep_time_ms_168, sleep_time_ms_169, sleep_time_ms_170, sleep_time_ms_171, sleep_time_ms_172, sleep_time_ms_173, sleep_time_ms_174, sleep_time_ms_175, sleep_time_ms_176, sleep_time_ms_177, sleep_time_ms_178, sleep_time_ms_179, sleep_time_ms_180, sleep_time_ms_181, sleep_time_ms_182, sleep_time_ms_183, sleep_time_ms_184, sleep_time_ms_185, sleep_time_ms_186, sleep_time_ms_187, sleep_time_ms_188, sleep_time_ms_189, sleep_time_ms_190, sleep_time_ms_191, sleep_time_ms_192, sleep_time_ms_193, sleep_time_ms_194, sleep_time_ms_195, sleep_time_ms_196, sleep_time_ms_197, sleep_time_ms_198, sleep_time_ms_199, sleep_time_ms_200, sleep_time_ms_201, sleep_time_ms_202, sleep_time_ms_203, sleep_time_ms_204, sleep_time_ms_205, sleep_time_ms_206, sleep_time_ms_207, sleep_time_ms_208, sleep_time_ms_209, sleep_time_ms_210, sleep_time_ms_211, sleep_time_ms_212, sleep_time_ms_213, sleep_time_ms_214, sleep_time_ms_215, sleep_time_ms_216, sleep_time_ms_217, sleep_time_ms_218, sleep_time_ms_219, sleep_time_ms_220, sleep_time_ms_221, sleep_time_ms_222, sleep_time_ms_223, sleep_time_ms_224, sleep_time_ms_225, sleep_time_ms_226, sleep_time_ms_227, sleep_time_ms_228, sleep_time_ms_229, sleep_time_ms_230, sleep_time_ms_231, sleep_time_ms_232, sleep_time_ms_233, sleep_time_ms_234, sleep_time_ms_235, sleep_time_ms_236, sleep_time_ms_237, sleep_time_ms_238, sleep_time_ms_239, sleep_time_ms_240, sleep_time_ms_241, sleep_time_ms_242, sleep_time_ms_243, sleep_time_ms_244, sleep_time_ms_245, sleep_time_ms_246, sleep_time_ms_247, sleep_time_ms_248, sleep_time_ms_249, sleep_time_ms_250, sleep_time_ms_251, sleep_time_ms_252, sleep_time_ms_253, sleep_time_ms_254, sleep_time_ms_255, sleep_time_ms_256, _ = execute_parallel_tasks(tasks)

            sleep_time_ms = max(sleep_time_ms_1, sleep_time_ms_2, sleep_time_ms_3, sleep_time_ms_4, sleep_time_ms_5, sleep_time_ms_6, sleep_time_ms_7, sleep_time_ms_8, sleep_time_ms_9, sleep_time_ms_10, sleep_time_ms_11, sleep_time_ms_12, sleep_time_ms_13, sleep_time_ms_14, sleep_time_ms_15, sleep_time_ms_16, sleep_time_ms_17, sleep_time_ms_18, sleep_time_ms_19, sleep_time_ms_20, sleep_time_ms_21, sleep_time_ms_22, sleep_time_ms_23, sleep_time_ms_24, sleep_time_ms_25, sleep_time_ms_26, sleep_time_ms_27, sleep_time_ms_28, sleep_time_ms_29, sleep_time_ms_30, sleep_time_ms_31, sleep_time_ms_32, sleep_time_ms_33, sleep_time_ms_34, sleep_time_ms_35, sleep_time_ms_36, sleep_time_ms_37, sleep_time_ms_38, sleep_time_ms_39, sleep_time_ms_40, sleep_time_ms_41, sleep_time_ms_42, sleep_time_ms_43, sleep_time_ms_44, sleep_time_ms_45, sleep_time_ms_46, sleep_time_ms_47, sleep_time_ms_48, sleep_time_ms_49, sleep_time_ms_50, sleep_time_ms_51, sleep_time_ms_52, sleep_time_ms_53, sleep_time_ms_54, sleep_time_ms_55, sleep_time_ms_56, sleep_time_ms_57, sleep_time_ms_58, sleep_time_ms_59, sleep_time_ms_60, sleep_time_ms_61, sleep_time_ms_62, sleep_time_ms_63, sleep_time_ms_64, sleep_time_ms_65, sleep_time_ms_66, sleep_time_ms_67, sleep_time_ms_68, sleep_time_ms_69, sleep_time_ms_70, sleep_time_ms_71, sleep_time_ms_72, sleep_time_ms_73, sleep_time_ms_74, sleep_time_ms_75, sleep_time_ms_76, sleep_time_ms_77, sleep_time_ms_78, sleep_time_ms_79, sleep_time_ms_80, sleep_time_ms_81, sleep_time_ms_82, sleep_time_ms_83, sleep_time_ms_84, sleep_time_ms_85, sleep_time_ms_86, sleep_time_ms_87, sleep_time_ms_88, sleep_time_ms_89, sleep_time_ms_90, sleep_time_ms_91, sleep_time_ms_92, sleep_time_ms_93, sleep_time_ms_94, sleep_time_ms_95, sleep_time_ms_96, sleep_time_ms_97, sleep_time_ms_98, sleep_time_ms_99, sleep_time_ms_100, sleep_time_ms_101, sleep_time_ms_102, sleep_time_ms_103, sleep_time_ms_104, sleep_time_ms_105, sleep_time_ms_106, sleep_time_ms_107, sleep_time_ms_108, sleep_time_ms_109, sleep_time_ms_110, sleep_time_ms_111, sleep_time_ms_112, sleep_time_ms_113, sleep_time_ms_114, sleep_time_ms_115, sleep_time_ms_116, sleep_time_ms_117, sleep_time_ms_118, sleep_time_ms_119, sleep_time_ms_120, sleep_time_ms_121, sleep_time_ms_122, sleep_time_ms_123, sleep_time_ms_124, sleep_time_ms_125, sleep_time_ms_126, sleep_time_ms_127, sleep_time_ms_128, sleep_time_ms_129, sleep_time_ms_130, sleep_time_ms_131, sleep_time_ms_132, sleep_time_ms_133, sleep_time_ms_134, sleep_time_ms_135, sleep_time_ms_136, sleep_time_ms_137, sleep_time_ms_138, sleep_time_ms_139, sleep_time_ms_140, sleep_time_ms_141, sleep_time_ms_142, sleep_time_ms_143, sleep_time_ms_144, sleep_time_ms_145, sleep_time_ms_146, sleep_time_ms_147, sleep_time_ms_148, sleep_time_ms_149, sleep_time_ms_150, sleep_time_ms_151, sleep_time_ms_152, sleep_time_ms_153, sleep_time_ms_154, sleep_time_ms_155, sleep_time_ms_156, sleep_time_ms_157, sleep_time_ms_158, sleep_time_ms_159, sleep_time_ms_160, sleep_time_ms_161, sleep_time_ms_162, sleep_time_ms_163, sleep_time_ms_164, sleep_time_ms_165, sleep_time_ms_166, sleep_time_ms_167, sleep_time_ms_168, sleep_time_ms_169, sleep_time_ms_170, sleep_time_ms_171, sleep_time_ms_172, sleep_time_ms_173, sleep_time_ms_174, sleep_time_ms_175, sleep_time_ms_176, sleep_time_ms_177, sleep_time_ms_178, sleep_time_ms_179, sleep_time_ms_180, sleep_time_ms_181, sleep_time_ms_182, sleep_time_ms_183, sleep_time_ms_184, sleep_time_ms_185, sleep_time_ms_186, sleep_time_ms_187, sleep_time_ms_188, sleep_time_ms_189, sleep_time_ms_190, sleep_time_ms_191, sleep_time_ms_192, sleep_time_ms_193, sleep_time_ms_194, sleep_time_ms_195, sleep_time_ms_196, sleep_time_ms_197, sleep_time_ms_198, sleep_time_ms_199, sleep_time_ms_200, sleep_time_ms_201, sleep_time_ms_202, sleep_time_ms_203, sleep_time_ms_204, sleep_time_ms_205, sleep_time_ms_206, sleep_time_ms_207, sleep_time_ms_208, sleep_time_ms_209, sleep_time_ms_210, sleep_time_ms_211, sleep_time_ms_212, sleep_time_ms_213, sleep_time_ms_214, sleep_time_ms_215, sleep_time_ms_216, sleep_time_ms_217, sleep_time_ms_218, sleep_time_ms_219, sleep_time_ms_220, sleep_time_ms_221, sleep_time_ms_222, sleep_time_ms_223, sleep_time_ms_224, sleep_time_ms_225, sleep_time_ms_226, sleep_time_ms_227, sleep_time_ms_228, sleep_time_ms_229, sleep_time_ms_230, sleep_time_ms_231, sleep_time_ms_232, sleep_time_ms_233, sleep_time_ms_234, sleep_time_ms_235, sleep_time_ms_236, sleep_time_ms_237, sleep_time_ms_238, sleep_time_ms_239, sleep_time_ms_240, sleep_time_ms_241, sleep_time_ms_242, sleep_time_ms_243, sleep_time_ms_244, sleep_time_ms_245, sleep_time_ms_246, sleep_time_ms_247, sleep_time_ms_248, sleep_time_ms_249, sleep_time_ms_250, sleep_time_ms_251, sleep_time_ms_252, sleep_time_ms_253, sleep_time_ms_254, sleep_time_ms_255, sleep_time_ms_256)

            logging.info(f"WHC IMP IMP IMP: sleep_time_ms: {sleep_time_ms} sleep_time_ms_1: {sleep_time_ms_1} sleep_time_ms_2: {sleep_time_ms_2} sleep_time_ms_3: {sleep_time_ms_3} sleep_time_ms_4: {sleep_time_ms_4} sleep_time_ms_5: {sleep_time_ms_5} sleep_time_ms_6: {sleep_time_ms_6} sleep_time_ms_7: {sleep_time_ms_7} sleep_time_ms_8: {sleep_time_ms_8} sleep_time_ms_9: {sleep_time_ms_9} sleep_time_ms_10: {sleep_time_ms_10} sleep_time_ms_11: {sleep_time_ms_11} sleep_time_ms_12: {sleep_time_ms_12} sleep_time_ms_13: {sleep_time_ms_13} sleep_time_ms_14: {sleep_time_ms_14} sleep_time_ms_15: {sleep_time_ms_15} sleep_time_ms_16: {sleep_time_ms_16} sleep_time_ms_17: {sleep_time_ms_17} sleep_time_ms_18: {sleep_time_ms_18} sleep_time_ms_19: {sleep_time_ms_19} sleep_time_ms_20: {sleep_time_ms_20} sleep_time_ms_21: {sleep_time_ms_21} sleep_time_ms_22: {sleep_time_ms_22} sleep_time_ms_23: {sleep_time_ms_23} sleep_time_ms_24: {sleep_time_ms_24} sleep_time_ms_25: {sleep_time_ms_25} sleep_time_ms_26: {sleep_time_ms_26} sleep_time_ms_27: {sleep_time_ms_27} sleep_time_ms_28: {sleep_time_ms_28} sleep_time_ms_29: {sleep_time_ms_29} sleep_time_ms_30: {sleep_time_ms_30} sleep_time_ms_31: {sleep_time_ms_31} sleep_time_ms_32: {sleep_time_ms_32} sleep_time_ms_33: {sleep_time_ms_33} sleep_time_ms_34: {sleep_time_ms_34} sleep_time_ms_35: {sleep_time_ms_35} sleep_time_ms_36: {sleep_time_ms_36} sleep_time_ms_37: {sleep_time_ms_37} sleep_time_ms_38: {sleep_time_ms_38} sleep_time_ms_39: {sleep_time_ms_39} sleep_time_ms_40: {sleep_time_ms_40} sleep_time_ms_41: {sleep_time_ms_41} sleep_time_ms_42: {sleep_time_ms_42} sleep_time_ms_43: {sleep_time_ms_43} sleep_time_ms_44: {sleep_time_ms_44} sleep_time_ms_45: {sleep_time_ms_45} sleep_time_ms_46: {sleep_time_ms_46} sleep_time_ms_47: {sleep_time_ms_47} sleep_time_ms_48: {sleep_time_ms_48} sleep_time_ms_49: {sleep_time_ms_49} sleep_time_ms_50: {sleep_time_ms_50} sleep_time_ms_51: {sleep_time_ms_51} sleep_time_ms_52: {sleep_time_ms_52} sleep_time_ms_53: {sleep_time_ms_53} sleep_time_ms_54: {sleep_time_ms_54} sleep_time_ms_55: {sleep_time_ms_55} sleep_time_ms_56: {sleep_time_ms_56} sleep_time_ms_57: {sleep_time_ms_57} sleep_time_ms_58: {sleep_time_ms_58} sleep_time_ms_59: {sleep_time_ms_59} sleep_time_ms_60: {sleep_time_ms_60} sleep_time_ms_61: {sleep_time_ms_61} sleep_time_ms_62: {sleep_time_ms_62} sleep_time_ms_63: {sleep_time_ms_63} sleep_time_ms_64: {sleep_time_ms_64} sleep_time_ms_65: {sleep_time_ms_65} sleep_time_ms_66: {sleep_time_ms_66} sleep_time_ms_67: {sleep_time_ms_67} sleep_time_ms_68: {sleep_time_ms_68} sleep_time_ms_69: {sleep_time_ms_69} sleep_time_ms_70: {sleep_time_ms_70} sleep_time_ms_71: {sleep_time_ms_71} sleep_time_ms_72: {sleep_time_ms_72} sleep_time_ms_73: {sleep_time_ms_73} sleep_time_ms_74: {sleep_time_ms_74} sleep_time_ms_75: {sleep_time_ms_75} sleep_time_ms_76: {sleep_time_ms_76} sleep_time_ms_77: {sleep_time_ms_77} sleep_time_ms_78: {sleep_time_ms_78} sleep_time_ms_79: {sleep_time_ms_79} sleep_time_ms_80: {sleep_time_ms_80} sleep_time_ms_81: {sleep_time_ms_81} sleep_time_ms_82: {sleep_time_ms_82} sleep_time_ms_83: {sleep_time_ms_83} sleep_time_ms_84: {sleep_time_ms_84} sleep_time_ms_85: {sleep_time_ms_85} sleep_time_ms_86: {sleep_time_ms_86} sleep_time_ms_87: {sleep_time_ms_87} sleep_time_ms_88: {sleep_time_ms_88} sleep_time_ms_89: {sleep_time_ms_89} sleep_time_ms_90: {sleep_time_ms_90} sleep_time_ms_91: {sleep_time_ms_91} sleep_time_ms_92: {sleep_time_ms_92} sleep_time_ms_93: {sleep_time_ms_93} sleep_time_ms_94: {sleep_time_ms_94} sleep_time_ms_95: {sleep_time_ms_95} sleep_time_ms_96: {sleep_time_ms_96} sleep_time_ms_97: {sleep_time_ms_97} sleep_time_ms_98: {sleep_time_ms_98} sleep_time_ms_99: {sleep_time_ms_99} sleep_time_ms_100: {sleep_time_ms_100} sleep_time_ms_101: {sleep_time_ms_101} sleep_time_ms_102: {sleep_time_ms_102} sleep_time_ms_103: {sleep_time_ms_103} sleep_time_ms_104: {sleep_time_ms_104} sleep_time_ms_105: {sleep_time_ms_105} sleep_time_ms_106: {sleep_time_ms_106} sleep_time_ms_107: {sleep_time_ms_107} sleep_time_ms_108: {sleep_time_ms_108} sleep_time_ms_109: {sleep_time_ms_109} sleep_time_ms_110: {sleep_time_ms_110} sleep_time_ms_111: {sleep_time_ms_111} sleep_time_ms_112: {sleep_time_ms_112} sleep_time_ms_113: {sleep_time_ms_113} sleep_time_ms_114: {sleep_time_ms_114} sleep_time_ms_115: {sleep_time_ms_115} sleep_time_ms_116: {sleep_time_ms_116} sleep_time_ms_117: {sleep_time_ms_117} sleep_time_ms_118: {sleep_time_ms_118} sleep_time_ms_119: {sleep_time_ms_119} sleep_time_ms_120: {sleep_time_ms_120} sleep_time_ms_121: {sleep_time_ms_121} sleep_time_ms_122: {sleep_time_ms_122} sleep_time_ms_123: {sleep_time_ms_123} sleep_time_ms_124: {sleep_time_ms_124} sleep_time_ms_125: {sleep_time_ms_125} sleep_time_ms_126: {sleep_time_ms_126} sleep_time_ms_127: {sleep_time_ms_127} sleep_time_ms_128: {sleep_time_ms_128} sleep_time_ms_129: {sleep_time_ms_129} sleep_time_ms_130: {sleep_time_ms_130} sleep_time_ms_131: {sleep_time_ms_131} sleep_time_ms_132: {sleep_time_ms_132} sleep_time_ms_133: {sleep_time_ms_133} sleep_time_ms_134: {sleep_time_ms_134} sleep_time_ms_135: {sleep_time_ms_135} sleep_time_ms_136: {sleep_time_ms_136} sleep_time_ms_137: {sleep_time_ms_137} sleep_time_ms_138: {sleep_time_ms_138} sleep_time_ms_139: {sleep_time_ms_139} sleep_time_ms_140: {sleep_time_ms_140} sleep_time_ms_141: {sleep_time_ms_141} sleep_time_ms_142: {sleep_time_ms_142} sleep_time_ms_143: {sleep_time_ms_143} sleep_time_ms_144: {sleep_time_ms_144} sleep_time_ms_145: {sleep_time_ms_145} sleep_time_ms_146: {sleep_time_ms_146} sleep_time_ms_147: {sleep_time_ms_147} sleep_time_ms_148: {sleep_time_ms_148} sleep_time_ms_149: {sleep_time_ms_149} sleep_time_ms_150: {sleep_time_ms_150} sleep_time_ms_151: {sleep_time_ms_151} sleep_time_ms_152: {sleep_time_ms_152} sleep_time_ms_153: {sleep_time_ms_153} sleep_time_ms_154: {sleep_time_ms_154} sleep_time_ms_155: {sleep_time_ms_155} sleep_time_ms_156: {sleep_time_ms_156} sleep_time_ms_157: {sleep_time_ms_157} sleep_time_ms_158: {sleep_time_ms_158} sleep_time_ms_159: {sleep_time_ms_159} sleep_time_ms_160: {sleep_time_ms_160} sleep_time_ms_161: {sleep_time_ms_161} sleep_time_ms_162: {sleep_time_ms_162} sleep_time_ms_163: {sleep_time_ms_163} sleep_time_ms_164: {sleep_time_ms_164} sleep_time_ms_165: {sleep_time_ms_165} sleep_time_ms_166: {sleep_time_ms_166} sleep_time_ms_167: {sleep_time_ms_167} sleep_time_ms_168: {sleep_time_ms_168} sleep_time_ms_169: {sleep_time_ms_169} sleep_time_ms_170: {sleep_time_ms_170} sleep_time_ms_171: {sleep_time_ms_171} sleep_time_ms_172: {sleep_time_ms_172} sleep_time_ms_173: {sleep_time_ms_173} sleep_time_ms_174: {sleep_time_ms_174} sleep_time_ms_175: {sleep_time_ms_175} sleep_time_ms_176: {sleep_time_ms_176} sleep_time_ms_177: {sleep_time_ms_177} sleep_time_ms_178: {sleep_time_ms_178} sleep_time_ms_179: {sleep_time_ms_179} sleep_time_ms_180: {sleep_time_ms_180} sleep_time_ms_181: {sleep_time_ms_181} sleep_time_ms_182: {sleep_time_ms_182} sleep_time_ms_183: {sleep_time_ms_183} sleep_time_ms_184: {sleep_time_ms_184} sleep_time_ms_185: {sleep_time_ms_185} sleep_time_ms_186: {sleep_time_ms_186} sleep_time_ms_187: {sleep_time_ms_187} sleep_time_ms_188: {sleep_time_ms_188} sleep_time_ms_189: {sleep_time_ms_189} sleep_time_ms_190: {sleep_time_ms_190} sleep_time_ms_191: {sleep_time_ms_191} sleep_time_ms_192: {sleep_time_ms_192} sleep_time_ms_193: {sleep_time_ms_193} sleep_time_ms_194: {sleep_time_ms_194} sleep_time_ms_195: {sleep_time_ms_195} sleep_time_ms_196: {sleep_time_ms_196} sleep_time_ms_197: {sleep_time_ms_197} sleep_time_ms_198: {sleep_time_ms_198} sleep_time_ms_199: {sleep_time_ms_199} sleep_time_ms_200: {sleep_time_ms_200} sleep_time_ms_201: {sleep_time_ms_201} sleep_time_ms_202: {sleep_time_ms_202} sleep_time_ms_203: {sleep_time_ms_203} sleep_time_ms_204: {sleep_time_ms_204} sleep_time_ms_205: {sleep_time_ms_205} sleep_time_ms_206: {sleep_time_ms_206} sleep_time_ms_207: {sleep_time_ms_207} sleep_time_ms_208: {sleep_time_ms_208} sleep_time_ms_209: {sleep_time_ms_209} sleep_time_ms_210: {sleep_time_ms_210} sleep_time_ms_211: {sleep_time_ms_211} sleep_time_ms_212: {sleep_time_ms_212} sleep_time_ms_213: {sleep_time_ms_213} sleep_time_ms_214: {sleep_time_ms_214} sleep_time_ms_215: {sleep_time_ms_215} sleep_time_ms_216: {sleep_time_ms_216} sleep_time_ms_217: {sleep_time_ms_217} sleep_time_ms_218: {sleep_time_ms_218} sleep_time_ms_219: {sleep_time_ms_219} sleep_time_ms_220: {sleep_time_ms_220} sleep_time_ms_221: {sleep_time_ms_221} sleep_time_ms_222: {sleep_time_ms_222} sleep_time_ms_223: {sleep_time_ms_223} sleep_time_ms_224: {sleep_time_ms_224} sleep_time_ms_225: {sleep_time_ms_225} sleep_time_ms_226: {sleep_time_ms_226} sleep_time_ms_227: {sleep_time_ms_227} sleep_time_ms_228: {sleep_time_ms_228} sleep_time_ms_229: {sleep_time_ms_229} sleep_time_ms_230: {sleep_time_ms_230} sleep_time_ms_231: {sleep_time_ms_231} sleep_time_ms_232: {sleep_time_ms_232} sleep_time_ms_233: {sleep_time_ms_233} sleep_time_ms_234: {sleep_time_ms_234} sleep_time_ms_235: {sleep_time_ms_235} sleep_time_ms_236: {sleep_time_ms_236} sleep_time_ms_237: {sleep_time_ms_237} sleep_time_ms_238: {sleep_time_ms_238} sleep_time_ms_239: {sleep_time_ms_239} sleep_time_ms_240: {sleep_time_ms_240} sleep_time_ms_241: {sleep_time_ms_241} sleep_time_ms_242: {sleep_time_ms_242} sleep_time_ms_243: {sleep_time_ms_243} sleep_time_ms_244: {sleep_time_ms_244} sleep_time_ms_245: {sleep_time_ms_245} sleep_time_ms_246: {sleep_time_ms_246} sleep_time_ms_247: {sleep_time_ms_247} sleep_time_ms_248: {sleep_time_ms_248} sleep_time_ms_249: {sleep_time_ms_249} sleep_time_ms_250: {sleep_time_ms_250} sleep_time_ms_251: {sleep_time_ms_251} sleep_time_ms_252: {sleep_time_ms_252} sleep_time_ms_253: {sleep_time_ms_253} sleep_time_ms_254: {sleep_time_ms_254} sleep_time_ms_255: {sleep_time_ms_255} sleep_time_ms_256: {sleep_time_ms_256}")

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

    func_1_2_output = func_1_2(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_2', enable_optimization=_enable_optimization)

    func_1_3_output = func_1_3(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_3', enable_optimization=_enable_optimization)

    func_1_4_output = func_1_4(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_4', enable_optimization=_enable_optimization)

    func_1_5_output = func_1_5(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_5', enable_optimization=_enable_optimization)

    func_1_6_output = func_1_6(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_6', enable_optimization=_enable_optimization)

    func_1_7_output = func_1_7(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_7', enable_optimization=_enable_optimization)

    func_1_8_output = func_1_8(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_8', enable_optimization=_enable_optimization)

    func_1_9_output = func_1_9(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_9', enable_optimization=_enable_optimization)

    func_1_10_output = func_1_10(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_10', enable_optimization=_enable_optimization)

    func_1_11_output = func_1_11(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_11', enable_optimization=_enable_optimization)

    func_1_12_output = func_1_12(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_12', enable_optimization=_enable_optimization)

    func_1_13_output = func_1_13(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_13', enable_optimization=_enable_optimization)

    func_1_14_output = func_1_14(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_14', enable_optimization=_enable_optimization)

    func_1_15_output = func_1_15(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_15', enable_optimization=_enable_optimization)

    func_1_16_output = func_1_16(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_16', enable_optimization=_enable_optimization)

    func_1_17_output = func_1_17(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_17', enable_optimization=_enable_optimization)

    func_1_18_output = func_1_18(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_18', enable_optimization=_enable_optimization)

    func_1_19_output = func_1_19(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_19', enable_optimization=_enable_optimization)

    func_1_20_output = func_1_20(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_20', enable_optimization=_enable_optimization)

    func_1_21_output = func_1_21(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_21', enable_optimization=_enable_optimization)

    func_1_22_output = func_1_22(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_22', enable_optimization=_enable_optimization)

    func_1_23_output = func_1_23(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_23', enable_optimization=_enable_optimization)

    func_1_24_output = func_1_24(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_24', enable_optimization=_enable_optimization)

    func_1_25_output = func_1_25(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_25', enable_optimization=_enable_optimization)

    func_1_26_output = func_1_26(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_26', enable_optimization=_enable_optimization)

    func_1_27_output = func_1_27(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_27', enable_optimization=_enable_optimization)

    func_1_28_output = func_1_28(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_28', enable_optimization=_enable_optimization)

    func_1_29_output = func_1_29(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_29', enable_optimization=_enable_optimization)

    func_1_30_output = func_1_30(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_30', enable_optimization=_enable_optimization)

    func_1_31_output = func_1_31(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_31', enable_optimization=_enable_optimization)

    func_1_32_output = func_1_32(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_32', enable_optimization=_enable_optimization)

    func_1_33_output = func_1_33(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_33', enable_optimization=_enable_optimization)

    func_1_34_output = func_1_34(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_34', enable_optimization=_enable_optimization)

    func_1_35_output = func_1_35(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_35', enable_optimization=_enable_optimization)

    func_1_36_output = func_1_36(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_36', enable_optimization=_enable_optimization)

    func_1_37_output = func_1_37(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_37', enable_optimization=_enable_optimization)

    func_1_38_output = func_1_38(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_38', enable_optimization=_enable_optimization)

    func_1_39_output = func_1_39(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_39', enable_optimization=_enable_optimization)

    func_1_40_output = func_1_40(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_40', enable_optimization=_enable_optimization)

    func_1_41_output = func_1_41(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_41', enable_optimization=_enable_optimization)

    func_1_42_output = func_1_42(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_42', enable_optimization=_enable_optimization)

    func_1_43_output = func_1_43(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_43', enable_optimization=_enable_optimization)

    func_1_44_output = func_1_44(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_44', enable_optimization=_enable_optimization)

    func_1_45_output = func_1_45(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_45', enable_optimization=_enable_optimization)

    func_1_46_output = func_1_46(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_46', enable_optimization=_enable_optimization)

    func_1_47_output = func_1_47(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_47', enable_optimization=_enable_optimization)

    func_1_48_output = func_1_48(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_48', enable_optimization=_enable_optimization)

    func_1_49_output = func_1_49(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_49', enable_optimization=_enable_optimization)

    func_1_50_output = func_1_50(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_50', enable_optimization=_enable_optimization)

    func_1_51_output = func_1_51(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_51', enable_optimization=_enable_optimization)

    func_1_52_output = func_1_52(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_52', enable_optimization=_enable_optimization)

    func_1_53_output = func_1_53(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_53', enable_optimization=_enable_optimization)

    func_1_54_output = func_1_54(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_54', enable_optimization=_enable_optimization)

    func_1_55_output = func_1_55(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_55', enable_optimization=_enable_optimization)

    func_1_56_output = func_1_56(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_56', enable_optimization=_enable_optimization)

    func_1_57_output = func_1_57(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_57', enable_optimization=_enable_optimization)

    func_1_58_output = func_1_58(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_58', enable_optimization=_enable_optimization)

    func_1_59_output = func_1_59(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_59', enable_optimization=_enable_optimization)

    func_1_60_output = func_1_60(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_60', enable_optimization=_enable_optimization)

    func_1_61_output = func_1_61(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_61', enable_optimization=_enable_optimization)

    func_1_62_output = func_1_62(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_62', enable_optimization=_enable_optimization)

    func_1_63_output = func_1_63(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_63', enable_optimization=_enable_optimization)

    func_1_64_output = func_1_64(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_64', enable_optimization=_enable_optimization)

    func_1_65_output = func_1_65(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_65', enable_optimization=_enable_optimization)

    func_1_66_output = func_1_66(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_66', enable_optimization=_enable_optimization)

    func_1_67_output = func_1_67(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_67', enable_optimization=_enable_optimization)

    func_1_68_output = func_1_68(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_68', enable_optimization=_enable_optimization)

    func_1_69_output = func_1_69(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_69', enable_optimization=_enable_optimization)

    func_1_70_output = func_1_70(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_70', enable_optimization=_enable_optimization)

    func_1_71_output = func_1_71(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_71', enable_optimization=_enable_optimization)

    func_1_72_output = func_1_72(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_72', enable_optimization=_enable_optimization)

    func_1_73_output = func_1_73(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_73', enable_optimization=_enable_optimization)

    func_1_74_output = func_1_74(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_74', enable_optimization=_enable_optimization)

    func_1_75_output = func_1_75(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_75', enable_optimization=_enable_optimization)

    func_1_76_output = func_1_76(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_76', enable_optimization=_enable_optimization)

    func_1_77_output = func_1_77(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_77', enable_optimization=_enable_optimization)

    func_1_78_output = func_1_78(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_78', enable_optimization=_enable_optimization)

    func_1_79_output = func_1_79(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_79', enable_optimization=_enable_optimization)

    func_1_80_output = func_1_80(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_80', enable_optimization=_enable_optimization)

    func_1_81_output = func_1_81(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_81', enable_optimization=_enable_optimization)

    func_1_82_output = func_1_82(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_82', enable_optimization=_enable_optimization)

    func_1_83_output = func_1_83(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_83', enable_optimization=_enable_optimization)

    func_1_84_output = func_1_84(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_84', enable_optimization=_enable_optimization)

    func_1_85_output = func_1_85(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_85', enable_optimization=_enable_optimization)

    func_1_86_output = func_1_86(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_86', enable_optimization=_enable_optimization)

    func_1_87_output = func_1_87(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_87', enable_optimization=_enable_optimization)

    func_1_88_output = func_1_88(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_88', enable_optimization=_enable_optimization)

    func_1_89_output = func_1_89(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_89', enable_optimization=_enable_optimization)

    func_1_90_output = func_1_90(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_90', enable_optimization=_enable_optimization)

    func_1_91_output = func_1_91(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_91', enable_optimization=_enable_optimization)

    func_1_92_output = func_1_92(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_92', enable_optimization=_enable_optimization)

    func_1_93_output = func_1_93(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_93', enable_optimization=_enable_optimization)

    func_1_94_output = func_1_94(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_94', enable_optimization=_enable_optimization)

    func_1_95_output = func_1_95(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_95', enable_optimization=_enable_optimization)

    func_1_96_output = func_1_96(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_96', enable_optimization=_enable_optimization)

    func_1_97_output = func_1_97(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_97', enable_optimization=_enable_optimization)

    func_1_98_output = func_1_98(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_98', enable_optimization=_enable_optimization)

    func_1_99_output = func_1_99(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_99', enable_optimization=_enable_optimization)

    func_1_100_output = func_1_100(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_100', enable_optimization=_enable_optimization)

    func_1_101_output = func_1_101(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_101', enable_optimization=_enable_optimization)

    func_1_102_output = func_1_102(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_102', enable_optimization=_enable_optimization)

    func_1_103_output = func_1_103(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_103', enable_optimization=_enable_optimization)

    func_1_104_output = func_1_104(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_104', enable_optimization=_enable_optimization)

    func_1_105_output = func_1_105(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_105', enable_optimization=_enable_optimization)

    func_1_106_output = func_1_106(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_106', enable_optimization=_enable_optimization)

    func_1_107_output = func_1_107(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_107', enable_optimization=_enable_optimization)

    func_1_108_output = func_1_108(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_108', enable_optimization=_enable_optimization)

    func_1_109_output = func_1_109(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_109', enable_optimization=_enable_optimization)

    func_1_110_output = func_1_110(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_110', enable_optimization=_enable_optimization)

    func_1_111_output = func_1_111(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_111', enable_optimization=_enable_optimization)

    func_1_112_output = func_1_112(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_112', enable_optimization=_enable_optimization)

    func_1_113_output = func_1_113(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_113', enable_optimization=_enable_optimization)

    func_1_114_output = func_1_114(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_114', enable_optimization=_enable_optimization)

    func_1_115_output = func_1_115(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_115', enable_optimization=_enable_optimization)

    func_1_116_output = func_1_116(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_116', enable_optimization=_enable_optimization)

    func_1_117_output = func_1_117(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_117', enable_optimization=_enable_optimization)

    func_1_118_output = func_1_118(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_118', enable_optimization=_enable_optimization)

    func_1_119_output = func_1_119(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_119', enable_optimization=_enable_optimization)

    func_1_120_output = func_1_120(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_120', enable_optimization=_enable_optimization)

    func_1_121_output = func_1_121(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_121', enable_optimization=_enable_optimization)

    func_1_122_output = func_1_122(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_122', enable_optimization=_enable_optimization)

    func_1_123_output = func_1_123(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_123', enable_optimization=_enable_optimization)

    func_1_124_output = func_1_124(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_124', enable_optimization=_enable_optimization)

    func_1_125_output = func_1_125(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_125', enable_optimization=_enable_optimization)

    func_1_126_output = func_1_126(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_126', enable_optimization=_enable_optimization)

    func_1_127_output = func_1_127(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_127', enable_optimization=_enable_optimization)

    func_1_128_output = func_1_128(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_128', enable_optimization=_enable_optimization)

    func_1_129_output = func_1_129(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_129', enable_optimization=_enable_optimization)

    func_1_130_output = func_1_130(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_130', enable_optimization=_enable_optimization)

    func_1_131_output = func_1_131(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_131', enable_optimization=_enable_optimization)

    func_1_132_output = func_1_132(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_132', enable_optimization=_enable_optimization)

    func_1_133_output = func_1_133(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_133', enable_optimization=_enable_optimization)

    func_1_134_output = func_1_134(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_134', enable_optimization=_enable_optimization)

    func_1_135_output = func_1_135(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_135', enable_optimization=_enable_optimization)

    func_1_136_output = func_1_136(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_136', enable_optimization=_enable_optimization)

    func_1_137_output = func_1_137(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_137', enable_optimization=_enable_optimization)

    func_1_138_output = func_1_138(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_138', enable_optimization=_enable_optimization)

    func_1_139_output = func_1_139(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_139', enable_optimization=_enable_optimization)

    func_1_140_output = func_1_140(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_140', enable_optimization=_enable_optimization)

    func_1_141_output = func_1_141(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_141', enable_optimization=_enable_optimization)

    func_1_142_output = func_1_142(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_142', enable_optimization=_enable_optimization)

    func_1_143_output = func_1_143(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_143', enable_optimization=_enable_optimization)

    func_1_144_output = func_1_144(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_144', enable_optimization=_enable_optimization)

    func_1_145_output = func_1_145(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_145', enable_optimization=_enable_optimization)

    func_1_146_output = func_1_146(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_146', enable_optimization=_enable_optimization)

    func_1_147_output = func_1_147(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_147', enable_optimization=_enable_optimization)

    func_1_148_output = func_1_148(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_148', enable_optimization=_enable_optimization)

    func_1_149_output = func_1_149(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_149', enable_optimization=_enable_optimization)

    func_1_150_output = func_1_150(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_150', enable_optimization=_enable_optimization)

    func_1_151_output = func_1_151(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_151', enable_optimization=_enable_optimization)

    func_1_152_output = func_1_152(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_152', enable_optimization=_enable_optimization)

    func_1_153_output = func_1_153(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_153', enable_optimization=_enable_optimization)

    func_1_154_output = func_1_154(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_154', enable_optimization=_enable_optimization)

    func_1_155_output = func_1_155(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_155', enable_optimization=_enable_optimization)

    func_1_156_output = func_1_156(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_156', enable_optimization=_enable_optimization)

    func_1_157_output = func_1_157(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_157', enable_optimization=_enable_optimization)

    func_1_158_output = func_1_158(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_158', enable_optimization=_enable_optimization)

    func_1_159_output = func_1_159(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_159', enable_optimization=_enable_optimization)

    func_1_160_output = func_1_160(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_160', enable_optimization=_enable_optimization)

    func_1_161_output = func_1_161(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_161', enable_optimization=_enable_optimization)

    func_1_162_output = func_1_162(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_162', enable_optimization=_enable_optimization)

    func_1_163_output = func_1_163(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_163', enable_optimization=_enable_optimization)

    func_1_164_output = func_1_164(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_164', enable_optimization=_enable_optimization)

    func_1_165_output = func_1_165(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_165', enable_optimization=_enable_optimization)

    func_1_166_output = func_1_166(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_166', enable_optimization=_enable_optimization)

    func_1_167_output = func_1_167(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_167', enable_optimization=_enable_optimization)

    func_1_168_output = func_1_168(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_168', enable_optimization=_enable_optimization)

    func_1_169_output = func_1_169(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_169', enable_optimization=_enable_optimization)

    func_1_170_output = func_1_170(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_170', enable_optimization=_enable_optimization)

    func_1_171_output = func_1_171(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_171', enable_optimization=_enable_optimization)

    func_1_172_output = func_1_172(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_172', enable_optimization=_enable_optimization)

    func_1_173_output = func_1_173(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_173', enable_optimization=_enable_optimization)

    func_1_174_output = func_1_174(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_174', enable_optimization=_enable_optimization)

    func_1_175_output = func_1_175(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_175', enable_optimization=_enable_optimization)

    func_1_176_output = func_1_176(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_176', enable_optimization=_enable_optimization)

    func_1_177_output = func_1_177(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_177', enable_optimization=_enable_optimization)

    func_1_178_output = func_1_178(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_178', enable_optimization=_enable_optimization)

    func_1_179_output = func_1_179(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_179', enable_optimization=_enable_optimization)

    func_1_180_output = func_1_180(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_180', enable_optimization=_enable_optimization)

    func_1_181_output = func_1_181(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_181', enable_optimization=_enable_optimization)

    func_1_182_output = func_1_182(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_182', enable_optimization=_enable_optimization)

    func_1_183_output = func_1_183(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_183', enable_optimization=_enable_optimization)

    func_1_184_output = func_1_184(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_184', enable_optimization=_enable_optimization)

    func_1_185_output = func_1_185(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_185', enable_optimization=_enable_optimization)

    func_1_186_output = func_1_186(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_186', enable_optimization=_enable_optimization)

    func_1_187_output = func_1_187(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_187', enable_optimization=_enable_optimization)

    func_1_188_output = func_1_188(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_188', enable_optimization=_enable_optimization)

    func_1_189_output = func_1_189(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_189', enable_optimization=_enable_optimization)

    func_1_190_output = func_1_190(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_190', enable_optimization=_enable_optimization)

    func_1_191_output = func_1_191(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_191', enable_optimization=_enable_optimization)

    func_1_192_output = func_1_192(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_192', enable_optimization=_enable_optimization)

    func_1_193_output = func_1_193(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_193', enable_optimization=_enable_optimization)

    func_1_194_output = func_1_194(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_194', enable_optimization=_enable_optimization)

    func_1_195_output = func_1_195(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_195', enable_optimization=_enable_optimization)

    func_1_196_output = func_1_196(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_196', enable_optimization=_enable_optimization)

    func_1_197_output = func_1_197(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_197', enable_optimization=_enable_optimization)

    func_1_198_output = func_1_198(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_198', enable_optimization=_enable_optimization)

    func_1_199_output = func_1_199(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_199', enable_optimization=_enable_optimization)

    func_1_200_output = func_1_200(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_200', enable_optimization=_enable_optimization)

    func_1_201_output = func_1_201(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_201', enable_optimization=_enable_optimization)

    func_1_202_output = func_1_202(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_202', enable_optimization=_enable_optimization)

    func_1_203_output = func_1_203(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_203', enable_optimization=_enable_optimization)

    func_1_204_output = func_1_204(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_204', enable_optimization=_enable_optimization)

    func_1_205_output = func_1_205(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_205', enable_optimization=_enable_optimization)

    func_1_206_output = func_1_206(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_206', enable_optimization=_enable_optimization)

    func_1_207_output = func_1_207(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_207', enable_optimization=_enable_optimization)

    func_1_208_output = func_1_208(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_208', enable_optimization=_enable_optimization)

    func_1_209_output = func_1_209(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_209', enable_optimization=_enable_optimization)

    func_1_210_output = func_1_210(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_210', enable_optimization=_enable_optimization)

    func_1_211_output = func_1_211(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_211', enable_optimization=_enable_optimization)

    func_1_212_output = func_1_212(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_212', enable_optimization=_enable_optimization)

    func_1_213_output = func_1_213(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_213', enable_optimization=_enable_optimization)

    func_1_214_output = func_1_214(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_214', enable_optimization=_enable_optimization)

    func_1_215_output = func_1_215(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_215', enable_optimization=_enable_optimization)

    func_1_216_output = func_1_216(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_216', enable_optimization=_enable_optimization)

    func_1_217_output = func_1_217(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_217', enable_optimization=_enable_optimization)

    func_1_218_output = func_1_218(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_218', enable_optimization=_enable_optimization)

    func_1_219_output = func_1_219(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_219', enable_optimization=_enable_optimization)

    func_1_220_output = func_1_220(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_220', enable_optimization=_enable_optimization)

    func_1_221_output = func_1_221(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_221', enable_optimization=_enable_optimization)

    func_1_222_output = func_1_222(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_222', enable_optimization=_enable_optimization)

    func_1_223_output = func_1_223(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_223', enable_optimization=_enable_optimization)

    func_1_224_output = func_1_224(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_224', enable_optimization=_enable_optimization)

    func_1_225_output = func_1_225(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_225', enable_optimization=_enable_optimization)

    func_1_226_output = func_1_226(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_226', enable_optimization=_enable_optimization)

    func_1_227_output = func_1_227(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_227', enable_optimization=_enable_optimization)

    func_1_228_output = func_1_228(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_228', enable_optimization=_enable_optimization)

    func_1_229_output = func_1_229(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_229', enable_optimization=_enable_optimization)

    func_1_230_output = func_1_230(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_230', enable_optimization=_enable_optimization)

    func_1_231_output = func_1_231(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_231', enable_optimization=_enable_optimization)

    func_1_232_output = func_1_232(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_232', enable_optimization=_enable_optimization)

    func_1_233_output = func_1_233(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_233', enable_optimization=_enable_optimization)

    func_1_234_output = func_1_234(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_234', enable_optimization=_enable_optimization)

    func_1_235_output = func_1_235(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_235', enable_optimization=_enable_optimization)

    func_1_236_output = func_1_236(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_236', enable_optimization=_enable_optimization)

    func_1_237_output = func_1_237(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_237', enable_optimization=_enable_optimization)

    func_1_238_output = func_1_238(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_238', enable_optimization=_enable_optimization)

    func_1_239_output = func_1_239(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_239', enable_optimization=_enable_optimization)

    func_1_240_output = func_1_240(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_240', enable_optimization=_enable_optimization)

    func_1_241_output = func_1_241(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_241', enable_optimization=_enable_optimization)

    func_1_242_output = func_1_242(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_242', enable_optimization=_enable_optimization)

    func_1_243_output = func_1_243(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_243', enable_optimization=_enable_optimization)

    func_1_244_output = func_1_244(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_244', enable_optimization=_enable_optimization)

    func_1_245_output = func_1_245(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_245', enable_optimization=_enable_optimization)

    func_1_246_output = func_1_246(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_246', enable_optimization=_enable_optimization)

    func_1_247_output = func_1_247(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_247', enable_optimization=_enable_optimization)

    func_1_248_output = func_1_248(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_248', enable_optimization=_enable_optimization)

    func_1_249_output = func_1_249(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_249', enable_optimization=_enable_optimization)

    func_1_250_output = func_1_250(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_250', enable_optimization=_enable_optimization)

    func_1_251_output = func_1_251(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_251', enable_optimization=_enable_optimization)

    func_1_252_output = func_1_252(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_252', enable_optimization=_enable_optimization)

    func_1_253_output = func_1_253(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_253', enable_optimization=_enable_optimization)

    func_1_254_output = func_1_254(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_254', enable_optimization=_enable_optimization)

    func_1_255_output = func_1_255(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_255', enable_optimization=_enable_optimization)

    func_1_256_output = func_1_256(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_256', enable_optimization=_enable_optimization)

    func_1_257_output = func_1_257(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_1', task_name='func_1_257', enable_optimization=_enable_optimization)

    func_1_258_output = func_1_258(sleep_time_ms_1 = func_1_2_output, sleep_time_ms_2 = func_1_3_output, sleep_time_ms_3 = func_1_4_output, sleep_time_ms_4 = func_1_5_output, sleep_time_ms_5 = func_1_6_output, sleep_time_ms_6 = func_1_7_output, sleep_time_ms_7 = func_1_8_output, sleep_time_ms_8 = func_1_9_output, sleep_time_ms_9 = func_1_10_output, sleep_time_ms_10 = func_1_11_output, sleep_time_ms_11 = func_1_12_output, sleep_time_ms_12 = func_1_13_output, sleep_time_ms_13 = func_1_14_output, sleep_time_ms_14 = func_1_15_output, sleep_time_ms_15 = func_1_16_output, sleep_time_ms_16 = func_1_17_output, sleep_time_ms_17 = func_1_18_output, sleep_time_ms_18 = func_1_19_output, sleep_time_ms_19 = func_1_20_output, sleep_time_ms_20 = func_1_21_output, sleep_time_ms_21 = func_1_22_output, sleep_time_ms_22 = func_1_23_output, sleep_time_ms_23 = func_1_24_output, sleep_time_ms_24 = func_1_25_output, sleep_time_ms_25 = func_1_26_output, sleep_time_ms_26 = func_1_27_output, sleep_time_ms_27 = func_1_28_output, sleep_time_ms_28 = func_1_29_output, sleep_time_ms_29 = func_1_30_output, sleep_time_ms_30 = func_1_31_output, sleep_time_ms_31 = func_1_32_output, sleep_time_ms_32 = func_1_33_output, sleep_time_ms_33 = func_1_34_output, sleep_time_ms_34 = func_1_35_output, sleep_time_ms_35 = func_1_36_output, sleep_time_ms_36 = func_1_37_output, sleep_time_ms_37 = func_1_38_output, sleep_time_ms_38 = func_1_39_output, sleep_time_ms_39 = func_1_40_output, sleep_time_ms_40 = func_1_41_output, sleep_time_ms_41 = func_1_42_output, sleep_time_ms_42 = func_1_43_output, sleep_time_ms_43 = func_1_44_output, sleep_time_ms_44 = func_1_45_output, sleep_time_ms_45 = func_1_46_output, sleep_time_ms_46 = func_1_47_output, sleep_time_ms_47 = func_1_48_output, sleep_time_ms_48 = func_1_49_output, sleep_time_ms_49 = func_1_50_output, sleep_time_ms_50 = func_1_51_output, sleep_time_ms_51 = func_1_52_output, sleep_time_ms_52 = func_1_53_output, sleep_time_ms_53 = func_1_54_output, sleep_time_ms_54 = func_1_55_output, sleep_time_ms_55 = func_1_56_output, sleep_time_ms_56 = func_1_57_output, sleep_time_ms_57 = func_1_58_output, sleep_time_ms_58 = func_1_59_output, sleep_time_ms_59 = func_1_60_output, sleep_time_ms_60 = func_1_61_output, sleep_time_ms_61 = func_1_62_output, sleep_time_ms_62 = func_1_63_output, sleep_time_ms_63 = func_1_64_output, sleep_time_ms_64 = func_1_65_output, sleep_time_ms_65 = func_1_66_output, sleep_time_ms_66 = func_1_67_output, sleep_time_ms_67 = func_1_68_output, sleep_time_ms_68 = func_1_69_output, sleep_time_ms_69 = func_1_70_output, sleep_time_ms_70 = func_1_71_output, sleep_time_ms_71 = func_1_72_output, sleep_time_ms_72 = func_1_73_output, sleep_time_ms_73 = func_1_74_output, sleep_time_ms_74 = func_1_75_output, sleep_time_ms_75 = func_1_76_output, sleep_time_ms_76 = func_1_77_output, sleep_time_ms_77 = func_1_78_output, sleep_time_ms_78 = func_1_79_output, sleep_time_ms_79 = func_1_80_output, sleep_time_ms_80 = func_1_81_output, sleep_time_ms_81 = func_1_82_output, sleep_time_ms_82 = func_1_83_output, sleep_time_ms_83 = func_1_84_output, sleep_time_ms_84 = func_1_85_output, sleep_time_ms_85 = func_1_86_output, sleep_time_ms_86 = func_1_87_output, sleep_time_ms_87 = func_1_88_output, sleep_time_ms_88 = func_1_89_output, sleep_time_ms_89 = func_1_90_output, sleep_time_ms_90 = func_1_91_output, sleep_time_ms_91 = func_1_92_output, sleep_time_ms_92 = func_1_93_output, sleep_time_ms_93 = func_1_94_output, sleep_time_ms_94 = func_1_95_output, sleep_time_ms_95 = func_1_96_output, sleep_time_ms_96 = func_1_97_output, sleep_time_ms_97 = func_1_98_output, sleep_time_ms_98 = func_1_99_output, sleep_time_ms_99 = func_1_100_output, sleep_time_ms_100 = func_1_101_output, sleep_time_ms_101 = func_1_102_output, sleep_time_ms_102 = func_1_103_output, sleep_time_ms_103 = func_1_104_output, sleep_time_ms_104 = func_1_105_output, sleep_time_ms_105 = func_1_106_output, sleep_time_ms_106 = func_1_107_output, sleep_time_ms_107 = func_1_108_output, sleep_time_ms_108 = func_1_109_output, sleep_time_ms_109 = func_1_110_output, sleep_time_ms_110 = func_1_111_output, sleep_time_ms_111 = func_1_112_output, sleep_time_ms_112 = func_1_113_output, sleep_time_ms_113 = func_1_114_output, sleep_time_ms_114 = func_1_115_output, sleep_time_ms_115 = func_1_116_output, sleep_time_ms_116 = func_1_117_output, sleep_time_ms_117 = func_1_118_output, sleep_time_ms_118 = func_1_119_output, sleep_time_ms_119 = func_1_120_output, sleep_time_ms_120 = func_1_121_output, sleep_time_ms_121 = func_1_122_output, sleep_time_ms_122 = func_1_123_output, sleep_time_ms_123 = func_1_124_output, sleep_time_ms_124 = func_1_125_output, sleep_time_ms_125 = func_1_126_output, sleep_time_ms_126 = func_1_127_output, sleep_time_ms_127 = func_1_128_output, sleep_time_ms_128 = func_1_129_output, sleep_time_ms_129 = func_1_130_output, sleep_time_ms_130 = func_1_131_output, sleep_time_ms_131 = func_1_132_output, sleep_time_ms_132 = func_1_133_output, sleep_time_ms_133 = func_1_134_output, sleep_time_ms_134 = func_1_135_output, sleep_time_ms_135 = func_1_136_output, sleep_time_ms_136 = func_1_137_output, sleep_time_ms_137 = func_1_138_output, sleep_time_ms_138 = func_1_139_output, sleep_time_ms_139 = func_1_140_output, sleep_time_ms_140 = func_1_141_output, sleep_time_ms_141 = func_1_142_output, sleep_time_ms_142 = func_1_143_output, sleep_time_ms_143 = func_1_144_output, sleep_time_ms_144 = func_1_145_output, sleep_time_ms_145 = func_1_146_output, sleep_time_ms_146 = func_1_147_output, sleep_time_ms_147 = func_1_148_output, sleep_time_ms_148 = func_1_149_output, sleep_time_ms_149 = func_1_150_output, sleep_time_ms_150 = func_1_151_output, sleep_time_ms_151 = func_1_152_output, sleep_time_ms_152 = func_1_153_output, sleep_time_ms_153 = func_1_154_output, sleep_time_ms_154 = func_1_155_output, sleep_time_ms_155 = func_1_156_output, sleep_time_ms_156 = func_1_157_output, sleep_time_ms_157 = func_1_158_output, sleep_time_ms_158 = func_1_159_output, sleep_time_ms_159 = func_1_160_output, sleep_time_ms_160 = func_1_161_output, sleep_time_ms_161 = func_1_162_output, sleep_time_ms_162 = func_1_163_output, sleep_time_ms_163 = func_1_164_output, sleep_time_ms_164 = func_1_165_output, sleep_time_ms_165 = func_1_166_output, sleep_time_ms_166 = func_1_167_output, sleep_time_ms_167 = func_1_168_output, sleep_time_ms_168 = func_1_169_output, sleep_time_ms_169 = func_1_170_output, sleep_time_ms_170 = func_1_171_output, sleep_time_ms_171 = func_1_172_output, sleep_time_ms_172 = func_1_173_output, sleep_time_ms_173 = func_1_174_output, sleep_time_ms_174 = func_1_175_output, sleep_time_ms_175 = func_1_176_output, sleep_time_ms_176 = func_1_177_output, sleep_time_ms_177 = func_1_178_output, sleep_time_ms_178 = func_1_179_output, sleep_time_ms_179 = func_1_180_output, sleep_time_ms_180 = func_1_181_output, sleep_time_ms_181 = func_1_182_output, sleep_time_ms_182 = func_1_183_output, sleep_time_ms_183 = func_1_184_output, sleep_time_ms_184 = func_1_185_output, sleep_time_ms_185 = func_1_186_output, sleep_time_ms_186 = func_1_187_output, sleep_time_ms_187 = func_1_188_output, sleep_time_ms_188 = func_1_189_output, sleep_time_ms_189 = func_1_190_output, sleep_time_ms_190 = func_1_191_output, sleep_time_ms_191 = func_1_192_output, sleep_time_ms_192 = func_1_193_output, sleep_time_ms_193 = func_1_194_output, sleep_time_ms_194 = func_1_195_output, sleep_time_ms_195 = func_1_196_output, sleep_time_ms_196 = func_1_197_output, sleep_time_ms_197 = func_1_198_output, sleep_time_ms_198 = func_1_199_output, sleep_time_ms_199 = func_1_200_output, sleep_time_ms_200 = func_1_201_output, sleep_time_ms_201 = func_1_202_output, sleep_time_ms_202 = func_1_203_output, sleep_time_ms_203 = func_1_204_output, sleep_time_ms_204 = func_1_205_output, sleep_time_ms_205 = func_1_206_output, sleep_time_ms_206 = func_1_207_output, sleep_time_ms_207 = func_1_208_output, sleep_time_ms_208 = func_1_209_output, sleep_time_ms_209 = func_1_210_output, sleep_time_ms_210 = func_1_211_output, sleep_time_ms_211 = func_1_212_output, sleep_time_ms_212 = func_1_213_output, sleep_time_ms_213 = func_1_214_output, sleep_time_ms_214 = func_1_215_output, sleep_time_ms_215 = func_1_216_output, sleep_time_ms_216 = func_1_217_output, sleep_time_ms_217 = func_1_218_output, sleep_time_ms_218 = func_1_219_output, sleep_time_ms_219 = func_1_220_output, sleep_time_ms_220 = func_1_221_output, sleep_time_ms_221 = func_1_222_output, sleep_time_ms_222 = func_1_223_output, sleep_time_ms_223 = func_1_224_output, sleep_time_ms_224 = func_1_225_output, sleep_time_ms_225 = func_1_226_output, sleep_time_ms_226 = func_1_227_output, sleep_time_ms_227 = func_1_228_output, sleep_time_ms_228 = func_1_229_output, sleep_time_ms_229 = func_1_230_output, sleep_time_ms_230 = func_1_231_output, sleep_time_ms_231 = func_1_232_output, sleep_time_ms_232 = func_1_233_output, sleep_time_ms_233 = func_1_234_output, sleep_time_ms_234 = func_1_235_output, sleep_time_ms_235 = func_1_236_output, sleep_time_ms_236 = func_1_237_output, sleep_time_ms_237 = func_1_238_output, sleep_time_ms_238 = func_1_239_output, sleep_time_ms_239 = func_1_240_output, sleep_time_ms_240 = func_1_241_output, sleep_time_ms_241 = func_1_242_output, sleep_time_ms_242 = func_1_243_output, sleep_time_ms_243 = func_1_244_output, sleep_time_ms_244 = func_1_245_output, sleep_time_ms_245 = func_1_246_output, sleep_time_ms_246 = func_1_247_output, sleep_time_ms_247 = func_1_248_output, sleep_time_ms_248 = func_1_249_output, sleep_time_ms_249 = func_1_250_output, sleep_time_ms_250 = func_1_251_output, sleep_time_ms_251 = func_1_252_output, sleep_time_ms_252 = func_1_253_output, sleep_time_ms_253 = func_1_254_output, sleep_time_ms_254 = func_1_255_output, sleep_time_ms_255 = func_1_256_output, sleep_time_ms_256 = func_1_257_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w256_d3', upstream_task_id='func_1_257', task_name='func_1_258', enable_optimization=_enable_optimization)


# execute dag
etl_dag = dag_w256_d3()
