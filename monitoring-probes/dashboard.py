"""Generate the Availability Grafana dashboard (dashboard.yaml).

    python3 monitoring-probes/dashboard.py > monitoring-probes/dashboard.yaml

Edit this file, not dashboard.yaml.

The data is the blackbox probes (targets.py, rules.yaml). Every target is
probed from both sites (label vantage); "up" means up from at least one site,
which is target:probe_success:max. Like the Hardware and Router dashboards:
status uses the status colours with a text label (green "✓", amber "◐" or
"⚠", red "✗"), and series use the categorical palette in its fixed order,
JD blue and LINDS orange wherever both are drawn.
"""
import json
import sys

DS = {"type": "prometheus", "uid": "prometheus"}
# Dark steps of the validated categorical palette, in slot order (as in
# monitoring-hardware/dashboard.py), and the status palette. Slot 6 (green) is
# left out: on this dashboard green means "up". Slots 1-5 and 7 pass the
# palette validator together on the dark surface.
BLUE, ORANGE, AQUA, YELLOW, MAGENTA, VIOLET = "#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#9085e9"
GOOD, WARN, CRIT = "#0ca30c", "#fab219", "#d03b3b"
SITE_COLOR = {"jd": BLUE, "linds": ORANGE}

# The variables, as label matchers. VARS is for panels that follow every
# variable; the status history panels leave out kind (each is one kind).
BB = 'job="blackbox"'
VARS = f'{BB}, site=~"$site", kind=~"$kind", target=~"$target"'
RANGE_VARS = f'{VARS}, vantage=~"$vantage"'
REC = 'site=~"$site", kind=~"$kind", target=~"$target"'   # target:probe_success:max has no job selector need
UP_ANYWHERE = f"max by (target) (probe_success{{{VARS}}})"
UP_EVERYWHERE = f"min by (target) (probe_success{{{VARS}}})"

_ids = iter(range(1, 1000))


def target(expr, legend="", ref="A", instant=False, fmt=None, interval=None):
    t = {"datasource": DS, "refId": ref, "expr": expr, "legendFormat": legend, "range": not instant, "instant": instant}
    if fmt:
        t["format"] = fmt
    if interval:
        t["interval"] = interval
    return t


def fixed(color):
    return {"mode": "fixed", "fixedColor": color}


def override(name, display=None, color=None, extra=None, regex=False):
    props = []
    if display:
        props.append({"id": "displayName", "value": display})
    if color:
        props.append({"id": "color", "value": fixed(color)})
    props.extend(extra or [])
    return {"matcher": {"id": "byRegexp" if regex else "byName", "options": name}, "properties": props}


def thresholds(color="text"):
    return {"mode": "absolute", "steps": [{"color": color, "value": None}]}


def count_mappings(sign, color):
    """0 shows as a green "✓ None"; any other count as "<sign> n" in color. The sign
    is a unit prefix: Grafana 13 does not fill in ${__value.raw} in a mapping's text."""
    return {"unit": f"prefix:{sign} ", "thresholds": thresholds(color),
            "mappings": [{"type": "value", "options": {"0": {"text": "✓ None", "color": GOOD, "index": 0}}}]}


# 1 up from every site, 0.5 from one of the two, 0 down from every site.
STATE_MAPPINGS = [
    {"type": "value", "options": {
        "1": {"text": "✓ Up", "color": GOOD, "index": 0},
        "0": {"text": "✗ Down", "color": CRIT, "index": 1},
    }},
    {"type": "range", "options": {"from": 0.01, "to": 0.99, "result": {"text": "◐ One site", "color": WARN, "index": 2}}},
]

# The mTLS gate, worst first: 2 an answer came back without a certificate,
# 1 not tested (no TCP or TLS, so the refusal could not be seen), 0 refused.
GATE_MAPPINGS = [{"type": "value", "options": {
    "0": {"text": "✓ Refuses anonymous", "color": GOOD, "index": 0},
    "1": {"text": "? Not tested", "color": WARN, "index": 1},
    "2": {"text": "✗ OPEN to anyone", "color": CRIT, "index": 2},
}}]
GATE_LAST = 'last_over_time({m}{{job="mtls-gate"{f}}}[20m])'


def gate_badness(f=""):
    """f: extra matchers, such as the site and target variables."""
    s, r = GATE_LAST.format(m="probe_success", f=f), GATE_LAST.format(m="probe_failed_due_to_regex", f=f)
    return f"{s} * 2 + (1 - {s}) * (1 - {r})"


GATE_BADNESS = gate_badness()


def stat(title, desc, targets, grid, unit="none", mappings=None, overrides=None, text_mode="auto",
         color_mode="value", no_value=None, value_size=30, decimals=None, links=None, counts=None):
    defaults = {"unit": unit, "color": {"mode": "thresholds"}, "mappings": mappings or [], "thresholds": thresholds()}
    if counts:
        defaults.update(counts)
    if no_value:
        defaults["noValue"] = no_value
    if decimals is not None:
        defaults["decimals"] = decimals
    p = {
        "type": "stat", "id": next(_ids), "title": title, "description": desc, "datasource": DS,
        "gridPos": grid, "targets": targets,
        "fieldConfig": {"defaults": defaults, "overrides": overrides or []},
        "options": {
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "colorMode": color_mode, "graphMode": "none", "justifyMode": "auto", "textMode": text_mode,
            "orientation": "auto", "wideLayout": True, "text": {"valueSize": value_size},
            "showPercentChange": False,
        },
    }
    if links:
        p["links"] = links
    return p


def history(title, desc, expr, grid, mappings=STATE_MAPPINGS, links=None, interval="1m"):
    """A state timeline, one row per target. Fixed colour mode: with
    color.mode thresholds Grafana ignores the value mappings' colours."""
    p = {
        "type": "state-timeline", "id": next(_ids), "title": title, "description": desc, "datasource": DS,
        "gridPos": grid, "targets": [target(expr, "{{target}}", interval=interval)],
        "fieldConfig": {
            "defaults": {"color": fixed("text"), "mappings": mappings, "thresholds": thresholds(),
                         "custom": {"fillOpacity": 85, "lineWidth": 0, "hideFrom": {"legend": False, "tooltip": False,
                                                                                     "viz": False}}},
            "overrides": [],
        },
        "options": {
            "mergeValues": True, "showValue": "never", "alignValue": "left", "rowHeight": 0.85,
            "legend": {"showLegend": False, "displayMode": "list", "placement": "bottom"},
            "tooltip": {"mode": "single", "sort": "none"},
        },
    }
    if links:
        p["links"] = links
    return p


def timeseries(title, desc, targets, grid, unit, overrides=None, fill=0, stack=False, soft_max=None, links=None):
    custom = {
        "drawStyle": "line", "lineWidth": 2, "lineInterpolation": "linear", "fillOpacity": fill,
        "gradientMode": "none", "showPoints": "never", "pointSize": 4, "spanNulls": False,
        "axisPlacement": "auto", "axisLabel": "", "axisBorderShow": False, "axisCenteredZero": False,
        "barAlignment": 0, "stacking": {"mode": "normal" if stack else "none", "group": "A"},
        "thresholdsStyle": {"mode": "off"},
    }
    if soft_max is not None:
        custom["axisSoftMax"] = soft_max
    p = {
        "type": "timeseries", "id": next(_ids), "title": title, "description": desc, "datasource": DS,
        "gridPos": grid, "targets": targets,
        "fieldConfig": {"defaults": {"unit": unit, "min": 0, "color": {"mode": "palette-classic"}, "custom": custom,
                                     "thresholds": thresholds()},
                        "overrides": overrides or []},
        "options": {
            "legend": {"showLegend": True, "displayMode": "list", "placement": "bottom", "calcs": []},
            "tooltip": {"mode": "multi", "sort": "desc"},
        },
    }
    if links:
        p["links"] = links
    return p


def table(title, desc, grid, queries, columns, overrides=None, sort=None, links=None):
    """One row per target: queries are [(expr, ref)], each cut down to the same
    key labels plus a value, so merge lines them up. columns maps a field
    (label name or "Value #<ref>") to its header, in display order; a field
    mapped to None is hidden."""
    p = {
        "type": "table", "id": next(_ids), "title": title, "description": desc, "datasource": DS, "gridPos": grid,
        "targets": [target(e, "", ref, True, "table") for e, ref in queries],
        "transformations": [
            {"id": "merge", "options": {}},
            {"id": "organize", "options": {
                "excludeByName": {"Time": True, **{f: True for f, h in columns.items() if h is None}},
                "indexByName": {f: i for i, f in enumerate(columns)},
                "renameByName": {f: h for f, h in columns.items() if h},
            }},
        ],
        "fieldConfig": {
            "defaults": {"custom": {"align": "auto", "cellOptions": {"type": "auto"}, "inspect": False},
                         "mappings": [], "thresholds": thresholds(), "color": {"mode": "thresholds"},
                         "noValue": "–"},
            "overrides": overrides or [],
        },
        "options": {"showHeader": True, "cellHeight": "sm", "footer": {"show": False, "reducer": ["sum"], "fields": ""},
                    "sortBy": sort or []},
    }
    if links:
        p["links"] = links
    return p


def widths(**px):
    """Column widths in pixels, by header (underscores for spaces)."""
    return [override(k.replace("_", " "), extra=[{"id": "custom.width", "value": v}]) for k, v in px.items()]


def text_column(name, states):
    """A column that holds a value to show as a coloured word: states maps the value to (text, colour)."""
    return override(name, extra=[
        {"id": "mappings", "value": [{"type": "value", "options": {
            k: {"text": t, "color": c, "index": i} for i, (k, (t, c)) in enumerate(states.items())}}]},
        {"id": "custom.cellOptions", "value": {"type": "color-text"}}])


def row(title, y):
    return {"type": "row", "id": next(_ids), "title": title, "collapsed": False,
            "gridPos": {"x": 0, "y": y, "w": 24, "h": 1}, "panels": []}


def g(x, y, w, h):
    return {"x": x, "y": y, "w": w, "h": h}


def link(title, uid):
    return {"title": title, "url": f"/d/{uid}?${{__url_time_range}}", "targetBlank": False}


ROUTER = link("Router dashboard", "router")
HARDWARE = link("Hardware dashboard", "hardware")
INGRESS = link("Ingress traffic dashboard", "ingress-traffic")
SECURITY_ACCESS = link("Security access dashboard", "security-access")
SURICATA = link("Suricata dashboard", "suricata")

panels = []

# --- Now ------------------------------------------------------------------------
panels += [
    stat("Up", "Targets that answer from at least one site now, with the variables above.",
         [target(f"count({UP_ANYWHERE} == 1) or vector(0)", instant=True)], g(0, 0, 3, 4),
         color_mode="none"),
    stat("Down", "Targets that answer from no site. ProbeTargetDown fires for one after 10 minutes, unless it is "
         "dashboard only or another alert already says it (rules.yaml). Down now, below, names them.",
         [target(f"count({UP_ANYWHERE} == 0) or vector(0)", instant=True)], g(3, 0, 3, 4),
         counts=count_mappings("✗", CRIT)),
    stat("One site only", "Targets that answer from one site and not the other: the path between the sites, or one "
         "exporter. ProbeFailsFromOneSite fires after 15 minutes.",
         [target(f"count(({UP_EVERYWHERE} == 0) and ({UP_ANYWHERE} == 1)) or vector(0)", instant=True)],
         g(6, 0, 3, 4), counts=count_mappings("◐", WARN)),
    stat("Uptime", "Over the dashboard's time range, the share of minutes each target answered from at least one "
         "site, averaged over the targets shown (target:probe_success:max).",
         [target(f"avg(avg_over_time(target:probe_success:max{{{REC}}}[$__range]))", instant=True)],
         g(9, 0, 3, 4), unit="percentunit", decimals=2, color_mode="none"),
    stat("Certificates", "Certificates with 21 days or fewer left, of every TLS target shown. "
         "ProbeCertificateExpiring fires for those cert-manager does not issue; CertificateExpiringSoon for the rest.",
         [target(f"count(min by (target) (probe_ssl_earliest_cert_expiry{{{VARS}}}) - time() < 21 * 86400) "
                 "or vector(0)", instant=True)],
         g(12, 0, 3, 4), counts=count_mappings("⚠", WARN)),
    stat("mTLS gate", "Whether the public ingress refuses a request with no client certificate, the worst of its "
         "four names (job mtls-gate, every 15 minutes, from JD). Not tested: the probe got no TCP or TLS "
         "connection, so it could not see a refusal. MtlsGateAcceptsAnonymous fires when it is open.",
         [target(f"max({GATE_BADNESS})", instant=True)], g(15, 0, 3, 4), mappings=GATE_MAPPINGS,
         no_value="? No result", value_size=18),
    stat("Exporters", "Whether Prometheus can scrape the blackbox exporter at each site. A down exporter is "
         "PrometheusTargetDown for each of its targets; one with no targets at all is BlackboxProbesMissing.",
         [target('max by (vantage) (up{job="blackbox"})', "{{vantage}}", instant=True)], g(18, 0, 3, 4),
         mappings=[{"type": "value", "options": {"1": {"text": "✓ Up", "color": GOOD, "index": 0},
                                                 "0": {"text": "✗ Down", "color": CRIT, "index": 1}}}],
         text_mode="value_and_name", no_value="✗ Missing", value_size=16),
    stat("Probe alerts", "Alerts from rules.yaml firing now, as Discord got them.",
         [target('count(ALERTS{alertstate="firing", alertname=~"ProbeTargetDown|ProbeFailsFromOneSite|'
                 'ProbeCertificateExpiring|MtlsGateAcceptsAnonymous|BlackboxProbes.+"}) or vector(0)', instant=True)],
         g(21, 0, 3, 4), counts=count_mappings("⚠", WARN)),
]

# Down now: everything not up from every site. State 2 is down from every
# site, 1 from one (2 - max - min, so a target with one site's result only is
# 0 or 2). "Down for" is the time since the target last answered from every
# site, at most a day back (a subquery at 1-minute steps).
KEY = "target, kind, site"
STATE = f"(2 - max by ({KEY}) (probe_success{{{VARS}}}) - min by ({KEY}) (probe_success{{{VARS}}}))"
LAST_ALL_UP = f"max_over_time((timestamp(min by ({KEY}) (probe_success{{{VARS}}}) == 1))[1d:1m])"
panels.append(table(
    "Down now",
    "Every target that does not answer from every site, worst first. Down: from no site. One site: from one of the "
    "two. Down for: since it last answered from every site (over a day shows as 1 day). HTTP: the status code the "
    "failing probe got (no answer: none at all, as for a TLS or connection failure). Dashboard only: no alert fires "
    "for it (its device has one of its own).",
    g(0, 4, 24, 7), [
        (f"max by ({KEY}, alert) (probe_success{{{VARS}}}) * 0 + on ({KEY}) group_left () ({STATE} > 0)", "A"),
        (f"(time() - {LAST_ALL_UP} or on ({KEY}) ({STATE} * 0 + 86400)) and on ({KEY}) ({STATE} > 0)", "B"),
        (f'max by ({KEY}) (probe_success{{{VARS}, vantage="jd"}}) and on ({KEY}) ({STATE} > 0)', "C"),
        (f'max by ({KEY}) (probe_success{{{VARS}, vantage="linds"}}) and on ({KEY}) ({STATE} > 0)', "D"),
        # The status code of the failing probes only: the answering site's 200 explains nothing.
        (f"max by ({KEY}) (probe_http_status_code{{{VARS}}} and probe_success{{{VARS}}} == 0)", "E"),
    ],
    {"target": "Target", "kind": "Kind", "site": "Site", "Value #A": "State", "Value #B": "Down for",
     "Value #C": "From JD", "Value #D": "From LINDS", "Value #E": "HTTP", "alert": "Alert"},
    overrides=[
        text_column("State", {"2": ("✗ Down", CRIT), "1": ("◐ One site", WARN)}),
        override("Down for", extra=[{"id": "unit", "value": "dtdurations"}, {"id": "decimals", "value": 0},
                                    {"id": "max", "value": 86400}]),
        text_column("From JD", {"1": ("✓ Answers", GOOD), "0": ("✗ Fails", CRIT)}),
        text_column("From LINDS", {"1": ("✓ Answers", GOOD), "0": ("✗ Fails", CRIT)}),
        override("HTTP", extra=[{"id": "mappings", "value": [{"type": "value", "options": {
            "0": {"text": "no answer", "index": 0}}}]}]),
        override("Alert", extra=[{"id": "mappings", "value": [{"type": "value", "options": {
            "no": {"text": "dashboard only", "index": 0}}}]}]),
        *widths(Target=240, Kind=110, Site=80, State=120, Down_for=150, From_JD=120, From_LINDS=120, HTTP=110),
    ],
    sort=[{"displayName": "State", "desc": True}]))

# --- Status history ---------------------------------------------------------------
y = 11
panels.append(row("Status history · green: up from every site · amber: from one site only · red: down", y))


def kind_history(title, kind, grid, desc, links=None):
    expr = f'avg by (target) (probe_success{{{BB}, kind="{kind}", site=~"$site", target=~"$target"}})'
    return history(title, desc + " One row per target; the kind variable does not hide these panels, each is one kind.",
                   expr, grid, links=links)


panels += [
    kind_history("Web apps", "web", g(0, y + 1, 12, 11),
                 "Each app's own health URL through the internal ingress (nginx, 172.16.1.11), by name.",
                 [INGRESS]),
    kind_history("Identity", "identity", g(12, y + 1, 12, 11),
                 "The three domain controllers (Kerberos, LDAP, LDAPS, SMB) by address, and Keycloak's OpenID "
                 "configuration for the linds realm.", [SECURITY_ACCESS]),
    kind_history("DNS", "dns", g(0, y + 12, 12, 10),
                 "Every resolver: the routers' Unbound, the DCs and CoreDNS, each for an AD name (the DC locator SRV "
                 "record) and an internet name (github.com). Every 120 s.", [ROUTER]),
    kind_history("Public endpoints", "public", g(12, y + 12, 12, 6),
                 "What the internet reaches, tested at the end of the chain: the mTLS ingress's TLS for each public "
                 "name, both Plex servers and Minecraft. Cloudflare and the routers' forwards are not in the path.",
                 [INGRESS, SURICATA]),
    history("mTLS gate", "A request with no client certificate, for each public name, every 15 minutes from JD. "
            "Refuses is the gate working.",
            f'max by (target) ({gate_badness(", site=~\"$site\", target=~\"$target\"")})', g(12, y + 18, 12, 4),
            mappings=GATE_MAPPINGS, interval="5m"),
    kind_history("Storage", "storage", g(0, y + 22, 6, 6),
                 "The NFS, SMB and S3 servers, by the names the cluster mounts them with, and the TrueNAS web UI.",
                 [HARDWARE]),
    kind_history("Hypervisors", "hypervisor", g(6, y + 22, 6, 6),
                 "The Proxmox web UIs and the BMCs (dashboard only).", [HARDWARE]),
    kind_history("Network devices", "network", g(12, y + 22, 6, 6),
                 "The UniFi console and linds-switch-02 (dashboard only).", [ROUTER]),
    kind_history("Platform", "platform", g(18, y + 22, 6, 6),
                 "The Kubernetes API server's /readyz and Vault's health (503 when sealed)."),
]

# --- Uptime and certificates ------------------------------------------------------
y = 40
panels.append(row("Uptime and certificates", y))
panels += [
    table("Uptime", "Over the dashboard's time range, for each target: the share of minutes it answered from at least "
          "one site, that as a time down, and its average probe time (from the slower site, or the one chosen in "
          "Probed from). Worst first.",
          g(0, y + 1, 12, 16), [
              (f"max by ({KEY}) (avg_over_time(target:probe_success:max{{{REC}}}[$__range]))", "A"),
              (f"max by ({KEY}) ((1 - avg_over_time(target:probe_success:max{{{REC}}}[$__range])) * $__range_s)", "B"),
              (f"max by ({KEY}) (avg_over_time(probe_duration_seconds{{{RANGE_VARS}}}[$__range]))", "C"),
          ], {"target": "Target", "kind": "Kind", "site": "Site", "Value #A": "Uptime", "Value #B": "Time down",
              "Value #C": "Probe time"},
          overrides=[
              override("Uptime", extra=[
                  {"id": "unit", "value": "percentunit"}, {"id": "decimals", "value": 2},
                  {"id": "min", "value": 0.9}, {"id": "max", "value": 1},
                  {"id": "thresholds", "value": {"mode": "absolute", "steps": [
                      {"color": CRIT, "value": None}, {"color": WARN, "value": 0.99}, {"color": GOOD, "value": 0.999}]}},
                  {"id": "custom.cellOptions", "value": {"type": "gauge", "mode": "basic", "valueDisplayMode": "text"}}]),
              override("Time down", extra=[{"id": "unit", "value": "dtdurations"}, {"id": "decimals", "value": 0},
                                           {"id": "mappings", "value": [{"type": "range", "options": {
                                               "from": 0, "to": 59, "result": {"text": "–", "index": 0}}}]}]),
              override("Probe time", extra=[{"id": "unit", "value": "s"}, {"id": "decimals", "value": 3}]),
              *widths(Target=230, Kind=100, Site=70, Time_down=110, Probe_time=100),
          ], sort=[{"displayName": "Uptime", "desc": False}]),
    table("Certificates", "Every certificate a TLS probe saw, fewest days left first: red under 7, amber under 21. "
          "Issued by: cert-manager (CertificateExpiringSoon watches those), AD CS (the DCs' auto-enrolment), "
          "device (linds-CA certificates that LINDS-Ansible playbooks/certificates.yml installs by hand) or Talos "
          "(the API server). ProbeCertificateExpiring fires for all but cert-manager's.",
          g(12, y + 1, 12, 16), [
              (f"(min by ({KEY}, cert) (probe_ssl_earliest_cert_expiry{{{VARS}}}) - time()) / 86400", "A"),
              (f"min by ({KEY}, cert) (probe_ssl_earliest_cert_expiry{{{VARS}}}) * 1000", "B"),
              # Go writes DC= as an OID (0.9.2342.19200300.100.1.25=linds): keep the CN.
              (f'max by ({KEY}, cert, issuer) (label_replace(probe_ssl_last_chain_info{{{VARS}}}, '
               f'"issuer", "$1", "issuer", "CN=([^,]+).*"))', "C"),
          ], {"target": "Target", "kind": None, "site": None, "cert": "Issued by", "issuer": "Issuer",
              "Value #A": "Days left", "Value #B": "Expires", "Value #C": None},
          overrides=[
              override("Days left", extra=[
                  {"id": "unit", "value": "suffix: days"}, {"id": "decimals", "value": 0},
                  {"id": "thresholds", "value": {"mode": "absolute", "steps": [
                      {"color": CRIT, "value": None}, {"color": WARN, "value": 7},
                      {"color": GOOD, "value": 21}]}},
                  {"id": "custom.cellOptions", "value": {"type": "color-text"}}]),
              override("Expires", extra=[{"id": "unit", "value": "time:YYYY-MM-DD"}]),
              override("Issued by", extra=[{"id": "mappings", "value": [{"type": "value", "options": {
                  "cert-manager": {"text": "cert-manager", "index": 0}, "ad-cs": {"text": "AD CS", "index": 1},
                  "device": {"text": "device (Ansible)", "index": 2}, "talos": {"text": "Talos", "index": 3}}}]}]),
              *widths(Target=200, Issued_by=130, Issuer=100, Days_left=95),
          ], sort=[{"displayName": "Days left", "desc": False}]),
]

# --- Probe time -------------------------------------------------------------------
y = 57
panels.append(row("Probe time · how long each probe takes, connection and answer together", y))
# The resolver is the first word of the target: "jd-dc-01 dns ad", "coredns cluster".
RESOLVER = 'label_replace({sel}, "resolver", "$1", "target", "([^ ]+) .+")'
RESOLVER_COLOR = {"jd-router-01": BLUE, "linds-router-01": ORANGE, "jd-dc-01": AQUA, "linds-dc": YELLOW,
                  "linds-dc2": MAGENTA, "coredns": VIOLET}


def dns_panel(vantage, x):
    sel = f'probe_duration_seconds{{{BB}, kind="dns", site=~"$site", target=~"$target", vantage="{vantage}"}}'
    return timeseries(
        f"DNS answer time from {vantage.upper()}",
        f"Each resolver as the {vantage.upper()} exporter sees it, the slower of its two questions (AD name, "
        "internet name). A resolver at the other site includes the tunnel's round trip, about 13 ms.",
        [target(f"max by (resolver) ({RESOLVER.format(sel=sel)})", "{{resolver}}", interval="2m")],
        g(x, y + 9, 12, 8), "s", overrides=[override(r, color=c) for r, c in RESOLVER_COLOR.items()],
        links=[ROUTER])


panels += [
    timeseries("Probe time from each site",
               "The median probe time of the targets shown, from each site. Narrow Target to one to see its "
               "time from both sites; the difference is the path between the sites.",
               [target(f'quantile by (vantage) (0.5, probe_duration_seconds{{{RANGE_VARS}}})', "from {{vantage}}")],
               g(0, y + 1, 12, 8), "s",
               overrides=[override("from jd", color=BLUE), override("from linds", color=ORANGE)]),
    timeseries("HTTP phases",
               "Where the time of the HTTP probes shown goes, averaged over them: DNS lookup, TCP connect, TLS "
               "handshake, the server's processing (to the first byte) and the transfer. Narrow Target to one.",
               [target(f'avg by (phase) (probe_http_duration_seconds{{{RANGE_VARS}}})', "{{phase}}")],
               g(12, y + 1, 12, 8), "s", fill=60, stack=True,
               overrides=[override("resolve", "DNS lookup", BLUE), override("connect", "TCP connect", ORANGE),
                          override("tls", "TLS handshake", AQUA), override("processing", "Server processing", YELLOW),
                          override("transfer", "Transfer", MAGENTA)]),
    dns_panel("jd", 0),
    dns_panel("linds", 12),
]

dashboard = {
    "uid": "availability",
    "title": "Availability",
    "description": "Black-box probes of every service from both sites: what is down now, what was down, how slow it "
                   "is, and the certificates that expire. Probes, alerts and this dashboard: LINDS-Kubernetes "
                   "monitoring-probes/ (README).",
    "tags": ["availability", "blackbox"],
    "timezone": "browser",
    "editable": True,
    "graphTooltip": 1,
    "schemaVersion": 39,
    "time": {"from": "now-24h", "to": "now"},
    "refresh": "1m",
    "links": [
        {"title": "Homelab overview", "type": "link", "url": "/d/overview", "keepTime": True, "icon": "dashboard"},
        {"title": "Router", "type": "link", "url": "/d/router", "keepTime": True, "icon": "dashboard"},
        {"title": "Hardware", "type": "link", "url": "/d/hardware", "keepTime": True, "icon": "dashboard"},
        {"title": "Ingress traffic", "type": "link", "url": "/d/ingress-traffic", "keepTime": True, "icon": "dashboard"},
        {"title": "Backups", "type": "link", "url": "/d/backups", "keepTime": True, "icon": "dashboard"},
        {"title": "Security overview", "type": "link", "url": "/d/security-overview", "keepTime": True,
         "icon": "dashboard"},
        {"title": "Security access", "type": "link", "url": "/d/security-access", "keepTime": True,
         "icon": "dashboard"},
        {"title": "Suricata", "type": "link", "url": "/d/suricata", "keepTime": True, "icon": "dashboard"},
    ],
    "templating": {"list": [
        {"name": "site", "label": "Site", "type": "query", "datasource": DS,
         "query": {"qryType": 1, "query": f"label_values(probe_success{{{BB}}}, site)", "refId": "PrometheusVariableQueryEditor-VariableQuery"},
         "definition": f"label_values(probe_success{{{BB}}}, site)",
         "refresh": 2, "multi": True, "includeAll": True, "allValue": ".*",
         "current": {"selected": True, "text": ["All"], "value": ["$__all"]}, "sort": 1, "options": []},
        {"name": "kind", "label": "Kind", "type": "query", "datasource": DS,
         "query": {"qryType": 1, "query": f'label_values(probe_success{{{BB}, site=~"$site"}}, kind)', "refId": "PrometheusVariableQueryEditor-VariableQuery"},
         "definition": f'label_values(probe_success{{{BB}, site=~"$site"}}, kind)',
         "refresh": 2, "multi": True, "includeAll": True, "allValue": ".*",
         "current": {"selected": True, "text": ["All"], "value": ["$__all"]}, "sort": 1, "options": []},
        {"name": "target", "label": "Target", "type": "query", "datasource": DS,
         "query": {"qryType": 1, "query": f'label_values(probe_success{{{BB}, site=~"$site", kind=~"$kind"}}, target)',
                   "refId": "PrometheusVariableQueryEditor-VariableQuery"},
         "definition": f'label_values(probe_success{{{BB}, site=~"$site", kind=~"$kind"}}, target)',
         "refresh": 2, "multi": True, "includeAll": True, "allValue": ".*",
         "current": {"selected": True, "text": ["All"], "value": ["$__all"]}, "sort": 1, "options": []},
        {"name": "vantage", "label": "Probed from", "type": "query", "datasource": DS,
         "description": "Which exporter's results the probe time panels use. Up and down always use both.",
         "query": {"qryType": 1, "query": f"label_values(probe_success{{{BB}}}, vantage)", "refId": "PrometheusVariableQueryEditor-VariableQuery"},
         "definition": f"label_values(probe_success{{{BB}}}, vantage)",
         "refresh": 2, "multi": True, "includeAll": True, "allValue": ".*",
         "current": {"selected": True, "text": ["All"], "value": ["$__all"]}, "sort": 1, "options": []},
    ]},
    "annotations": {"list": [{
        "name": "Probe alerts", "enable": True, "datasource": DS,
        "expr": 'ALERTS{alertname=~"ProbeTargetDown|ProbeFailsFromOneSite|MtlsGateAcceptsAnonymous|BlackboxProbes.+", '
                'alertstate="firing"}',
        "step": "60s", "titleFormat": "{{alertname}}", "textFormat": "{{target}}{{vantage}}",
        "iconColor": CRIT, "useValueForTime": False,
    }]},
    "panels": panels,
}

HEADER = """---
# Grafana dashboard "Availability": the blackbox probes of every service, from
# both sites. Picked up by the kube-prometheus grafana dashboard sidecar via
# the grafana_dashboard label; grafana_folder puts it in "Infrastructure".
#
# GENERATED by dashboard.py. Edit that file and run it again:
#   python3 monitoring-probes/dashboard.py > monitoring-probes/dashboard.yaml
#
# The data: jobs blackbox and mtls-gate (scrape-configs.yaml, from targets.py)
# and target:probe_success:max (rules.yaml). The probe alerts show as
# annotations.
apiVersion: v1
kind: ConfigMap
metadata:
  name: availability-dashboard
  namespace: monitoring
  labels:
    grafana_dashboard: "1"
  annotations:
    grafana_folder: Infrastructure
data:
  availability.json: |
"""
sys.stdout.write(HEADER)
for line in json.dumps(dashboard, indent=2, ensure_ascii=False).splitlines():
    sys.stdout.write("    " + line + "\n")
