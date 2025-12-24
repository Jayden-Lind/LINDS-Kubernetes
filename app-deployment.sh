#! /bin/bash

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
kubectl create -f applications

kubectl create -k base
echo "NOW APPLYING AGAIN"
kubectl apply -k base

# Reboot ubuntu nodes after provisioning

# Deleting kube-proxy to prevent collision with calico
#kubectl -n kube-system delete ds kube-proxy
#kubectl -n kube-system delete cm kube-proxy
