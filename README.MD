# LINDS-Kubernetes

This is my kubernetes set up that runs on 1 master node (CentOS 9 VM), and 2 worker nodes (CentOS 9 VM)

1. Sonarr
2. Radarr
3. Jackett

## Usage:
``` sh

$ git clone git@github.com:Jayden-Lind/LINDS-Kube.git

$ kubectl apply -f deployment.yml

$ chmod +x nginx-ingress.sh; ./nginx-ingress.sh

```

Ensure the below secret is created and applied for the nginx-ingress to secure the endpoints.

```

---
apiVersion: v1
kind: Secret
metadata:
  name: linds-certificate-secret
  namespace: default
type: kubernetes.io/tls
data:
  tls.crt: xxx
  tls.key: xxx
---

```