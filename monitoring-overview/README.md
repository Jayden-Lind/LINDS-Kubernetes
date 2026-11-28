# Overview and backups

Two Grafana dashboards in the folder Overview, and the rules that they read.

- **Homelab overview** (uid `overview`): the front page. It shows whether
  both sites are OK and, if not, where to look.
- **Backups & data protection** (uid `backups`): every backup, snapshot and
  replica, with the age of its newest good copy, and the data that has none.

Both use only metrics and logs that exist. Nothing new is scraped.

## Files

| File | What it is |
|---|---|
| `dashboards.py` | Makes both dashboard files. Edit it, then run `python3 monitoring-overview/dashboards.py`. |
| `overview-dashboard.yaml`, `backups-dashboard.yaml` | The dashboards. Generated; do not edit them by hand. |
| `rules.yaml` | Recording rules for the overview's status tiles and alert table, and the Postgres backup alerts. |
| `log-rules.yaml` | Alerts that read logs. Loki's ruler runs them. |
| `tests/rules.test.yaml` | promtool tests for `rules.yaml`. |

## The overview

| Part | What it shows |
|---|---|
| JD, LINDS, Cluster & apps | The worst check of each. A check is 0 (OK), 1 (warning) or 2 (problem). Missing data counts as a problem. |
| Firing alerts | The alerts that fire now, the worst first. Each alert goes to Discord one time, so a problem that stays is here. Notices (info) do not change a site's state. |
| Failing checks | The checks that are not OK, by site. |
| Data protection | The age of the newest good copy of each backup chain. The Backups dashboard has the detail. |
| Connectivity, Compute, Storage, Platform | One line of state for each part. Each panel links to the dashboard with the detail. |

The checks are the recording rule `overview:check:status`:

| Site | Checks |
|---|---|
| `jd` | the router answers, its WAN works, its DNS works, jd-proxmox-02 is up, the JD nodes are Ready, the worst firing alert at JD |
| `linds` | the tunnel, then the same for linds-router-01, linds-proxmox-01 and the LINDS nodes |
| `cluster` | the Kubernetes API, the alert rules run (Watchdog), Alertmanager, Loki, the worst firing alert that is not at one site |

`overview:alert:active_seconds` has one series for each firing alert, with
`site`, `where` and `what`. The site comes from the instance, node or host
name: `jd-*` and 10.0.* are JD, `linds-*`, 10.3.* and 192.168.* are LINDS,
and the rest is `cluster`.

## Alerts

| Alert | Severity | When | Where |
|---|---|---|---|
| `PostgreSQLBaseBackupStale` | warning | No new base backup of linds-postgres for 36 hours. | `rules.yaml` |
| `PostgreSQLBackupMetricsMissing` | warning | The barman-cloud plugin's backup metrics are gone for 2 hours. | `rules.yaml` |
| `StorageSanoidSnapshotsMissing` | warning | sanoid took no daily snapshot of VM/truenas-nas in 26 hours. | `log-rules.yaml` |
| `StorageTrueNasReplicationMissing` | warning | linds-truenas-01 did not pull from jd-proxmox-02 in 26 hours. | `log-rules.yaml` |
| `StorageTrueNasReplicationErrors` | warning | The replication logged ERROR in the last day. | `log-rules.yaml` |
| `WindowsShadowCopiesLost` | warning | Windows deleted or aborted shadow copies in the last day. | `log-rules.yaml` |

The other backup alerts are in `base/monitoring/`: `StorageBackblaze*`
(the weekly Backblaze run) and `PostgreSQL*` (WAL archiving, failed base
backups).

NOTE: The alerts from Loki's ruler are not in Prometheus. They do not show in
the overview's alert table. The Data protection row shows the same state.

## Make the overview the home page

Add this to the `grafana.ini` values in `applications/kube-prometheus.yml`:

```yaml
dashboards:
  default_home_dashboard_path: /tmp/dashboards/Overview/overview.json
```

The dashboard sidecar writes each dashboard to
`/tmp/dashboards/<grafana_folder>/<key>`.

## Test

```bash
yq '.spec' monitoring-overview/rules.yaml > /tmp/overview.rules.yaml
promtool check rules /tmp/overview.rules.yaml
promtool test rules monitoring-overview/tests/rules.test.yaml
```

promtool cannot test LogQL. To test a rule in `log-rules.yaml`, run its
expression in Grafana Explore (data source Loki). Use a shorter range to make
it fire: `[5h]` instead of `[26h]`.

## Limits

- The Backblaze metrics file is on /run on jd-proxmox-02. After a restart of
  the host, it is gone until the next run. The age of the last finished
  backup comes from the last 14 days of Prometheus data.
- DFS Replication, shadow copies and TrueNAS replication have only events in
  their logs. The Backups dashboard's Gaps panel lists what is missing and the
  smallest change that adds it.
