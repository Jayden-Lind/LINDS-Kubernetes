# CloudNativePG – Bootstrap from MinIO Backups (Barman Cloud plugin)

This doc shows how to **rebuild** the `linds-postgres` cluster **from backups in MinIO** using the **Barman Cloud plugin**. It also explains the common _“Expected empty archive”_ error and how to avoid it.

## TL;DR

1. Make sure **cert-manager**, **CNPG operator**, and the **Barman Cloud plugin** are installed in `postgresql-linds`.  
2. Ensure the MinIO creds Secret exists: `cnpg-s3-creds` (ACCESS_KEY_ID/SECRET_ACCESS_KEY).  
3. Apply (or keep) the `ObjectStore` named `minio-store`.  
4. **Restore** by creating a `Cluster` that:
   - reads backups from the **old** path (e.g., `serverName: linds-postgres`) via `externalClusters`.
   - registers the plugin on the **Cluster** with **`isBackupExecutor: true`** and a **new** `serverName` (e.g., `linds-postgres-new`) to avoid WAL path collisions.
5. (Optional) Add a `ScheduledBackup` so new full backups run nightly.

---

## Prereqs

- Namespace: `postgresql-linds`
- Secrets:
  - `cnpg-s3-creds` → MinIO keys
  - `app-postgres-superuser` → desired `postgres` user/password for the new cluster
- Backups already present in MinIO under bucket `postgresql-backup`, server name **`linds-postgres`** (your original cluster name).

---

## ObjectStore (MinIO)

    apiVersion: barmancloud.cnpg.io/v1
    kind: ObjectStore
    metadata:
      name: minio-store
      namespace: postgresql-linds
    spec:
      configuration:
        destinationPath: s3://postgresql-backup
        endpointURL: http://jd-truenas-01.linds.com.au:9000
        s3ForcePathStyle: true
        s3Region: us-east-1
        s3Credentials:
          accessKeyId:
            name: cnpg-s3-creds
            key: ACCESS_KEY_ID
          secretAccessKey:
            name: cnpg-s3-creds
            key: SECRET_ACCESS_KEY
      retentionPolicy: 7d

> `s3ForcePathStyle: true` is recommended for MinIO.

---

## Restore the cluster (from the latest backup)

> **Key idea:** read **from** the old path `linds-postgres`, but write future backups **to a new path** `linds-postgres-new`. This avoids the _“Expected empty archive”_ safety check.

    apiVersion: postgresql.cnpg.io/v1
    kind: Cluster
    metadata:
      name: linds-postgres
      namespace: postgresql-linds
    spec:
      instances: 2
      imageName: ghcr.io/cloudnative-pg/postgresql:17
      enableSuperuserAccess: true
      superuserSecret:
        name: app-postgres-superuser
      storage:
        size: 50Gi
        storageClass: nfs-client
      monitoring:
        enablePodMonitor: true
      affinity:
        nodeSelector:
          datacenter: "jd"
        enablePodAntiAffinity: true

      # Register the plugin for BACKUPS ONLY (no WAL archiving)
      plugins:
        - name: barman-cloud.cloudnative-pg.io
          isBackupExecutor: true
          parameters:
            barmanObjectName: minio-store
            serverName: linds-postgres-new    # NEW path for future backups

      # Bootstrap this cluster FROM existing backups
      bootstrap:
        recovery:
          source: backup-truenas

      externalClusters:
        - name: backup-truenas
          plugin:
            name: barman-cloud.cloudnative-pg.io
            parameters:
              barmanObjectName: minio-store
              serverName: linds-postgres      # OLD path where backups already exist
              # Optional (restore to specific backup/time):
              # backupID: "LATEST"
              # recoveryTarget:
              #   targetTime: "YYYY-MM-DD HH:MM:SS+00"

Apply & watch:

    kubectl apply -f objectstore.yaml
    kubectl apply -f cluster-restore.yaml

    kubectl -n postgresql-linds get pods,jobs
    kubectl -n postgresql-linds describe cluster linds-postgres | sed -n '/Events:/,$p'
    kubectl -n postgresql-linds logs job/linds-postgres-1-full-recovery --all-containers -f

When recovery finishes, the primary will start and replicas will follow.

---

## Nightly full backups (no WAL archiving)

    apiVersion: postgresql.cnpg.io/v1
    kind: ScheduledBackup
    metadata:
      name: linds-postgres-nightly
      namespace: postgresql-linds
    spec:
      cluster:
        name: linds-postgres
      schedule: "0 18 * * *"   # 18:00 UTC ≈ 04:00 AEST
      immediate: true
      backupOwnerReference: self
      method: plugin
      pluginConfiguration:
        name: barman-cloud.cloudnative-pg.io
        parameters:
          barmanObjectName: minio-store
          serverName: linds-postgres-new     # keep new backups separate from the old path

> We’re using **backup-only** mode (no PITR). You can still restore to the **latest full** backup later by setting `backupID: "LATEST"` in a future recovery.

---

## Common error & fix

**Error:**  
`barman-cloud-check-wal-archive ... ERROR: WAL archive check failed ... Expected empty archive`

**Meaning:** The plugin refuses to write into a path that already contains WAL/backups (prevents mixing timelines).

**Fix:** Set a **different `serverName`** on the Cluster’s plugin (e.g. `linds-postgres-new`) so the cluster writes to a **new, empty** archive path. Keep the **source** path under `externalClusters` pointing at the **old** server name (`linds-postgres`) for reading backups.

---

## Useful commands

    # Check plugin & cert-manager are healthy
    kubectl -n postgresql-linds get deploy | egrep 'cloud|barman'
    kubectl get crds | grep cert-manager.io

    # List backup CRs
    kubectl -n postgresql-linds get backups
    kubectl -n postgresql-linds describe backup <name>

    # Inspect MinIO bucket layout (from any host with mc):
    mc alias set minio http://jd-truenas-01.linds.com.au:9000 <USER> '<PASS>'
    mc tree --depth 2 minio/postgresql-backup

---

## Notes

- If you later want **PITR**, add WAL archiving by setting the plugin on the Cluster with `isWALArchiver: true` and keep its `serverName` on a **fresh** path.
- The `Database` CRs are optional: backups already contain your DBs/roles. Keep them only if you want declarative creation in case of fresh init.

