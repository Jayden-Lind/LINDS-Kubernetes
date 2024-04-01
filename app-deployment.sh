#! /bin/bash

CALICO_VERSION=v3.27.2
NGINX_VERSION=v3.3.1

kubectl create -f https://raw.githubusercontent.com/projectcalico/calico/$CALICO_VERSION/manifests/tigera-operator.yaml
kubectl create -f calico

kubectl label nodes jd-kube-03 datacenter=jd
kubectl label nodes jd-kube-02 datacenter=jd
kubectl label nodes linds-kube-01 datacenter=linds
kubectl label nodes linds-kube-02 datacenter=linds

if ! test -f /usr/local/bin/kubectl-calico; then
    curl -L https://github.com/projectcalico/calico/releases/download/v3.26.3/calicoctl-linux-amd64 -o /usr/local/bin/kubectl-calico && chmod +x /usr/local/bin/kubectl-calico
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

##NGINX
kubectl apply -f https://raw.githubusercontent.com/nginxinc/kubernetes-ingress/$NGINX_VERSION/deployments/common/ns-and-sa.yaml
kubectl apply -f https://raw.githubusercontent.com/nginxinc/kubernetes-ingress/$NGINX_VERSION/deployments/rbac/rbac.yaml
kubectl apply -f https://raw.githubusercontent.com/nginxinc/kubernetes-ingress/$NGINX_VERSION/deployments/rbac/ap-rbac.yaml
kubectl apply -f https://raw.githubusercontent.com/nginxinc/kubernetes-ingress/$NGINX_VERSION/deployments/rbac/apdos-rbac.yaml
kubectl apply -f https://raw.githubusercontent.com/nginxinc/kubernetes-ingress/$NGINX_VERSION/deployments/common/crds/k8s.nginx.org_virtualserverroutes.yaml
kubectl apply -f https://raw.githubusercontent.com/nginxinc/kubernetes-ingress/$NGINX_VERSION/deployments/common/crds/k8s.nginx.org_virtualservers.yaml
kubectl apply -f https://raw.githubusercontent.com/nginxinc/kubernetes-ingress/$NGINX_VERSION/deployments/common/crds/k8s.nginx.org_transportservers.yaml
kubectl apply -f https://raw.githubusercontent.com/nginxinc/kubernetes-ingress/$NGINX_VERSION/deployments/common/crds/k8s.nginx.org_policies.yaml
kubectl apply -f nginx


kubectl apply -f postgresql
kubectl apply -f nfs-provisioner

kubectl apply -f zabbix

kubectl apply -f linds/deploy