#! /bin/bash

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

kubectl apply -f applications

kubectl create -k base

# Reboot ubuntu nodes after provisioning