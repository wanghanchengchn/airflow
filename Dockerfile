FROM apache/airflow:2.4.3
USER root
RUN curl -o kn -L https://github.com/knative/client/releases/download/knative-v1.4.0/kn-linux-amd64 && chmod +x kn && mv kn /usr/local/bin/kn
USER airflow
COPY airflow /home/airflow/.local/lib/python3.7/site-packages/airflow
COPY workflows/image/airflow-dags /opt/airflow/dags
