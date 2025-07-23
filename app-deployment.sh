#! /bin/bash

# Calico (Networking)
kubectl create namespace tigera-operator
helm repo add projectcalico https://docs.tigera.io/calico/charts
helm install calico projectcalico/tigera-operator \
  --namespace tigera-operator \
  --create-namespace \
  --version v3.30.2 \
  --set calicoNetwork.containerIPForwarding=Enabled \
  --set calicoNetwork.bgp=Enabled \
  --set calicoNetwork.ipPools[0].allowedUses[0]=Workload \
  --set calicoNetwork.ipPools[0].allowedUses[1]=Tunnel \
  --set calicoNetwork.ipPools[0].name=default-ipv4-ippool \
  --set calicoNetwork.ipPools[0].disableBGPExport=false \
  --set calicoNetwork.ipPools[0].blockSize=26 \
  --set calicoNetwork.ipPools[0].cidr=10.244.0.0/16 \
  --set calicoNetwork.ipPools[0].encapsulation=IPIPCrossSubnet \
  --set calicoNetwork.ipPools[0].natOutgoing=Enabled \
  --set calicoNetwork.ipPools[0].nodeSelector="all()"


#argo-cd
kubectl create namespace argocd
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

# Reboot ubuntu nodes after provisioning

# Deleting kube-proxy to prevent collision with calico
kubectl -n kube-system delete ds kube-proxy
kubectl -n kube-system delete cm kube-proxy
