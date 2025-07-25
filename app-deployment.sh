#! /bin/bash

# Calico (Networking)
helm repo add projectcalico https://docs.tigera.io/calico/charts
helm upgrade --install calico projectcalico/tigera-operator \
  --namespace tigera-operator \
  --create-namespace \
  --version v3.30.2 \
  --set installation.calicoNetwork.containerIPForwarding=Enabled \
  --set installation.calicoNetwork.bgp=Enabled \
  --set installation.calicoNetwork.linuxDataplane=BPF \
  --set installation.calicoNetwork.ipPools[0].name=default-ipv4-ippool \
  --set installation.calicoNetwork.ipPools[0].cidr=10.244.0.0/16 \
  --set installation.calicoNetwork.ipPools[0].blockSize=26 \
  --set installation.calicoNetwork.ipPools[0].encapsulation=IPIPCrossSubnet \
  --set installation.calicoNetwork.ipPools[0].natOutgoing=Enabled \
  --set installation.calicoNetwork.ipPools[0].allowedUses[0]=Workload \
  --set installation.calicoNetwork.ipPools[0].disableBGPExport=false \
  --set installation.calicoNetwork.ipPools[0].nodeSelector="all()"


#argo-cd
kubectl create namespace argocd
kubectl apply -f base/linds-secret.yml
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml

if ! test -f /usr/local/bin/argocd; then
    curl -sSL -o argocd-linux-amd64 https://github.com/argoproj/argo-cd/releases/latest/download/argocd-linux-amd64
    sudo install -m 555 argocd-linux-amd64 /usr/local/bin/argocd
    rm argocd-linux-amd64
fi

# Allow master to receive jobs to run the pre-hooks to finish provisioning the cluster
kubectl taint node jd-kube-01 node-role.kubernetes.io/control-plane:NoSchedule-

kubectl create -f applications

kubectl create -k base
echo "NOW APPLYING AGAIN"
kubectl apply -k base

# Reboot ubuntu nodes after provisioning

# Deleting kube-proxy to prevent collision with calico
#kubectl -n kube-system delete ds kube-proxy
#kubectl -n kube-system delete cm kube-proxy
