# LINDS Kubernetes Homelab

This repository contains my personal Kubernetes homelab setup, designed to run on bare metal servers with a focus on networking performance, GitOps, and automation.

## Cluster Overview

* **OS:** Ubuntu 24.04 LTS (control and worker nodes)
* **Networking:** [Calico](https://www.tigera.io/project-calico/) with **eBPF dataplane**, **BGP peering** directly to my VyOS routers
* **Service Load Balancing:** Provided natively by Calico BGP (no MetalLB)
* **Proxy:** Kube-proxy is **disabled**; Calico eBPF handles service load balancing and cluster networking
* **Storage:** Backed by TrueNAS (NFS/iSCSI)
* **GitOps:** [Argo CD](https://argo-cd.readthedocs.io/) provisions and manages all applications

## Bootstrap

After building the cluster with [Ansible](https://github.com/Jayden-Lind/LINDS-Ansible/tree/main/roles/kubernetes), the initial application deployment can be bootstrapped by running:

```bash
./app-deployment.sh
```

This script installs the base Argo CD configuration, which then provisions everything else declaratively.

## Provisioning

* **Argo CD** manages all workloads, applications, monitoring, logging, and supporting services.
* **Exception:** Calico (with eBPF + BGP) is installed and configured manually as part of cluster bootstrap.

## Key Features

* **eBPF dataplane:** Improves performance and observability, removes the need for kube-proxy.
* **BGP integration:** Calico peers with my VyOS routers, advertising cluster services and pod CIDRs for seamless external access.
* **Declarative GitOps:** All apps are managed through Git with Argo CD, enabling full reproducibility and rollback.

---

This setup prioritizes clean GitOps workflows, minimal moving parts, and high-performance networking using Calico.
