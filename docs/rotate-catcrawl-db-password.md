# Runbook: rotate the `catcrawl` database password

Applies to the `catcrawl` role on `linds-postgres` (namespace `postgresql-linds`),
which the Woolworths, Coles and Aldi crawlers, catcrawl-viewer and the weekly
vacuum job all log in as. Rotate it whenever a copy may have been kept outside
the secret store: once a copy exists somewhere else, rotating is the only thing
that retires it.

## Where the password lives

| Holder | Kubernetes Secret (namespace) | Key | Vault key |
|---|---|---|---|
| The role itself, via CloudNativePG `managed.roles` | `catcrawl-auth` (`postgresql-linds`) | `password` | `linds-keyvault/catcrawl-auth` |
| Woolworths crawler | `catcrawl-env-secret` (`default`) | `DB_PASSWORD` | `linds-keyvault/catcrawl-env-secret` |
| Coles and Aldi crawlers, catcrawl-viewer, catcrawl-vacuum | `catcrawl-coles-env-secret` (`default`) | `DB_PASSWORD` | `linds-keyvault/catcrawl-coles-env-secret` |
| A developer machine, for running a crawler by hand | a local env file, never committed | `DB_PASSWORD` | — |

All three ExternalSecrets (`external-secrets/secrets.yaml`) use
`refreshPolicy: OnChange`. That means **changing Vault changes nothing in the
cluster by itself**: each ExternalSecret has to be told to sync. Skipping that
step leaves the Secrets holding the old password, which works right up until
the role is changed, and then nothing can log in.

## When

Not on a Wednesday. The crawls start at 02:00 UTC and may run until 13:00 UTC,
and the vacuum runs at 18:00 UTC. A crawl that loses its login halfway through
records a partial failure. Check that nothing is running:

```sh
kubectl get jobs -n default | grep catcrawl
```

## Steps

1. **Generate** a password with no characters that need escaping in a
   connection string:

   ```sh
   openssl rand -base64 48 | tr -d '/+=' | cut -c1-40
   ```

2. **Write it to all three Vault keys** in the table — `password` in
   `catcrawl-auth`, and `DB_PASSWORD` in the two env secrets — the way you
   normally edit `linds-keyvault`. Change only that key in each, leaving the
   others as they are.

3. **Sync the role's secret first.** CloudNativePG then runs `ALTER ROLE` for
   you:

   ```sh
   kubectl annotate externalsecret -n postgresql-linds catcrawl-auth \
     force-sync="$(date +%s)" --overwrite
   kubectl get cluster -n postgresql-linds linds-postgres \
     -o jsonpath='{.status.managedRolesStatus}'; echo
   ```

   From this point the old password is refused for **new** connections.
   Connections already open stay open, which is why the viewer keeps working
   until step 5.

4. **Sync the two workload secrets:**

   ```sh
   for s in catcrawl-env-secret catcrawl-coles-env-secret; do
     kubectl annotate externalsecret -n default "$s" force-sync="$(date +%s)" --overwrite
   done
   ```

5. **Restart the one long-lived holder of connections.** The CronJobs read
   the Secret when their pod starts, so their next scheduled run picks up the
   new password without anything being done.

   ```sh
   kubectl rollout restart -n default deploy/catcrawl-viewer
   kubectl rollout status  -n default deploy/catcrawl-viewer
   ```

6. **Update any local copy** a developer machine keeps for running the
   crawlers by hand, and make sure no repository tracks that file. A tracked
   copy, updated and committed, would leak the new password in exactly the way
   a rotation is meant to undo.

## Verify

Log in with each workload Secret's own copy of the password, because a Secret
that missed step 4 would otherwise go unnoticed until its crawl fails. This
pod uses the database's own image and is deleted as soon as it exits:

```sh
for s in catcrawl-env-secret catcrawl-coles-env-secret; do
kubectl apply -n default -f - <<POD
apiVersion: v1
kind: Pod
metadata: { name: catcrawl-login-check-${s%-env-secret} }
spec:
  restartPolicy: Never
  containers:
    - name: psql
      image: ghcr.io/cloudnative-pg/postgresql:18.4-standard-trixie@sha256:802cb43a4d482acf1037b418e421c865b16959ba22e07f16fc003e06cb21084c
      command: [psql, --no-psqlrc, --dbname=catcrawl, --command=SELECT current_user]
      env:
        - { name: PGHOST,     valueFrom: { secretKeyRef: { name: $s, key: DB_HOST } } }
        - { name: PGPORT,     valueFrom: { secretKeyRef: { name: $s, key: DB_PORT } } }
        - { name: PGUSER,     valueFrom: { secretKeyRef: { name: $s, key: DB_USER } } }
        - { name: PGPASSWORD, valueFrom: { secretKeyRef: { name: $s, key: DB_PASSWORD } } }
POD
done
sleep 20
kubectl logs -n default catcrawl-login-check-catcrawl        # expect: catcrawl
kubectl logs -n default catcrawl-login-check-catcrawl-coles  # expect: catcrawl
kubectl delete pod -n default catcrawl-login-check-catcrawl catcrawl-login-check-catcrawl-coles
```

Then confirm the viewer is serving (`CatcrawlViewerDown` quiet, and its logs
free of `password authentication failed`), and watch the next Wednesday's
crawl alerts.

## If a login fails

- `password authentication failed` from a workload: its Secret missed step 4,
  or its pod predates it. Repeat step 4 for that Secret and restart the pod.
- `managedRolesStatus` reports an error: the `catcrawl-auth` Secret probably
  lost its `username` key or type. CloudNativePG needs a
  `kubernetes.io/basic-auth` Secret with both `username` and `password`.
- As a stopgap only, putting the old password back in all three Vault keys
  and repeating steps 3–5 restores the previous state. The old password is in
  a git history, so this is not a place to stay.

## Afterwards

If the old password was ever committed anywhere, removing it from that
history (`git filter-repo`, a force-push, a re-clone everywhere) becomes
cosmetic once the password no longer works. It is worth doing only for a
repository that might one day be made public.
