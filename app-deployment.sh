#! /bin/bash

CALICO_VERSION=v3.28.1
NGINX_VERSION=v3.6.1

kubectl create -f https://raw.githubusercontent.com/projectcalico/calico/$CALICO_VERSION/manifests/tigera-operator.yaml
kubectl create -f calico

kubectl label nodes jd-kube-03 datacenter=jd
kubectl label nodes jd-kube-02 datacenter=jd
kubectl label nodes linds-kube-01 datacenter=linds
kubectl label nodes linds-kube-02 datacenter=linds

if ! test -f /usr/local/bin/kubectl-calico; then
    curl -L https://github.com/projectcalico/calico/releases/download/$CALICO_VERSION/calicoctl-linux-amd64 -o /usr/local/bin/kubectl-calico && chmod +x /usr/local/bin/kubectl-calico
fi

kubectl apply -f coredns.yml

#argo-cd
kubectl create namespace argocd
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml

if ! test -f /usr/local/bin/argocd; then
    curl -sSL -o argocd-linux-amd64 https://github.com/argoproj/argo-cd/releases/latest/download/argocd-linux-amd64
    sudo install -m 555 argocd-linux-amd64 /usr/local/bin/argocd
    rm argocd-linux-amd64
fi

kubectl apply -f applications

# Reboot ubuntu nodes after provisioning