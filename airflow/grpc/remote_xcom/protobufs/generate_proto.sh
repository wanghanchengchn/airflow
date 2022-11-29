TOOL=grpc_tools.protoc

python3 -m grpc_tools.protoc -I . \
--python_out=. \
--pyi_out=. \
--grpc_python_out=. \
./*.proto

printf "change remote_xcom_pb2_grpc.py module from\nimport remote_xcom_pb2 as remote__xcom__pb2\n to \nfrom . import remote_xcom_pb2 as remote__xcom__pb2"