# LINDS Kubernetes Homelab

This repository hosts the configuration for my personal Kubernetes homelab. The cluster is provisioned on **Proxmox Virtual Environment** using **Talos Linux**, with a strong focus on high-performance networking, GitOps, and automation.

![Architecture](img/Kubernetes%202026.drawio.png)

## Cluster Overview

* **OS:** Talos Linux (running on Proxmox VE)
* **Networking:** [Calico](https://www.tigera.io/project-calico/) with **eBPF dataplane**, **BGP peering** directly to my VyOS routers
* **Service Load Balancing:** Provided natively by Calico BGP (no MetalLB)
* **Proxy:** Kube-proxy is **disabled**; Calico eBPF handles service load balancing and cluster networking
* **Storage:** Backed by TrueNAS (NFS/iSCSI)
* **GitOps:** [Argo CD](https://argo-cd.readthedocs.io/) provisions and manages all applications

## Bootstrap

After building the cluster with [Terraform](https://github.com/Jayden-Lind/LINDS-Terraform/blob/main/proxmox/talos.tf), the initial application deployment can be bootstrapped by running:

```bash
./app-deployment.sh
```

This script initializes **Argo CD**, applies the root application manifests, and bootstraps the cluster services. Once executed, Argo CD takes over to hydrate the cluster with the remaining applications.

## Provisioning

* **Argo CD** manages all workloads, applications, monitoring, logging, and supporting services.
* **Exception:** Calico CNI is installed via Talos configuration, while BGP peering and IP pools are configured declaratively via GitOps.

## Key Features

* **eBPF dataplane:** Improves performance and observability, removes the need for kube-proxy.
* **BGP integration:** Calico peers with my VyOS routers, advertising cluster services and pod CIDRs for seamless external access.
* **Declarative GitOps:** All apps are managed through Git with Argo CD, enabling full reproducibility and rollback.

---

This setup prioritizes clean GitOps workflows, minimal moving parts, and high-performance networking using Calico.
