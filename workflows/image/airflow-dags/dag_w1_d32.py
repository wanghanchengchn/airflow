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
def dag_w1_d32():
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

    @task
    @timing
    def func_1_9(sleep_time_ms):
        t_module.sleep(sleep_time_ms / 1000)
        return sleep_time_ms
    
    @task
    @timing
    def func_1_10(sleep_time_ms):
        t_module.sleep(sleep_time_ms / 1000)
        return sleep_time_ms

    @task
    @timing
    def func_1_11(sleep_time_ms):
        t_module.sleep(sleep_time_ms / 1000)
        return sleep_time_ms

    @task
    @timing
    def func_1_12(sleep_time_ms):
        t_module.sleep(sleep_time_ms / 1000)
        return sleep_time_ms
    
    @task
    @timing
    def func_1_13(sleep_time_ms):
        t_module.sleep(sleep_time_ms / 1000)
        return sleep_time_ms
        
    @task
    @timing
    def func_1_14(sleep_time_ms):
        t_module.sleep(sleep_time_ms / 1000)
        return sleep_time_ms
    
    @task
    @timing
    def func_1_15(sleep_time_ms):
        t_module.sleep(sleep_time_ms / 1000)
        return sleep_time_ms
    
    @task
    @timing
    def func_1_16(sleep_time_ms):
        t_module.sleep(sleep_time_ms / 1000)
        return sleep_time_ms
    
    @task
    @timing
    def func_1_17(sleep_time_ms):
        t_module.sleep(sleep_time_ms / 1000)
        return sleep_time_ms
    
    @task
    @timing
    def func_1_18(sleep_time_ms):
        t_module.sleep(sleep_time_ms / 1000)
        return sleep_time_ms
    
    @task
    @timing
    def func_1_19(sleep_time_ms):
        t_module.sleep(sleep_time_ms / 1000)
        return sleep_time_ms
    
    @task
    @timing
    def func_1_20(sleep_time_ms):
        t_module.sleep(sleep_time_ms / 1000)
        return sleep_time_ms
    
    @task
    @timing
    def func_1_21(sleep_time_ms):
        t_module.sleep(sleep_time_ms / 1000)
        return sleep_time_ms
    
    @task
    @timing
    def func_1_22(sleep_time_ms):
        t_module.sleep(sleep_time_ms / 1000)
        return sleep_time_ms
    
    @task
    @timing
    def func_1_23(sleep_time_ms):
        t_module.sleep(sleep_time_ms / 1000)
        return sleep_time_ms
    
    @task
    @timing
    def func_1_24(sleep_time_ms):
        t_module.sleep(sleep_time_ms / 1000)
        return sleep_time_ms
    
    @task
    @timing
    def func_1_25(sleep_time_ms):
        t_module.sleep(sleep_time_ms / 1000)
        return sleep_time_ms
    
    @task
    @timing
    def func_1_26(sleep_time_ms):
        t_module.sleep(sleep_time_ms / 1000)
        return sleep_time_ms
    
    @task
    @timing
    def func_1_27(sleep_time_ms):
        t_module.sleep(sleep_time_ms / 1000)
        return sleep_time_ms
    
    @task
    @timing
    def func_1_28(sleep_time_ms):
        t_module.sleep(sleep_time_ms / 1000)
        return sleep_time_ms
    
    @task
    @timing
    def func_1_29(sleep_time_ms):
        t_module.sleep(sleep_time_ms / 1000)
        return sleep_time_ms
    
    @task
    @timing
    def func_1_30(sleep_time_ms):
        t_module.sleep(sleep_time_ms / 1000)
        return sleep_time_ms
    
    @task
    @timing
    def func_1_31(sleep_time_ms):
        t_module.sleep(sleep_time_ms / 1000)
        return sleep_time_ms
    
    @task
    @timing
    def func_1_32(sleep_time_ms):
        t_module.sleep(sleep_time_ms / 1000)
        return sleep_time_ms
    
    # specify data flow
    sleep_time_ms = 31
    func_1_1_output = func_1_1(sleep_time_ms)
    func_1_2_output = func_1_2(func_1_1_output)
    func_1_3_output = func_1_3(func_1_2_output)
    func_1_4_output = func_1_4(func_1_3_output)
    func_1_5_output = func_1_5(func_1_4_output)
    func_1_6_output = func_1_6(func_1_5_output)
    func_1_7_output = func_1_7(func_1_6_output)
    func_1_8_output = func_1_8(func_1_7_output)
    func_1_9_output = func_1_9(func_1_8_output)
    func_1_10_output = func_1_10(func_1_9_output)
    func_1_11_output = func_1_11(func_1_10_output)
    func_1_12_output = func_1_12(func_1_11_output)
    func_1_13_output = func_1_13(func_1_12_output)
    func_1_14_output = func_1_14(func_1_13_output)
    func_1_15_output = func_1_15(func_1_14_output)
    func_1_16_output = func_1_16(func_1_15_output)
    func_1_17_output = func_1_17(func_1_16_output)
    func_1_18_output = func_1_18(func_1_17_output)
    func_1_19_output = func_1_19(func_1_18_output)
    func_1_20_output = func_1_20(func_1_19_output)
    func_1_21_output = func_1_21(func_1_20_output)
    func_1_22_output = func_1_22(func_1_21_output)
    func_1_23_output = func_1_23(func_1_22_output)
    func_1_24_output = func_1_24(func_1_23_output)
    func_1_25_output = func_1_25(func_1_24_output)
    func_1_26_output = func_1_26(func_1_25_output)
    func_1_27_output = func_1_27(func_1_26_output)
    func_1_28_output = func_1_28(func_1_27_output)
    func_1_29_output = func_1_29(func_1_28_output)
    func_1_30_output = func_1_30(func_1_29_output)
    func_1_31_output = func_1_31(func_1_30_output)
    func_1_32(func_1_31_output)
    
# execute dag
etl_dag = dag_w1_d32()
