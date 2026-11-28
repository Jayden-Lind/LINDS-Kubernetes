# Availability probes

blackbox_exporter tests each service from the outside in, the way a client
uses it: an HTTP request to an app's health URL, a TLS handshake, a TCP
connect, a DNS question. The alerts go to Discord through the existing
Alertmanager. The **Availability** dashboard in Grafana (folder
Infrastructure, uid `availability`) shows what is down now, what was down, how
slow each probe is, and which certificates expire first.

## Two vantage points

There is one exporter at each site: `blackbox-exporter-jd` and
`blackbox-exporter-linds`, two replicas each, each held at its site by a
nodeSelector. Prometheus asks both to probe every target. So a target at one
site is also probed from the other, across the tunnel, the way that site's
clients reach it. The label `vantage` (`jd` or `linds`) says which exporter
probed.

- **Down** is down from every site: the max over `vantage` is 0. That is
  `ProbeTargetDown`.
- **One site** is down from one site and up from the other: the path between
  the sites, or one exporter. That is `ProbeFailsFromOneSite`, one alert per
  site however many targets.

## Labels, for other dashboards

Every probe series is
`probe_success{job="blackbox", target, kind, site, vantage, module, instance}`,
plus `cert` on TLS targets, `hostname` on targets probed by address, and
`alert="no"` on the dashboard-only ones.

| Label | Values |
|---|---|
| `target` | a short name, unique in the job: the app (`grafana`), or `<host> <check>` (`jd-dc-01 ldaps`, `jd-router-01 dns ad`) |
| `kind` | `web`, `public`, `identity`, `dns`, `storage`, `hypervisor`, `network`, `platform` |
| `site` | where the target is: `jd` or `linds` |
| `vantage` | which exporter probed it: `jd` or `linds` |

Each target has **two** series, one for each vantage point. To count or list
targets, take the max over `vantage` first, or use the recording rule
`target:probe_success:max`, which is exactly that (one series per target, 1
when it answers from at least one site):

```promql
count(target:probe_success:max == 0)          # targets down now
avg_over_time(target:probe_success:max[7d])  # uptime per target
```

`up{job="blackbox"}` is the exception: its `site` is the site of the
**exporter**, and the target's site is in `target_site`. Prometheus is at JD,
so when the tunnel is down it cannot scrape the LINDS exporter, and
PrometheusTargetDown fires for each of its targets. With `site="linds"` on
those, Alertmanager holds them back while `RouterTunnelDown` fires, as for the
other LINDS targets. The docstring of `targets.py` has the details.

`job="mtls-gate"` is separate on purpose. See "The mTLS gate" below.

## Targets

Made by `python3 monitoring-probes/targets.py --markdown`.

| Target | Kind | Site | Probed | Healthy when | Alert |
|---|---|---|---|---|---|
| argocd | web | jd | `https://argocd.linds.com.au/healthz` (http_200) | GET /healthz answers 200 (argocd-server) | ProbeTargetDown, warning |
| bazarr | web | linds | `https://bazarr.linds.com.au/api/system/ping` (http_200) | GET /api/system/ping answers 200 | ProbeTargetDown, warning |
| catcrawl | web | jd | `https://catcrawl.linds.com.au/healthz` (http_200) | GET /healthz answers 200 | ProbeTargetDown, warning |
| flaresolverr | web | linds | `https://flaresolverr.linds.com.au/health` (http_200) | GET /health answers 200 | ProbeTargetDown, warning |
| grafana | web | jd | `https://grafana.linds.com.au/api/health` (http_200) | GET /api/health answers 200 (Grafana and its database) | ProbeTargetDown, warning |
| home-assistant | web | jd | `https://home.linds.com.au/manifest.json` (http_200) | GET /manifest.json answers 200 (Home Assistant's own web server) | ProbeTargetDown, warning |
| hubble-ui | web | jd | `https://hubble.linds.com.au/` (http_200) | GET / answers 200 | ProbeTargetDown, warning |
| immich | web | jd | `https://photos.linds.com.au/api/server/ping` (http_200) | GET /api/server/ping answers 200 | ProbeTargetDown, warning |
| jackett | web | linds | `https://jackett.linds.com.au/health` (http_200) | GET /health answers 200 | ProbeTargetDown, warning |
| maintainerr | web | linds | `https://maintainerr.linds.com.au/api/app/status` (http_200) | GET /api/app/status answers 200 | ProbeTargetDown, warning |
| radarr | web | linds | `https://radarr.linds.com.au/ping` (http_200) | GET /ping answers 200 | ProbeTargetDown, warning |
| sonarr | web | linds | `https://sonarr.linds.com.au/ping` (http_200) | GET /ping answers 200 | ProbeTargetDown, warning |
| stirling-pdf | web | jd | `https://pdf.linds.com.au/api/v1/info/status` (http_200) | GET /api/v1/info/status answers 200 | ProbeTargetDown, warning |
| tautulli | web | linds | `https://tautulli.linds.com.au/status` (http_200) | GET /status answers 200 | ProbeTargetDown, warning |
| train-roulette | web | jd | `https://trainroulette.linds.com.au/healthz` (http_200) | GET /healthz answers 200 | ProbeTargetDown, warning |
| home public | public | jd | `172.16.1.12:443` (tls) | the mTLS ingress completes a TLS handshake for home.linds.com.au with a valid linds-CA certificate | ProbeTargetDown, warning |
| minecraft | public | jd | `172.16.1.13:25565` (minecraft_status) | the server answers a Server List Ping with its status | ProbeTargetDown, warning |
| photos public | public | jd | `172.16.1.12:443` (tls) | the mTLS ingress completes a TLS handshake for photos.linds.com.au with a valid linds-CA certificate | ProbeTargetDown, warning |
| plex-jd | public | jd | `http://172.16.1.50:32400/identity` (http_200) | GET /identity on the Plex LoadBalancer (forwarded port 32400) answers 200 | ProbeTargetDown, warning |
| plex-linds | public | linds | `http://10.3.1.20:32400/identity` (http_200) | GET /identity on linds-plex-01 (port 32400, forwarded by linds-router-01) answers 200 | ProbeTargetDown, warning |
| radarr public | public | jd | `172.16.1.12:443` (tls) | the mTLS ingress completes a TLS handshake for radarr.linds.com.au with a valid linds-CA certificate | ProbeTargetDown, warning |
| sonarr public | public | jd | `172.16.1.12:443` (tls) | the mTLS ingress completes a TLS handshake for sonarr.linds.com.au with a valid linds-CA certificate | ProbeTargetDown, warning |
| home public | public | jd | `172.16.1.12:443` (mtls_gate_home) | REFUSED is healthy: the mTLS ingress closes the connection to a request for home.linds.com.au without a client certificate (probe_success 0, probe_failed_due_to_regex 1) | MtlsGateAcceptsAnonymous |
| photos public | public | jd | `172.16.1.12:443` (mtls_gate_photos) | REFUSED is healthy: the mTLS ingress closes the connection to a request for photos.linds.com.au without a client certificate (probe_success 0, probe_failed_due_to_regex 1) | MtlsGateAcceptsAnonymous |
| radarr public | public | jd | `172.16.1.12:443` (mtls_gate_radarr) | REFUSED is healthy: the mTLS ingress closes the connection to a request for radarr.linds.com.au without a client certificate (probe_success 0, probe_failed_due_to_regex 1) | MtlsGateAcceptsAnonymous |
| sonarr public | public | jd | `172.16.1.12:443` (mtls_gate_sonarr) | REFUSED is healthy: the mTLS ingress closes the connection to a request for sonarr.linds.com.au without a client certificate (probe_success 0, probe_failed_due_to_regex 1) | MtlsGateAcceptsAnonymous |
| jd-dc-01 kerberos | identity | jd | `10.0.50.200:88` (tcp) | TCP port 88 (Kerberos) accepts a connection | ProbeTargetDown, critical |
| jd-dc-01 ldap | identity | jd | `10.0.50.200:389` (tcp) | TCP port 389 (LDAP) accepts a connection | ProbeTargetDown, critical |
| jd-dc-01 ldaps | identity | jd | `10.0.50.200:636` (tls) | LDAPS on port 636 completes a TLS handshake with a valid certificate for jd-dc-01.linds.com.au | ProbeTargetDown, critical |
| jd-dc-01 smb | identity | jd | `10.0.50.200:445` (tcp) | TCP port 445 (SMB: SYSVOL and NETLOGON; on linds-dc also the LINDS NAS share) accepts a connection | ProbeTargetDown, critical |
| keycloak | identity | jd | `https://keycloak.linds.com.au/realms/linds/.well-known/openid-configuration` (http_200) | the linds realm's OpenID configuration answers 200 (what every Keycloak sign-in starts with) | ProbeTargetDown, critical |
| linds-dc kerberos | identity | linds | `10.3.1.200:88` (tcp) | TCP port 88 (Kerberos) accepts a connection | ProbeTargetDown, critical |
| linds-dc ldap | identity | linds | `10.3.1.200:389` (tcp) | TCP port 389 (LDAP) accepts a connection | ProbeTargetDown, critical |
| linds-dc ldaps | identity | linds | `10.3.1.200:636` (tls) | LDAPS on port 636 completes a TLS handshake with a valid certificate for linds-dc.linds.com.au | ProbeTargetDown, critical |
| linds-dc smb | identity | linds | `10.3.1.200:445` (tcp) | TCP port 445 (SMB: SYSVOL and NETLOGON; on linds-dc also the LINDS NAS share) accepts a connection | ProbeTargetDown, critical |
| linds-dc2 kerberos | identity | linds | `10.3.1.201:88` (tcp) | TCP port 88 (Kerberos) accepts a connection | ProbeTargetDown, critical |
| linds-dc2 ldap | identity | linds | `10.3.1.201:389` (tcp) | TCP port 389 (LDAP) accepts a connection | ProbeTargetDown, critical |
| linds-dc2 ldaps | identity | linds | `10.3.1.201:636` (tls) | LDAPS on port 636 completes a TLS handshake with a valid certificate for linds-dc2.linds.com.au | ProbeTargetDown, critical |
| linds-dc2 smb | identity | linds | `10.3.1.201:445` (tcp) | TCP port 445 (SMB: SYSVOL and NETLOGON; on linds-dc also the LINDS NAS share) accepts a connection | ProbeTargetDown, critical |
| coredns cluster | dns | jd | `10.96.0.10` (dns_cluster) | answers kubernetes.default.svc.cluster.local with an A record | ProbeTargetDown, critical |
| coredns internet | dns | jd | `10.96.0.10` (dns_internet) | answers github.com with at least one A record (forwarded to jd-router-01) | ProbeTargetDown, critical |
| jd-dc-01 dns ad | dns | jd | `10.0.50.200` (dns_ad) | answers the SRV query _ldap._tcp.dc._msdcs.linds.com.au with at least one record | ProbeTargetDown, critical |
| jd-dc-01 dns internet | dns | jd | `10.0.50.200` (dns_internet) | answers github.com with at least one A record | ProbeTargetDown, critical |
| jd-router-01 dns ad | dns | jd | `10.0.53.1` (dns_ad) | answers the SRV query _ldap._tcp.dc._msdcs.linds.com.au with at least one record | ProbeTargetDown, critical |
| jd-router-01 dns internet | dns | jd | `10.0.53.1` (dns_internet) | answers github.com with at least one A record | ProbeTargetDown, critical |
| linds-dc dns ad | dns | linds | `10.3.1.200` (dns_ad) | answers the SRV query _ldap._tcp.dc._msdcs.linds.com.au with at least one record | ProbeTargetDown, critical |
| linds-dc dns internet | dns | linds | `10.3.1.200` (dns_internet) | answers github.com with at least one A record | ProbeTargetDown, critical |
| linds-dc2 dns ad | dns | linds | `10.3.1.201` (dns_ad) | answers the SRV query _ldap._tcp.dc._msdcs.linds.com.au with at least one record | ProbeTargetDown, critical |
| linds-dc2 dns internet | dns | linds | `10.3.1.201` (dns_internet) | answers github.com with at least one A record | ProbeTargetDown, critical |
| linds-router-01 dns ad | dns | linds | `10.3.1.1` (dns_ad) | answers the SRV query _ldap._tcp.dc._msdcs.linds.com.au with at least one record | ProbeTargetDown, critical |
| linds-router-01 dns internet | dns | linds | `10.3.1.1` (dns_internet) | answers github.com with at least one A record | ProbeTargetDown, critical |
| jd-fs-01 smb | storage | jd | `jd-fs-01.linds.com.au:445` (tcp) | TCP port 445 (SMB) accepts a connection: the JD NAS share and the Immich and photo volumes | ProbeTargetDown, warning |
| jd-s3-01 | storage | jd | `http://jd-s3-01.linds.com.au:9000/health` (http_200) | versitygw's GET /health answers 200 (Terraform state, CNPG backups, Loki chunks) | ProbeTargetDown, warning |
| jd-truenas-01 nfs | storage | jd | `jd-truenas-01.linds.com.au:2049` (tcp) | TCP port 2049 (NFS) accepts a connection: jd-proxmox-02's own NFS export, which StorageClass nfs-csi uses | ProbeTargetDown, warning |
| linds-truenas-01 https | storage | linds | `https://10.3.1.50/ui/` (http_200) | the TrueNAS web UI answers 200 with its device certificate | ProbeTargetDown, warning |
| linds-truenas-01 nfs | storage | linds | `linds-truenas-01.linds.com.au:2049` (tcp) | TCP port 2049 (NFS) accepts a connection: the LINDS media share | ProbeTargetDown, warning |
| jd-proxmox-02 bmc | hypervisor | jd | `10.0.50.240:443` (tls) | the XCC completes a TLS handshake with its device certificate | dashboard only |
| jd-proxmox-02 https | hypervisor | jd | `https://10.0.50.246:8006/` (http_200) | the Proxmox web UI answers 200 with its device certificate | ProbeTargetDown, warning |
| linds-proxmox-01 bmc | hypervisor | linds | `192.168.6.240:443` (tls) | the iDRAC completes a TLS handshake with its device certificate | dashboard only |
| linds-proxmox-01 https | hypervisor | linds | `https://192.168.6.205:8006/` (http_200) | the Proxmox web UI answers 200 with its device certificate | ProbeTargetDown, warning |
| jd-unifi-01 | network | jd | `10.0.52.7:443` (tls) | the UniFi console completes a TLS handshake with its device certificate | ProbeTargetDown, warning |
| linds-switch-02 | network | linds | `10.0.80.3:443` (tls) | the EdgeOS web UI completes a TLS handshake with its device certificate | dashboard only |
| kubernetes-api | platform | jd | `https://10.0.53.200:6443/readyz` (http_kube_api) | GET /readyz answers 200: the API server and etcd are ready | ProbeTargetDown, critical |
| vault | platform | jd | `https://vault.linds.com.au/v1/sys/health` (http_200) | GET /v1/sys/health answers 200: initialised, unsealed and active (503 is sealed) | ProbeTargetDown, critical |

The arr apps are pinned to LINDS. argocd-server, stirling-pdf, hubble-ui and
train-roulette are not pinned, so they move between sites; their `site` says
`jd`.

### Not probed

| What | Why |
|---|---|
| Factorio | Its game port is UDP, which blackbox cannot test. Its only TCP port is RCON, and the server logs every RCON connection ("New RCON connection"): about 2,900 lines a day. KubePodNotReady watches the pod. |
| Mumble | It logs two lines for every connection. It is not a game server. |
| iSCSI on jd-proxmox-02 | A connect that does not log in writes two kernel lines on the host ("iSCSI Login negotiation failed") each time. |
| Valheim | Retired (replicas 0). |
| claude.linds.com.au | An orphan: the namespace has a Service and an Ingress and no workload, so the ingress answers 502. |
| The routers' SSH, BGP and NTP | sshd and FRR log a connection that does not finish. `router-metrics.yaml` watches the routers. |

## The mTLS gate

The public ingress (`nginx-mtls`, 172.16.1.12) must refuse a request that has
no client certificate. It completes the TLS handshake and then closes the
connection without an answer (`return 444`, server-snippets in
`applications/nginx-ingress-mtls.yaml`). The job `mtls-gate` sends that
request for each public name. For it the good result is a **failed** probe:

| probe_success | probe_failed_due_to_regex | Meaning |
|---|---|---|
| 0 | 1 | Refused: the gate works. |
| 1 | – | **Open**: an answer came back without a certificate. `MtlsGateAcceptsAnonymous` fires. |
| 0 | 0 | Not tested: no TCP or TLS connection. The `<name> public` probes of job `blackbox` report that. |

These run every 15 minutes, from JD only. blackbox logs each failed probe as
two ERROR lines, and no flag turns that off. So the JD exporter's log has
eight ERROR lines every 15 minutes ("Regexp did not match", "Probe failed"
for `mtls_gate_*`). That is the gate working.

## Network policies

Minecraft, Plex and the mTLS ingress accept connections from `world` only
(their CiliumNetworkPolicies). A probe from a pod is not `world`: Cilium sends
a pod's connection to a LoadBalancer address straight to a backend pod, so the
backend sees the pod's own identity and drops it. `network-policies.yaml`
adds a policy in each of the three namespaces. Each lets the blackbox pods
open the port the internet already reaches, and nothing else. Cilium adds up
the policies of an endpoint, so the workload's own policy does not change.

The same socket load balancing means the public probes test the end of the
chain only: the LoadBalancer address and the backend. Cloudflare and the
routers' port forwards are not in the path.

## Files

| File | What it is |
|---|---|
| `blackbox-exporter.yaml` | The two exporters, their Services, PodDisruptionBudgets and service account |
| `blackbox.yml` | The modules (the ConfigMap `blackbox-exporter-config`; a change restarts the exporters) |
| `targets.py` | The targets. Edit it, then run `python3 monitoring-probes/targets.py > monitoring-probes/scrape-configs.yaml` |
| `scrape-configs.yaml` | The ScrapeConfigs. Generated by `targets.py`; do not edit it by hand. |
| `network-policies.yaml` | The three policies above |
| `rules.yaml`, `tests/rules.test.yaml` | The alerts, the recording rule, and their unit tests |
| `dashboard.py` | Makes `dashboard.yaml`. Edit it, then run `python3 monitoring-probes/dashboard.py > monitoring-probes/dashboard.yaml` |
| `dashboard.yaml` | The Grafana dashboard. Generated by `dashboard.py`; do not edit it by hand. |

The image tag is in `kustomization.yaml` (`images:`). Renovate's kustomize
manager updates it.

## Alerts

| Alert | Severity | When |
|---|---|---|
| `ProbeTargetDown` | critical for `dns`, `identity`, `platform`; warning for the rest | A target answers from no site for 10 minutes. Not for `alert="no"` targets. Held back while another alert already says it: `RouterDNSDown` for a router's DNS, `KubeAPIDown`/PrometheusTargetDown for the API server, `CatcrawlViewerDown` for catcrawl, PrometheusTargetDown (job `pve`) for a Proxmox web UI. |
| `ProbeFailsFromOneSite` | warning | Targets fail from one site and answer from the other for 15 minutes. One alert per site; `$value` is how many. |
| `ProbeCertificateExpiring` | warning under 21 days, critical under 7 | A certificate that cert-manager does not issue: the device certificates, the DCs' (AD CS), the API server's (Talos). cert-manager's own are `CertificateExpiringSoon`. |
| `MtlsGateAcceptsAnonymous` | critical | The public ingress answered a request without a client certificate. |
| `BlackboxProbesMissing` | warning | Prometheus has no probe targets for a vantage point or a job for 15 minutes (a ScrapeConfig deleted or not loaded). |
| `BlackboxProbesAllFailing` | critical | Every probe fails from both sites for 10 minutes: the probers, not the targets. `ProbeTargetDown` is held back meanwhile. |

An exporter that does not answer its scrapes is `PrometheusTargetDown`
(`base/monitoring/alerts.yaml`), for each of its targets.

`base/monitoring/alertmanager-config.yaml` routes them by the default route:
each is sent once when it starts and once when it resolves. Two of its
inhibit rules matter here:

- While `RouterTunnelDown` fires for the LINDS tunnel, alerts with
  `site="linds"` are held back: the LINDS targets, and the LINDS exporter's
  own scrapes.
- A critical alert holds back the warnings of the same name. While a critical
  `ProbeTargetDown` fires (DNS, identity, platform), the warning ones wait:
  when DNS or AD fails, every app by name fails with it, and only the cause is
  sent. An unrelated warning waits too. It is sent when the critical
  resolves, if it still fires then.

Test the rules after a change:

```bash
yq '.spec' monitoring-probes/rules.yaml > /tmp/probes.rules.yaml
promtool check rules /tmp/probes.rules.yaml
promtool test rules monitoring-probes/tests/rules.test.yaml
```

## See what a probe sees

```bash
kubectl get --raw '/api/v1/namespaces/monitoring/services/http:blackbox-exporter-jd:9115/proxy/probe?debug=true&module=http_200&target=https://grafana.linds.com.au/api/health'
```

Use `blackbox-exporter-linds` for the view from LINDS. For a target probed by
address, add `&hostname=<its name>`. Each alert's description has the command
for its target.

## Add a target

Add a `Probe` to `PROBES` in `targets.py` with its name, kind, site, module,
address and what "healthy" means. Run `targets.py` again (both commands
above), and paste the `--markdown` table into this file. A new kind of check
may need a module in `blackbox.yml`. A target behind a policy that admits
`world` only needs a policy in `network-policies.yaml`.

## Limits

- **The API server probe uses a token.** The cluster refuses anonymous
  requests, so `http_kube_api` sends the token of the service account
  `blackbox-exporter`. That account has no RBAC of its own, and only that
  module sends the token.
- **DNS questions show in Suricata.** Each question to a router is a Suricata
  DNS event in Loki, so the DNS probes run every 120 s. That is about 6,000
  events a day for the two routers: `github.com` and
  `_ldap._tcp.dc._msdcs.linds.com.au` from the node addresses.
- **CoreDNS's interim hosts entry for jd-fs-01** (kube-system ConfigMap
  `coredns`) answers `jd-fs-01.linds.com.au` before AD does, so the
  `jd-fs-01 smb` probe cannot see a lost AD record for it.
