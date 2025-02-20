import pendulum
from airflow.decorators import dag, task
import logging
from functools import wraps
from time import time


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
    is_paused_upon_creation=False
)
def etl_example():
    @task
    @timing
    def extract():
        # dummy data source
        return {"1001": 301.27, "1002": 433.21, "1003": 502.22}

    @task
    @timing
    def transform(order_data):
            total_order_value = 0
            for value in order_data.values():
                total_order_value += value

            return {"total_order_value": total_order_value}

    @task
    @timing
    def load(data):
        return data

    # specify data flow
    load(transform(extract()))

# execute dag
etl_dag = etl_example()
