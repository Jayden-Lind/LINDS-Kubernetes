#! /bin/bash
kubectl create -f https://raw.githubusercontent.com/projectcalico/calico/v3.24.1/manifests/tigera-operator.yaml
kubectl apply -f calico.yml

NGINX_VERSION=v2.4.0

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

kubectl apply -f https://raw.githubusercontent.com/metallb/metallb/v0.13.6/config/manifests/metallb-native.yaml
kubectl apply -f deployment.yml
kubectl apply -f tautulli.yml
kubectl apply -f linds-virtualserver.yml
kubectl apply -f duin.yml
kubectl apply -f factorio.yml
kubectl apply -f postgresql.yml
kubectl apply -f unifi.yaml
kubectl apply -f metallb.yml
kubectl apply -f linds-secret.yml

kubectl apply -f postgresql
kubectl apply -f nfs-provisioner