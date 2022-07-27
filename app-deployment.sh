#! /bin/bash
kubectl apply -f deployment.yml
kubectl apply -f tautulli.yml
kubectl apply -f linds-virtualserver.yml
kubectl apply -f smb-deployment.yml