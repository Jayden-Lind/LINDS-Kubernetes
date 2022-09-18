#! /bin/bash
curl -skSL https://raw.githubusercontent.com/kubernetes-csi/csi-driver-smb/v1.8.0/deploy/install-driver.sh | bash -s v1.8.0 --
kubectl apply -f https://raw.githubusercontent.com/nginxinc/kubernetes-ingress/main/deployments/common/crds/k8s.nginx.org_virtualserverroutes.yaml
kubectl apply -f https://raw.githubusercontent.com/nginxinc/kubernetes-ingress/main/deployments/common/crds/k8s.nginx.org_virtualservers.yaml
kubectl apply -f https://raw.githubusercontent.com/nginxinc/kubernetes-ingress/main/deployments/common/crds/k8s.nginx.org_transportservers.yaml
kubectl apply -f https://raw.githubusercontent.com/nginxinc/kubernetes-ingress/main/deployments/common/crds/k8s.nginx.org_policies.yaml
kubectl apply -f nginx-config.yml
kubectl apply -f nginx-controller.yml
kubectl apply -f https://raw.githubusercontent.com/metallb/metallb/v0.13.5/config/manifests/metallb-native.yaml
kubectl apply -f deployment.yml
kubectl apply -f tautulli.yml
kubectl apply -f linds-virtualserver.yml
kubectl apply -f duin.yml
kubectl apply -f factorio.yml
kubectl apply -f postgresql.yml
kubectl apply -f unifi.yaml
kubectl apply -f https://raw.githubusercontent.com/kubernetes/dashboard/v2.6.1/aio/deploy/recommended.yaml
kubectl apply -f kube-dashboard.yaml