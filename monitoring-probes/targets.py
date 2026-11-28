"""Generate the probe targets (scrape-configs.yaml) from the table below.

    python3 monitoring-probes/targets.py > monitoring-probes/scrape-configs.yaml
    python3 monitoring-probes/targets.py --markdown   # the target table in README.md

Edit this file, not scrape-configs.yaml. Only the standard library is used.

Every probe in job blackbox runs from both vantage points: the blackbox
exporter at JD and the one at LINDS (blackbox-exporter.yaml). So each target
has two series, told apart by the label `vantage`, and a probe from the other
site also tests the tunnel. Rules and panels that ask "is it up" take the
max over `vantage` (up from somewhere); target:probe_success:max in
rules.yaml is that. The labels of every probe_* series:

  job      blackbox (or mtls-gate, see below)
  target   a short name, unique within the job: the app, or "<host> <check>"
  kind     web, public, identity, dns, storage, hypervisor, network, platform
  site     jd or linds: where the target is (not where it was probed from)
  vantage  jd or linds: which exporter probed it
  module   the module in blackbox.yml
  instance the address probed
  cert     on TLS targets only: who issues the certificate (cert-manager,
           ad-cs, device, talos). ProbeCertificateExpiring leaves out
           cert-manager, which CertificateExpiringSoon already watches.
  alert    "no" on the few targets that only the dashboard shows (their
           device has its own alert, see below); absent everywhere else
  hostname on a target given by address: the TLS server name (and HTTP
           Host) to ask for, sent to the exporter as ?hostname=

`up{job="blackbox"}` is different on purpose: its `site` is the site of the
EXPORTER (equal to `vantage`), and the target's site is in `target_site`.
Prometheus is at JD, so when the tunnel is down it cannot scrape the LINDS
exporter at all, and PrometheusTargetDown fires for every one of its targets.
With site="linds" on those, Alertmanager holds them back while
RouterTunnelDown fires (base/monitoring/alertmanager-config.yaml), as it does
for the other LINDS targets. metricRelabelings put the target's own site back
on the probe_* series.

job mtls-gate holds the four checks that the public ingress refuses a
request without a client certificate. For them a failed probe is the good
result (blackbox.yml, "The mTLS gate"), so they are kept out of job blackbox,
where probe_success 1 always means healthy. They run from JD only, every 15
minutes (GROUPS below says why).
"""
import json
import sys
from dataclasses import dataclass

EXPORTERS = {
    "jd": "blackbox-exporter-jd.monitoring.svc:9115",
    "linds": "blackbox-exporter-linds.monitoring.svc:9115",
}


@dataclass
class Probe:
    target: str
    kind: str
    site: str
    module: str
    address: str
    healthy: str               # what "up" means, for the comment and the README
    hostname: str = ""         # TLS server name (and Host header) for an address
    cert: str = ""             # who issues the certificate, on TLS targets
    alert: bool = True         # False: dashboard only
    job: str = "blackbox"
    group: str = "main"        # main (every 60 s) or dns (every 120 s)


def web(target, url, healthy, site="jd"):
    """An app behind the internal ingress (nginx, 172.16.1.11), probed by name like a browser."""
    return Probe(target, "web", site, "http_200", url, healthy, cert="cert-manager")


def dns(target, resolver, site, module, healthy, alert=True):
    return Probe(target, "dns", site, module, resolver, healthy, alert=alert, group="dns")


PROBES = [
    # --- Web apps: each app's own health URL, through the internal ingress --
    # Probed by name, so a missing DNS record fails too. site is where the
    # app's pods run: the arr apps are pinned to LINDS (datacenter: linds),
    # the rest to JD or not pinned (argocd-server, stirling-pdf, hubble-ui
    # and train-roulette float; site says jd for them).
    web("argocd", "https://argocd.linds.com.au/healthz", "GET /healthz answers 200 (argocd-server)"),
    web("bazarr", "https://bazarr.linds.com.au/api/system/ping", "GET /api/system/ping answers 200", "linds"),
    web("flaresolverr", "https://flaresolverr.linds.com.au/health", "GET /health answers 200", "linds"),
    web("jackett", "https://jackett.linds.com.au/health", "GET /health answers 200", "linds"),
    web("maintainerr", "https://maintainerr.linds.com.au/api/app/status", "GET /api/app/status answers 200", "linds"),
    web("radarr", "https://radarr.linds.com.au/ping", "GET /ping answers 200", "linds"),
    web("sonarr", "https://sonarr.linds.com.au/ping", "GET /ping answers 200", "linds"),
    web("tautulli", "https://tautulli.linds.com.au/status", "GET /status answers 200", "linds"),
    # CatcrawlViewerDown (base/monitoring/alerts.yaml) already reports the
    # viewer's pod; rules.yaml holds this probe's alert back while it fires.
    web("catcrawl", "https://catcrawl.linds.com.au/healthz", "GET /healthz answers 200"),
    web("stirling-pdf", "https://pdf.linds.com.au/api/v1/info/status", "GET /api/v1/info/status answers 200"),
    web("train-roulette", "https://trainroulette.linds.com.au/healthz", "GET /healthz answers 200"),
    web("home-assistant", "https://home.linds.com.au/manifest.json", "GET /manifest.json answers 200 (Home Assistant's own web server)"),
    web("immich", "https://photos.linds.com.au/api/server/ping", "GET /api/server/ping answers 200"),
    web("hubble-ui", "https://hubble.linds.com.au/", "GET / answers 200"),
    web("grafana", "https://grafana.linds.com.au/api/health", "GET /api/health answers 200 (Grafana and its database)"),

    # --- Public endpoints: what the internet reaches through jd-router-01 ---
    # The probes cannot come in from the internet, so they test the end of
    # the chain: the LoadBalancer address the router forwards to, with the
    # public name. Cloudflare and the router's forward are not in the path.
    # In the cluster, Cilium sends a pod's connection to a LoadBalancer
    # address straight to a backend pod, so these need the policies in
    # network-policies.yaml.
    Probe("home public", "public", "jd", "tls", "172.16.1.12:443",
          "the mTLS ingress completes a TLS handshake for home.linds.com.au with a valid linds-CA certificate",
          hostname="home.linds.com.au", cert="cert-manager"),
    Probe("photos public", "public", "jd", "tls", "172.16.1.12:443",
          "the mTLS ingress completes a TLS handshake for photos.linds.com.au with a valid linds-CA certificate",
          hostname="photos.linds.com.au", cert="cert-manager"),
    Probe("radarr public", "public", "jd", "tls", "172.16.1.12:443",
          "the mTLS ingress completes a TLS handshake for radarr.linds.com.au with a valid linds-CA certificate",
          hostname="radarr.linds.com.au", cert="cert-manager"),
    Probe("sonarr public", "public", "jd", "tls", "172.16.1.12:443",
          "the mTLS ingress completes a TLS handshake for sonarr.linds.com.au with a valid linds-CA certificate",
          hostname="sonarr.linds.com.au", cert="cert-manager"),
    Probe("plex-jd", "public", "jd", "http_200", "http://172.16.1.50:32400/identity",
          "GET /identity on the Plex LoadBalancer (forwarded port 32400) answers 200"),
    Probe("plex-linds", "public", "linds", "http_200", "http://10.3.1.20:32400/identity",
          "GET /identity on linds-plex-01 (port 32400, forwarded by linds-router-01) answers 200"),
    Probe("minecraft", "public", "jd", "minecraft_status", "172.16.1.13:25565",
          "the server answers a Server List Ping with its status"),

    # --- Identity: the three domain controllers and Keycloak ----------------
    # By address, so these do not depend on DNS (the dns probes test that).
    # LDAPS gives the expiry of each DC's own certificate (AD CS
    # auto-enrolment, not cert-manager).
    *[p for dc, ip, site in (("jd-dc-01", "10.0.50.200", "jd"), ("linds-dc", "10.3.1.200", "linds"),
                             ("linds-dc2", "10.3.1.201", "linds")) for p in (
        Probe(f"{dc} kerberos", "identity", site, "tcp", f"{ip}:88", "TCP port 88 (Kerberos) accepts a connection"),
        Probe(f"{dc} ldap", "identity", site, "tcp", f"{ip}:389", "TCP port 389 (LDAP) accepts a connection"),
        Probe(f"{dc} ldaps", "identity", site, "tls", f"{ip}:636",
              f"LDAPS on port 636 completes a TLS handshake with a valid certificate for {dc}.linds.com.au",
              hostname=f"{dc}.linds.com.au", cert="ad-cs"),
        Probe(f"{dc} smb", "identity", site, "tcp", f"{ip}:445",
              "TCP port 445 (SMB: SYSVOL and NETLOGON; on linds-dc also the LINDS NAS share) accepts a connection"),
    )],
    Probe("keycloak", "identity", "jd", "http_200",
          "https://keycloak.linds.com.au/realms/linds/.well-known/openid-configuration",
          "the linds realm's OpenID configuration answers 200 (what every Keycloak sign-in starts with)",
          cert="cert-manager"),

    # --- DNS: every resolver, for an AD name and an internet name ----------
    # Every 120 s, not 60: each question to a router is also a Suricata DNS
    # event in Loki. The routers' own resolvers are 10.0.53.1 and 10.3.1.1,
    # the addresses on the node VLANs (CoreDNS forwards to 10.0.53.1). When
    # Unbound itself is down, RouterDNSDown says so and rules.yaml holds
    # these two back.
    *[p for name, ip, site in (("jd-router-01", "10.0.53.1", "jd"), ("linds-router-01", "10.3.1.1", "linds"),
                               ("jd-dc-01", "10.0.50.200", "jd"), ("linds-dc", "10.3.1.200", "linds"),
                               ("linds-dc2", "10.3.1.201", "linds")) for p in (
        dns(f"{name} dns ad", ip, site, "dns_ad", "answers the SRV query _ldap._tcp.dc._msdcs.linds.com.au with at least one record"),
        dns(f"{name} dns internet", ip, site, "dns_internet", "answers github.com with at least one A record"),
    )],
    # The cluster's own DNS (the kube-dns Service), which every pod uses.
    dns("coredns cluster", "10.96.0.10", "jd", "dns_cluster", "answers kubernetes.default.svc.cluster.local with an A record"),
    dns("coredns internet", "10.96.0.10", "jd", "dns_internet", "answers github.com with at least one A record (forwarded to jd-router-01)"),

    # --- Storage -------------------------------------------------------------
    # By the names the cluster mounts them with (StorageClass nfs-csi, the
    # SMB PersistentVolumes, CNPG and Loki's S3), so a lost DNS record fails
    # here as it would for a new mount.
    Probe("jd-fs-01 smb", "storage", "jd", "tcp", "jd-fs-01.linds.com.au:445",
          "TCP port 445 (SMB) accepts a connection: the JD NAS share and the Immich and photo volumes"),
    Probe("jd-truenas-01 nfs", "storage", "jd", "tcp", "jd-truenas-01.linds.com.au:2049",
          "TCP port 2049 (NFS) accepts a connection: jd-proxmox-02's own NFS export, which StorageClass nfs-csi uses"),
    Probe("linds-truenas-01 nfs", "storage", "linds", "tcp", "linds-truenas-01.linds.com.au:2049",
          "TCP port 2049 (NFS) accepts a connection: the LINDS media share"),
    Probe("linds-truenas-01 https", "storage", "linds", "http_200", "https://10.3.1.50/ui/",
          "the TrueNAS web UI answers 200 with its device certificate", cert="device"),
    Probe("jd-s3-01", "storage", "jd", "http_200", "http://jd-s3-01.linds.com.au:9000/health",
          "versitygw's GET /health answers 200 (Terraform state, CNPG backups, Loki chunks)"),

    # --- Hypervisors -----------------------------------------------------------
    # The Proxmox web UI is also the API that pve-exporter reads: while that
    # scrape fails, PrometheusTargetDown says so and rules.yaml holds these
    # back. The BMCs only show here (their certificates matter, their web UI
    # less): HardwareBmcUnreachable watches the XCC over IPMI and
    # PrometheusTargetDown the iDRAC over SNMP.
    Probe("jd-proxmox-02 https", "hypervisor", "jd", "http_200", "https://10.0.50.246:8006/",
          "the Proxmox web UI answers 200 with its device certificate", cert="device"),
    Probe("linds-proxmox-01 https", "hypervisor", "linds", "http_200", "https://192.168.6.205:8006/",
          "the Proxmox web UI answers 200 with its device certificate", cert="device"),
    Probe("jd-proxmox-02 bmc", "hypervisor", "jd", "tls", "10.0.50.240:443",
          "the XCC completes a TLS handshake with its device certificate", cert="device", alert=False),
    Probe("linds-proxmox-01 bmc", "hypervisor", "linds", "tls", "192.168.6.240:443",
          "the iDRAC completes a TLS handshake with its device certificate", cert="device", alert=False),

    # --- Network devices -------------------------------------------------------
    # linds-switch-02 only shows here: PrometheusTargetDown already watches it
    # over SNMP.
    Probe("jd-unifi-01", "network", "jd", "tls", "10.0.52.7:443",
          "the UniFi console completes a TLS handshake with its device certificate", cert="device"),
    Probe("linds-switch-02", "network", "linds", "tls", "10.0.80.3:443",
          "the EdgeOS web UI completes a TLS handshake with its device certificate", cert="device", alert=False),

    # --- Platform ----------------------------------------------------------------
    # While the API server's own scrape fails, KubeAPIDown and
    # PrometheusTargetDown say so and rules.yaml holds this one back; it then
    # reports only an API server that answers but is not ready.
    Probe("kubernetes-api", "platform", "jd", "http_kube_api", "https://10.0.53.200:6443/readyz",
          "GET /readyz answers 200: the API server and etcd are ready", cert="talos"),
    Probe("vault", "platform", "jd", "http_200", "https://vault.linds.com.au/v1/sys/health",
          "GET /v1/sys/health answers 200: initialised, unsealed and active (503 is sealed)", cert="cert-manager"),

    # --- The mTLS gate (job mtls-gate): a request without a client certificate
    # (The module sets the TLS server name itself; hostname is for the alert.)
    *[Probe(f"{h} public", "public", "jd", f"mtls_gate_{h}", "172.16.1.12:443",
            f"REFUSED is healthy: the mTLS ingress closes the connection to a request for {h}.linds.com.au "
            "without a client certificate (probe_success 0, probe_failed_due_to_regex 1)",
            hostname=f"{h}.linds.com.au", job="mtls-gate")
      for h in ("home", "photos", "radarr", "sonarr")],
]

# What each ScrapeConfig is for: (job, group) -> (name prefix, interval,
# vantage points, comment).
GROUPS = {
    ("blackbox", "main"): ("blackbox", "60s", ("jd", "linds"), "Availability probes, every 60 s."),
    ("blackbox", "dns"): ("blackbox-dns", "120s", ("jd", "linds"),
                          "DNS probes, every 120 s: each question to a router is also a Suricata event in Loki."),
    # Every 15 minutes and from JD only. A refused request is a failed probe,
    # and blackbox logs each failed probe as two ERROR lines (no flag turns
    # that off): every minute from both sites that was 23,000 lines a day of
    # the gate working. The gate changes only with a sync, so 15 minutes is
    # soon enough, and both sites reach the same nginx-mtls pods. Prometheus
    # forgets a sample after 5 minutes, so rules and panels read this job
    # with max_over_time or last_over_time over 20 minutes.
    ("mtls-gate", "main"): ("mtls-gate", "15m", ("jd",),
                            "The mTLS gate: a request with no client certificate must be refused (see blackbox.yml)."),
}


def q(v):
    """A YAML scalar: JSON strings are valid YAML, and quoting keeps "no" a string."""
    return json.dumps(v)


def scrape_config(job, group, vantage):
    prefix, interval, _, comment = GROUPS[(job, group)]
    probes = [p for p in PROBES if p.job == job and p.group == group]
    out = [
        "---",
        f"# {comment} From {vantage.upper()}.",
        "apiVersion: monitoring.coreos.com/v1alpha1",
        "kind: ScrapeConfig",
        "metadata:",
        f"  name: {prefix}-{vantage}",
        "  namespace: monitoring",
        "  labels:",
        "    # What the Prometheus resource selects scrape configs by.",
        "    release: monitoring-kube-prometheus-stack",
        "spec:",
        f"  jobName: {job}",
        "  metricsPath: /probe",
        f"  scrapeInterval: {interval}",
        "  # Above every module's timeout (10 s at most), so a probe that times",
        "  # out still returns probe_success 0 instead of failing the scrape.",
        "  scrapeTimeout: 15s",
        "  staticConfigs:",
    ]
    for p in probes:
        out.append(f"    # {p.target}: {p.healthy}")
        out.append(f"    - targets: [{q(p.address)}]")
        out.append("      labels:")
        labels = {"target": p.target, "kind": p.kind, "site": p.site, "module": p.module}
        if p.cert:
            labels["cert"] = p.cert
        if not p.alert:
            labels["alert"] = "no"
        if p.hostname:
            labels["hostname"] = p.hostname
        out += [f"        {k}: {q(v)}" for k, v in labels.items()]
    out += [
        "  # action: replace is the default, written out so that ArgoCD's diff",
        "  # matches what the API server stores.",
        "  relabelings:",
        "    - action: replace",
        "      sourceLabels: [__address__]",
        "      targetLabel: __param_target",
        "    - action: replace",
        "      sourceLabels: [__address__]",
        "      targetLabel: instance",
        "    - action: replace",
        "      sourceLabels: [module]",
        "      targetLabel: __param_module",
        "    # Empty, and so not sent, for a target without a hostname label.",
        "    - action: replace",
        "      sourceLabels: [hostname]",
        "      targetLabel: __param_hostname",
        "    - action: replace",
        "      targetLabel: vantage",
        f"      replacement: {vantage}",
        "    # The exporter's site on the target (so on up and PrometheusTargetDown),",
        "    # the target's own in target_site. The docstring of targets.py says why.",
        "    - action: replace",
        "      sourceLabels: [site]",
        "      targetLabel: target_site",
        "    - action: replace",
        "      targetLabel: site",
        f"      replacement: {vantage}",
        "    - action: replace",
        "      targetLabel: __address__",
        f"      replacement: {EXPORTERS[vantage]}",
        "  # The probe_* series get the target's site back.",
        "  metricRelabelings:",
        "    - action: replace",
        "      sourceLabels: [target_site]",
        "      targetLabel: site",
        "    - action: labeldrop",
        "      regex: target_site",
    ]
    return "\n".join(out) + "\n"


HEADER = """# GENERATED by targets.py. Edit that file and run it again:
#   python3 monitoring-probes/targets.py > monitoring-probes/scrape-configs.yaml
#
# What Prometheus asks the two blackbox exporters to probe: the targets of
# job blackbox from both, so their ScrapeConfigs are here once per vantage
# point. The exporter is a proxy: Prometheus scrapes its Service and names the
# target in ?target=, the module in ?module= and, for a target given by
# address, the TLS server name in ?hostname=. targets.py explains the labels.
"""


def markdown():
    kinds = ["web", "public", "identity", "dns", "storage", "hypervisor", "network", "platform"]
    rows = ["| Target | Kind | Site | Probed | Healthy when | Alert |", "|---|---|---|---|---|---|"]
    for p in sorted(PROBES, key=lambda p: (kinds.index(p.kind), p.job != "blackbox", p.target)):
        severity = "critical" if p.kind in ("dns", "identity", "platform") else "warning"
        alert = ("MtlsGateAcceptsAnonymous" if p.job == "mtls-gate"
                 else f"ProbeTargetDown, {severity}" if p.alert else "dashboard only")
        rows.append(f"| {p.target} | {p.kind} | {p.site} | `{p.address}` ({p.module}) | {p.healthy} | {alert} |")
    return "\n".join(rows) + "\n"


def main():
    names = [(p.job, p.target) for p in PROBES]
    dupes = {n for n in names if names.count(n) > 1}
    if dupes:
        sys.exit(f"duplicate targets: {sorted(dupes)}")
    if "--markdown" in sys.argv:
        sys.stdout.write(markdown())
        return
    sys.stdout.write(HEADER)
    for (job, group), (_, _, vantages, _) in GROUPS.items():
        for vantage in vantages:
            sys.stdout.write(scrape_config(job, group, vantage))


if __name__ == "__main__":
    main()
