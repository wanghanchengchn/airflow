FROM wanghanchengchn/airflow-nehalem90-version:latest
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
USER root
RUN curl -o kn -L https://github.com/knative/client/releases/download/knative-v1.4.0/kn-linux-amd64 && chmod +x kn && mv kn /usr/local/bin/kn
USER airflow
COPY airflow /home/airflow/.local/lib/python3.8/site-packages/airflow
COPY workflows/image/airflow-dags /opt/airflow/dags
