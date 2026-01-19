#!/usr/bin/env python3
"""
DAG 生成器脚本
自动生成指定扇出数量的 Airflow DAG 代码

用法:
    python generate_dag.py 128
    python generate_dag.py 128 256 512 1024
"""

import sys
import os


def generate_dag(fanout: int) -> str:
    """生成指定扇出数量的 DAG 代码"""
    
    dag_name = f"dag_w{fanout}_d3"
    
    # 生成导入部分
    imports = '''import pendulum
from airflow.decorators import dag, task
import logging
from functools import wraps
from time import time
import time as t_module
from airflow.models import TaskInstance
from airflow.settings import Session
from concurrent.futures import ThreadPoolExecutor, TimeoutError, wait, FIRST_COMPLETED
from typing import Optional, Union, Tuple
'''

    # 生成工具函数
    utils = '''
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
'''

    # 生成 DAG 装饰器
    dag_decorator = f'''
@dag(
    schedule_interval=None,
    start_date=pendulum.datetime(2021, 1, 1, tz="UTC"),
    catchup=False,
    is_paused_upon_creation=False)
def {dag_name}():
'''

    # 生成 func_1_1（起始任务）
    func_1_1 = f'''    @task
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

'''

    # 生成中间层任务（func_1_2 到 func_1_{fanout+1}）
    middle_tasks = ""
    for i in range(2, fanout + 2):
        task_name = f"func_1_{i}"
        middle_tasks += f'''
    @task
    @timing
    def {task_name}(
        sleep_time_ms: int,
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = '{dag_name}',
        upstream_task_id: str = 'func_1_1',
        task_name: str = '{task_name}',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'{dag_name}'
            upstream_task_id: 上游任务ID，默认'func_1_1'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
        current_run_id = get_current_task_run_id(dag_id, task_name)

        if enable_optimization:
            # 数据平面优化模式
            tasks = [
                (get_upstream_task_value, (dag_id, task_name, current_run_id, upstream_task_id)),
                (fixed_sleep_task, (fixed_sleep_seconds, f"{{task_name}}_partA"))
            ]
            
            # 并行执行任务
            sleep_time_ms_from_db, _ = execute_parallel_tasks(tasks)
            
            # 执行最后的sleep，使用优化比例
            return dynamic_sleep_task(
                sleep_time_ms=sleep_time_ms_from_db,
                dynamic_ratio=dynamic_ratio,
                task_name=f"{{task_name}}_partB"
            )
        else:
            # 普通模式：串行执行
            sleep_time_ms = get_upstream_task_value(dag_id, task_name, current_run_id, upstream_task_id)
            
            return dynamic_sleep_task(
                sleep_time_ms=sleep_time_ms,
                dynamic_ratio=1,
                task_name=task_name
            )

'''

    # 生成汇聚任务（func_1_{fanout+2}）
    final_task_name = f"func_1_{fanout + 2}"
    last_middle_task = f"func_1_{fanout + 1}"
    
    # 生成参数列表
    params = ",\n        ".join([f"sleep_time_ms_{i}: int" for i in range(1, fanout + 1)])
    
    # 生成 get_upstream_task_value 调用列表
    upstream_tasks = ",\n                ".join([
        f"(get_upstream_task_value, (dag_id, task_name, current_run_id, 'func_1_{i}'))"
        for i in range(2, fanout + 2)
    ])
    
    # 生成解包变量列表
    unpack_vars = ", ".join([f"sleep_time_ms_{i}" for i in range(1, fanout + 1)]) + ", _"
    
    # 生成 max 参数列表
    max_params = ", ".join([f"sleep_time_ms_{i}" for i in range(1, fanout + 1)])
    
    # 生成日志字符串
    log_vars = " ".join([f"sleep_time_ms_{i}: {{sleep_time_ms_{i}}}" for i in range(1, fanout + 1)])
    
    final_task = f'''
    @task
    @timing
    def {final_task_name}(
        {params},
        fixed_sleep_seconds: float = 2.5,
        dynamic_ratio: float = 0.5,
        dag_id: str = '{dag_name}',
        upstream_task_id: str = '{last_middle_task}',
        task_name: str = '{final_task_name}',
        enable_optimization: bool = True
    ) -> int:
        """执行并行的固定睡眠和动态睡眠任务

        Args:
            sleep_time_ms: 睡眠时间（毫秒）
            fixed_sleep_seconds: 固定睡眠时间（秒），默认2.5秒
            dynamic_ratio: 动态时间优化比例，默认0.5
            dag_id: DAG的ID，默认'{dag_name}'
            upstream_task_id: 上游任务ID，默认'{last_middle_task}'
            task_name: 任务名称，用于日志
            enable_optimization: 是否启用数据平面优化，默认True
        Returns:
            int: 从上游任务获取的睡眠时间
        """
        current_run_id = get_current_task_run_id(dag_id, task_name)

        if enable_optimization:
            tasks = [
                {upstream_tasks},
                (fixed_sleep_task, (fixed_sleep_seconds, f"{{task_name}}_partA"))
            ]
            
            # 并行执行任务
            {unpack_vars} = execute_parallel_tasks(tasks)

            sleep_time_ms = max({max_params})

            logging.info(f"WHC IMP IMP IMP: sleep_time_ms: {{sleep_time_ms}} {log_vars}")

            # 执行最后的sleep，使用优化比例
            return dynamic_sleep_task(
                sleep_time_ms=sleep_time_ms,
                dynamic_ratio=dynamic_ratio,
                task_name=f"{{task_name}}_partB"
            )
        else:
            # 普通模式：串行执行
            sleep_time_ms = get_upstream_task_value(dag_id, task_name, current_run_id, upstream_task_id)
            
            return dynamic_sleep_task(
                sleep_time_ms=sleep_time_ms,
                dynamic_ratio=1,
                task_name=task_name
            )

'''

    # 生成数据流定义
    data_flow = f'''
    # specify data flow
    sleep_time_ms = 5000
    _enable_optimization = True

    func_1_1_output = func_1_1(sleep_time_ms = sleep_time_ms, dynamic_ratio=1, task_name='func_1_1')

'''

    # 生成中间层任务调用
    for i in range(2, fanout + 2):
        data_flow += f"    func_1_{i}_output = func_1_{i}(sleep_time_ms = func_1_1_output, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='{dag_name}', upstream_task_id='func_1_1', task_name='func_1_{i}', enable_optimization=_enable_optimization)\n"
        if i < fanout + 1:
            data_flow += "\n"

    # 生成汇聚任务调用
    final_call_params = ", ".join([f"sleep_time_ms_{i} = func_1_{i+1}_output" for i in range(1, fanout + 1)])
    data_flow += f'''
    {final_task_name}_output = {final_task_name}({final_call_params}, fixed_sleep_seconds=(sleep_time_ms / 1000) /2, dynamic_ratio=0.5, dag_id='{dag_name}', upstream_task_id='{last_middle_task}', task_name='{final_task_name}', enable_optimization=_enable_optimization)
'''

    # 生成 DAG 执行
    dag_execute = f'''

# execute dag
etl_dag = {dag_name}()
'''

    # 组合所有部分
    full_code = imports + utils + dag_decorator + func_1_1 + middle_tasks + final_task + data_flow + dag_execute
    
    return full_code


def main():
    if len(sys.argv) < 2:
        print("用法: python generate_dag.py <fanout1> [fanout2] [fanout3] ...")
        print("示例: python generate_dag.py 128 256 512 1024")
        sys.exit(1)
    
    # 获取当前脚本所在目录
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    for arg in sys.argv[1:]:
        try:
            fanout = int(arg)
            if fanout < 1:
                print(f"错误: 扇出数量必须大于 0，跳过 {arg}")
                continue
            
            print(f"正在生成 fanout={fanout} 的 DAG...")
            
            # 生成代码
            code = generate_dag(fanout)
            
            # 写入文件
            filename = f"dag_w{fanout}_d3.py"
            filepath = os.path.join(script_dir, filename)
            
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(code)
            
            print(f"✓ 已生成: {filepath}")
            
        except ValueError:
            print(f"错误: '{arg}' 不是有效的数字，跳过")
            continue
    
    print("\n完成！")


if __name__ == "__main__":
    main()
