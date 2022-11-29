git clone --depth=1 https://github.com/vhive-serverless/vhive.git
cd vhive
mkdir -p /tmp/vhive-logs
./scripts/cloudlab/setup_node.sh > >(tee -a /tmp/vhive-logs/setup_node.stdout) 2> >(tee -a /tmp/vhive-logs/setup_node.stderr >&2)
./scripts/cloudlab/setup_node.sh;
sudo screen -dmS containerd containerd; sleep 5;
sudo PATH=$PATH screen -dmS firecracker /usr/local/bin/firecracker-containerd --config /etc/firecracker-containerd/config.toml; sleep 5;
source /etc/profile && go build;
sudo screen -dmS vhive ./vhive; sleep 5;
./scripts/cluster/create_one_node_cluster.sh

curl https://baltocdn.com/helm/signing.asc | gpg --dearmor | sudo tee /usr/share/keyrings/helm.gpg > /dev/null
sudo apt-get install apt-transport-https --yes
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/helm.gpg] https://baltocdn.com/helm/stable/debian/ all main" | sudo tee /etc/apt/sources.list.d/helm-stable-debian.list
sudo apt-get update
sudo apt-get install helm

kubectl create namespace airflow
sudo mkdir /mnt/data{0..19}
sudo chmod 777 /mnt/data*
kubectl -n airflow create -f volumes.yaml
helm repo add apache-airflow https://airflow.apache.org
helm upgrade --install airflow apache-airflow/airflow --namespace airflow -f values.yaml --debug

