[![License](https://img.shields.io/:license-Apache%202-blue.svg)](https://www.apache.org/licenses/LICENSE-2.0.txt)

# Airflow-vHive: Workflow Programming and Orchestration with Airflow atop of the vHive Serverless Platform

This fork of Apache Airflow executes DAGs similarly to the Kubernetes Executor shipped with stock Apache Airflow.
However, instead of creating and deleting Kubernetes pods to execute tasks, it uses Knative services.

These Knative services must be created ahead of time.
However, as Knative works differently, this does not mean that a worker pod is running all time.
Instead, Knative creates/scales/deletes the pods automatically as needed.
Also, this Knative worker function works seamlessly with other Airflow components, to maximize compatibility.


## Airflow Architecture

![Airflow-vHive_Architecture](./docs/figure/Airflow-kn-Page-2.drawio.svg)


## Getting started with Airflow-vHive
Please take a look at [Quickstart Guide](./docs/quickstart_guide.md)

## Developing Airflow-vHive
Please take a look at [Developer's Guide](./docs/developers_guide.md)

## License and copyright
This fork inherits the license and copyright of the original [Apache/Airflow](https://github.com/apache/airflows). This code is published under the terms of the Apache 2 license. 

The software is maintained by the HyScale Lab in the Nanyang Technological University, Singapore and vHive community.

### Maintainer
  - [JooYoung Park](https://github.com/JooyoungPark73)
