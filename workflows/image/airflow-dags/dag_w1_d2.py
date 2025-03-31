import pendulum
from airflow.decorators import dag, task
import logging
from functools import wraps
from time import time
import time as t_module

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

@dag(
    schedule_interval=None,
    start_date=pendulum.datetime(2021, 1, 1, tz="UTC"),
    catchup=False,
    is_paused_upon_creation=False)
def dag_w1_d2():
    @task
    @timing
    def func_1_1(sleep_time_ms):
        t_module.sleep(sleep_time_ms / 1000)
        return sleep_time_ms

    @task
    @timing
    def func_1_2(sleep_time_ms):
        from airflow.models import TaskInstance
        from airflow.settings import Session
        import time
        from concurrent.futures import ThreadPoolExecutor, TimeoutError, wait, FIRST_COMPLETED
        
        def get_current_run_id():
            session = Session()
            try:
                current_task = session.query(TaskInstance).filter(
                    TaskInstance.dag_id == 'dag_w1_d2',
                    TaskInstance.task_id == 'func_1_2'
                ).order_by(TaskInstance.start_date.desc()).first()
                
                if not current_task:
                    raise ValueError("Cannot find current task instance")
                    
                return current_task.run_id
            finally:
                session.close()
        
        def try_get_upstream_value(run_id):
            max_retries = 300
            retry_delay = 0.1
            
            for attempt in range(max_retries):
                session = Session()
                try:
                    upstream_task = session.query(TaskInstance).filter(
                        TaskInstance.dag_id == 'dag_w1_d2',
                        TaskInstance.task_id == 'func_1_1',
                        TaskInstance.run_id == run_id
                    ).first()
                    
                    if upstream_task:
                        value = upstream_task.xcom_pull(task_ids='func_1_1')
                        if value is not None:
                            logging.info(f"get upstream value: {value}")
                            return value
                    logging.info(f"Attempt {attempt + 1}/{max_retries}: Waiting for upstream XCom...")
                    time.sleep(retry_delay)
                except Exception as e:
                    logging.info(f"Error getting upstream value: {str(e)}")
                finally:
                    session.close()
            
            logging.info("Max retries reached, using default value")
            return 1000  # 默认值

        def part_A():
            logging.info("start sleep 2.5")
            t_module.sleep(2.5)
            logging.info("end sleep 2.5")
            return True

        def part_B(sleep_time_ms):
            logging.info(f"sleep_time_ms: {sleep_time_ms}")
            t_module.sleep(sleep_time_ms / 1000 / 2)
            return sleep_time_ms

        # 获取当前run_id
        current_run_id = get_current_run_id()
        
        # 创建线程池并同时执行两个任务
        with ThreadPoolExecutor(max_workers=2) as executor:
            # 提交两个任务
            future_db = executor.submit(try_get_upstream_value, current_run_id)
            future_sleep = executor.submit(part_A)
            
            # 等待两个任务都完成
            sleep_time_ms = future_db.result()  # 获取数据库查询结果
            future_sleep.result()  # 等待sleep完成
            
            # 执行最后的sleep
            return part_B(sleep_time_ms)

    # specify data flow
    sleep_time_ms = 5000
    func_1_1_output = func_1_1(sleep_time_ms)
    func_1_2(func_1_1_output)

# execute dag
etl_dag = dag_w1_d2()
