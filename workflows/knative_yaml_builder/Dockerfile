FROM apache/airflow:2.8.0
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
COPY knative_yaml_builder/yaml_builder.py /opt/airflow/yaml_builder.py
ENTRYPOINT ["python3", "/opt/airflow/yaml_builder.py"]
