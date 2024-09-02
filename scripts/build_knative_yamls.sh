docker build -f ./workflows/knative_yaml_builder/Dockerfile ./workflows -t yaml-builder:latest
tmpdir="$(mktemp -d)"
chmod 777 "$tmpdir"
docker run -it -v "$(pwd)"/workflows/image/airflow-dags:/dag_import -v "$tmpdir":/output -v "$(pwd)"/workflows/knative_yaml_builder/knative_service_template.yaml:/knative_service_template.yaml yaml-builder:latest
mkdir -p ./workflows/knative_yamls
for dag_dir in "$tmpdir"/*; do
	cp -r "$dag_dir" ./workflows/knative_yamls/
done

find ./workflows/knative_yamls -name "*.yaml" -type f | while read -r file; do
	sed -i -e '$a\' "$file"
    echo "        autoscaling.knative.dev/minScale: \"1\"" >> "$file"
    echo "Modified $file"
done

echo "All YAML files have been processed."