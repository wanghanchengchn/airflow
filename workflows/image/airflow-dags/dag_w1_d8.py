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
def dag_w1_d8():
    @task
    @timing
    def func_1_1(sleep_time_ms):
        t_module.sleep(sleep_time_ms / 1000)
        return sleep_time_ms

    @task
    @timing
    def func_1_2(sleep_time_ms):
        t_module.sleep(sleep_time_ms / 1000)
        return sleep_time_ms

    @task
    @timing
    def func_1_3(sleep_time_ms):
        t_module.sleep(sleep_time_ms / 1000)
        return sleep_time_ms
    
    @task
    @timing
    def func_1_4(sleep_time_ms):
        t_module.sleep(sleep_time_ms / 1000)
        return sleep_time_ms
    
    @task
    @timing
    def func_1_5(sleep_time_ms):
        t_module.sleep(sleep_time_ms / 1000)
        return sleep_time_ms

    @task
    @timing
    def func_1_6(sleep_time_ms):
        t_module.sleep(sleep_time_ms / 1000)
        return sleep_time_ms

    @task
    @timing
    def func_1_7(sleep_time_ms):
        t_module.sleep(sleep_time_ms / 1000)
        return sleep_time_ms

    @task
    @timing
    def func_1_8(sleep_time_ms):
        t_module.sleep(sleep_time_ms / 1000)
        return sleep_time_ms

    # specify data flow
    sleep_time_ms = 125
    func_1_1_output = func_1_1(sleep_time_ms)
    func_1_2_output = func_1_2(func_1_1_output)
    func_1_3_output = func_1_3(func_1_2_output)
    func_1_4_output = func_1_4(func_1_3_output)
    func_1_5_output = func_1_5(func_1_4_output)
    func_1_6_output = func_1_6(func_1_5_output)
    func_1_7_output = func_1_7(func_1_6_output)
    func_1_8(func_1_7_output)
    
# execute dag
etl_dag = dag_w1_d8()
