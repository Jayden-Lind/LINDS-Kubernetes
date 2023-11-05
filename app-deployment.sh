#! /bin/bash

CALICO_VERSION=v3.26.3
NGINX_VERSION=v3.2.1
METALLB_VERSION=v0.13.12

kubectl create -f https://raw.githubusercontent.com/projectcalico/calico/$CALICO_VERSION/manifests/tigera-operator.yaml
kubectl create -f calico.yml
kubectl apply -f calico-bgp.yml

if ! test -f /usr/local/bin/kubectl-calico; then
    curl -L https://github.com/projectcalico/calico/releases/download/v3.26.3/calicoctl-linux-amd64 -o /usr/local/bin/kubectl-calico && chmod +x /usr/local/bin/kubectl-calico
fi

kubectl apply -f https://raw.githubusercontent.com/metallb/metallb/$METALLB_VERSION/config/manifests/metallb-native.yaml
kubectl apply -f coredns.yml

##NGINX
kubectl apply -f https://raw.githubusercontent.com/nginxinc/kubernetes-ingress/$NGINX_VERSION/deployments/common/ns-and-sa.yaml
kubectl apply -f https://raw.githubusercontent.com/nginxinc/kubernetes-ingress/$NGINX_VERSION/deployments/rbac/rbac.yaml
kubectl apply -f https://raw.githubusercontent.com/nginxinc/kubernetes-ingress/$NGINX_VERSION/deployments/rbac/ap-rbac.yaml
kubectl apply -f https://raw.githubusercontent.com/nginxinc/kubernetes-ingress/$NGINX_VERSION/deployments/rbac/apdos-rbac.yaml
kubectl apply -f https://raw.githubusercontent.com/nginxinc/kubernetes-ingress/$NGINX_VERSION/deployments/common/crds/k8s.nginx.org_virtualserverroutes.yaml
kubectl apply -f https://raw.githubusercontent.com/nginxinc/kubernetes-ingress/$NGINX_VERSION/deployments/common/crds/k8s.nginx.org_virtualservers.yaml
kubectl apply -f https://raw.githubusercontent.com/nginxinc/kubernetes-ingress/$NGINX_VERSION/deployments/common/crds/k8s.nginx.org_transportservers.yaml
kubectl apply -f https://raw.githubusercontent.com/nginxinc/kubernetes-ingress/$NGINX_VERSION/deployments/common/crds/k8s.nginx.org_policies.yaml
kubectl apply -f nginx-config.yml
kubectl apply -f nginx-controller.yml

kubectl apply -f deployment.yml
kubectl apply -f tautulli.yml
kubectl apply -f linds-virtualserver.yml
kubectl apply -f duin.yml
kubectl apply -f factorio.yml
kubectl apply -f postgresql.yml
kubectl apply -f unifi.yaml
kubectl apply -f linds-secret.yml

kubectl apply -f postgresql
kubectl apply -f nfs-provisioner

kubectl apply -f zabbix
