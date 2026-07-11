# Runbook: arr / zfs-iscsi PVCs fail to mount (pods stuck in ContainerCreating)

Applies to any PVC on the `zfs-iscsi` StorageClass (democratic-csi → LIO/targetcli
on jd-proxmox-02, `10.0.50.246`). First seen 2026-07-11 with the whole `arr`
namespace stuck after a reboot of jd-proxmox-02.

## Symptoms

Pods sit in `ContainerCreating`. `kubectl describe pod` shows one or both of:

```
Warning  FailedAttachVolume  Multi-Attach error for volume "pvc-..." Volume is
         already exclusively attached to one node and can't be attached to another
Warning  FailedMount         MountVolume.MountDevice failed for volume "pvc-..." :
         rpc error: ... unable to attach any iscsi devices
```

The democratic-csi node pod (`kubectl logs -n democratic-csi
democratic-csi-iscsi-node-XXXX -c csi-driver`) logs:

```
hit timeout waiting for device node to appear:
/dev/disk/by-path/ip-10.0.50.246:3260-iscsi-iqn.2026-06.au.com.linds:csi-pvc-...-lun-0
```

## Triage — two different problems that look the same

### 1. Multi-Attach error (usually transient)

`zfs-iscsi` volumes are RWO: they can only attach to one node. When a pod is
rescheduled to a different node, the attach fails until the old node's
`VolumeAttachment` is detached (normally < 1 minute; up to ~6 minutes if the
old node went down uncleanly).

```bash
kubectl get volumeattachment | grep <pvc-uuid>
```

* If it self-resolves (a `SuccessfulAttachVolume` event follows), it was just
  the normal detach lag — no action needed.
* If it persists >6 min and the old node is dead/gone, delete the stale
  attachment so the attach-detach controller can move it:

  ```bash
  kubectl delete volumeattachment <csi-...-id-on-the-OLD-node>
  ```

  Only do this when you are sure no pod on the old node still has the volume
  mounted (RWO + two writers = filesystem corruption).

### 2. `unable to attach any iscsi devices` — LUNs missing on the target (the 2026-07-11 incident)

The iSCSI *login* succeeds but no disk appears, because the LIO target on
jd-proxmox-02 has **no LUN mapped**. Root cause chain:

1. jd-proxmox-02 reboots.
2. `rtslib-fb-targetctl.service` (restores the LIO config from
   `/etc/rtslib-fb-target/saveconfig.json`) runs a few seconds **before** the
   `VM` pool's zvol `/dev` links exist (`zvol_wait` doesn't help — the pool
   itself is imported late, after `zfs-volumes.target` is already reached).
3. `targetctl restore` *silently skips* every block backstore whose device is
   missing ("`not a TYPE_DISK block device, skipped`") **and** their LUN
   mappings ("`Could not find matching StorageObject for LUN 0, skipped`"),
   then exits 0. Result: all `iqn.2026-06.au.com.linds:csi-pvc-*` targets
   exist with `LUNs: 0`.

Confirm on the host:

```bash
ssh root@10.0.50.246
targetcli ls /iscsi          # csi targets show "LUNs: 0"
targetcli ls /backstores     # block: Storage Objects: 0
journalctl -b -u rtslib-fb-targetctl.service   # the "skipped" lines above
```

**Fix** (non-disruptive if `targetcli sessions` shows no open sessions —
which it will, since nothing can mount):

```bash
zfs list -t volume | grep k8s-iscsi   # sanity: zvols still exist
targetctl restore                      # re-restore now that /dev links exist
targetcli ls /iscsi                    # every csi target should show LUNs: 1
```

No Kubernetes-side action needed afterwards: kubelet retries the mount
(backoff up to ~2 min) and the pods come up on their own.

> `targetctl restore` replaces the whole running LIO config with
> saveconfig.json. That's exactly what you want here, but if volumes were
> provisioned *after* the last `saveconfig` they'd be lost from the running
> config — check saveconfig.json's mtime against the newest PVC first.

## Prevention (installed 2026-07-12 on jd-proxmox-02)

* `/usr/local/sbin/wait-lio-backstore-devs.sh` — parses saveconfig.json and
  waits (up to 180 s) for every referenced `/dev/...` backstore device to
  exist.
* `/etc/systemd/system/rtslib-fb-targetctl.service.d/wait-zvols.conf` — runs
  that script as `ExecStartPre=` and orders the unit
  `After=zfs.target zfs-volumes.target`.

Both live only on the host (not in this repo) — **re-create them if
jd-proxmox-02 is ever rebuilt.** Verify after any reboot with:

```bash
journalctl -b -u rtslib-fb-targetctl.service
# want: "all N backstore devices present", and no "skipped" lines
```

Other hardening ideas (not implemented):

* Monitoring: alert when any `iqn...:csi-pvc-*` target has 0 LUNs, or simply
  on `arr` pods stuck in `ContainerCreating` > 5 min.
* democratic-csi can be pointed at a dedicated portal IP + CHAP; unrelated to
  this failure but worth doing eventually.

## Related gotcha: target with no *portal*

A pre-existing target bound to a specific `IP:3260` blocks the default
wildcard `0.0.0.0:3260` bind for newly created targets, which then have **no
portal** — same "login OK but no disk" symptom at provision time. Keep all
targets on wildcard portals (see the 2026-06 arr-suite migration notes).
