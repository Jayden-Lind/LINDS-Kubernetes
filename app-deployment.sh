#! /bin/bash
kubectl apply -f deployment.yml
kubectl apply -f tautulli.yml
kubectl apply -f linds-virtualserver.yml
kubectl apply -f smb-deployment.yml
curl -skSL https://raw.githubusercontent.com/kubernetes-csi/csi-driver-smb/v1.8.0/deploy/install-driver.sh | bash -s v1.8.0 --
