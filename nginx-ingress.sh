#! /bin/bash
kubectl apply -f https://raw.githubusercontent.com/nginxinc/kubernetes-ingress/main/deployments/common/crds/k8s.nginx.org_virtualserverroutes.yaml
kubectl apply -f https://raw.githubusercontent.com/nginxinc/kubernetes-ingress/main/deployments/common/crds/k8s.nginx.org_virtualservers.yaml
kubectl apply -f https://raw.githubusercontent.com/nginxinc/kubernetes-ingress/main/deployments/common/crds/k8s.nginx.org_transportservers.yaml
kubectl apply -f https://raw.githubusercontent.com/nginxinc/kubernetes-ingress/main/deployments/common/crds/k8s.nginx.org_policies.yaml
kubectl apply -f nginx-config.yml
kubectl apply -f nginx-controller.yml

