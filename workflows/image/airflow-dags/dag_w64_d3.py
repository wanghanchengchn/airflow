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
def dag_w64_d3():
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
        dag_id: str = 'dag_w64_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_2',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w64_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
        current_run_id = get_current_task_run_id(dag_id, task_name)

        if enable_optimization:
            # 数据平面优化模式
            tasks = [
                (get_upstream_task_value, (dag_id, task_name, current_run_id, upstream_task_id)),
                (fixed_sleep_task, (fixed_sleep_seconds, f"{task_name}_partA"))
            ]
            
            # 并行执行任务
            sleep_time_ms_from_db, _ = execute_parallel_tasks(tasks)
            
            # 执行最后的sleep，使用优化比例
            return dynamic_sleep_task(
                sleep_time_ms=sleep_time_ms_from_db,
                dynamic_ratio=dynamic_ratio,
                task_name=f"{task_name}_partB"
            )
        else:
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
        dag_id: str = 'dag_w64_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_3',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w64_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
        current_run_id = get_current_task_run_id(dag_id, task_name)

        if enable_optimization:
            tasks = [
                (get_upstream_task_value, (dag_id, task_name, current_run_id, upstream_task_id)),
                (fixed_sleep_task, (fixed_sleep_seconds, f"{task_name}_partA"))
            ]
            
            # 并行执行任务
            sleep_time_ms_from_db, _ = execute_parallel_tasks(tasks)

            # 执行最后的sleep，使用优化比例
            return dynamic_sleep_task(
                sleep_time_ms=sleep_time_ms_from_db,
                dynamic_ratio=dynamic_ratio,
                task_name=f"{task_name}_partB"
            )
        else:
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
        dag_id: str = 'dag_w64_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_4',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w64_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
        current_run_id = get_current_task_run_id(dag_id, task_name)

        if enable_optimization:
            tasks = [
                (get_upstream_task_value, (dag_id, task_name, current_run_id, upstream_task_id)),
                (fixed_sleep_task, (fixed_sleep_seconds, f"{task_name}_partA"))
            ]
            
            # 并行执行任务
            sleep_time_ms_from_db, _ = execute_parallel_tasks(tasks)

            # 执行最后的sleep，使用优化比例
            return dynamic_sleep_task(
                sleep_time_ms=sleep_time_ms_from_db,
                dynamic_ratio=dynamic_ratio,
                task_name=f"{task_name}_partB"
            )
        else:
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
        dag_id: str = 'dag_w64_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_5',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w64_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
        current_run_id = get_current_task_run_id(dag_id, task_name)

        if enable_optimization:
            tasks = [
                (get_upstream_task_value, (dag_id, task_name, current_run_id, upstream_task_id)),
                (fixed_sleep_task, (fixed_sleep_seconds, f"{task_name}_partA"))
            ]
            
            # 并行执行任务
            sleep_time_ms_from_db, _ = execute_parallel_tasks(tasks)

            # 执行最后的sleep，使用优化比例
            return dynamic_sleep_task(
                sleep_time_ms=sleep_time_ms_from_db,
                dynamic_ratio=dynamic_ratio,
                task_name=f"{task_name}_partB"
            )
        else:
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
        dag_id: str = 'dag_w64_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_6',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w64_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
        current_run_id = get_current_task_run_id(dag_id, task_name)

        if enable_optimization:
            # 数据平面优化模式
            tasks = [
                (get_upstream_task_value, (dag_id, task_name, current_run_id, upstream_task_id)),
                (fixed_sleep_task, (fixed_sleep_seconds, f"{task_name}_partA"))
            ]
            
            # 并行执行任务
            sleep_time_ms_from_db, _ = execute_parallel_tasks(tasks)
            
            # 执行最后的sleep，使用优化比例
            return dynamic_sleep_task(
                sleep_time_ms=sleep_time_ms_from_db,
                dynamic_ratio=dynamic_ratio,
                task_name=f"{task_name}_partB"
            )
        else:
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
        dag_id: str = 'dag_w64_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_7',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w64_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
        current_run_id = get_current_task_run_id(dag_id, task_name)

        if enable_optimization:
            # 数据平面优化模式
            tasks = [
                (get_upstream_task_value, (dag_id, task_name, current_run_id, upstream_task_id)),
                (fixed_sleep_task, (fixed_sleep_seconds, f"{task_name}_partA"))
            ]
            
            # 并行执行任务
            sleep_time_ms_from_db, _ = execute_parallel_tasks(tasks)
            
            # 执行最后的sleep，使用优化比例
            return dynamic_sleep_task(
                sleep_time_ms=sleep_time_ms_from_db,
                dynamic_ratio=dynamic_ratio,
                task_name=f"{task_name}_partB"
            )
        else:
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
        dag_id: str = 'dag_w64_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_8',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w64_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
        current_run_id = get_current_task_run_id(dag_id, task_name)

        if enable_optimization:
            # 数据平面优化模式
            tasks = [
                (get_upstream_task_value, (dag_id, task_name, current_run_id, upstream_task_id)),
                (fixed_sleep_task, (fixed_sleep_seconds, f"{task_name}_partA"))
            ]
            
            # 并行执行任务
            sleep_time_ms_from_db, _ = execute_parallel_tasks(tasks)
            
            # 执行最后的sleep，使用优化比例
            return dynamic_sleep_task(
                sleep_time_ms=sleep_time_ms_from_db,
                dynamic_ratio=dynamic_ratio,
                task_name=f"{task_name}_partB"
            )
        else:
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
        dag_id: str = 'dag_w64_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_9',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w64_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
        current_run_id = get_current_task_run_id(dag_id, task_name)

        if enable_optimization:
            # 数据平面优化模式
            tasks = [
                (get_upstream_task_value, (dag_id, task_name, current_run_id, upstream_task_id)),
                (fixed_sleep_task, (fixed_sleep_seconds, f"{task_name}_partA"))
            ]
            
            # 并行执行任务
            sleep_time_ms_from_db, _ = execute_parallel_tasks(tasks)
            
            # 执行最后的sleep，使用优化比例
            return dynamic_sleep_task(
                sleep_time_ms=sleep_time_ms_from_db,
                dynamic_ratio=dynamic_ratio,
                task_name=f"{task_name}_partB"
            )
        else:
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
        dag_id: str = 'dag_w64_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_10',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w64_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
        current_run_id = get_current_task_run_id(dag_id, task_name)

        if enable_optimization:
            # 数据平面优化模式
            tasks = [
                (get_upstream_task_value, (dag_id, task_name, current_run_id, upstream_task_id)),
                (fixed_sleep_task, (fixed_sleep_seconds, f"{task_name}_partA"))
            ]
            
            # 并行执行任务
            sleep_time_ms_from_db, _ = execute_parallel_tasks(tasks)
            
            # 执行最后的sleep，使用优化比例
            return dynamic_sleep_task(
                sleep_time_ms=sleep_time_ms_from_db,
                dynamic_ratio=dynamic_ratio,
                task_name=f"{task_name}_partB"
            )
        else:
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
        dag_id: str = 'dag_w64_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_11',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w64_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
        current_run_id = get_current_task_run_id(dag_id, task_name)

        if enable_optimization:
            # 数据平面优化模式
            tasks = [
                (get_upstream_task_value, (dag_id, task_name, current_run_id, upstream_task_id)),
                (fixed_sleep_task, (fixed_sleep_seconds, f"{task_name}_partA"))
            ]
            
            # 并行执行任务
            sleep_time_ms_from_db, _ = execute_parallel_tasks(tasks)
            
            # 执行最后的sleep，使用优化比例
            return dynamic_sleep_task(
                sleep_time_ms=sleep_time_ms_from_db,
                dynamic_ratio=dynamic_ratio,
                task_name=f"{task_name}_partB"
            )
        else:
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
        dag_id: str = 'dag_w64_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_12',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w64_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
        current_run_id = get_current_task_run_id(dag_id, task_name)

        if enable_optimization:
            # 数据平面优化模式
            tasks = [
                (get_upstream_task_value, (dag_id, task_name, current_run_id, upstream_task_id)),
                (fixed_sleep_task, (fixed_sleep_seconds, f"{task_name}_partA"))
            ]
            
            # 并行执行任务
            sleep_time_ms_from_db, _ = execute_parallel_tasks(tasks)
            
            # 执行最后的sleep，使用优化比例
            return dynamic_sleep_task(
                sleep_time_ms=sleep_time_ms_from_db,
                dynamic_ratio=dynamic_ratio,
                task_name=f"{task_name}_partB"
            )
        else:
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
        dag_id: str = 'dag_w64_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_13',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w64_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
        current_run_id = get_current_task_run_id(dag_id, task_name)

        if enable_optimization:
            # 数据平面优化模式
            tasks = [
                (get_upstream_task_value, (dag_id, task_name, current_run_id, upstream_task_id)),
                (fixed_sleep_task, (fixed_sleep_seconds, f"{task_name}_partA"))
            ]
            
            # 并行执行任务
            sleep_time_ms_from_db, _ = execute_parallel_tasks(tasks)
            
            # 执行最后的sleep，使用优化比例
            return dynamic_sleep_task(
                sleep_time_ms=sleep_time_ms_from_db,
                dynamic_ratio=dynamic_ratio,
                task_name=f"{task_name}_partB"
            )
        else:
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
        dag_id: str = 'dag_w64_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_14',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w64_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
        current_run_id = get_current_task_run_id(dag_id, task_name)

        if enable_optimization:
            # 数据平面优化模式
            tasks = [
                (get_upstream_task_value, (dag_id, task_name, current_run_id, upstream_task_id)),
                (fixed_sleep_task, (fixed_sleep_seconds, f"{task_name}_partA"))
            ]
            
            # 并行执行任务
            sleep_time_ms_from_db, _ = execute_parallel_tasks(tasks)
            
            # 执行最后的sleep，使用优化比例
            return dynamic_sleep_task(
                sleep_time_ms=sleep_time_ms_from_db,
                dynamic_ratio=dynamic_ratio,
                task_name=f"{task_name}_partB"
            )
        else:
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
        dag_id: str = 'dag_w64_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_15',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w64_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
        current_run_id = get_current_task_run_id(dag_id, task_name)

        if enable_optimization:
            # 数据平面优化模式
            tasks = [
                (get_upstream_task_value, (dag_id, task_name, current_run_id, upstream_task_id)),
                (fixed_sleep_task, (fixed_sleep_seconds, f"{task_name}_partA"))
            ]
            
            # 并行执行任务
            sleep_time_ms_from_db, _ = execute_parallel_tasks(tasks)
            
            # 执行最后的sleep，使用优化比例
            return dynamic_sleep_task(
                sleep_time_ms=sleep_time_ms_from_db,
                dynamic_ratio=dynamic_ratio,
                task_name=f"{task_name}_partB"
            )
        else:
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
        dag_id: str = 'dag_w64_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_16',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w64_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
        current_run_id = get_current_task_run_id(dag_id, task_name)

        if enable_optimization:
            # 数据平面优化模式
            tasks = [
                (get_upstream_task_value, (dag_id, task_name, current_run_id, upstream_task_id)),
                (fixed_sleep_task, (fixed_sleep_seconds, f"{task_name}_partA"))
            ]
            
            # 并行执行任务
            sleep_time_ms_from_db, _ = execute_parallel_tasks(tasks)
            
            # 执行最后的sleep，使用优化比例
            return dynamic_sleep_task(
                sleep_time_ms=sleep_time_ms_from_db,
                dynamic_ratio=dynamic_ratio,
                task_name=f"{task_name}_partB"
            )
        else:
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
        dag_id: str = 'dag_w64_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_17',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w64_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
        current_run_id = get_current_task_run_id(dag_id, task_name)

        if enable_optimization:
            # 数据平面优化模式
            tasks = [
                (get_upstream_task_value, (dag_id, task_name, current_run_id, upstream_task_id)),
                (fixed_sleep_task, (fixed_sleep_seconds, f"{task_name}_partA"))
            ]
            
            # 并行执行任务
            sleep_time_ms_from_db, _ = execute_parallel_tasks(tasks)
            
            # 执行最后的sleep，使用优化比例
            return dynamic_sleep_task(
                sleep_time_ms=sleep_time_ms_from_db,
                dynamic_ratio=dynamic_ratio,
                task_name=f"{task_name}_partB"
            )
        else:
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
        dag_id: str = 'dag_w64_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_18',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w64_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
        current_run_id = get_current_task_run_id(dag_id, task_name)

        if enable_optimization:
            # 数据平面优化模式
            tasks = [
                (get_upstream_task_value, (dag_id, task_name, current_run_id, upstream_task_id)),
                (fixed_sleep_task, (fixed_sleep_seconds, f"{task_name}_partA"))
            ]
            
            # 并行执行任务
            sleep_time_ms_from_db, _ = execute_parallel_tasks(tasks)
            
            # 执行最后的sleep，使用优化比例
            return dynamic_sleep_task(
                sleep_time_ms=sleep_time_ms_from_db,
                dynamic_ratio=dynamic_ratio,
                task_name=f"{task_name}_partB"
            )
        else:
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
        dag_id: str = 'dag_w64_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_19',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w64_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
        current_run_id = get_current_task_run_id(dag_id, task_name)

        if enable_optimization:
            # 数据平面优化模式
            tasks = [
                (get_upstream_task_value, (dag_id, task_name, current_run_id, upstream_task_id)),
                (fixed_sleep_task, (fixed_sleep_seconds, f"{task_name}_partA"))
            ]
            
            # 并行执行任务
            sleep_time_ms_from_db, _ = execute_parallel_tasks(tasks)
            
            # 执行最后的sleep，使用优化比例
            return dynamic_sleep_task(
                sleep_time_ms=sleep_time_ms_from_db,
                dynamic_ratio=dynamic_ratio,
                task_name=f"{task_name}_partB"
            )
        else:
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
        dag_id: str = 'dag_w64_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_20',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w64_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
        current_run_id = get_current_task_run_id(dag_id, task_name)

        if enable_optimization:
            # 数据平面优化模式
            tasks = [
                (get_upstream_task_value, (dag_id, task_name, current_run_id, upstream_task_id)),
                (fixed_sleep_task, (fixed_sleep_seconds, f"{task_name}_partA"))
            ]
            
            # 并行执行任务
            sleep_time_ms_from_db, _ = execute_parallel_tasks(tasks)
            
            # 执行最后的sleep，使用优化比例
            return dynamic_sleep_task(
                sleep_time_ms=sleep_time_ms_from_db,
                dynamic_ratio=dynamic_ratio,
                task_name=f"{task_name}_partB"
            )
        else:
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
        dag_id: str = 'dag_w64_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_21',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w64_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
        current_run_id = get_current_task_run_id(dag_id, task_name)

        if enable_optimization:
            # 数据平面优化模式
            tasks = [
                (get_upstream_task_value, (dag_id, task_name, current_run_id, upstream_task_id)),
                (fixed_sleep_task, (fixed_sleep_seconds, f"{task_name}_partA"))
            ]
            
            # 并行执行任务
            sleep_time_ms_from_db, _ = execute_parallel_tasks(tasks)
            
            # 执行最后的sleep，使用优化比例
            return dynamic_sleep_task(
                sleep_time_ms=sleep_time_ms_from_db,
                dynamic_ratio=dynamic_ratio,
                task_name=f"{task_name}_partB"
            )
        else:
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
        dag_id: str = 'dag_w64_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_22',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w64_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
        current_run_id = get_current_task_run_id(dag_id, task_name)

        if enable_optimization:
            # 数据平面优化模式
            tasks = [
                (get_upstream_task_value, (dag_id, task_name, current_run_id, upstream_task_id)),
                (fixed_sleep_task, (fixed_sleep_seconds, f"{task_name}_partA"))
            ]
            
            # 并行执行任务
            sleep_time_ms_from_db, _ = execute_parallel_tasks(tasks)
            
            # 执行最后的sleep，使用优化比例
            return dynamic_sleep_task(
                sleep_time_ms=sleep_time_ms_from_db,
                dynamic_ratio=dynamic_ratio,
                task_name=f"{task_name}_partB"
            )
        else:
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
        dag_id: str = 'dag_w64_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_23',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w64_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
        current_run_id = get_current_task_run_id(dag_id, task_name)

        if enable_optimization:
            # 数据平面优化模式
            tasks = [
                (get_upstream_task_value, (dag_id, task_name, current_run_id, upstream_task_id)),
                (fixed_sleep_task, (fixed_sleep_seconds, f"{task_name}_partA"))
            ]
            
            # 并行执行任务
            sleep_time_ms_from_db, _ = execute_parallel_tasks(tasks)
            
            # 执行最后的sleep，使用优化比例
            return dynamic_sleep_task(
                sleep_time_ms=sleep_time_ms_from_db,
                dynamic_ratio=dynamic_ratio,
                task_name=f"{task_name}_partB"
            )
        else:
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
        dag_id: str = 'dag_w64_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_24',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w64_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
        current_run_id = get_current_task_run_id(dag_id, task_name)

        if enable_optimization:
            # 数据平面优化模式
            tasks = [
                (get_upstream_task_value, (dag_id, task_name, current_run_id, upstream_task_id)),
                (fixed_sleep_task, (fixed_sleep_seconds, f"{task_name}_partA"))
            ]
            
            # 并行执行任务
            sleep_time_ms_from_db, _ = execute_parallel_tasks(tasks)
            
            # 执行最后的sleep，使用优化比例
            return dynamic_sleep_task(
                sleep_time_ms=sleep_time_ms_from_db,
                dynamic_ratio=dynamic_ratio,
                task_name=f"{task_name}_partB"
            )
        else:
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
        dag_id: str = 'dag_w64_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_25',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w64_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
        current_run_id = get_current_task_run_id(dag_id, task_name)

        if enable_optimization:
            # 数据平面优化模式
            tasks = [
                (get_upstream_task_value, (dag_id, task_name, current_run_id, upstream_task_id)),
                (fixed_sleep_task, (fixed_sleep_seconds, f"{task_name}_partA"))
            ]
            
            # 并行执行任务
            sleep_time_ms_from_db, _ = execute_parallel_tasks(tasks)
            
            # 执行最后的sleep，使用优化比例
            return dynamic_sleep_task(
                sleep_time_ms=sleep_time_ms_from_db,
                dynamic_ratio=dynamic_ratio,
                task_name=f"{task_name}_partB"
            )
        else:
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
        dag_id: str = 'dag_w64_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_26',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w64_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
        current_run_id = get_current_task_run_id(dag_id, task_name)

        if enable_optimization:
            # 数据平面优化模式
            tasks = [
                (get_upstream_task_value, (dag_id, task_name, current_run_id, upstream_task_id)),
                (fixed_sleep_task, (fixed_sleep_seconds, f"{task_name}_partA"))
            ]
            
            # 并行执行任务
            sleep_time_ms_from_db, _ = execute_parallel_tasks(tasks)
            
            # 执行最后的sleep，使用优化比例
            return dynamic_sleep_task(
                sleep_time_ms=sleep_time_ms_from_db,
                dynamic_ratio=dynamic_ratio,
                task_name=f"{task_name}_partB"
            )
        else:
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
        dag_id: str = 'dag_w64_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_27',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w64_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
        current_run_id = get_current_task_run_id(dag_id, task_name)

        if enable_optimization:
            # 数据平面优化模式
            tasks = [
                (get_upstream_task_value, (dag_id, task_name, current_run_id, upstream_task_id)),
                (fixed_sleep_task, (fixed_sleep_seconds, f"{task_name}_partA"))
            ]
            
            # 并行执行任务
            sleep_time_ms_from_db, _ = execute_parallel_tasks(tasks)
            
            # 执行最后的sleep，使用优化比例
            return dynamic_sleep_task(
                sleep_time_ms=sleep_time_ms_from_db,
                dynamic_ratio=dynamic_ratio,
                task_name=f"{task_name}_partB"
            )
        else:
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
        dag_id: str = 'dag_w64_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_28',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w64_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
        current_run_id = get_current_task_run_id(dag_id, task_name)

        if enable_optimization:
            # 数据平面优化模式
            tasks = [
                (get_upstream_task_value, (dag_id, task_name, current_run_id, upstream_task_id)),
                (fixed_sleep_task, (fixed_sleep_seconds, f"{task_name}_partA"))
            ]
            
            # 并行执行任务
            sleep_time_ms_from_db, _ = execute_parallel_tasks(tasks)
            
            # 执行最后的sleep，使用优化比例
            return dynamic_sleep_task(
                sleep_time_ms=sleep_time_ms_from_db,
                dynamic_ratio=dynamic_ratio,
                task_name=f"{task_name}_partB"
            )
        else:
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
        dag_id: str = 'dag_w64_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_29',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w64_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
        current_run_id = get_current_task_run_id(dag_id, task_name)

        if enable_optimization:
            # 数据平面优化模式
            tasks = [
                (get_upstream_task_value, (dag_id, task_name, current_run_id, upstream_task_id)),
                (fixed_sleep_task, (fixed_sleep_seconds, f"{task_name}_partA"))
            ]
            
            # 并行执行任务
            sleep_time_ms_from_db, _ = execute_parallel_tasks(tasks)
            
            # 执行最后的sleep，使用优化比例
            return dynamic_sleep_task(
                sleep_time_ms=sleep_time_ms_from_db,
                dynamic_ratio=dynamic_ratio,
                task_name=f"{task_name}_partB"
            )
        else:
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
        dag_id: str = 'dag_w64_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_30',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w64_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
        current_run_id = get_current_task_run_id(dag_id, task_name)

        if enable_optimization:
            # 数据平面优化模式
            tasks = [
                (get_upstream_task_value, (dag_id, task_name, current_run_id, upstream_task_id)),
                (fixed_sleep_task, (fixed_sleep_seconds, f"{task_name}_partA"))
            ]
            
            # 并行执行任务
            sleep_time_ms_from_db, _ = execute_parallel_tasks(tasks)
            
            # 执行最后的sleep，使用优化比例
            return dynamic_sleep_task(
                sleep_time_ms=sleep_time_ms_from_db,
                dynamic_ratio=dynamic_ratio,
                task_name=f"{task_name}_partB"
            )
        else:
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
        dag_id: str = 'dag_w64_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_31',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w64_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
        current_run_id = get_current_task_run_id(dag_id, task_name)

        if enable_optimization:
            # 数据平面优化模式
            tasks = [
                (get_upstream_task_value, (dag_id, task_name, current_run_id, upstream_task_id)),
                (fixed_sleep_task, (fixed_sleep_seconds, f"{task_name}_partA"))
            ]
            
            # 并行执行任务
            sleep_time_ms_from_db, _ = execute_parallel_tasks(tasks)
            
            # 执行最后的sleep，使用优化比例
            return dynamic_sleep_task(
                sleep_time_ms=sleep_time_ms_from_db,
                dynamic_ratio=dynamic_ratio,
                task_name=f"{task_name}_partB"
            )
        else:
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
        dag_id: str = 'dag_w64_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_32',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w64_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
        current_run_id = get_current_task_run_id(dag_id, task_name)

        if enable_optimization:
            # 数据平面优化模式
            tasks = [
                (get_upstream_task_value, (dag_id, task_name, current_run_id, upstream_task_id)),
                (fixed_sleep_task, (fixed_sleep_seconds, f"{task_name}_partA"))
            ]
            
            # 并行执行任务
            sleep_time_ms_from_db, _ = execute_parallel_tasks(tasks)
            
            # 执行最后的sleep，使用优化比例
            return dynamic_sleep_task(
                sleep_time_ms=sleep_time_ms_from_db,
                dynamic_ratio=dynamic_ratio,
                task_name=f"{task_name}_partB"
            )
        else:
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
        dag_id: str = 'dag_w64_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_33',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w64_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
        current_run_id = get_current_task_run_id(dag_id, task_name)

        if enable_optimization:
            # 数据平面优化模式
            tasks = [
                (get_upstream_task_value, (dag_id, task_name, current_run_id, upstream_task_id)),
                (fixed_sleep_task, (fixed_sleep_seconds, f"{task_name}_partA"))
            ]
            
            # 并行执行任务
            sleep_time_ms_from_db, _ = execute_parallel_tasks(tasks)
            
            # 执行最后的sleep，使用优化比例
            return dynamic_sleep_task(
                sleep_time_ms=sleep_time_ms_from_db,
                dynamic_ratio=dynamic_ratio,
                task_name=f"{task_name}_partB"
            )
        else:
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
        dag_id: str = 'dag_w64_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_34',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w64_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
        current_run_id = get_current_task_run_id(dag_id, task_name)

        if enable_optimization:
            # 数据平面优化模式
            tasks = [
                (get_upstream_task_value, (dag_id, task_name, current_run_id, upstream_task_id)),
                (fixed_sleep_task, (fixed_sleep_seconds, f"{task_name}_partA"))
            ]
            
            # 并行执行任务
            sleep_time_ms_from_db, _ = execute_parallel_tasks(tasks)
            
            # 执行最后的sleep，使用优化比例
            return dynamic_sleep_task(
                sleep_time_ms=sleep_time_ms_from_db,
                dynamic_ratio=dynamic_ratio,
                task_name=f"{task_name}_partB"
            )
        else:
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
        dag_id: str = 'dag_w64_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_35',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w64_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
        current_run_id = get_current_task_run_id(dag_id, task_name)

        if enable_optimization:
            # 数据平面优化模式
            tasks = [
                (get_upstream_task_value, (dag_id, task_name, current_run_id, upstream_task_id)),
                (fixed_sleep_task, (fixed_sleep_seconds, f"{task_name}_partA"))
            ]
            
            # 并行执行任务
            sleep_time_ms_from_db, _ = execute_parallel_tasks(tasks)
            
            # 执行最后的sleep，使用优化比例
            return dynamic_sleep_task(
                sleep_time_ms=sleep_time_ms_from_db,
                dynamic_ratio=dynamic_ratio,
                task_name=f"{task_name}_partB"
            )
        else:
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
        dag_id: str = 'dag_w64_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_36',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w64_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
        current_run_id = get_current_task_run_id(dag_id, task_name)

        if enable_optimization:
            # 数据平面优化模式
            tasks = [
                (get_upstream_task_value, (dag_id, task_name, current_run_id, upstream_task_id)),
                (fixed_sleep_task, (fixed_sleep_seconds, f"{task_name}_partA"))
            ]
            
            # 并行执行任务
            sleep_time_ms_from_db, _ = execute_parallel_tasks(tasks)
            
            # 执行最后的sleep，使用优化比例
            return dynamic_sleep_task(
                sleep_time_ms=sleep_time_ms_from_db,
                dynamic_ratio=dynamic_ratio,
                task_name=f"{task_name}_partB"
            )
        else:
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
        dag_id: str = 'dag_w64_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_37',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w64_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
        current_run_id = get_current_task_run_id(dag_id, task_name)

        if enable_optimization:
            # 数据平面优化模式
            tasks = [
                (get_upstream_task_value, (dag_id, task_name, current_run_id, upstream_task_id)),
                (fixed_sleep_task, (fixed_sleep_seconds, f"{task_name}_partA"))
            ]
            
            # 并行执行任务
            sleep_time_ms_from_db, _ = execute_parallel_tasks(tasks)
            
            # 执行最后的sleep，使用优化比例
            return dynamic_sleep_task(
                sleep_time_ms=sleep_time_ms_from_db,
                dynamic_ratio=dynamic_ratio,
                task_name=f"{task_name}_partB"
            )
        else:
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
        dag_id: str = 'dag_w64_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_38',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w64_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
        current_run_id = get_current_task_run_id(dag_id, task_name)

        if enable_optimization:
            # 数据平面优化模式
            tasks = [
                (get_upstream_task_value, (dag_id, task_name, current_run_id, upstream_task_id)),
                (fixed_sleep_task, (fixed_sleep_seconds, f"{task_name}_partA"))
            ]
            
            # 并行执行任务
            sleep_time_ms_from_db, _ = execute_parallel_tasks(tasks)
            
            # 执行最后的sleep，使用优化比例
            return dynamic_sleep_task(
                sleep_time_ms=sleep_time_ms_from_db,
                dynamic_ratio=dynamic_ratio,
                task_name=f"{task_name}_partB"
            )
        else:
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
        dag_id: str = 'dag_w64_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_39',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w64_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
        current_run_id = get_current_task_run_id(dag_id, task_name)

        if enable_optimization:
            # 数据平面优化模式
            tasks = [
                (get_upstream_task_value, (dag_id, task_name, current_run_id, upstream_task_id)),
                (fixed_sleep_task, (fixed_sleep_seconds, f"{task_name}_partA"))
            ]
            
            # 并行执行任务
            sleep_time_ms_from_db, _ = execute_parallel_tasks(tasks)
            
            # 执行最后的sleep，使用优化比例
            return dynamic_sleep_task(
                sleep_time_ms=sleep_time_ms_from_db,
                dynamic_ratio=dynamic_ratio,
                task_name=f"{task_name}_partB"
            )
        else:
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
        dag_id: str = 'dag_w64_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_40',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w64_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
        current_run_id = get_current_task_run_id(dag_id, task_name)

        if enable_optimization:
            # 数据平面优化模式
            tasks = [
                (get_upstream_task_value, (dag_id, task_name, current_run_id, upstream_task_id)),
                (fixed_sleep_task, (fixed_sleep_seconds, f"{task_name}_partA"))
            ]
            
            # 并行执行任务
            sleep_time_ms_from_db, _ = execute_parallel_tasks(tasks)
            
            # 执行最后的sleep，使用优化比例
            return dynamic_sleep_task(
                sleep_time_ms=sleep_time_ms_from_db,
                dynamic_ratio=dynamic_ratio,
                task_name=f"{task_name}_partB"
            )
        else:
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
        dag_id: str = 'dag_w64_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_41',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w64_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
        current_run_id = get_current_task_run_id(dag_id, task_name)

        if enable_optimization:
            # 数据平面优化模式
            tasks = [
                (get_upstream_task_value, (dag_id, task_name, current_run_id, upstream_task_id)),
                (fixed_sleep_task, (fixed_sleep_seconds, f"{task_name}_partA"))
            ]
            
            # 并行执行任务
            sleep_time_ms_from_db, _ = execute_parallel_tasks(tasks)
            
            # 执行最后的sleep，使用优化比例
            return dynamic_sleep_task(
                sleep_time_ms=sleep_time_ms_from_db,
                dynamic_ratio=dynamic_ratio,
                task_name=f"{task_name}_partB"
            )
        else:
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
        dag_id: str = 'dag_w64_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_42',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w64_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
        current_run_id = get_current_task_run_id(dag_id, task_name)

        if enable_optimization:
            # 数据平面优化模式
            tasks = [
                (get_upstream_task_value, (dag_id, task_name, current_run_id, upstream_task_id)),
                (fixed_sleep_task, (fixed_sleep_seconds, f"{task_name}_partA"))
            ]
            
            # 并行执行任务
            sleep_time_ms_from_db, _ = execute_parallel_tasks(tasks)
            
            # 执行最后的sleep，使用优化比例
            return dynamic_sleep_task(
                sleep_time_ms=sleep_time_ms_from_db,
                dynamic_ratio=dynamic_ratio,
                task_name=f"{task_name}_partB"
            )
        else:
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
        dag_id: str = 'dag_w64_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_43',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w64_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
        current_run_id = get_current_task_run_id(dag_id, task_name)

        if enable_optimization:
            # 数据平面优化模式
            tasks = [
                (get_upstream_task_value, (dag_id, task_name, current_run_id, upstream_task_id)),
                (fixed_sleep_task, (fixed_sleep_seconds, f"{task_name}_partA"))
            ]
            
            # 并行执行任务
            sleep_time_ms_from_db, _ = execute_parallel_tasks(tasks)
            
            # 执行最后的sleep，使用优化比例
            return dynamic_sleep_task(
                sleep_time_ms=sleep_time_ms_from_db,
                dynamic_ratio=dynamic_ratio,
                task_name=f"{task_name}_partB"
            )
        else:
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
        dag_id: str = 'dag_w64_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_44',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w64_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
        current_run_id = get_current_task_run_id(dag_id, task_name)

        if enable_optimization:
            # 数据平面优化模式
            tasks = [
                (get_upstream_task_value, (dag_id, task_name, current_run_id, upstream_task_id)),
                (fixed_sleep_task, (fixed_sleep_seconds, f"{task_name}_partA"))
            ]
            
            # 并行执行任务
            sleep_time_ms_from_db, _ = execute_parallel_tasks(tasks)
            
            # 执行最后的sleep，使用优化比例
            return dynamic_sleep_task(
                sleep_time_ms=sleep_time_ms_from_db,
                dynamic_ratio=dynamic_ratio,
                task_name=f"{task_name}_partB"
            )
        else:
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
        dag_id: str = 'dag_w64_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_45',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w64_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
        current_run_id = get_current_task_run_id(dag_id, task_name)

        if enable_optimization:
            # 数据平面优化模式
            tasks = [
                (get_upstream_task_value, (dag_id, task_name, current_run_id, upstream_task_id)),
                (fixed_sleep_task, (fixed_sleep_seconds, f"{task_name}_partA"))
            ]
            
            # 并行执行任务
            sleep_time_ms_from_db, _ = execute_parallel_tasks(tasks)
            
            # 执行最后的sleep，使用优化比例
            return dynamic_sleep_task(
                sleep_time_ms=sleep_time_ms_from_db,
                dynamic_ratio=dynamic_ratio,
                task_name=f"{task_name}_partB"
            )
        else:
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
        dag_id: str = 'dag_w64_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_46',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w64_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
        current_run_id = get_current_task_run_id(dag_id, task_name)

        if enable_optimization:
            # 数据平面优化模式
            tasks = [
                (get_upstream_task_value, (dag_id, task_name, current_run_id, upstream_task_id)),
                (fixed_sleep_task, (fixed_sleep_seconds, f"{task_name}_partA"))
            ]
            
            # 并行执行任务
            sleep_time_ms_from_db, _ = execute_parallel_tasks(tasks)
            
            # 执行最后的sleep，使用优化比例
            return dynamic_sleep_task(
                sleep_time_ms=sleep_time_ms_from_db,
                dynamic_ratio=dynamic_ratio,
                task_name=f"{task_name}_partB"
            )
        else:
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
        dag_id: str = 'dag_w64_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_47',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w64_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
        current_run_id = get_current_task_run_id(dag_id, task_name)

        if enable_optimization:
            # 数据平面优化模式
            tasks = [
                (get_upstream_task_value, (dag_id, task_name, current_run_id, upstream_task_id)),
                (fixed_sleep_task, (fixed_sleep_seconds, f"{task_name}_partA"))
            ]
            
            # 并行执行任务
            sleep_time_ms_from_db, _ = execute_parallel_tasks(tasks)
            
            # 执行最后的sleep，使用优化比例
            return dynamic_sleep_task(
                sleep_time_ms=sleep_time_ms_from_db,
                dynamic_ratio=dynamic_ratio,
                task_name=f"{task_name}_partB"
            )
        else:
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
        dag_id: str = 'dag_w64_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_48',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w64_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
        current_run_id = get_current_task_run_id(dag_id, task_name)

        if enable_optimization:
            # 数据平面优化模式
            tasks = [
                (get_upstream_task_value, (dag_id, task_name, current_run_id, upstream_task_id)),
                (fixed_sleep_task, (fixed_sleep_seconds, f"{task_name}_partA"))
            ]
            
            # 并行执行任务
            sleep_time_ms_from_db, _ = execute_parallel_tasks(tasks)
            
            # 执行最后的sleep，使用优化比例
            return dynamic_sleep_task(
                sleep_time_ms=sleep_time_ms_from_db,
                dynamic_ratio=dynamic_ratio,
                task_name=f"{task_name}_partB"
            )
        else:
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
        dag_id: str = 'dag_w64_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_49',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w64_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
        current_run_id = get_current_task_run_id(dag_id, task_name)

        if enable_optimization:
            # 数据平面优化模式
            tasks = [
                (get_upstream_task_value, (dag_id, task_name, current_run_id, upstream_task_id)),
                (fixed_sleep_task, (fixed_sleep_seconds, f"{task_name}_partA"))
            ]
            
            # 并行执行任务
            sleep_time_ms_from_db, _ = execute_parallel_tasks(tasks)
            
            # 执行最后的sleep，使用优化比例
            return dynamic_sleep_task(
                sleep_time_ms=sleep_time_ms_from_db,
                dynamic_ratio=dynamic_ratio,
                task_name=f"{task_name}_partB"
            )
        else:
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
        dag_id: str = 'dag_w64_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_50',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w64_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
        current_run_id = get_current_task_run_id(dag_id, task_name)

        if enable_optimization:
            # 数据平面优化模式
            tasks = [
                (get_upstream_task_value, (dag_id, task_name, current_run_id, upstream_task_id)),
                (fixed_sleep_task, (fixed_sleep_seconds, f"{task_name}_partA"))
            ]
            
            # 并行执行任务
            sleep_time_ms_from_db, _ = execute_parallel_tasks(tasks)
            
            # 执行最后的sleep，使用优化比例
            return dynamic_sleep_task(
                sleep_time_ms=sleep_time_ms_from_db,
                dynamic_ratio=dynamic_ratio,
                task_name=f"{task_name}_partB"
            )
        else:
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
        dag_id: str = 'dag_w64_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_51',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w64_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
        current_run_id = get_current_task_run_id(dag_id, task_name)

        if enable_optimization:
            # 数据平面优化模式
            tasks = [
                (get_upstream_task_value, (dag_id, task_name, current_run_id, upstream_task_id)),
                (fixed_sleep_task, (fixed_sleep_seconds, f"{task_name}_partA"))
            ]
            
            # 并行执行任务
            sleep_time_ms_from_db, _ = execute_parallel_tasks(tasks)
            
            # 执行最后的sleep，使用优化比例
            return dynamic_sleep_task(
                sleep_time_ms=sleep_time_ms_from_db,
                dynamic_ratio=dynamic_ratio,
                task_name=f"{task_name}_partB"
            )
        else:
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
        dag_id: str = 'dag_w64_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_52',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w64_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
        current_run_id = get_current_task_run_id(dag_id, task_name)

        if enable_optimization:
            # 数据平面优化模式
            tasks = [
                (get_upstream_task_value, (dag_id, task_name, current_run_id, upstream_task_id)),
                (fixed_sleep_task, (fixed_sleep_seconds, f"{task_name}_partA"))
            ]
            
            # 并行执行任务
            sleep_time_ms_from_db, _ = execute_parallel_tasks(tasks)
            
            # 执行最后的sleep，使用优化比例
            return dynamic_sleep_task(
                sleep_time_ms=sleep_time_ms_from_db,
                dynamic_ratio=dynamic_ratio,
                task_name=f"{task_name}_partB"
            )
        else:
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
        dag_id: str = 'dag_w64_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_53',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w64_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
        current_run_id = get_current_task_run_id(dag_id, task_name)

        if enable_optimization:
            # 数据平面优化模式
            tasks = [
                (get_upstream_task_value, (dag_id, task_name, current_run_id, upstream_task_id)),
                (fixed_sleep_task, (fixed_sleep_seconds, f"{task_name}_partA"))
            ]
            
            # 并行执行任务
            sleep_time_ms_from_db, _ = execute_parallel_tasks(tasks)
            
            # 执行最后的sleep，使用优化比例
            return dynamic_sleep_task(
                sleep_time_ms=sleep_time_ms_from_db,
                dynamic_ratio=dynamic_ratio,
                task_name=f"{task_name}_partB"
            )
        else:
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
        dag_id: str = 'dag_w64_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_54',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w64_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
        current_run_id = get_current_task_run_id(dag_id, task_name)

        if enable_optimization:
            # 数据平面优化模式
            tasks = [
                (get_upstream_task_value, (dag_id, task_name, current_run_id, upstream_task_id)),
                (fixed_sleep_task, (fixed_sleep_seconds, f"{task_name}_partA"))
            ]
            
            # 并行执行任务
            sleep_time_ms_from_db, _ = execute_parallel_tasks(tasks)
            
            # 执行最后的sleep，使用优化比例
            return dynamic_sleep_task(
                sleep_time_ms=sleep_time_ms_from_db,
                dynamic_ratio=dynamic_ratio,
                task_name=f"{task_name}_partB"
            )
        else:
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
        dag_id: str = 'dag_w64_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_55',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w64_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
        current_run_id = get_current_task_run_id(dag_id, task_name)

        if enable_optimization:
            # 数据平面优化模式
            tasks = [
                (get_upstream_task_value, (dag_id, task_name, current_run_id, upstream_task_id)),
                (fixed_sleep_task, (fixed_sleep_seconds, f"{task_name}_partA"))
            ]
            
            # 并行执行任务
            sleep_time_ms_from_db, _ = execute_parallel_tasks(tasks)
            
            # 执行最后的sleep，使用优化比例
            return dynamic_sleep_task(
                sleep_time_ms=sleep_time_ms_from_db,
                dynamic_ratio=dynamic_ratio,
                task_name=f"{task_name}_partB"
            )
        else:
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
        dag_id: str = 'dag_w64_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_56',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w64_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
        current_run_id = get_current_task_run_id(dag_id, task_name)

        if enable_optimization:
            # 数据平面优化模式
            tasks = [
                (get_upstream_task_value, (dag_id, task_name, current_run_id, upstream_task_id)),
                (fixed_sleep_task, (fixed_sleep_seconds, f"{task_name}_partA"))
            ]
            
            # 并行执行任务
            sleep_time_ms_from_db, _ = execute_parallel_tasks(tasks)
            
            # 执行最后的sleep，使用优化比例
            return dynamic_sleep_task(
                sleep_time_ms=sleep_time_ms_from_db,
                dynamic_ratio=dynamic_ratio,
                task_name=f"{task_name}_partB"
            )
        else:
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
        dag_id: str = 'dag_w64_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_57',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w64_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
        current_run_id = get_current_task_run_id(dag_id, task_name)

        if enable_optimization:
            # 数据平面优化模式
            tasks = [
                (get_upstream_task_value, (dag_id, task_name, current_run_id, upstream_task_id)),
                (fixed_sleep_task, (fixed_sleep_seconds, f"{task_name}_partA"))
            ]
            
            # 并行执行任务
            sleep_time_ms_from_db, _ = execute_parallel_tasks(tasks)
            
            # 执行最后的sleep，使用优化比例
            return dynamic_sleep_task(
                sleep_time_ms=sleep_time_ms_from_db,
                dynamic_ratio=dynamic_ratio,
                task_name=f"{task_name}_partB"
            )
        else:
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
        dag_id: str = 'dag_w64_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_58',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w64_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
        current_run_id = get_current_task_run_id(dag_id, task_name)

        if enable_optimization:
            # 数据平面优化模式
            tasks = [
                (get_upstream_task_value, (dag_id, task_name, current_run_id, upstream_task_id)),
                (fixed_sleep_task, (fixed_sleep_seconds, f"{task_name}_partA"))
            ]
            
            # 并行执行任务
            sleep_time_ms_from_db, _ = execute_parallel_tasks(tasks)
            
            # 执行最后的sleep，使用优化比例
            return dynamic_sleep_task(
                sleep_time_ms=sleep_time_ms_from_db,
                dynamic_ratio=dynamic_ratio,
                task_name=f"{task_name}_partB"
            )
        else:
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
        dag_id: str = 'dag_w64_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_59',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w64_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
        current_run_id = get_current_task_run_id(dag_id, task_name)

        if enable_optimization:
            # 数据平面优化模式
            tasks = [
                (get_upstream_task_value, (dag_id, task_name, current_run_id, upstream_task_id)),
                (fixed_sleep_task, (fixed_sleep_seconds, f"{task_name}_partA"))
            ]
            
            # 并行执行任务
            sleep_time_ms_from_db, _ = execute_parallel_tasks(tasks)
            
            # 执行最后的sleep，使用优化比例
            return dynamic_sleep_task(
                sleep_time_ms=sleep_time_ms_from_db,
                dynamic_ratio=dynamic_ratio,
                task_name=f"{task_name}_partB"
            )
        else:
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
        dag_id: str = 'dag_w64_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_60',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w64_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
        current_run_id = get_current_task_run_id(dag_id, task_name)

        if enable_optimization:
            # 数据平面优化模式
            tasks = [
                (get_upstream_task_value, (dag_id, task_name, current_run_id, upstream_task_id)),
                (fixed_sleep_task, (fixed_sleep_seconds, f"{task_name}_partA"))
            ]
            
            # 并行执行任务
            sleep_time_ms_from_db, _ = execute_parallel_tasks(tasks)
            
            # 执行最后的sleep，使用优化比例
            return dynamic_sleep_task(
                sleep_time_ms=sleep_time_ms_from_db,
                dynamic_ratio=dynamic_ratio,
                task_name=f"{task_name}_partB"
            )
        else:
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
        dag_id: str = 'dag_w64_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_61',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w64_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
        current_run_id = get_current_task_run_id(dag_id, task_name)

        if enable_optimization:
            # 数据平面优化模式
            tasks = [
                (get_upstream_task_value, (dag_id, task_name, current_run_id, upstream_task_id)),
                (fixed_sleep_task, (fixed_sleep_seconds, f"{task_name}_partA"))
            ]
            
            # 并行执行任务
            sleep_time_ms_from_db, _ = execute_parallel_tasks(tasks)
            
            # 执行最后的sleep，使用优化比例
            return dynamic_sleep_task(
                sleep_time_ms=sleep_time_ms_from_db,
                dynamic_ratio=dynamic_ratio,
                task_name=f"{task_name}_partB"
            )
        else:
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
        dag_id: str = 'dag_w64_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_62',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w64_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
        current_run_id = get_current_task_run_id(dag_id, task_name)

        if enable_optimization:
            # 数据平面优化模式
            tasks = [
                (get_upstream_task_value, (dag_id, task_name, current_run_id, upstream_task_id)),
                (fixed_sleep_task, (fixed_sleep_seconds, f"{task_name}_partA"))
            ]
            
            # 并行执行任务
            sleep_time_ms_from_db, _ = execute_parallel_tasks(tasks)
            
            # 执行最后的sleep，使用优化比例
            return dynamic_sleep_task(
                sleep_time_ms=sleep_time_ms_from_db,
                dynamic_ratio=dynamic_ratio,
                task_name=f"{task_name}_partB"
            )
        else:
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
        dag_id: str = 'dag_w64_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_63',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w64_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
        current_run_id = get_current_task_run_id(dag_id, task_name)

        if enable_optimization:
            # 数据平面优化模式
            tasks = [
                (get_upstream_task_value, (dag_id, task_name, current_run_id, upstream_task_id)),
                (fixed_sleep_task, (fixed_sleep_seconds, f"{task_name}_partA"))
            ]
            
            # 并行执行任务
            sleep_time_ms_from_db, _ = execute_parallel_tasks(tasks)
            
            # 执行最后的sleep，使用优化比例
            return dynamic_sleep_task(
                sleep_time_ms=sleep_time_ms_from_db,
                dynamic_ratio=dynamic_ratio,
                task_name=f"{task_name}_partB"
            )
        else:
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
        dag_id: str = 'dag_w64_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_64',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w64_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
        current_run_id = get_current_task_run_id(dag_id, task_name)

        if enable_optimization:
            # 数据平面优化模式
            tasks = [
                (get_upstream_task_value, (dag_id, task_name, current_run_id, upstream_task_id)),
                (fixed_sleep_task, (fixed_sleep_seconds, f"{task_name}_partA"))
            ]
            
            # 并行执行任务
            sleep_time_ms_from_db, _ = execute_parallel_tasks(tasks)
            
            # 执行最后的sleep，使用优化比例
            return dynamic_sleep_task(
                sleep_time_ms=sleep_time_ms_from_db,
                dynamic_ratio=dynamic_ratio,
                task_name=f"{task_name}_partB"
            )
        else:
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
        dag_id: str = 'dag_w64_d3',
        upstream_task_id: str = 'func_1_1',
        task_name: str = 'func_1_65',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w64_d3'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
        current_run_id = get_current_task_run_id(dag_id, task_name)

        if enable_optimization:
            # 数据平面优化模式
            tasks = [
                (get_upstream_task_value, (dag_id, task_name, current_run_id, upstream_task_id)),
                (fixed_sleep_task, (fixed_sleep_seconds, f"{task_name}_partA"))
            ]
            
            # 并行执行任务
            sleep_time_ms_from_db, _ = execute_parallel_tasks(tasks)
            
            # 执行最后的sleep，使用优化比例
            return dynamic_sleep_task(
                sleep_time_ms=sleep_time_ms_from_db,
                dynamic_ratio=dynamic_ratio,
                task_name=f"{task_name}_partB"
            )
        else:
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
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = 'dag_w64_d3',
        upstream_task_id: str = 'func_1_65',
        task_name: str = 'func_1_66',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'dag_w64_d3'
            upstream_task_id: 上游任务ID，默认'func_1_65'
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
                (fixed_sleep_task, (fixed_sleep_seconds, f"{task_name}_partA"))
            ]
            
            # 并行执行任务
            sleep_time_ms_1, sleep_time_ms_2, sleep_time_ms_3, sleep_time_ms_4, sleep_time_ms_5, sleep_time_ms_6, sleep_time_ms_7, sleep_time_ms_8, sleep_time_ms_9, sleep_time_ms_10, sleep_time_ms_11, sleep_time_ms_12, sleep_time_ms_13, sleep_time_ms_14, sleep_time_ms_15, sleep_time_ms_16, sleep_time_ms_17, sleep_time_ms_18, sleep_time_ms_19, sleep_time_ms_20, sleep_time_ms_21, sleep_time_ms_22, sleep_time_ms_23, sleep_time_ms_24, sleep_time_ms_25, sleep_time_ms_26, sleep_time_ms_27, sleep_time_ms_28, sleep_time_ms_29, sleep_time_ms_30, sleep_time_ms_31, sleep_time_ms_32, sleep_time_ms_33, sleep_time_ms_34, sleep_time_ms_35, sleep_time_ms_36, sleep_time_ms_37, sleep_time_ms_38, sleep_time_ms_39, sleep_time_ms_40, sleep_time_ms_41, sleep_time_ms_42, sleep_time_ms_43, sleep_time_ms_44, sleep_time_ms_45, sleep_time_ms_46, sleep_time_ms_47, sleep_time_ms_48, sleep_time_ms_49, sleep_time_ms_50, sleep_time_ms_51, sleep_time_ms_52, sleep_time_ms_53, sleep_time_ms_54, sleep_time_ms_55, sleep_time_ms_56, sleep_time_ms_57, sleep_time_ms_58, sleep_time_ms_59, sleep_time_ms_60, sleep_time_ms_61, sleep_time_ms_62, sleep_time_ms_63, sleep_time_ms_64, _ = execute_parallel_tasks(tasks)
            
            sleep_time_ms = max(sleep_time_ms_1, sleep_time_ms_2, sleep_time_ms_3, sleep_time_ms_4, sleep_time_ms_5, sleep_time_ms_6, sleep_time_ms_7, sleep_time_ms_8, sleep_time_ms_9, sleep_time_ms_10, sleep_time_ms_11, sleep_time_ms_12, sleep_time_ms_13, sleep_time_ms_14, sleep_time_ms_15, sleep_time_ms_16, sleep_time_ms_17, sleep_time_ms_18, sleep_time_ms_19, sleep_time_ms_20, sleep_time_ms_21, sleep_time_ms_22, sleep_time_ms_23, sleep_time_ms_24, sleep_time_ms_25, sleep_time_ms_26, sleep_time_ms_27, sleep_time_ms_28, sleep_time_ms_29, sleep_time_ms_30, sleep_time_ms_31, sleep_time_ms_32, sleep_time_ms_33, sleep_time_ms_34, sleep_time_ms_35, sleep_time_ms_36, sleep_time_ms_37, sleep_time_ms_38, sleep_time_ms_39, sleep_time_ms_40, sleep_time_ms_41, sleep_time_ms_42, sleep_time_ms_43, sleep_time_ms_44, sleep_time_ms_45, sleep_time_ms_46, sleep_time_ms_47, sleep_time_ms_48, sleep_time_ms_49, sleep_time_ms_50, sleep_time_ms_51, sleep_time_ms_52, sleep_time_ms_53, sleep_time_ms_54, sleep_time_ms_55, sleep_time_ms_56, sleep_time_ms_57, sleep_time_ms_58, sleep_time_ms_59, sleep_time_ms_60, sleep_time_ms_61, sleep_time_ms_62, sleep_time_ms_63, sleep_time_ms_64)

            logging.info(f"WHC IMP IMP IMP: sleep_time_ms: {sleep_time_ms}")

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
    _enable_optimization = False

    func_1_1_output = func_1_1(sleep_time_ms = sleep_time_ms, dynamic_ratio=1, task_name='func_1_1')

    func_1_2_output = func_1_2(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w64_d3', upstream_task_id='func_1_1', task_name='func_1_2', enable_optimization=_enable_optimization)
    
    func_1_3_output = func_1_3(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w64_d3', upstream_task_id='func_1_1', task_name='func_1_3', enable_optimization=_enable_optimization)
    
    func_1_4_output = func_1_4(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w64_d3', upstream_task_id='func_1_1', task_name='func_1_4', enable_optimization=_enable_optimization)

    func_1_5_output = func_1_5(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w64_d3', upstream_task_id='func_1_1', task_name='func_1_5', enable_optimization=_enable_optimization)
    
    func_1_6_output = func_1_6(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w64_d3', upstream_task_id='func_1_1', task_name='func_1_6', enable_optimization=_enable_optimization)

    func_1_7_output = func_1_7(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w64_d3', upstream_task_id='func_1_1', task_name='func_1_7', enable_optimization=_enable_optimization)

    func_1_8_output = func_1_8(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w64_d3', upstream_task_id='func_1_1', task_name='func_1_8', enable_optimization=_enable_optimization)

    func_1_9_output = func_1_9(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w64_d3', upstream_task_id='func_1_1', task_name='func_1_9', enable_optimization=_enable_optimization)

    func_1_10_output = func_1_10(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w64_d3', upstream_task_id='func_1_1', task_name='func_1_10', enable_optimization=_enable_optimization)

    func_1_11_output = func_1_11(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w64_d3', upstream_task_id='func_1_1', task_name='func_1_11', enable_optimization=_enable_optimization)

    func_1_12_output = func_1_12(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w64_d3', upstream_task_id='func_1_1', task_name='func_1_12', enable_optimization=_enable_optimization)

    func_1_13_output = func_1_13(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w64_d3', upstream_task_id='func_1_1', task_name='func_1_13', enable_optimization=_enable_optimization)

    func_1_14_output = func_1_14(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w64_d3', upstream_task_id='func_1_1', task_name='func_1_14', enable_optimization=_enable_optimization)

    func_1_15_output = func_1_15(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w64_d3', upstream_task_id='func_1_1', task_name='func_1_15', enable_optimization=_enable_optimization)

    func_1_16_output = func_1_16(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w64_d3', upstream_task_id='func_1_1', task_name='func_1_16', enable_optimization=_enable_optimization)

    func_1_17_output = func_1_17(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w64_d3', upstream_task_id='func_1_1', task_name='func_1_17', enable_optimization=_enable_optimization)

    func_1_18_output = func_1_18(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w64_d3', upstream_task_id='func_1_1', task_name='func_1_18', enable_optimization=_enable_optimization)

    func_1_19_output = func_1_19(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w64_d3', upstream_task_id='func_1_1', task_name='func_1_19', enable_optimization=_enable_optimization)

    func_1_20_output = func_1_20(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w64_d3', upstream_task_id='func_1_1', task_name='func_1_20', enable_optimization=_enable_optimization)

    func_1_21_output = func_1_21(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w64_d3', upstream_task_id='func_1_1', task_name='func_1_21', enable_optimization=_enable_optimization)

    func_1_22_output = func_1_22(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w64_d3', upstream_task_id='func_1_1', task_name='func_1_22', enable_optimization=_enable_optimization)

    func_1_23_output = func_1_23(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w64_d3', upstream_task_id='func_1_1', task_name='func_1_23', enable_optimization=_enable_optimization)

    func_1_24_output = func_1_24(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w64_d3', upstream_task_id='func_1_1', task_name='func_1_24', enable_optimization=_enable_optimization)

    func_1_25_output = func_1_25(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w64_d3', upstream_task_id='func_1_1', task_name='func_1_25', enable_optimization=_enable_optimization)

    func_1_26_output = func_1_26(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w64_d3', upstream_task_id='func_1_1', task_name='func_1_26', enable_optimization=_enable_optimization)

    func_1_27_output = func_1_27(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w64_d3', upstream_task_id='func_1_1', task_name='func_1_27', enable_optimization=_enable_optimization)

    func_1_28_output = func_1_28(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w64_d3', upstream_task_id='func_1_1', task_name='func_1_28', enable_optimization=_enable_optimization)

    func_1_29_output = func_1_29(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w64_d3', upstream_task_id='func_1_1', task_name='func_1_29', enable_optimization=_enable_optimization)

    func_1_30_output = func_1_30(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w64_d3', upstream_task_id='func_1_1', task_name='func_1_30', enable_optimization=_enable_optimization)

    func_1_31_output = func_1_31(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w64_d3', upstream_task_id='func_1_1', task_name='func_1_31', enable_optimization=_enable_optimization)

    func_1_32_output = func_1_32(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w64_d3', upstream_task_id='func_1_1', task_name='func_1_32', enable_optimization=_enable_optimization)

    func_1_33_output = func_1_33(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w64_d3', upstream_task_id='func_1_1', task_name='func_1_33', enable_optimization=_enable_optimization)

    func_1_34_output = func_1_34(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w64_d3', upstream_task_id='func_1_1', task_name='func_1_34', enable_optimization=_enable_optimization)

    func_1_35_output = func_1_35(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w64_d3', upstream_task_id='func_1_1', task_name='func_1_35', enable_optimization=_enable_optimization)

    func_1_36_output = func_1_36(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w64_d3', upstream_task_id='func_1_1', task_name='func_1_36', enable_optimization=_enable_optimization)

    func_1_37_output = func_1_37(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w64_d3', upstream_task_id='func_1_1', task_name='func_1_37', enable_optimization=_enable_optimization)

    func_1_38_output = func_1_38(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w64_d3', upstream_task_id='func_1_1', task_name='func_1_38', enable_optimization=_enable_optimization)

    func_1_39_output = func_1_39(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w64_d3', upstream_task_id='func_1_1', task_name='func_1_39', enable_optimization=_enable_optimization)

    func_1_40_output = func_1_40(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w64_d3', upstream_task_id='func_1_1', task_name='func_1_40', enable_optimization=_enable_optimization)

    func_1_41_output = func_1_41(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w64_d3', upstream_task_id='func_1_1', task_name='func_1_41', enable_optimization=_enable_optimization)

    func_1_42_output = func_1_42(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w64_d3', upstream_task_id='func_1_1', task_name='func_1_42', enable_optimization=_enable_optimization)

    func_1_43_output = func_1_43(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w64_d3', upstream_task_id='func_1_1', task_name='func_1_43', enable_optimization=_enable_optimization)

    func_1_44_output = func_1_44(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w64_d3', upstream_task_id='func_1_1', task_name='func_1_44', enable_optimization=_enable_optimization)

    func_1_45_output = func_1_45(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w64_d3', upstream_task_id='func_1_1', task_name='func_1_45', enable_optimization=_enable_optimization)

    func_1_46_output = func_1_46(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w64_d3', upstream_task_id='func_1_1', task_name='func_1_46', enable_optimization=_enable_optimization)

    func_1_47_output = func_1_47(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w64_d3', upstream_task_id='func_1_1', task_name='func_1_47', enable_optimization=_enable_optimization)

    func_1_48_output = func_1_48(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w64_d3', upstream_task_id='func_1_1', task_name='func_1_48', enable_optimization=_enable_optimization)

    func_1_49_output = func_1_49(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w64_d3', upstream_task_id='func_1_1', task_name='func_1_49', enable_optimization=_enable_optimization)

    func_1_50_output = func_1_50(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w64_d3', upstream_task_id='func_1_1', task_name='func_1_50', enable_optimization=_enable_optimization)

    func_1_51_output = func_1_51(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w64_d3', upstream_task_id='func_1_1', task_name='func_1_51', enable_optimization=_enable_optimization)

    func_1_52_output = func_1_52(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w64_d3', upstream_task_id='func_1_1', task_name='func_1_52', enable_optimization=_enable_optimization)

    func_1_53_output = func_1_53(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w64_d3', upstream_task_id='func_1_1', task_name='func_1_53', enable_optimization=_enable_optimization)

    func_1_54_output = func_1_54(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w64_d3', upstream_task_id='func_1_1', task_name='func_1_54', enable_optimization=_enable_optimization)

    func_1_55_output = func_1_55(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w64_d3', upstream_task_id='func_1_1', task_name='func_1_55', enable_optimization=_enable_optimization)

    func_1_56_output = func_1_56(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w64_d3', upstream_task_id='func_1_1', task_name='func_1_56', enable_optimization=_enable_optimization)

    func_1_57_output = func_1_57(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w64_d3', upstream_task_id='func_1_1', task_name='func_1_57', enable_optimization=_enable_optimization)

    func_1_58_output = func_1_58(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w64_d3', upstream_task_id='func_1_1', task_name='func_1_58', enable_optimization=_enable_optimization)

    func_1_59_output = func_1_59(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w64_d3', upstream_task_id='func_1_1', task_name='func_1_59', enable_optimization=_enable_optimization)

    func_1_60_output = func_1_60(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w64_d3', upstream_task_id='func_1_1', task_name='func_1_60', enable_optimization=_enable_optimization)

    func_1_61_output = func_1_61(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w64_d3', upstream_task_id='func_1_1', task_name='func_1_61', enable_optimization=_enable_optimization)

    func_1_62_output = func_1_62(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w64_d3', upstream_task_id='func_1_1', task_name='func_1_62', enable_optimization=_enable_optimization)

    func_1_63_output = func_1_63(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w64_d3', upstream_task_id='func_1_1', task_name='func_1_63', enable_optimization=_enable_optimization)

    func_1_64_output = func_1_64(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w64_d3', upstream_task_id='func_1_1', task_name='func_1_64', enable_optimization=_enable_optimization)

    func_1_65_output = func_1_65(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w64_d3', upstream_task_id='func_1_1', task_name='func_1_65', enable_optimization=_enable_optimization)

    func_1_66_output = func_1_66(sleep_time_ms_1 = func_1_2_output, sleep_time_ms_2 = func_1_3_output, sleep_time_ms_3 = func_1_4_output, sleep_time_ms_4 = func_1_5_output, sleep_time_ms_5 = func_1_6_output, sleep_time_ms_6 = func_1_7_output, sleep_time_ms_7 = func_1_8_output, sleep_time_ms_8 = func_1_9_output, sleep_time_ms_9 = func_1_10_output, sleep_time_ms_10 = func_1_11_output, sleep_time_ms_11 = func_1_12_output, sleep_time_ms_12 = func_1_13_output, sleep_time_ms_13 = func_1_14_output, sleep_time_ms_14 = func_1_15_output, sleep_time_ms_15 = func_1_16_output, sleep_time_ms_16 = func_1_17_output, sleep_time_ms_17 = func_1_18_output, sleep_time_ms_18 = func_1_19_output, sleep_time_ms_19 = func_1_20_output, sleep_time_ms_20 = func_1_21_output, sleep_time_ms_21 = func_1_22_output, sleep_time_ms_22 = func_1_23_output, sleep_time_ms_23 = func_1_24_output, sleep_time_ms_24 = func_1_25_output, sleep_time_ms_25 = func_1_26_output, sleep_time_ms_26 = func_1_27_output, sleep_time_ms_27 = func_1_28_output, sleep_time_ms_28 = func_1_29_output, sleep_time_ms_29 = func_1_30_output, sleep_time_ms_30 = func_1_31_output, sleep_time_ms_31 = func_1_32_output, sleep_time_ms_32 = func_1_33_output, sleep_time_ms_33 = func_1_34_output, sleep_time_ms_34 = func_1_35_output, sleep_time_ms_35 = func_1_36_output, sleep_time_ms_36 = func_1_37_output, sleep_time_ms_37 = func_1_38_output, sleep_time_ms_38 = func_1_39_output, sleep_time_ms_39 = func_1_40_output, sleep_time_ms_40 = func_1_41_output, sleep_time_ms_41 = func_1_42_output, sleep_time_ms_42 = func_1_43_output, sleep_time_ms_43 = func_1_44_output, sleep_time_ms_44 = func_1_45_output, sleep_time_ms_45 = func_1_46_output, sleep_time_ms_46 = func_1_47_output, sleep_time_ms_47 = func_1_48_output, sleep_time_ms_48 = func_1_49_output, sleep_time_ms_49 = func_1_50_output, sleep_time_ms_50 = func_1_51_output, sleep_time_ms_51 = func_1_52_output, sleep_time_ms_52 = func_1_53_output, sleep_time_ms_53 = func_1_54_output, sleep_time_ms_54 = func_1_55_output, sleep_time_ms_55 = func_1_56_output, sleep_time_ms_56 = func_1_57_output, sleep_time_ms_57 = func_1_58_output, sleep_time_ms_58 = func_1_59_output, sleep_time_ms_59 = func_1_60_output, sleep_time_ms_60 = func_1_61_output, sleep_time_ms_61 = func_1_62_output, sleep_time_ms_62 = func_1_63_output, sleep_time_ms_63 = func_1_64_output, sleep_time_ms_64 = func_1_65_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='dag_w64_d3', upstream_task_id='func_1_65', task_name='func_1_66', enable_optimization=_enable_optimization)
    
# execute dag
etl_dag = dag_w64_d3()
