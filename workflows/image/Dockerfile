FROM apache/airflow:2.8.0
STOPSIGNAL SIGINT
USER root
RUN apt-get update && apt-get install -y \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*
USER airflow
RUN pip install grpcio grpcio-tools opencv-python
COPY airflow-dags /opt/airflow/dags
COPY airflow /home/airflow/.local/lib/python3.8/site-packages/airflow
EXPOSE 50000
ENTRYPOINT ["python", "/home/airflow/.local/lib/python3.8/site-packages/airflow/grpc/remote_xcom/grpc_worker_entrypoint.py", "--port", "50000"]
