# LINDS Kubernetes Homelab

This repository hosts the configuration for my personal Kubernetes homelab. The cluster is provisioned on **Proxmox Virtual Environment** using **Talos Linux**, with a strong focus on high-performance networking, GitOps, and automation.

![Architecture](img/Kubernetes%202026.drawio.png)

## Cluster Overview

* **OS:** Talos Linux (running on Proxmox VE)
* **Networking:** [Cilium](https://cilium.io/) with the **eBPF dataplane**, native routing, and the **BGP control plane** peering with the VyOS router at each site; Hubble for flow visibility
* **Service Load Balancing:** Cilium LB-IPAM (`172.16.1.0/24`) advertised over BGP, no MetalLB
* **Proxy:** Kube-proxy is **disabled**; Cilium's kube-proxy replacement handles service load balancing and cluster networking
* **Storage:** Backed by TrueNAS (NFS/iSCSI)
* **GitOps:** [Argo CD](https://argo-cd.readthedocs.io/) provisions and manages all applications

## Bootstrap

After building the cluster with [Terraform](https://github.com/Jayden-Lind/LINDS-Terraform/blob/main/proxmox/talos.tf), the cluster is hydrated with three `kubectl` commands:

```bash
# 1. Vault bootstrap token for External Secrets (gitignored - not in this repo)
kubectl apply -f linds-secret.yml

# 2. Install Argo CD (pinned version + config baked in via kustomize)
kubectl apply --server-side -k bootstrap/

# 3. Create the root app-of-apps - Argo CD takes over from here
kubectl apply -f applications/root.yaml
```

The [root Application](applications/root.yaml) syncs everything in [`applications/`](applications/), which includes [Argo CD itself](applications/argocd.yaml) (self-managed from [`bootstrap/`](bootstrap/)). Adding a new app is just committing a new `Application` manifest to `applications/` — no manual `kubectl` needed. Argo CD upgrades are done by bumping the pinned version in [`bootstrap/kustomization.yaml`](bootstrap/kustomization.yaml).

## Provisioning

* **Argo CD** manages all workloads, applications, monitoring, logging, and supporting services.
* **Exception:** Cilium (Helm release, BGP peering and the LB IP pool) is managed from [LINDS-Terraform](https://github.com/Jayden-Lind/LINDS-Terraform/tree/main/proxmox) next to the Talos machine configs, because the CNI has to exist before Argo CD can run.

## Key Features

* **eBPF dataplane:** Improves performance and observability, removes the need for kube-proxy.
* **BGP integration:** Cilium peers with my VyOS routers, advertising pod CIDRs, ClusterIPs and LoadBalancer IPs for seamless external access.
* **Declarative GitOps:** All apps are managed through Git with Argo CD, enabling full reproducibility and rollback.
* **mTLS-only ingress:** A dedicated ingress class for publishing services to the internet behind client-certificate auth — see [nginx-ingress-mtls/](nginx-ingress-mtls/README.md).
* **AD-backed SSO:** Keycloak federates users and groups read-only from the `linds.com.au` Active Directory over LDAPS, and fronts the services that speak OIDC/SAML natively — see [keycloak/](keycloak/README.md).

---

This setup prioritizes clean GitOps workflows, minimal moving parts, and high-performance networking using Cilium.
