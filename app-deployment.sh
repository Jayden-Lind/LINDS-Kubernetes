#! /bin/bash

# Calico (Networking)
helm repo add projectcalico https://docs.tigera.io/calico/charts
helm upgrade --install calico projectcalico/tigera-operator \
  --namespace tigera-operator \
  --create-namespace \
  --version v3.31.1 \
  --set installation.calicoNetwork.containerIPForwarding=Enabled \
  --set installation.calicoNetwork.bgp=Enabled \
  --set installation.calicoNetwork.mtu=1300 \
  --set installation.calicoNetwork.kubeProxyManagement=Enabled \
  --set installation.calicoNetwork.bpfNetworkBootstrap=Disabled \
  --set installation.calicoNetwork.linuxDataplane=BPF \
  --set installation.calicoNetwork.ipPools[0].name=default-ipv4-ippool \
  --set installation.calicoNetwork.ipPools[0].cidr=10.244.0.0/16 \
  --set installation.calicoNetwork.ipPools[0].blockSize=26 \
  --set installation.calicoNetwork.ipPools[0].encapsulation=IPIPCrossSubnet \
  --set installation.calicoNetwork.ipPools[0].natOutgoing=Enabled \
  --set installation.calicoNetwork.ipPools[0].disableBGPExport=false \
  --set installation.calicoNetwork.ipPools[0].nodeSelector="all()" \
  \
  --set installation.calicoNetwork.ipPools[1].name=lb-172-16-1 \
  --set installation.calicoNetwork.ipPools[1].cidr=172.16.1.0/24 \
  --set installation.calicoNetwork.ipPools[1].blockSize=24 \
  --set installation.calicoNetwork.ipPools[1].encapsulation=None \
  --set installation.calicoNetwork.ipPools[1].natOutgoing=Disabled \
  --set installation.calicoNetwork.ipPools[1].assignmentMode=Automatic \
  --set installation.calicoNetwork.ipPools[1].allowedUses[0]=LoadBalancer \
  --set installation.calicoNetwork.ipPools[1].nodeSelector="all()"

kubectl apply -f - <<EOF
kind: ConfigMap
apiVersion: v1
metadata:
  name: kubernetes-services-endpoint
  namespace: tigera-operator
data:
  KUBERNETES_SERVICE_HOST: "10.0.53.11"
  KUBERNETES_SERVICE_PORT: "6443"
EOF

#argo-cd
kubectl create namespace argocd
kubectl apply -f base/linds-secret.yml
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
kubectl patch configmap argocd-cmd-params-cm -n argocd --type merge -p '{"data":{"server.insecure":"true"}}'
kubectl -n argocd patch configmap argocd-cm \
  --type merge \
  -p '{
    "data": {
      "timeout.reconciliation": "3600s",
      "timeout.reconciliation.jitter": "300s"
    }
  }'



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
