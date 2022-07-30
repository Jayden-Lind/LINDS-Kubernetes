# LINDS-Kubernetes

This is my kubernetes set up that runs on 1 master node (CentOS 9 VM), and 2 worker nodes (CentOS 9 VM)

1. Sonarr
2. Radarr
3. Jackett
4. Tautulli

Kubernetes is installed on the VM's through [LINDS-Puppet](https://github.com/Jayden-Lind/LINDS-Puppet)

## Usage:
``` sh

$ git clone git@github.com:Jayden-Lind/LINDS-Kube.git

$ chmod +x nginx-ingress.sh; ./nginx-ingress.sh

$ curl -skSL https://raw.githubusercontent.com/kubernetes-csi/csi-driver-smb/v1.8.0/deploy/install-driver.sh | bash -s v1.8.0 

$ chmod +x app-deployment.sh; ./app-deployment.sh

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
apiVersion: v1
kind: Secret
metadata:
  name: linds-smb-secret
  namespace: default
type: smb.csi.k8s.io
data:
  username: xxx
  password: xxx
```
