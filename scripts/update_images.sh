#!/usr/bin/zsh

function cleanup {
	rm -rf workflows/image/airflow
}

trap cleanup EXIT

cleanup
cp -r airflow workflows/image/airflow
(cd ./workflows/image && docker build . -t airflow-worker:latest) || (echo Failed to build airflow-worker:latest && exit 1)
echo Built airflow-worker:latest
docker build . -t airflow:latest || (echo Failed to build airflow:latest && exit 1)
echo Built airflow:latest

docker tag airflow-worker:latest nehalem90/airflow-worker:latest
docker push nehalem90/airflow-worker:latest
docker tag airflow:latest nehalem90/airflow:latest
docker push nehalem90/airflow:latest