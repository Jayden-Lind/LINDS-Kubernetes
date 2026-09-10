# JD storage tuning (jd-proxmox-02)

Space and write-efficiency settings on the `VM` pool (`ssd-mixed` in Proxmox),
which backs every `nfs-csi` and `zfs-iscsi` volume in the cluster. The
StorageClass lives in this repo; sanoid (config, gate script, opt-out list)
is managed by LINDS-Ansible's `proxmox` role; the thin-provisioning settings
exist only on the host. Applied 2026-09-10.

## Snapshots: sanoid, with a per-dataset opt-out

sanoid takes a daily snapshot of everything under `VM/truenas-nas` (the NFS
share, MinIO, every zfs-iscsi zvol) and keeps 14. The source of truth is
LINDS-Ansible: `roles/proxmox/templates/sanoid.conf.j2`, the
`proxmox_sanoid_templates` defaults and the `proxmox_sanoid_policies` /
`proxmox_sanoid_optout` inventory vars in `inventory/proxmox.yml`. Edit
those, not `/etc/sanoid/sanoid.conf` — the role overwrites it.

A dataset whose churn makes snapshots both expensive and worthless opts out
through `proxmox_sanoid_optout`, which sets a ZFS user property (the same
thing by hand, effective immediately):

```bash
zfs set au.com.linds:sanoid=off <dataset>     # stop snapshotting it
zfs inherit au.com.linds:sanoid <dataset>     # back to the default policy
```

`/usr/local/sbin/sanoid-snapshot-gate` (`roles/proxmox/files/`) is the
template's `pre_snapshot_script`, with `no_inconsistent_snapshot = yes`: it
exits non-zero for a dataset carrying the property and sanoid skips that
snapshot. An opted-out dataset never gets a snapshot, so every sanoid run
(every 15 minutes) finds its daily due and logs
`WARN: pre_snapshot_script failed, 256` for it — that is the skip, not a
fault. `sanoid --readonly` never runs `pre_snapshot_script`, so a readonly
pass still claims it would snapshot opted-out datasets. The gate fails open
(no target or a zfs error means the snapshot is taken), and it never touches
existing snapshots: destroy those by hand.

Do not replace this with a `[child]` section carrying its own template.
sanoid 2.2.0 walks config sections in Perl hash order and `recursive = yes`
copies every parent key onto each child, so on some runs the parent silently
overwrites the child's settings. The gate script is inherited by every child
instead, which is deterministic.

| Opted out | What | Why |
|---|---|---|
| `VM/truenas-nas/k8s-iscsi/v/pvc-6bc3d715-6306-4c54-a4ca-871de99d36f1` | Prometheus TSDB | Compaction rewrites TSDB blocks every few hours, so 14 dailies pinned 20.9G of deleted blocks — rollback points for data Prometheus expires on its own (14d / 15GB). |
| `VM/truenas-nas/k8s-iscsi/v/pvc-cf4eacc1-da88-451b-92a7-71126abc6559` | Loki WAL / compactor scratch | Chunks live in MinIO; the volume held 3.7G of snapshots for ~20 MB of live data. |

The zvols are named after their PV, so if either PVC is ever recreated, put
the new `pvc-<uid>` in `proxmox_sanoid_optout` (the role reports names it
cannot find rather than creating them).

Grafana is deliberately not opted out: its data is a ~70 MB directory inside
the shared NFS dataset, whose snapshots cost ~250 MB for every app together.

## Thin-provisioned VM disks

`ssd-mixed` has `sparse 1` and every VM zvol `refreservation=none`. The thick
reservations were holding 404G the guests had never written: Proxmox showed
the storage 83% full with the pool 44% allocated. Now that nothing is
reserved, watch real allocation (`zpool list VM`), not Proxmox's percentage
alone.

## TRIM for zfs-iscsi volumes

The `zfs-iscsi` StorageClass mounts ext4 with `discard`, and the driver
config sets LIO `emulate_tpu=1`, so blocks a pod deletes reach the zvol as
SCSI UNMAP and go back to the pool. Without it a zvol only ever grows to its
high-water mark: Prometheus's held 23.2G for 8G of data (6.7G after one
trim), Loki's 3.3G for 20 MB (62 MB after).

Only PVs provisioned since the change inherit the mount option. An older PV
needs `spec.mountOptions: [discard]` patched in (applies on its next mount —
done for the Prometheus and Loki PVs), or a one-off trim from the
democratic-csi node pod on the node where the volume is mounted:

```bash
kubectl exec -n democratic-csi <democratic-csi-iscsi-node-pod> -c csi-driver -- \
  sh -c 'grep <pv-name> /proc/mounts'          # the .../volumes/kubernetes.io~csi/<pv>/mount path
kubectl exec -n democratic-csi <democratic-csi-iscsi-node-pod> -c csi-driver -- \
  fstrim -v <that mount path>
```

A trim only frees blocks no snapshot still references. On a snapshotted
volume the space comes back as those snapshots age out.

## Not done: dedup

`zdb -S VM` (2026-09-10) simulated 1.49x, mostly from the near-identical
Talos node disks. It stayed off: ZFS dedups only data written after it is
enabled, every write and free pays a dedup-table lookup and update (the
opposite of cheap writes), and the pool was never short of physical space —
the reservations above were.

## Limitation: the VM-pool SSDs get no TRIM

The three VM-pool disks report `discard_max_bytes=0` through the Adaptec
Series 8 controller (`zpool status -t VM` says "trim unsupported"), unlike the
NAS-SSD pool's drives on the same controller. ZFS frees space logically, but
the SSDs are never told, so their internal write amplification stays higher.
`autotrim=on` is set and harmless.
