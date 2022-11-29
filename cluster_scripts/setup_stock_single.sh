# cluster setup
git clone https://github.com/vhive-serverless/vhive
cd vhive
./scripts/cloudlab/setup_node.sh stock-only
sudo containerd
./scripts/cluster/create_one_node_cluster.sh stock-only

# install helm
curl https://baltocdn.com/helm/signing.asc | gpg --dearmor | sudo tee /usr/share/keyrings/helm.gpg > /dev/null
sudo apt-get install apt-transport-https --yes
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/helm.gpg] https://baltocdn.com/helm/stable/debian/ all main" | sudo tee /etc/apt/sources.list.d/helm-stable-debian.list
sudo apt-get update
sudo apt-get install helm

