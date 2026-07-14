# CloudNativePG — `linds-postgres`

PostgreSQL cluster managed by the CNPG operator, with backups and WAL archiving
to MinIO via the **Barman Cloud plugin** (CNPG-I).

| Component | Where | Version source |
|---|---|---|
| Operator | `applications/postgres-native.yaml` (Helm chart `cloudnative-pg`) | chart `targetRevision` |
| Barman Cloud plugin | `kustomization.yaml` (release manifest URL) | URL tag |
| Postgres image | `postgres-cluster.yaml` `spec.imageName` | pinned tag **and digest** |

## Image pinning (important)

`spec.imageName` is pinned to an exact tag **plus digest**
(e.g. `18.4-standard-trixie@sha256:…`). Never use a floating tag like `:18` —
nodes pull it at different times, so instances end up on different builds. This
bit us once: the primary had pgvector 0.8.1 while the DB catalog was at 0.8.2,
and Immich refused to start.

Also note:

- The plain `ghcr.io/cloudnative-pg/postgresql:18` "system" images are
  **deprecated**. Use the `-standard-` flavour — it includes pgvector, which
  Immich needs (`-minimal-` does not).
- All databases use `LC_COLLATE=C`, so Debian base / glibc jumps
  (bullseye→trixie) are safe for indexes.

**To upgrade Postgres:** find the new tag, resolve its digest, update both in
`postgres-cluster.yaml`, push to master. CNPG rolls replicas first, then does a
switchover (`primaryUpdateMethod: switchover`).

```sh
TOKEN=$(curl -s "https://ghcr.io/token?scope=repository:cloudnative-pg/postgresql:pull" | jq -r .token)
curl -sI -H "Authorization: Bearer $TOKEN" -H "Accept: application/vnd.oci.image.index.v1+json" \
  "https://ghcr.io/v2/cloudnative-pg/postgresql/manifests/<TAG>" | grep -i docker-content-digest
```

## Backups

- **Nightly base backup** (`ScheduledBackup`, midnight) + **continuous WAL
  archiving** (`isWALArchiver: true`) → full **PITR** within the 7-day
  retention window.
- Everything lives in `s3://postgresql-backup/<serverName>/` on MinIO
  (`jd-s3-01.linds.com.au:9000`). The active `serverName` is set **once** on the
  Cluster's plugin config (currently `linds-postgres-restored-4`). Base backups
  and WALs must share one serverName path or restores are impossible — the
  plugin ignores any `serverName` in `ScheduledBackup.pluginConfiguration`, so
  don't set one there.

Check backup health:

```sh
kubectl -n postgresql-linds get backups | tail -3
kubectl -n postgresql-linds get cluster linds-postgres -o yaml | grep -A5 conditions
# WAL archiving state (runs on the primary):
kubectl get --raw "/api/v1/namespaces/postgresql-linds/pods/<primary-pod>:9187/proxy/metrics" \
  | grep cnpg_pg_stat_archiver
```

Prometheus alerts for failed/stale WAL archiving live in
`base/monitoring/alerts.yaml`.

## Rebuilding the cluster from backup (no serverName bump needed)

Historically every rebuild required inventing a new serverName
(`linds-postgres` → `-new` → `-restored-3` → `-restored-4`) because the plugin
refuses to archive WAL into a non-empty path ("Expected empty archive" — a
guard against two clusters writing one archive).

That hack is gone. The Cluster now carries:

- `cnpg.io/skipEmptyWalArchiveCheck: enabled` annotation — both the operator
  and the barman-cloud plugin honour it during recovery, and
- a permanent `bootstrap.recovery` + `externalClusters` block pointing at **its
  own** archive path.

So disaster recovery is simply:

```sh
kubectl -n postgresql-linds delete cluster linds-postgres   # if it still exists
# then let ArgoCD re-apply, or:
kubectl apply -k postgresql/
```

The new cluster restores from the latest backup in its own path, starts a new
timeline, and archives to the same path. WAL filenames embed the timeline ID so
histories don't collide, and the 7-day retention ages out the old timeline.
`ScheduledBackup.immediate: true` takes a fresh base backup as soon as it's
created.

The safety trade-off: the annotation disables the "is this archive really
mine?" check at bootstrap. That's fine while exactly one cluster uses this
path — never point a second live cluster at the same serverName.

For point-in-time recovery instead of latest, add under
`bootstrap.recovery`:

```yaml
      recoveryTarget:
        targetTime: "2026-07-10 03:00:00+10"
```

(Remove it again after the rebuild.)

## Operator / plugin upgrades

- Operator: bump the chart `targetRevision` in
  `applications/postgres-native.yaml`.
- Plugin: bump the release-manifest URL in `kustomization.yaml`. Plugin CRD
  features must match — e.g. `data.compression: lz4` needs plugin ≥ 0.13.
- Known issue ([cloudnative-pg#9107](https://github.com/cloudnative-pg/cloudnative-pg/issues/9107)):
  operator upgrades with the plugin installed have been seen to stall after
  upgrading one standby. If instances stop rolling, check
  `kubectl -n postgresql-linds get cluster` and delete the stuck pod to nudge it.

## Housekeeping

Stale bucket prefixes from the old serverName bumps (`linds-postgres`,
`linds-postgres-new`, `linds-postgres-restored-3`) still hold dead data —
retention only prunes the **active** path. Safe to delete manually once
comfortable:

```sh
mc alias set minio http://jd-s3-01.linds.com.au:9000 <USER> '<PASS>'
mc rb --force minio/postgresql-backup/linds-postgres \
  minio/postgresql-backup/linds-postgres-new \
  minio/postgresql-backup/linds-postgres-restored-3
```
