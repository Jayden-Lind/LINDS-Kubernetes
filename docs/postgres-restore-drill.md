# Runbook: restore drill for `linds-postgres`

How to prove the nightly backups of the CNPG cluster are actually restorable,
**without touching the live cluster**. Applies to `linds-postgres` in
`postgresql-linds` (`postgresql/postgres-cluster.yaml`), whose backups go to
MinIO through the Barman Cloud plugin.

The backups have existed since the cluster did and have **never been
restore-tested**. That matters more than usual right now, because the crawler
databases have taken a lot of destructive traffic lately — a 57k-row prune, a
store-id relabel across 36k products and 401k observations
(`catcrawl-coles` migration `20260908000001`), and a manual `VACUUM FULL`. One
nightly backup has also failed outright (2026-09-06).

## What actually exists

| Thing | Value |
|---|---|
| Cluster | `linds-postgres`, namespace `postgresql-linds`, 2 instances, PG 18.4 |
| Object store CR | `ObjectStore/minio-store` in `postgresql-linds` |
| Bucket | `s3://postgresql-backup` on `http://jd-s3-01.linds.com.au:9000` |
| Archive path (`serverName`) | **`linds-postgres-restored-4`** |
| Nightly base backup | `ScheduledBackup/linds-postgres-nightly`, `0 0 0 * * *` → **00:00 UTC daily** (six fields: the leading `0` is seconds) |
| WAL archiving | continuous, `isWALArchiver: "true"` on the Cluster's plugin config |
| Retention | **`7d`** |
| S3 credentials | `Secret/cnpg-s3-creds` in `postgresql-linds` (from Vault via `external-secrets/secrets.yaml`) |
| Crawler databases | `catcrawl` (Woolworths), `catcrawl-coles`, `catcrawl-aldi` — all owned by the `catcrawl` role |

### The 7-day retention is the headline constraint

`retentionPolicy: 7d` means there is no copy of anything older than a week.
The destructive work listed above (the prune, the store-id relabel, the
`VACUUM FULL`) all happened well outside that window, so **it cannot be undone
from backup — those changes are permanent.** A drill can only ever answer "can
I get back to roughly last night", never "can I get back to before the
relabel". If you are about to do something you might want to reverse, take an
out-of-band dump first; do not assume the nightly backup covers you.

## Step 1 — verify a backup exists and is complete

Read the `Backup` objects. Do **not** trust the Cluster status or the CNPG
collector metrics for this — with `method: plugin` they are simply not
populated, and reading them as "no backups" or "no recovery point" is wrong:

```sh
kubectl -n postgresql-linds get cluster linds-postgres \
  -o jsonpath='{.status.lastSuccessfulBackup}{"|"}{.status.firstRecoverabilityPoint}{"\n"}'
# observed: "|"  — both empty, always, even with seven good backups on disk

kubectl get --raw "/api/v1/namespaces/postgresql-linds/pods/linds-postgres-1:9187/proxy/metrics" \
  | grep -E '^cnpg_collector_(first_recoverability_point|last_available_backup_timestamp)'
# observed: both 0 — hence no alert can be built on them
```

What to read instead:

```sh
kubectl -n postgresql-linds get backups --sort-by=.metadata.creationTimestamp
```

A healthy listing is one `completed` row per night for the retention window.
Anything in `failed` is a real gap — the 2026-09-06 row shows what that looks
like (`rpc error: code = Unknown desc = exit status 1`, `startedAt: null`, so
it never got as far as starting).

Then confirm the newest one is genuinely finished, and note the WAL range it
needs:

```sh
B=$(kubectl -n postgresql-linds get backups --sort-by=.metadata.creationTimestamp \
      -o jsonpath='{.items[-1].metadata.name}')
kubectl -n postgresql-linds get backup "$B" -o json | jq '{
  phase:.status.phase, startedAt:.status.startedAt, stoppedAt:.status.stoppedAt,
  backupId:.status.backupId, beginWal:.status.beginWal, endWal:.status.endWal,
  timeline:.status.pluginMetadata.timeline }'
```

`phase: completed` **and a non-null `stoppedAt`** together mean the base backup
closed properly. A recent good one looks like `startedAt 00:00:00Z` /
`stoppedAt 00:02:23Z` — around two and a half minutes.

A base backup is useless without the WAL that follows it, so check archiving is
current too:

```sh
kubectl get --raw "/api/v1/namespaces/postgresql-linds/pods/linds-postgres-1:9187/proxy/metrics" \
  | grep -E '^cnpg_pg_stat_archiver_(seconds_since_last_archival|failed_count|last_failed_time)'
```

`seconds_since_last_archival` should be seconds-to-minutes, not hours. The
`PostgreSQLWALArchivingFailing` / `PostgreSQLWALArchivingStale` alerts in
`base/monitoring/alerts.yaml` cover the ongoing case; this is the point check.

Finally, look in the bucket, which is the only real source of truth — the
`Backup` objects are Kubernetes objects and can be gone while the data is fine,
or present while the upload was truncated:

```sh
mc alias set minio http://jd-s3-01.linds.com.au:9000 <USER> '<PASS>'
mc ls   minio/postgresql-backup/linds-postgres-restored-4/
mc ls   minio/postgresql-backup/linds-postgres-restored-4/base/
mc du   minio/postgresql-backup/linds-postgres-restored-4/base/
mc ls   minio/postgresql-backup/linds-postgres-restored-4/wals/ | tail
```

Expect one `base/` entry per retained nightly backup, each a non-trivial size,
and `wals/` continuing past the newest backup's `endWal`. Ignore the stale
prefixes from the old serverName bumps (`linds-postgres`,
`linds-postgres-new`, `linds-postgres-restored-3`) — see the housekeeping
section of `postgresql/README.md`.

## Step 2 — restore into a scratch cluster

> Read "How not to destroy the live database" below **before** running any of
> this.

The drill restores into its **own namespace**, `postgresql-drill`, with its own
Cluster name. That is the whole safety design: every command carries
`-n postgresql-drill`, the scratch services are
`catcrawl-drill-rw.postgresql-drill.svc` so nothing configured for
`linds-postgres-rw.postgresql-linds.svc` can reach them, and teardown is one
namespace delete that cannot possibly remove anything live.

`ObjectStore` is a namespaced CR, so the drill namespace needs its own copy of
it plus the S3 credentials. Copy the secret through a pipe — **never** redirect
it to a file, this repo is public and the working tree is next to it:

```sh
kubectl create namespace postgresql-drill

kubectl -n postgresql-linds get secret cnpg-s3-creds -o json \
  | jq 'del(.metadata.namespace,.metadata.uid,.metadata.resourceVersion,
            .metadata.creationTimestamp,.metadata.ownerReferences,
            .metadata.annotations,.metadata.labels)' \
  | kubectl -n postgresql-drill create -f -
```

Then apply the scratch cluster. This manifest deliberately lives **here, in a
doc**, and not in `postgresql/` — anything under that path is owned by the
`cloudnativepg-operator` Argo CD Application, which has `automated.selfHeal`
and `prune: true`:

```sh
cat <<'EOF' | kubectl apply -f -
apiVersion: barmancloud.cnpg.io/v1
kind: ObjectStore
metadata:
  name: minio-store
  namespace: postgresql-drill
spec:
  configuration:
    destinationPath: s3://postgresql-backup
    endpointURL: http://jd-s3-01.linds.com.au:9000
    s3Credentials:
      accessKeyId:
        name: cnpg-s3-creds
        key: ACCESS_KEY_ID
      secretAccessKey:
        name: cnpg-s3-creds
        key: SECRET_ACCESS_KEY
---
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: catcrawl-drill
  namespace: postgresql-drill
spec:
  # One instance, and far less memory than the live cluster's 8Gi x 2 — this
  # has to fit on a jd worker alongside everything already running there.
  instances: 1
  imageName: ghcr.io/cloudnative-pg/postgresql:18.4-standard-trixie@sha256:802cb43a4d482acf1037b418e421c865b16959ba22e07f16fc003e06cb21084c
  resources:
    requests:
      memory: "2Gi"
      cpu: "250m"
    limits:
      memory: "2Gi"
  storage:
    size: 50Gi
    storageClass: zfs-iscsi
  affinity:
    nodeSelector:
      datacenter: "jd"

  # NOTHING HERE ARCHIVES. There is no `spec.plugins` block on purpose: the
  # plugin appears only under externalClusters, which is read-only. Adding it
  # to spec.plugins would make this second cluster write WAL into
  # linds-postgres-restored-4 alongside the live one and destroy the live
  # PITR archive. The live cluster carries
  # cnpg.io/skipEmptyWalArchiveCheck: enabled, so the guard that would
  # normally refuse that is switched off — this is on you, not the operator.
  #
  # No `managed.roles` either: the restore brings the real roles and their
  # passwords with it, so catcrawl already exists in the restored data.
  bootstrap:
    recovery:
      source: live-archive
      # For "can I get back to last night", leave this out and take the latest
      # backup. To land on a specific moment, uncomment — but remember the
      # 7-day retention, so the target must be inside the last week:
      # recoveryTarget:
      #   targetTime: "2026-09-20 03:00:00+00"
  externalClusters:
    - name: live-archive
      plugin:
        name: barman-cloud.cloudnative-pg.io
        parameters:
          barmanObjectName: minio-store
          serverName: linds-postgres-restored-4
EOF
```

Watch it come up. A restore of this cluster is minutes; the base backup is
small and the WAL replay is short:

```sh
kubectl -n postgresql-drill get cluster,pods -w
kubectl -n postgresql-drill logs -l cnpg.io/cluster=catcrawl-drill -c postgres --tail=50
```

Before going further, **prove it is not archiving**:

```sh
# Must be empty:
kubectl -n postgresql-drill get cluster catcrawl-drill -o json | jq '.spec.plugins'
# Must show archive_mode with no barman archive_command target, and the
# instance must not appear as a WAL archiver:
kubectl -n postgresql-drill get cluster catcrawl-drill -o yaml | grep -i -A3 archiv
```

and independently, watch the live archive's object count across the drill
(`mc ls --recursive ... | wc -l` before and after) — it should only grow by the
live cluster's own segments.

## Step 3 — validate the restored data

Query through the instance pod: inside the container the `postgres` OS user
connects over the local socket, so no password is needed and no credential
leaves the cluster.

```sh
DRILL="kubectl -n postgresql-drill exec -i catcrawl-drill-1 -c postgres -- psql -qAt"
LIVE="kubectl -n postgresql-linds exec -i linds-postgres-1 -c postgres -- psql -qAt"
```

First, the databases are all there and non-empty:

```sh
$DRILL -d postgres -c \
  "SELECT datname, pg_size_pretty(pg_database_size(datname))
     FROM pg_database WHERE datname LIKE 'catcrawl%' ORDER BY 1;"
```

Then the real check: run the **same** query against the scratch copy and the
live cluster and compare. Don't validate against remembered row counts — they
move every week. The live side of this is a read-only `SELECT`; it changes
nothing.

```sh
# The tables the crawlers actually write: `products` (PK store_id, product_id)
# and `product_observations` (the price history).
for db in catcrawl catcrawl-coles catcrawl-aldi; do
  q="SELECT '$db',
            (SELECT count(*) FROM products),
            (SELECT count(DISTINCT store_id) FROM products),
            (SELECT max(last_seen_at) FROM products),
            (SELECT count(*) FROM product_observations),
            (SELECT max(observed_at) FROM product_observations);"
  echo "drill: $($DRILL -d "$db" -c "$q")"
  echo "live : $($LIVE  -d "$db" -c "$q")"
done
```

How to read the result:

- **Row counts** should match live almost exactly. `products` only changes when
  a crawl runs, and the crawls are weekly (Wednesdays), so unless the drill
  straddles a Wednesday the two should be identical. `product_observations`
  only ever grows, so drill ≤ live; a drill copy with *more* rows than live
  means you are querying the wrong thing.
- **Store coverage**: each crawler captures a home store plus the 16 regional
  stores from `CAT_EXTRA_STORES`, except Aldi, which prices nationally and has
  one. `count(DISTINCT store_id)` dropping is how a partial restore would show
  up first. Cross-check the home stores are present — Coles `7674`, Woolworths
  `3161` (the values in `catcrawl-viewer-databases`):
  ```sh
  $DRILL -d catcrawl-coles -c "SELECT store_id, count(*) FROM products GROUP BY 1 ORDER BY 2 DESC;"
  ```
- **Freshness**: `max(last_seen_at)` and `max(observed_at)` must be *before*
  the backup's `stoppedAt` and within the last week or so. A timestamp far in
  the past means an older backup than you asked for; a timestamp after
  `stoppedAt` means you are not looking at the restored cluster at all.
- Check the post-relabel state survived, since that migration is now outside
  the retention window and this is the only copy of it there will ever be —
  Coles history should be labelled `7674`, with no `584` left:
  ```sh
  $DRILL -d catcrawl-coles -c "SELECT count(*) FROM products WHERE store_id = '584';"            # expect 0
  $DRILL -d catcrawl-coles -c "SELECT count(*) FROM product_observations WHERE store_id = '584';" # expect 0
  ```
- Confirm the schema arrived whole, not just the rows:
  ```sh
  $DRILL -d catcrawl-coles -c "\d+ products"
  $DRILL -d catcrawl -c "SELECT count(*) FROM pg_indexes WHERE tablename IN ('products','product_observations');"
  ```

Record the numbers in the drill log at the bottom of this file. The point of
the record is that next time you can tell "restore is broken" from "the
catalogue grew".

## Step 4 — tear the scratch copy down

```sh
kubectl delete namespace postgresql-drill
```

That is the only destructive command in this runbook, and it names a namespace
that contains nothing live.

**Then clean up the storage, because the namespace delete does not.**
`zfs-iscsi` has `reclaimPolicy: Retain`, so the PV survives as `Released` and
the zvol behind it stays allocated on `jd-proxmox-02` forever:

```sh
kubectl get pv | grep postgresql-drill      # expect Released
kubectl delete pv <name>                    # then the zvol, on jd-proxmox-02
```

A 50Gi zvol left behind per drill will quietly eat the `VM` pool — see
`docs/jd-storage-tuning.md`. Check `zfs list -o name,used,refer` on
`jd-proxmox-02` afterwards and remove the orphan.

Last, confirm the live side is untouched:

```sh
kubectl -n postgresql-linds get cluster linds-postgres   # "Cluster in healthy state", 2/2
kubectl get --raw "/api/v1/namespaces/postgresql-linds/pods/linds-postgres-1:9187/proxy/metrics" \
  | grep -E '^cnpg_pg_stat_archiver_(failed_count|seconds_since_last_archival)'
```

`failed_count` must not have moved during the drill.

## How not to destroy the live database

Every one of these is a plausible next step that ruins the live cluster. They
are listed in rough order of how easy they are to do by accident.

1. **Do not restore by editing `postgresql/postgres-cluster.yaml`.** It is
   tempting: the file already contains a working `bootstrap.recovery` block, so
   adding a `recoveryTarget` there looks like the natural way to restore. But
   that path is synced to the **live** cluster by Argo CD with `selfHeal: true`
   and `prune: true`. `bootstrap` is only read at creation, so the edit appears
   to do nothing — right up until the cluster is recreated for any reason, at
   which point the live database silently comes up at an old point in time.
   The rebuild procedure in `postgresql/README.md` is a **disaster-recovery**
   procedure, not a drill: it deletes the live cluster. Never run it to test a
   backup.
2. **Never give the scratch cluster a `spec.plugins` entry**, and never set
   `isWALArchiver: "true"` on it. Two clusters archiving into one `serverName`
   corrupts the archive for both, and the live cluster's
   `cnpg.io/skipEmptyWalArchiveCheck: enabled` annotation disables the exact
   check that would otherwise refuse it. This is the single most dangerous line
   in the scratch manifest.
3. **Never run the drill in the `postgresql-linds` namespace.** A separate
   namespace is what makes a mistyped Cluster name harmless; in the live
   namespace, one wrong `metadata.name` is a live cluster rebuild.
4. **Never point an application at the scratch cluster, or the scratch
   credentials at the live one.** The restored database contains the real
   `catcrawl` role with the real password, so a crawler or `catcrawl-viewer`
   pointed at `catcrawl-drill-rw` will happily write to it — and a `DB_HOST`
   left over from a drill will happily write crawl data into a cluster you are
   about to delete.
5. **Keep writes out of the drill entirely.** Queries against the scratch copy
   are `SELECT`s. If you need to test a destructive migration against restored
   data, that is a different exercise; do it knowing the scratch copy is the
   thing being destroyed.
6. **Reads against live are fine; nothing else is.** The comparison queries in
   step 3 are read-only by construction. Do not "fix" a discrepancy by writing
   to live.

## How often to drill

- **Quarterly**, at minimum. An untested backup is a hypothesis.
- **Before** any destructive change to the crawler databases — a prune, a
  relabel, a `VACUUM FULL`, a migration that rewrites rows. The 7-day retention
  means the window to notice a bad backup is one week; if the drill fails after
  the change, there is nothing to go back to.
- **After any `failed` nightly backup.** One failure is tolerable, but nothing
  currently *alerts* on it: the CNPG collector's backup metrics read `0` on
  this cluster (see step 1), so `PostgreSQLWALArchivingFailing` and
  `PostgreSQLWALArchivingStale` are the only automated coverage, and neither
  fires for a single failed base backup while WAL archiving keeps working. The
  2026-09-06 failure went unnoticed for exactly that reason. Until that gap is
  closed, `kubectl -n postgresql-linds get backups` is a manual check worth
  doing.
- **After any operator or Barman Cloud plugin upgrade** — both change the
  restore path, and a restore that worked on plugin 0.13 is not evidence about
  0.15.

## Drill log

Nothing here yet — the first entry will be the first drill. Append a line per
drill: date, backup ID restored, the row counts from step 3, whether anything
had to be worked around.

| Date | Backup ID | `catcrawl` products / observations | `catcrawl-coles` | `catcrawl-aldi` | Notes |
|---|---|---|---|---|---|
| | | | | | |
