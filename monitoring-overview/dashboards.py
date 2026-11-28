"""Generate the Homelab overview and Backups dashboards.

    python3 monitoring-overview/dashboards.py

It writes overview-dashboard.yaml and backups-dashboard.yaml next to this
file. Edit this file, not the YAML files.
"""
import json
import os

PROM = {"type": "prometheus", "uid": "prometheus"}
LOKI = {"type": "loki", "uid": "loki"}
MIXED = {"type": "datasource", "uid": "-- Mixed --"}

# The validated categorical palette (dark steps) and the status palette, the
# same as the Router and Hardware dashboards. JD is blue, LINDS orange.
BLUE, ORANGE, AQUA = "#3987e5", "#d95926", "#199e70"
GOOD, WARN, CRIT = "#0ca30c", "#fab219", "#d03b3b"

# The end of the dashboard's time range, in seconds. LogQL has no time(), so
# the log panels compute ages from this.
NOW = "${__to:date:seconds}"
# A query returns NONE when there is no record at all. The panels show it as
# "✗ No record", so a missing series never reads as fresh.
NONE = 999999999
NONE_MAP = {"type": "range", "options": {"from": 900000000, "to": 1e13,
                                         "result": {"text": "✗ No record", "color": CRIT, "index": 20}}}
DASH_MAP = {"type": "value", "options": {"-1": {"text": "–", "color": "text", "index": 21}}}

H, D = 3600, 86400

_ids = iter(range(1, 1000))


# --- Panel helpers ---------------------------------------------------------------

def prom(expr, legend="", ref="A", instant=True, fmt=None):
    t = {"datasource": PROM, "refId": ref, "expr": expr, "legendFormat": legend, "range": not instant,
         "instant": instant}
    if fmt:
        t["format"] = fmt
    return t


def loki(expr, legend="", ref="A", instant=True, step=None):
    t = {"datasource": LOKI, "refId": ref, "expr": expr, "legendFormat": legend,
         "queryType": "instant" if instant else "range"}
    if step:
        t["step"] = step
    return t


def ds_of(targets):
    kinds = {t["datasource"]["type"] for t in targets}
    if len(kinds) > 1:
        return MIXED
    return LOKI if kinds == {"loki"} else PROM


def g(x, y, w, h):
    return {"x": x, "y": y, "w": w, "h": h}


def fixed(color):
    return {"mode": "fixed", "fixedColor": color}


def steps(*pairs):
    """Threshold steps: steps(GOOD, (WARN, 10), (CRIT, 20))."""
    out = [{"color": pairs[0], "value": None}]
    out += [{"color": c, "value": v} for c, v in pairs[1:]]
    return {"mode": "absolute", "steps": out}


def vmap(states):
    """A value mapping: {value: (text, color)}."""
    return {"type": "value", "options": {str(k): {"text": t, "color": c, "index": i}
                                         for i, (k, (t, c)) in enumerate(states.items())}}


def rmap(lo, hi, text, color, index=10):
    return {"type": "range", "options": {"from": lo, "to": hi, "result": {"text": text, "color": color, "index": index}}}


def override(name, display=None, color=None, extra=None):
    props = []
    if display:
        props.append({"id": "displayName", "value": display})
    if color:
        props.append({"id": "color", "value": fixed(color)})
    props.extend(extra or [])
    return {"matcher": {"id": "byName", "options": name}, "properties": props}


def link(title, uid, query=""):
    return {"title": title, "url": f"/d/{uid}{query}", "targetBlank": False}


def stat(title, desc, targets, grid, unit="none", mappings=None, thresholds=None, overrides=None, text_mode="auto",
         color_mode="value", graph="none", no_value=None, decimals=None, orientation="auto", links=None,
         value_size=None, color=None, title_size=None):
    defaults = {"unit": unit, "color": color or {"mode": "thresholds"}, "mappings": mappings or [],
                "thresholds": thresholds or steps("text")}
    if no_value:
        defaults["noValue"] = no_value
    if decimals is not None:
        defaults["decimals"] = decimals
    options = {
        "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
        "colorMode": color_mode, "graphMode": graph, "justifyMode": "auto", "textMode": text_mode,
        "orientation": orientation, "wideLayout": True, "showPercentChange": False,
    }
    if value_size or title_size:
        options["text"] = {k: v for k, v in (("valueSize", value_size), ("titleSize", title_size)) if v}
    return {"type": "stat", "id": next(_ids), "title": title, "description": desc, "datasource": ds_of(targets),
            "gridPos": grid, "targets": targets, "links": links or [],
            "fieldConfig": {"defaults": defaults, "overrides": overrides or []}, "options": options}


def timeseries(title, desc, targets, grid, unit, overrides=None, legend=True, fill=0, min_=0, soft_max=None,
               links=None, draw="line", time_from=None, interval=None):
    custom = {
        "drawStyle": draw, "lineWidth": 2, "lineInterpolation": "linear", "fillOpacity": fill if draw == "line" else 80,
        "gradientMode": "none", "showPoints": "never", "pointSize": 4, "spanNulls": False, "axisPlacement": "auto",
        "axisLabel": "", "axisBorderShow": False, "axisCenteredZero": False, "barAlignment": 0,
        "stacking": {"mode": "none", "group": "A"}, "thresholdsStyle": {"mode": "off"},
    }
    if soft_max is not None:
        custom["axisSoftMax"] = soft_max
    defaults = {"unit": unit, "color": {"mode": "palette-classic"}, "custom": custom, "thresholds": steps("text")}
    if min_ is not None:
        defaults["min"] = min_
    p = {"type": "timeseries", "id": next(_ids), "title": title, "description": desc, "datasource": ds_of(targets),
         "gridPos": grid, "targets": targets, "links": links or [],
         "fieldConfig": {"defaults": defaults, "overrides": overrides or []},
         "options": {"legend": {"showLegend": legend, "displayMode": "list", "placement": "bottom", "calcs": []},
                     "tooltip": {"mode": "multi", "sort": "none"}}}
    if time_from:
        p["timeFrom"] = time_from
    if interval:
        p["interval"] = interval
    return p


def bargauge(title, desc, targets, grid, unit, max_=None, thresholds=None, no_value=None, links=None, decimals=None):
    defaults = {"unit": unit, "mappings": [], "color": {"mode": "thresholds"}, "thresholds": thresholds or steps(BLUE),
                "min": 0}
    if max_ is not None:
        defaults["max"] = max_
    if no_value:
        defaults["noValue"] = no_value
    if decimals is not None:
        defaults["decimals"] = decimals
    return {"type": "bargauge", "id": next(_ids), "title": title, "description": desc, "datasource": ds_of(targets),
            "gridPos": grid, "targets": targets, "links": links or [],
            "fieldConfig": {"defaults": defaults, "overrides": []},
            "options": {"orientation": "horizontal", "displayMode": "basic", "valueMode": "color",
                        "namePlacement": "left", "showUnfilled": True, "sizing": "manual", "minVizHeight": 16,
                        "minVizWidth": 8, "maxVizHeight": 22,
                        "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                        "legend": {"showLegend": False, "displayMode": "list", "placement": "bottom"}}}


def table(title, desc, grid, targets, transformations, overrides=None, no_value=None, links=None):
    defaults = {"custom": {"align": "auto", "cellOptions": {"type": "auto"}, "inspect": False},
                "mappings": [], "thresholds": steps("text"), "color": {"mode": "thresholds"}}
    if no_value:
        defaults["noValue"] = no_value
    return {"type": "table", "id": next(_ids), "title": title, "description": desc, "datasource": ds_of(targets),
            "gridPos": grid, "targets": targets, "transformations": transformations, "links": links or [],
            "fieldConfig": {"defaults": defaults, "overrides": overrides or []},
            "options": {"showHeader": True, "cellHeight": "sm",
                        "footer": {"show": False, "reducer": ["sum"], "fields": ""}}}


def organize(columns, extra_hide=()):
    """columns maps a field to its header, in display order; None hides it."""
    return {"id": "organize", "options": {
        "excludeByName": {"Time": True, **{f: True for f in extra_hide}, **{f: True for f, h in columns.items() if h is None}},
        "indexByName": {f: i for i, f in enumerate(columns)},
        "renameByName": {f: h for f, h in columns.items() if h}}}


def text_cells(states, other=None):
    """Mappings for a text column: {value: (text, color)}."""
    m = [vmap(states)]
    if other:
        m.append({"type": "regex", "options": {"pattern": "(.+)", "result": {"text": other[0], "color": other[1],
                                                                              "index": len(states)}}})
    return [{"id": "mappings", "value": m}, {"id": "custom.cellOptions", "value": {"type": "color-text"}}]


def widths(**px):
    return [override(k.replace("_", " "), extra=[{"id": "custom.width", "value": v}]) for k, v in px.items()]


def logs(title, desc, expr, grid, time_from=None):
    p = {"type": "logs", "id": next(_ids), "title": title, "description": desc, "datasource": LOKI, "gridPos": grid,
         "targets": [loki(expr, instant=False)],
         "options": {"showTime": True, "showLabels": False, "showCommonLabels": False, "wrapLogMessage": True,
                     "prettifyLogMessage": False, "enableLogDetails": True, "dedupStrategy": "none",
                     "sortOrder": "Descending"}}
    if time_from:
        p["timeFrom"] = time_from
    return p


def text(title, content, grid):
    return {"type": "text", "id": next(_ids), "title": title, "gridPos": grid,
            "options": {"mode": "markdown", "content": content}}


def row(title, y):
    return {"type": "row", "id": next(_ids), "title": title, "collapsed": False,
            "gridPos": {"x": 0, "y": y, "w": 24, "h": 1}, "panels": []}


# --- Shared mappings and expressions -----------------------------------------------

STATUS = [vmap({0: ("✓ OK", GOOD), 1: ("⚠ Warning", WARN), 2: ("✗ Problem", CRIT)})]
UPDOWN = [vmap({1: ("✓ Up", GOOD), 0: ("✗ Down", CRIT), -1: ("✗ No data", CRIT)})]
# Component health, as on the Hardware dashboard: 0 OK, 1 warning, 2 critical,
# 3 failed, below 0 unknown, NaN no reading.
HEALTH = [
    vmap({0: ("✓ OK", GOOD), 1: ("⚠ Warning", WARN), 2: ("✗ Critical", CRIT), 3: ("✗ Failed", CRIT)}),
    rmap(-2, -1, "? Unknown", "text", 4),
    {"type": "special", "options": {"match": "nan", "result": {"text": "– No reading", "color": "text", "index": 5}}},
]


def one_of(expr, missing):
    """expr as one label-less value, or missing when it has no series."""
    return f"max({expr}) or on () vector({missing})"


def tagged(expr, **labels):
    """expr with constant labels (PromQL and LogQL both have label_replace)."""
    for k, v in labels.items():
        expr = f'label_replace({expr}, "{k}", "{v}", "", "")'
    return expr


def guard(expr, present):
    """expr, but no data when the series in present does not exist: a count of
    zero then reads as "no data", not as "none"."""
    return f"({expr}) and on () (count({present}) > 0)"


# The checks behind the status tiles are recording rules (rules.yaml).
CHECK_NAMES = {
    "alerts": "Firing alerts", "router": "Router answers", "internet": "Internet (WAN)", "dns": "DNS (Unbound)",
    "proxmox": "Proxmox host", "nodes": "Kubernetes nodes", "tunnel": "Site tunnel", "api": "Kubernetes API",
    "rules": "Alert rules run", "alertmanager": "Alertmanager", "logs": "Loki (logs)",
}
SITE_NAMES = {"jd": "JD", "linds": "LINDS", "cluster": "Cluster & apps"}

# Hardware component health, the same expressions as monitoring-hardware/dashboard.py.
JD_HW = 'job="ipmi", instance="jd-proxmox-02"'
LI_HW = 'job="snmp", instance="linds-proxmox-01"'


def relabel(expr, mapping):
    for to, regex in mapping:
        expr = f'label_replace({expr}, "component", "{to}", "component", "{regex}")'
    return expr


JD_COMPONENTS = "max by (component) (" + relabel(
    f'label_replace({{{JD_HW}, __name__=~"ipmi_(temperature|fan_speed|voltage|current|power)_state"}}, '
    f'"component", "$1", "__name__", "ipmi_(.+)_state") or label_replace(ipmi_sensor_state{{{JD_HW}, '
    f'type=~"Processor|Memory|Power Supply|Drive Slot|Critical Interrupt|Cable/Interconnect|Physical Security"}}, '
    f'"component", "$1", "type", "(.+)")',
    [("Temperatures", "temperature"), ("Fans", "fan_speed"), ("Voltages", "voltage"),
     ("Power", "current|power|Power Supply"), ("Processors", "Processor"), ("Drive bays", "Drive Slot"),
     ("PCIe errors", "Critical Interrupt"), ("Cables", "Cable/Interconnect"), ("Intrusion", "Physical Security")],
) + ")"
LI_COMPONENTS = "max by (component) (" + relabel(
    f'label_replace({{{LI_HW}, __name__=~"(powerSupply|amperageProbe|coolingDevice|temperatureProbe|voltageProbe|'
    f'memoryDevice|processorDevice|systemBattery|intrusion)Status"}}, "component", "$1", "__name__", "(.+)Status")',
    [("Power", "powerSupply|amperageProbe"), ("Fans", "coolingDevice"), ("Temperatures", "temperatureProbe"),
     ("Voltages", "voltageProbe"), ("Memory", "memoryDevice"), ("Processors", "processorDevice"),
     ("Batteries", "systemBattery"), ("Intrusion", "intrusion")],
) + " - 3)"


def storage_alerts(names):
    """2 for each firing critical alert whose name matches, 1 for any other."""
    sel = f'alertstate="firing", alertname=~"{names}"'
    return f'(ALERTS{{{sel}, severity="critical"}} * 2 or ALERTS{{{sel}, severity!~"critical|info|none"}})'


# --- The data-protection chains ----------------------------------------------------
# Each chain: what it protects, where the copy goes, what proves the last
# success, and the expressions for the age of the newest good copy and its
# state (0 OK, 1 late, 2 stale or failing, 3 not monitored, 4 none
# configured). An age of -1 means that the chain has no age.

SANOID = '{job="syslog", appname="sanoid", hostname="jd-proxmox-02"} |= "taking snapshot " |= "_daily"'
PULL = ('{job="syslog", appname="ZETTAREPL", hostname="linds-truenas-01.linds.com.au"} '
        '|= "doing pull from \'VM/truenas-nas\' to \'NAS\'"')
TS = "| label_format ts=`{{ __timestamp__ | unixEpoch }}` | unwrap ts"
# The pull line names the snapshot it sends; its name holds its UTC time.
SNAP_TS = ('| regexp "of snapshot=\'autosnap_(?P<snap>[0-9]{4}-[0-9]{2}-[0-9]{2}_[0-9]{2}:[0-9]{2}:[0-9]{2})_daily\'" '
           '| label_format snapts=`{{ toDate "2006-01-02_15:04:05" .snap | unixEpoch }}` | unwrap snapts')
DFSR = '{job="windows", channel="DFS Replication"}'
VOLSNAP = '{job="windows", channel="System", level="error"} | source="Volsnap"'
VSS_START = '{job="windows", channel="System", hostname="HOST"} |= "Volume Shadow Copy service entered the running state"'


def log_age(stream, ts=TS, days=7):
    return f"({NOW} - max(max_over_time({stream} {ts} [{days}d]))) or vector({NONE})"


def age_state(age, warn, crit):
    """0 below warn, 1 below crit, 2 at or above crit (a missing record is NONE, so 2)."""
    return f"(({age}) > bool {warn}) + (({age}) > bool {crit})"


PG = 'namespace="postgresql-linds"'
PG_BASE_AGE = f"time() - max(barman_cloud_cloudnative_pg_io_last_available_backup_timestamp{{{PG}}}) or on () vector({NONE})"
PG_WAL_AGE = (f"max(cnpg_pg_stat_archiver_seconds_since_last_archival{{{PG}}} "
              f"and on (pod) (cnpg_pg_replication_in_recovery{{{PG}}} == 0)) or on () vector({NONE})")
BB = 'instance="jd-proxmox-02"'
BACKBLAZE_AGE = (f"time() - max(max_over_time((backblaze_run_last_end_timestamp_seconds{{{BB}}} "
                 f"and on (instance) (backblaze_run_completed{{{BB}}} == 1))[14d:10m])) or on () vector({NONE})")
SNAP_AGE = log_age(SANOID)
REPLICA_AGE = log_age(PULL, SNAP_TS)
VSS_AGE = {h: log_age(VSS_START.replace("HOST", h)) for h in ("jd-fs-01", "linds-dc")}
DFSR_ERRORS = (f'(sum(count_over_time({DFSR} | level="error" [1d])) or vector(0)) '
               f'and on () (sum(count_over_time({DFSR} [2d])) > 0) or vector(999999)')
VOLSNAP_ERRORS = (f'(sum(count_over_time({VOLSNAP} [7d])) or vector(0)) '
                  f'and on () (sum(count_over_time({{job="windows", channel="System"}} [1d])) > 0) or vector(999999)')
GUESTS_NO_BACKUP = guard('count(pve_not_backed_up_info{job="pve"} and on (instance, id) pve_guest_info{job="pve", template="0"}) '
                         'or on () vector(0)', 'pve_guest_info{job="pve"}')

CHAINS = [
    # order, chain, protects, copy goes to, proof, datasource, age, state
    ("01", "JD volume snapshots (sanoid)", "K8s volumes, NFS share, S3 data (Vault, Postgres backups)",
     "jd-proxmox-02 VM/truenas-nas: 14 dailies", "sanoid log: taking snapshot …_daily", "loki",
     SNAP_AGE, age_state(SNAP_AGE, 26 * H, 50 * H)),
    ("02", "Copy at LINDS (TrueNAS pull)", "The same, off site",
     "linds-truenas-01 pool NAS (LINDS)", "zettarepl log: doing pull …, no ERROR", "loki",
     REPLICA_AGE, age_state(REPLICA_AGE, 40 * H, 64 * H)),
    ("03", "Postgres base backup", "linds-postgres: every database",
     "S3 bucket on jd-s3-01: 7 days", "barman_cloud_…_last_available_backup_…", "prom",
     PG_BASE_AGE, age_state(PG_BASE_AGE, 26 * H, 36 * H)),
    ("04", "Postgres WAL archive", "linds-postgres: changes since the base backup",
     "The same bucket (point in time)", "cnpg_pg_stat_archiver_seconds_since_last_archival", "prom",
     PG_WAL_AGE, age_state(PG_WAL_AGE, 1800, 36 * H)),
    ("05", "NAS → Backblaze (weekly)", "jd-fs-01 D: (the NAS), from a ZFS clone",
     "Backblaze cloud: 1-year history", "backblaze_run_completed == 1 (Backblaze finished)", "prom",
     BACKBLAZE_AGE, age_state(BACKBLAZE_AGE, 8 * D, 15 * D)),
]


def chain_table_targets():
    """Four queries: the age and the state of the chains, for each data source.
    Each series carries the chain's columns as labels, so merge makes one row
    for each chain."""
    def tag(expr, c):
        return tagged(expr, order=c[0], chain=c[1], protects=c[2], dest=c[3], proof=c[4])
    rows = {("prom", "age"): [], ("prom", "state"): [], ("loki", "age"): [], ("loki", "state"): []}
    for c in CHAINS:
        rows[(c[5], "age")].append(tag(c[6], c))
        rows[(c[5], "state")].append(tag(c[7], c))
    # DFS Replication: errors only, no age.
    dfsr = ("06", "NAS mirror (DFS Replication)", "jd-fs-01 D: and linds-dc E:, both ways",
            "linds-dc E: (copies damage too)", "DFS Replication log: errors only")
    rows[("loki", "age")].append(tag("vector(0) - 1", dfsr))
    rows[("loki", "state")].append(tag(f"(({DFSR_ERRORS}) > bool 0) + (({DFSR_ERRORS}) > bool 99999)", dfsr))
    # Shadow copies: the older of the two servers' last VSS start, and Volsnap errors.
    shadow = ("07", "NAS shadow copies", "jd-fs-01 D: and linds-dc E: (Previous Versions)",
              "Same volume: 07:00, 12:00 weekdays", "VSS starts (indirect), Volsnap errors")
    vss = " or ".join(f'label_replace({VSS_AGE[h]}, "host", "{h}", "", "")' for h in VSS_AGE)
    rows[("loki", "age")].append(tag(f"max({vss})", shadow))
    rows[("loki", "state")].append(tag(f"(({VOLSNAP_ERRORS}) > bool 0) * 2", shadow))
    # Proxmox guests: no vzdump job exists.
    vz = ("08", "Proxmox guests (vzdump)", "Guest disks and configuration", "None: no backup job", "pve_not_backed_up_info")
    rows[("prom", "age")].append(tag("vector(-1)", vz))
    rows[("prom", "state")].append(tag(f"(({GUESTS_NO_BACKUP}) > bool 0) * 4 or on () vector(2)", vz))
    # Things with no backup, or no signal that one ran.
    for order, name, protects, dest, state in (
            ("09", "Kubernetes control plane (etcd)", "Cluster state that is not in git", "None found", 4),
            ("10", "Domain controllers (AD)", "The domain, DNS zones", "Replication between the 4 DCs only", 3),
            ("11", "LINDS media (TrueNAS ZFS_NAS)", "Media (can be downloaded again)", "None: no snapshot task", 4),
            ("12", "JD HDD-20T pool", "Torrents and media", "None: no sanoid policy", 4)):
        c = (order, name, protects, dest, "No metric or log")
        rows[("prom", "age")].append(tag("vector(-1)", c))
        rows[("prom", "state")].append(tag(f"vector({state})", c))
    return [prom(" or ".join(rows[("prom", "age")]), "", "A", fmt="table"),
            prom(" or ".join(rows[("prom", "state")]), "", "B", fmt="table"),
            loki(" or ".join(rows[("loki", "age")]), "", "C"),
            loki(" or ".join(rows[("loki", "state")]), "", "D")]


CHAIN_STATE = {0: ("✓ OK", GOOD), 1: ("⚠ Late", WARN), 2: ("✗ Stale or failing", CRIT),
               3: ("○ Not monitored", "text"), 4: ("○ None configured", "text")}


def chain_table(grid):
    def first(alias, fields):
        return {"id": "calculateField", "options": {"mode": "reduceRow", "alias": alias, "replaceFields": False,
                                                    "reduce": {"reducer": "firstNotNull", "include": fields}}}
    return table(
        "Every data-protection chain",
        "One row for each backup, snapshot or replica, and for each kind of data with none. Newest copy is the age "
        "of the newest good copy, from the proof column. State: Late is past the normal interval; Stale or failing "
        "is past the limit of its alert, or an error was logged. The rows from 09 on have no backup, or nothing "
        "shows that one ran.",
        grid, chain_table_targets(),
        [{"id": "organize", "options": {"excludeByName": {"Time": True}}},
         {"id": "merge", "options": {}},
         first("age", ["Value #A", "Value #C"]),
         first("state", ["Value #B", "Value #D"]),
         {"id": "sortBy", "options": {"fields": {}, "sort": [{"field": "order", "desc": False}]}},
         organize({"chain": "Chain", "protects": "Protects", "dest": "Copy goes to", "proof": "Proof of the last success",
                   "age": "Newest copy", "state": "State", "order": None},
                  extra_hide=("Value #A", "Value #B", "Value #C", "Value #D"))],
        overrides=[
            override("Newest copy", extra=[{"id": "unit", "value": "s"}, {"id": "decimals", "value": 1},
                                           {"id": "mappings", "value": [NONE_MAP, DASH_MAP]}]),
            override("State", extra=[{"id": "mappings", "value": [vmap(CHAIN_STATE)]},
                                     {"id": "custom.cellOptions", "value": {"type": "color-text"}}]),
            *widths(Chain=250, Protects=330, Copy_goes_to=330, Newest_copy=110, State=150),
        ])


def by_ref(ref, name, *props):
    return {"matcher": {"id": "byFrameRefID", "options": ref},
            "properties": [{"id": "displayName", "value": name}, *props]}


def age_props(warn, crit, none_text):
    return ({"id": "unit", "value": "s"}, {"id": "decimals", "value": 1},
            {"id": "thresholds", "value": steps(GOOD, (WARN, warn), (CRIT, crit))},
            {"id": "mappings", "value": [rmap(900000000, 1e13, none_text, CRIT, 20), rmap(-1.5, -0.5, "○ Not yet", "text", 21)]})


def count_props(suffix, colour, zero, none_text=None):
    m = {0: (zero, GOOD)}
    if none_text:
        m[999999] = (none_text, CRIT)
    return ({"id": "unit", "value": f"suffix: {suffix}"}, {"id": "decimals", "value": 0},
            {"id": "thresholds", "value": steps(GOOD, (colour, 1))}, {"id": "mappings", "value": [vmap(m)]})


def age_tile(title, desc, targets, grid, warn, crit, links, none_text="✗ No record"):
    """A tile with one age, coloured by its limits."""
    _, _, th, mp = age_props(warn, crit, none_text)
    return stat(title, desc, targets, grid, unit="s", decimals=1, thresholds=th["value"], mappings=mp["value"],
                links=links)


def protection_panel(grid, links):
    """The newest good copy of each chain, in one row."""
    return stat(
        "Newest good copy of each chain",
        "Snapshots at JD: sanoid's newest daily snapshot of VM/truenas-nas (Kubernetes volumes, NFS share, S3 data); "
        "daily, amber after 26 h, red after 50 h. Copy at LINDS: the newest snapshot that linds-truenas-01 pulled; "
        "14 to 38 h is normal, amber after 40 h, red after 64 h. Postgres: the newest base backup (nightly, alert at "
        "36 h) and the last archived WAL. Backblaze: the end of the last weekly run in which Backblaze finished "
        "(Prometheus keeps 14 days). DFS-R: error events in the last day. Shadow copies: Volsnap errors in 7 days "
        "(copies deleted). Guest backups: guests that no vzdump job covers.",
        # Grafana shows a mixed panel's Loki results first, so the order is: the volumes, the NAS, Postgres,
        # the guests.
        [loki(SNAP_AGE, "", "A"), loki(REPLICA_AGE, "", "B"), loki(DFSR_ERRORS, "", "C"), loki(VOLSNAP_ERRORS, "", "D"),
         prom(BACKBLAZE_AGE, "", "E"), prom(PG_BASE_AGE, "", "F"), prom(PG_WAL_AGE, "", "G"),
         prom(GUESTS_NO_BACKUP, "", "H")],
        grid, text_mode="value_and_name", value_size=26, title_size=14, links=links, no_value="✗ No data",
        thresholds=steps(CRIT),
        overrides=[
            by_ref("A", "Snapshots at JD", *age_props(26 * H, 50 * H, "✗ None in 7 days")),
            by_ref("B", "Copy at LINDS", *age_props(40 * H, 64 * H, "✗ None in 7 days")),
            by_ref("C", "DFS-R mirror", *count_props("errors", WARN, "✓ No errors", "✗ No DFS-R logs")),
            by_ref("D", "Shadow copies", *count_props("lost", CRIT, "✓ None lost", "✗ No Windows logs")),
            by_ref("E", "Backblaze", *age_props(8 * D, 15 * D, "✗ None in 14 days")),
            by_ref("F", "Postgres base backup", *age_props(26 * H, 36 * H, "✗ No record")),
            by_ref("G", "Postgres WAL archive", *age_props(1800, 36 * H, "✗ No record")),
            by_ref("H", "Guest backups", {"id": "unit", "value": "suffix: no job"}, {"id": "decimals", "value": 0},
                   {"id": "mappings", "value": [vmap({0: ("✓ All have a job", GOOD)})]}),
        ])


# --- Dashboard 1: Homelab overview -------------------------------------------------------

def overview():
    panels = []
    to_backups = [link("Backups & data protection", "backups")]
    to_router = [link("Router", "router")]
    to_hw = [link("Hardware", "hardware")]

    # Status: one tile for each site, the alerts, and what is failing.
    site_desc = {
        "jd": "The worst check at JD: jd-router-01 answers, its WAN and DNS work, jd-proxmox-02 is up, the JD "
              "Kubernetes nodes are Ready, and the worst firing alert at JD (critical or warning; notices do not "
              "count). Failing checks names the check.",
        "linds": "The worst check at LINDS: the site tunnel, linds-router-01 answers, its WAN and DNS work, "
                 "linds-proxmox-01 is up, the LINDS Kubernetes nodes are Ready, and the worst firing alert at LINDS. "
                 "Prometheus is at JD and reads LINDS through the tunnel.",
        "cluster": "The worst check of what both sites share: the Kubernetes API, the alert rules run (Watchdog), "
                   "Alertmanager and Loki answer, and the worst firing alert that is not at one site (apps, "
                   "certificates, Argo CD, Postgres).",
    }
    site_links = {
        "jd": [link("Router", "router", "?var-router=jd-router-01")] + to_hw,
        "linds": [link("Router", "router", "?var-router=linds-router-01")] + to_hw,
        "cluster": [link("Kubernetes", "k8s_views_global"), link("Argo CD", "qPkgGHg7k")],
    }
    for i, site in enumerate(("jd", "linds", "cluster")):
        panels.append(stat(SITE_NAMES[site], site_desc[site], [prom(f'overview:site:status{{site="{site}"}}')],
                           g(6 * i, 0, 6, 5), mappings=STATUS, no_value="✗ No data", value_size=40, thresholds=steps(CRIT),
                           links=site_links[site]))
    alive = 'overview:site:status'
    panels.append(stat(
        "Firing alerts", "Alerts firing now, by severity. Each one is sent to Discord once, when it starts, so a "
        "standing problem is here and not in new messages. Notices (info) say that something happened and clear "
        "by themselves. The security alerts from the logs are on the security dashboards.",
        [prom(guard(f'count(overview:alert:active_seconds{{severity="{s}"}}) or on () vector(0)', alive), n, r)
         for s, n, r in (("critical", "Critical", "A"), ("warning", "Warning", "B"), ("info", "Notices", "C"))],
        g(18, 0, 6, 5), text_mode="value_and_name", no_value="✗ No data", value_size=26, thresholds=steps(CRIT),
        overrides=[override("Critical", extra=[{"id": "thresholds", "value": steps(GOOD, (CRIT, 1))}]),
                   override("Warning", extra=[{"id": "thresholds", "value": steps(GOOD, (WARN, 1))}]),
                   override("Notices", extra=[{"id": "thresholds", "value": steps("text")}])]))

    panels.append(table(
        "Firing alerts", "Every alert that fires now, the worst first. Site comes from the instance, node or host "
        "name; Where and What are its most specific labels. Watchdog is left out.",
        g(0, 5, 16, 8),
        [prom('label_replace(overview:alert:active_seconds{severity="critical"}, "rank", "1", "", "") '
              'or label_replace(overview:alert:active_seconds{severity="warning"}, "rank", "2", "", "") '
              'or label_replace(overview:alert:active_seconds{severity!~"critical|warning"}, "rank", "3", "", "") '
              f'or on () absent({alive}) * -1', "", "A", fmt="table")],
        [{"id": "sortBy", "options": {"fields": {}, "sort": [{"field": "rank", "desc": False}]}},
         organize({"alertname": "Alert", "severity": "Severity", "site": "Site", "where": "Where", "what": "What",
                   "Value": "Active for", "rank": None})],
        overrides=[
            override("Severity", extra=text_cells({"critical": ("✗ critical", CRIT), "warning": ("⚠ warning", WARN),
                                                   "info": ("ℹ notice", "text")})),
            override("Site", extra=[{"id": "mappings", "value": [vmap({k: (v, "text") for k, v in SITE_NAMES.items()})]}]),
            override("Active for", extra=[{"id": "unit", "value": "s"}, {"id": "decimals", "value": 1},
                                          {"id": "mappings", "value": [vmap({-1: ("✗ Overview rules not loaded", CRIT)})]},
                                          {"id": "custom.cellOptions", "value": {"type": "color-text"}}]),
            *widths(Alert=260, Severity=110, Site=120, Active_for=110),
        ],
        no_value="✓ No alerts firing"))
    panels.append(table(
        "Failing checks", "The checks behind the three status tiles that are not OK. Warning: the backup WAN, a "
        "warning alert, or Loki down. Problem: the check failed, its data is missing, or a critical alert fires.",
        g(16, 5, 8, 8),
        [prom(f"overview:check:status > 0 or on () absent({alive}) * 3", "", "A", fmt="table")],
        [{"id": "sortBy", "options": {"fields": {}, "sort": [{"field": "Value", "desc": True}]}},
         organize({"site": "Site", "check": "Check", "Value": "State"})],
        overrides=[
            override("Site", extra=[{"id": "mappings", "value": [vmap({k: (v, "text") for k, v in SITE_NAMES.items()})]}]),
            override("Check", extra=[{"id": "mappings", "value": [vmap({k: (v, "text") for k, v in CHECK_NAMES.items()})]}]),
            override("State", extra=[{"id": "mappings", "value": [vmap({1: ("⚠ Warning", WARN), 2: ("✗ Problem", CRIT),
                                                                         3: ("✗ Rules not loaded", CRIT)})]},
                                     {"id": "custom.cellOptions", "value": {"type": "color-text"}}]),
        ],
        no_value="✓ All checks pass"))

    # Data protection: one tile for each chain.
    y = 13
    panels.append(row("Data protection · the Backups dashboard has each chain", y))
    panels.append(protection_panel(g(0, y + 1, 24, 4), to_backups))

    # Connectivity.
    y = 18
    panels.append(row("Connectivity · the Router dashboard has the detail", y))
    routers = (("JD", "jd-router-01"), ("LINDS", "linds-router-01"))

    def per_router(fn, missing=-1):
        return [prom(one_of(fn(r), missing), site, chr(65 + i)) for i, (site, r) in enumerate(routers)]

    wan = (lambda r: f'max_over_time(router_wan_active{{instance="{r}", wan="primary"}}[3m]) '
                     f'* max_over_time(router_wan_healthy{{instance="{r}", wan="primary"}}[3m]) * 2 '
                     f'or max_over_time(router_wan_active{{instance="{r}", wan="backup"}}[3m]) '
                     f'* max_over_time(router_wan_healthy{{instance="{r}", wan="backup"}}[3m])')
    panels += [
        stat("WAN", "Which WAN carries each site's traffic, by wan-failover's health checks. Backup is the cellular "
             "modem (RouterOnBackupWAN after 10 minutes).",
             per_router(wan), g(0, y + 1, 4, 4), text_mode="value_and_name", value_size=18, links=to_router,
             mappings=[vmap({2: ("✓ Primary", GOOD), 1: ("⚠ Backup", WARN), 0: ("✗ Down", CRIT),
                             -1: ("✗ No data", CRIT)})]),
        stat("Site tunnel", "The IPsec tunnel between the sites, as each router sees it (RouterTunnelDown after 5 "
             "minutes).", per_router(lambda r: f'max_over_time(router_ipsec_up{{instance="{r}", conn="LINDS"}}[3m])'),
             g(4, y + 1, 3, 4), text_mode="value_and_name", value_size=18, mappings=UPDOWN, links=to_router),
        stat("BGP peers", "Peers that were up in the last day and are not up now: the Kubernetes nodes (Cilium) "
             "and the other site's router. RouterBGPPeerDown names them.",
             per_router(lambda r: f'count(max_over_time(router_bgp_peer_up{{instance="{r}"}}[1d]) == 1) '
                                  f'- (count(max_over_time(router_bgp_peer_up{{instance="{r}"}}[3m]) == 1) or on () vector(0))'),
             g(7, y + 1, 3, 4), text_mode="value_and_name", value_size=18, links=to_router,
             unit="suffix: down", decimals=0, thresholds=steps(GOOD, (CRIT, 1)),
             mappings=[vmap({0: ("✓ All up", GOOD), -1: ("✗ No data", CRIT)})]),
        stat("DNS", "Unbound on each router answers (RouterDNSDown).",
             per_router(lambda r: f'max_over_time(router_dns_up{{instance="{r}"}}[3m])'),
             g(10, y + 1, 3, 4), text_mode="value_and_name", value_size=18, mappings=UPDOWN,
             links=[link("DNS blocking", "dns-blocking")]),
        stat("IPS", "The blocking Suricata at JD: on and attached to its queue. It fails open, so a detached one "
             "blocks nothing and nothing looks wrong. LINDS runs Suricata as an IDS only, so it has no IPS.",
             [prom(one_of('router_ips_enabled{instance="jd-router-01"} * (1 + router_ips_attached{instance="jd-router-01"})',
                          -1), "JD", "A"),
              prom(one_of('router_ips_enabled{instance="linds-router-01"} * (1 + router_ips_attached{instance="linds-router-01"})',
                          -2), "LINDS", "B")],
             g(13, y + 1, 4, 4), text_mode="value_and_name", value_size=18, links=[link("Suricata", "suricata")],
             mappings=[vmap({2: ("✓ Blocking", GOOD), 1: ("✗ Detached", CRIT), 0: ("⚠ Off", WARN),
                             -1: ("✗ No data", CRIT), -2: ("○ IDS only", "text")})]),
        stat("VPN exits", "Time since the last WireGuard handshake: JD wg10 is VLAN 58's way out (NordVPN), LINDS "
             "wg101 is VLAN 36's. RouterWireGuardStale fires after 15 minutes. JD wg101 has no hosts and never "
             "has a handshake.",
             [prom('label_replace(router_wireguard_handshake_age_seconds, "site", "$1", "instance", "(.+)-router-01")',
                   "{{site}} {{iface}}")],
             g(17, y + 1, 4, 4), unit="s", text_mode="value_and_name", value_size=16, links=to_router,
             thresholds=steps(CRIT, (GOOD, 0), (CRIT, 900)), mappings=[rmap(-1.5, -0.5, "– Unused", "text")],
             no_value="✗ No data"),
        stat("Probes", "Blackbox probes of the services (Availability dashboard) that fail now.",
             [prom(guard('count(probe_success{job="blackbox"} == 0) or on () vector(0)', 'probe_success{job="blackbox"}'))],
             g(21, y + 1, 3, 4), no_value="– Not deployed yet", links=[link("Availability", "availability")],
             unit="suffix: failing", decimals=0, thresholds=steps("text", (CRIT, 1)),
             mappings=[vmap({0: ("✓ All pass", GOOD)})]),
    ]
    internet = 'host!~"10\\\\..*"'
    panels += [
        timeseries("Internet latency", "Mean round trip from each router to the internet targets (1.1.1.1, 9.9.9.9 "
                   "and their IPv6 addresses), and across the tunnel from JD.",
                   [prom(f"avg by (instance) (rate(smokeping_response_duration_seconds_sum{{{internet}}}[$__rate_interval]) "
                         f"/ rate(smokeping_response_duration_seconds_count{{{internet}}}[$__rate_interval]))",
                         "{{instance}}", "A", instant=False),
                    prom('rate(smokeping_response_duration_seconds_sum{instance="jd-router-01", host=~"10\\\\..*"}[$__rate_interval]) '
                         '/ rate(smokeping_response_duration_seconds_count{instance="jd-router-01", host=~"10\\\\..*"}[$__rate_interval])',
                         "Tunnel (from JD)", "B", instant=False)],
                   g(0, y + 5, 12, 7), "s", links=to_router,
                   overrides=[override("jd-router-01", "JD", BLUE), override("linds-router-01", "LINDS", ORANGE),
                              override("Tunnel (from JD)", color=AQUA)]),
        timeseries("Packet loss", "Pings to the internet targets that got no answer, for each router.",
                   [prom(f"clamp_min(1 - sum by (instance) (rate(smokeping_response_duration_seconds_count{{{internet}}}[$__rate_interval])) "
                         f"/ sum by (instance) (rate(smokeping_requests_total{{{internet}}}[$__rate_interval])), 0)",
                         "{{instance}}", "A", instant=False)],
                   g(12, y + 5, 12, 7), "percentunit", soft_max=0.02, links=to_router,
                   overrides=[override("jd-router-01", "JD", BLUE), override("linds-router-01", "LINDS", ORANGE)]),
    ]

    # Compute.
    y = 30
    panels.append(row("Compute · the Hardware and Kubernetes dashboards have the detail", y))
    ksm = 'kube_node_status_condition{condition="Ready", status="true"}'
    panels += [
        stat("Kubernetes nodes", "Nodes that are Ready and nodes that are not (NodeNotReady after 2 minutes).",
             [prom(guard(f"count({ksm} == 1) or on () vector(0)", ksm), "Ready", "A"),
              prom(guard(f"count({ksm} == 0) or on () vector(0)", ksm), "Not ready", "B")],
             g(0, y + 1, 4, 4), text_mode="value_and_name", value_size=18, no_value="✗ No data", thresholds=steps(CRIT),
             links=[link("Kubernetes nodes", "k8s_views_nodes")],
             overrides=[override("Ready", extra=[{"id": "thresholds", "value": steps("text")}]),
                        override("Not ready", extra=[{"id": "thresholds", "value": steps(GOOD, (CRIT, 1))}])]),
        stat("Proxmox hosts", "Time since each host started; Down when Proxmox reports it down.",
             [prom(one_of(f'pve_uptime_seconds{{job="pve", id="node/{h}"}} * on (instance, id) '
                          f'max_over_time(pve_up{{job="pve", id="node/{h}"}}[3m])', -1), h, chr(65 + i))
              for i, h in enumerate(("jd-proxmox-02", "linds-proxmox-01"))],
             g(4, y + 1, 4, 4), unit="s", decimals=1, text_mode="value_and_name", value_size=16, links=to_hw,
             mappings=[vmap({0: ("✗ Down", CRIT)}), rmap(-1.5, -0.5, "✗ No data", CRIT)]),
        stat("Guests running", "Virtual machines and containers that run, for each host (templates left out). "
             "Stopped guests lists the others.",
             [prom('count by (instance) (pve_up{job="pve", id=~"(qemu|lxc)/.+"} == 1)', "{{instance}}")],
             g(8, y + 1, 4, 4), text_mode="value_and_name", value_size=16, no_value="✗ No data", links=to_hw,
             thresholds=steps(CRIT, ("text", 0))),
        stat("Hardware", "The worst sensor state of each host's BMC: the XCC over IPMI, the iDRAC over SNMP "
             "(HardwareSensorNotOk).",
             [prom(f"max({JD_COMPONENTS})", "jd-proxmox-02", "A"), prom(f"max({LI_COMPONENTS})", "linds-proxmox-01", "B")],
             g(12, y + 1, 4, 4), text_mode="value_and_name", value_size=16, mappings=HEALTH, no_value="✗ No reading",
             thresholds=steps(CRIT), links=to_hw),
        stat("Last node restart", "Time since the most recent start of a Kubernetes node. A rolling Talos upgrade "
             "restarts them all, and with them the pods (Restarts, below).",
             [prom('min(time() - node_boot_time_seconds{job="node-exporter"})')],
             g(16, y + 1, 4, 4), unit="s", decimals=1, no_value="✗ No data", thresholds=steps(CRIT, ("text", 0)),
             links=[link("Kubernetes nodes", "k8s_views_nodes")]),
        stat("Short of pods", "Deployments, StatefulSets and DaemonSets with fewer ready pods than they "
             "want (KubeDeploymentReplicasMismatch and the like fire after 15 minutes). A rollout shows here for a "
             "moment.",
             [prom(guard('(count(kube_deployment_status_replicas_available < kube_deployment_spec_replicas) or on () vector(0)) '
                         '+ (count(kube_statefulset_status_replicas_ready < kube_statefulset_replicas) or on () vector(0)) '
                         '+ (count(kube_daemonset_status_number_available < kube_daemonset_status_desired_number_scheduled) '
                         'or on () vector(0))', 'kube_deployment_spec_replicas'))],
             g(20, y + 1, 4, 4), decimals=0, no_value="✗ No data", thresholds=steps(CRIT, (GOOD, 0), (WARN, 1)),
             mappings=[vmap({0: ("✓ None", GOOD)})], links=[link("Kubernetes namespaces", "k8s_views_ns")]),
    ]
    mem = ('(1 - node_memory_MemAvailable_bytes{job="node-exporter"} / node_memory_MemTotal_bytes{job="node-exporter"}) '
           '* on (instance) group_left (nodename) node_uname_info{job="node-exporter"}')
    router_mem = ('label_replace(1 - node_memory_MemAvailable_bytes{job="router-node"} / node_memory_MemTotal_bytes{job="router-node"}, '
                  '"nodename", "$1", "instance", "(.+)")')
    # The Proxmox hosts: memory as Proxmox counts it (jd-proxmox-02's includes the ZFS cache), and the root
    # file system (the directory storage "local").
    host_mem = ('label_replace(pve_memory_usage_bytes{job="pve", id=~"node/.+"} / pve_memory_size_bytes{job="pve", id=~"node/.+"}, '
                '"nodename", "$1", "instance", "(.+)")')
    host_disk = ('label_replace(max by (instance) (pve_disk_usage_bytes{job="pve"} / pve_disk_size_bytes{job="pve"} '
                 '* on (instance, id) group_left () pve_storage_info{job="pve", plugintype="dir"}), "nodename", "$1", "instance", "(.+)")')
    fs = 'fstype!~"tmpfs|overlay|squashfs", mountpoint!~"/boot.*"'
    disk = (f'max by (nodename) ((1 - node_filesystem_avail_bytes{{job="node-exporter", {fs}}} / '
            f'node_filesystem_size_bytes{{job="node-exporter", {fs}}}) * on (instance) group_left (nodename) node_uname_info{{job="node-exporter"}})')
    router_disk = (f'label_replace(max by (instance) (1 - node_filesystem_avail_bytes{{job="router-node", {fs}}} / '
                   f'node_filesystem_size_bytes{{job="router-node", {fs}}}), "nodename", "$1", "instance", "(.+)")')
    panels += [
        bargauge("Memory used", "Memory in use on each Kubernetes node and router (MemAvailable), and on each "
                 "Proxmox host as Proxmox counts it. NodeMemoryHigh fires at 90%, NodeMemoryCritical at 95%. "
                 "jd-proxmox-02's figure includes the ZFS cache, which gives memory back when guests need it.",
                 [prom(f"sort_desc({mem} or {router_mem} or {host_mem})", "{{nodename}}")], g(0, y + 5, 8, 10),
                 "percentunit", max_=1,
                 thresholds=steps(BLUE, (WARN, 0.9), (CRIT, 0.95)), links=[link("Kubernetes nodes", "k8s_views_nodes")]),
        bargauge("Disk used", "The fullest file system of each Kubernetes node and router, and each Proxmox host's "
                 "root file system. NodeDiskAlmostFull fires at 90%, NodeDiskFull at 97%, "
                 "StorageProxmoxLocalNearlyFull at 90%.",
                 [prom(f"sort_desc({disk} or {router_disk} or {host_disk})", "{{nodename}}")], g(8, y + 5, 8, 10),
                 "percentunit", max_=1,
                 thresholds=steps(BLUE, (WARN, 0.9), (CRIT, 0.97)), links=[link("Kubernetes nodes", "k8s_views_nodes")]),
        table("Stopped guests", "Guests that do not run (templates left out). Some are stopped on purpose: old copies "
              "kept after a rebuild, the weekly Backblaze VM, guests started by hand. VM 102 at LINDS must never be "
              "started. ProxmoxGuestStopped (a notice) fires when a guest that ran stops.",
              g(16, y + 5, 8, 10),
              [prom('max by (instance, id, name) (pve_up{job="pve", id=~"(qemu|lxc)/.+"} * on (instance, id) '
                    'group_left (name) pve_guest_info{job="pve", template="0"}) == 0', "", "A", fmt="table"),
               prom('max by (instance, id, name) (max_over_time(pve_up{job="pve", id=~"(qemu|lxc)/.+"}[1d]) * on (instance, id) '
                    'group_left (name) pve_guest_info{job="pve", template="0"}) and on (instance, id) '
                    '(pve_up{job="pve", id=~"(qemu|lxc)/.+"} == 0)', "", "B", fmt="table")],
              [{"id": "merge", "options": {}},
               organize({"name": "Guest", "instance": "Host", "id": "ID", "Value #A": None, "Value #B": "Last day"})],
              overrides=[override("Last day", extra=text_cells({1: ("◐ Ran today", "text"), 0: ("○ Stopped", "text")})),
                         *widths(Guest=160, Host=130, ID=80)],
              no_value="✓ All guests run", links=to_hw),
    ]

    # Storage.
    y = 45
    panels.append(row("Storage · the Hardware dashboard has the detail", y))
    parts = [("Disks", "StorageSmart.+"), ("ZFS pools", "StorageZfs.+"), ("PERC", "StorageRaid.+"),
             ("Thin pools", "StorageThinPool.+"), ("NAS pools", "StorageTrueNas.+"), ("Proxmox local", "StorageProxmoxLocal.+"),
             ("Collector", "StorageHealth.+")]
    sh = 'job="proxmox-storage-health"'
    nas = 'job="snmp", instance="linds-truenas-01", datasetDescr!~".+/.+"'
    panels += [
        stat("Storage by part", "The worst storage alert firing now for each part. Collector means that a host stopped "
             "reporting.", [prom(f"max({storage_alerts(n)}) or on () vector(0)", p, chr(65 + i)) for i, (p, n) in enumerate(parts)],
             g(0, y + 1, 5, 9), mappings=HEALTH, text_mode="value_and_name", value_size=14, title_size=13,
             orientation="horizontal", links=to_hw),
        bargauge("Pools", "How full each pool is: the ZFS pools on jd-proxmox-02, the NAS pools on linds-truenas-01 "
                 "and the data space of the LVM thin pools. A full thin pool silently zero-fills new chunks "
                 "(StorageThinPoolNearlyFull at 90%). The ZFS and NAS pool alerts fire at 85%.",
                 [prom(f'label_join(storage_zfs_pool_allocated_bytes{{{sh}}} / storage_zfs_pool_size_bytes{{{sh}}}, '
                       f'"name", " · ", "instance", "pool")', "{{name}}", "A"),
                  prom(f'label_join(datasetUsedBytes{{{nas}}} / (datasetUsedBytes{{{nas}}} + datasetAvailableBytes{{{nas}}}), '
                       f'"name", " · ", "instance", "datasetDescr")', "{{name}}", "B"),
                  prom(f'label_join(storage_lvm_thin_used_ratio{{{sh}, space="data"}}, "name", " · ", "instance", "vg")',
                       "{{name}} (thin)", "C")],
                 g(5, y + 1, 10, 9), "percentunit", max_=1, thresholds=steps(BLUE, (WARN, 0.8), (CRIT, 0.9)), links=to_hw),
        bargauge("Fullest volumes", "The Kubernetes volumes with the least space left. PVCAlmostFull fires at 85%. A "
                 "volume on a share (NFS, SMB) shows the whole share.",
                 [prom('topk(7, max by (namespace, persistentvolumeclaim) (kubelet_volume_stats_used_bytes / '
                       'kubelet_volume_stats_capacity_bytes))', "{{namespace}}/{{persistentvolumeclaim}}")],
                 g(15, y + 1, 9, 9), "percentunit", max_=1, thresholds=steps(BLUE, (WARN, 0.85), (CRIT, 0.95)),
                 links=[link("Kubernetes namespaces", "k8s_views_ns")]),
    ]

    # Platform.
    y = 55
    panels.append(row("Platform · Argo CD, certificates, secrets, jobs, Postgres", y))
    argo = "argocd_app_info"
    cert_left = ('bottomk(1, min by (name) (certmanager_certificate_expiration_timestamp_seconds) - time())')
    restarts = "increase(kube_pod_container_status_restarts_total[1d])"
    oom = ('count(max by (namespace, pod, container) (kube_pod_container_status_last_terminated_reason{reason="OOMKilled"} == 1) '
           f'and on (namespace, pod, container) ({restarts} > 0)) or on () vector(0)')
    panels += [
        stat("Argo CD", "Applications that are not Synced, and not Healthy. ArgoCDAppOutOfSync, ArgoCDAppDegraded and "
             "ArgoCDAppUnhealthy say which.",
             [prom(guard(f'count({argo}{{sync_status!="Synced"}} == 1) or on () vector(0)', argo), "Not synced", "A"),
              prom(guard(f'count({argo}{{health_status!="Healthy"}} == 1) or on () vector(0)', argo), "Not healthy", "B")],
             g(0, y + 1, 4, 4), text_mode="value_and_name", value_size=18, no_value="✗ No data",
             thresholds=steps(CRIT, (GOOD, 0), (WARN, 1)), links=[link("Argo CD", "qPkgGHg7k")]),
        stat("Next certificate to expire", "The cert-manager certificate that expires first. cert-manager renews them "
             "before the end; CertificateExpiringSoon fires at 14 days and CertificateExpiringCritical at 7.",
             [prom(cert_left, "{{name}}")], g(4, y + 1, 5, 4), unit="s", decimals=0, text_mode="value_and_name",
             value_size=18, no_value="✗ No data", thresholds=steps(CRIT, (WARN, 7 * D), (GOOD, 14 * D)),
             links=[link("Cert-manager", "cdhrcds8aosg0c")]),
        stat("External secrets", "ExternalSecrets and ClusterExternalSecrets that are not Ready, and failed syncs from "
             "Vault in the last day.",
             [prom(guard('(count(externalsecret_status_condition{condition="Ready", status="False"} == 1) or on () vector(0)) '
                         '+ (count(clusterexternalsecret_status_condition{condition="Ready", status="False"} == 1) or on () vector(0))',
                         "externalsecret_sync_calls_total"), "Not ready", "A"),
              prom(guard('sum(increase(externalsecret_sync_calls_error[1d])) or on () vector(0)', "externalsecret_sync_calls_total"),
                   "Sync errors, 1 d", "B")],
             g(9, y + 1, 4, 4), text_mode="value_and_name", value_size=18, no_value="✗ No data", decimals=0,
             thresholds=steps(CRIT, (GOOD, 0), (WARN, 1)), links=[link("External Secrets", "bdtvyf4zxtv5sa")]),
        stat("Postgres", "linds-postgres: instances that answer (2 expected), replicas that stream from the primary "
             "(1 expected), and how far the replica is behind.",
             [prom(f"sum(cnpg_collector_up{{{PG}}}) or on () vector(0)", "Up", "A"),
              prom(f"max(cnpg_pg_replication_streaming_replicas{{{PG}}}) or on () vector(0)", "Streaming", "B"),
              prom(f"max(cnpg_pg_replication_lag{{{PG}}})", "Lag", "C")],
             g(13, y + 1, 6, 4), text_mode="value_and_name", value_size=18, decimals=0, no_value="✗ No data",
             thresholds=steps(CRIT), links=[link("CloudNativePG", "cloudnative-pg")],
             overrides=[override("Up", extra=[{"id": "thresholds", "value": steps(CRIT, (WARN, 1), (GOOD, 2))}]),
                        override("Streaming", extra=[{"id": "thresholds", "value": steps(WARN, (GOOD, 1))}]),
                        override("Lag", extra=[{"id": "unit", "value": "s"},
                                               {"id": "thresholds", "value": steps(GOOD, (WARN, 300))}])]),
        stat("Pods", "Containers that the kernel killed for memory in the last day (PodOOMKilled), and all container "
             "restarts in the last day.",
             [prom(oom, "OOM killed, 1 d", "A"), prom(f"round(sum({restarts}))", "Restarts, 1 d", "B")],
             g(19, y + 1, 5, 4), text_mode="value_and_name", value_size=18, decimals=0,
             links=[link("Kubernetes pods", "k8s_views_pods")],
             overrides=[override("OOM killed, 1 d", extra=[{"id": "thresholds", "value": steps(GOOD, (WARN, 1))}])]),
    ]
    cron_age = "max by (namespace, cronjob) (time() - kube_cronjob_status_last_successful_time)"
    cron_every = "max by (namespace, cronjob) (kube_cronjob_next_schedule_time - kube_cronjob_status_last_schedule_time)"
    panels += [
        table("CronJobs", "Each CronJob's last successful run against its schedule. Overdue: no success for 1.15 "
              "schedule intervals plus 15 minutes.",
              g(0, y + 5, 9, 7),
              [prom(cron_age, "", "A", fmt="table"), prom(cron_every, "", "B", fmt="table"),
               prom(f"({cron_age} > bool ({cron_every} * 1.15 + 900)) "
                    "+ 2 * max by (namespace, cronjob) (kube_cronjob_spec_suspend) "
                    "or max by (namespace, cronjob) (kube_cronjob_info) * 0 + 4", "", "C", fmt="table")],
              [{"id": "merge", "options": {}},
               organize({"cronjob": "CronJob", "namespace": None, "Value #A": "Last success",
                         "Value #B": "Every", "Value #C": "State"})],
              overrides=[override("Last success", extra=[{"id": "unit", "value": "s"}, {"id": "decimals", "value": 1}]),
                         override("Every", extra=[{"id": "unit", "value": "s"}, {"id": "decimals", "value": 0}]),
                         override("State", extra=[{"id": "mappings", "value": [vmap({
                             0: ("✓ On time", GOOD), 1: ("✗ Overdue", CRIT), 2: ("○ Suspended", "text"),
                             3: ("○ Suspended", "text"), 4: ("✗ Never succeeded", CRIT)})]},
                             {"id": "custom.cellOptions", "value": {"type": "color-text"}}]),
                         *widths(CronJob=190, Last_success=105, Every=80)],
              links=[link("Kubernetes namespaces", "k8s_views_ns")]),
        table("Argo CD applications to look at", "Applications that are not Synced or not Healthy.",
              g(9, y + 5, 7, 7),
              [prom(f'max by (name, sync_status, health_status) ({argo}{{sync_status!="Synced"}} == 1 '
                    f'or {argo}{{health_status!="Healthy"}} == 1)', "", "A", fmt="table")],
              [organize({"name": "Application", "sync_status": "Sync", "health_status": "Health", "Value": None})],
              overrides=[override("Sync", extra=text_cells({"Synced": ("✓ Synced", GOOD)}, ("⚠ $1", WARN))),
                         override("Health", extra=text_cells({"Healthy": ("✓ Healthy", GOOD),
                                                              "Progressing": ("◐ Progressing", "text")}, ("✗ $1", CRIT)))],
              no_value="✓ All synced and healthy", links=[link("Argo CD", "qPkgGHg7k")]),
        bargauge("Restarts in the last day", "The pods whose containers restarted most in the last day. After a "
                 "node restart every pod on it counts once.",
                 [prom(f"topk(7, sum by (namespace, pod) ({restarts}) > 0.5)", "{{pod}}")],
                 g(16, y + 5, 8, 7), "none", decimals=0, no_value="✓ No restarts",
                 links=[link("Kubernetes pods", "k8s_views_pods")]),
    ]

    return {
        "uid": "overview",
        "title": "Homelab overview",
        "description": "Is everything OK at both sites, and if not, where to look. Status tiles, firing alerts, "
                       "data protection, connectivity, compute, storage and the platform. Rules and generator: "
                       "LINDS-Kubernetes monitoring-overview/ (README).",
        "tags": ["overview"],
        "timezone": "browser", "editable": True, "graphTooltip": 1, "schemaVersion": 39,
        "time": {"from": "now-24h", "to": "now"}, "refresh": "1m",
        "links": [
            {"title": t, "type": "link", "url": f"/d/{u}", "icon": "dashboard"} for t, u in (
                ("Backups", "backups"), ("Router", "router"), ("Hardware", "hardware"), ("Availability", "availability"),
                ("Security", "security-overview"), ("Access", "security-access"), ("Ingress", "ingress-traffic"),
                ("Suricata", "suricata"), ("DNS blocking", "dns-blocking"), ("Network devices", "network-devices"),
                ("Kubernetes", "k8s_views_global"), ("Logs · Windows", "logs-windows"), ("Logs · Syslog", "logs-syslog"))],
        "templating": {"list": []},
        "annotations": {"list": [{
            "name": "Critical alert started", "enable": True, "datasource": PROM,
            "expr": 'ALERTS{alertstate="firing", severity="critical"} '
                    'unless ALERTS{alertstate="firing", severity="critical"} offset 1m',
            "step": "60s", "titleFormat": "{{alertname}}",
            "textFormat": "{{instance}}{{node}}{{namespace}} {{name}}", "iconColor": CRIT, "useValueForTime": False}]},
        "panels": panels,
    }


# --- Dashboard 2: Backups & data protection --------------------------------------------------

def backups():
    panels = []
    to_overview = [link("Homelab overview", "overview")]
    panels.append(protection_panel(g(0, 0, 24, 5), to_overview))
    panels.append(chain_table(g(0, 5, 24, 14)))

    # sanoid.
    y = 19
    panels.append(row("JD volume snapshots · sanoid on jd-proxmox-02", y))
    sanoid_all = '{job="syslog", appname="sanoid", hostname="jd-proxmox-02"}'
    gate = '|= "sanoid-snapshot-gate: skipping"'
    panels += [
        stat("Datasets snapshotted", "Datasets that sanoid snapshotted in the last 26 hours. VM/truenas-nas "
             "has a recursive policy (14 dailies), so this is every dataset under it that is not opted out.",
             [loki(f"sum(count_over_time({SANOID} [26h])) or vector(0)")], g(0, y + 1, 4, 5), decimals=0,
             thresholds=steps(CRIT, (GOOD, 1))),
        stat("Opted out", "Datasets that the snapshot gate skips (au.com.linds:sanoid=off, LINDS-Ansible "
             "proxmox_sanoid_optout): Prometheus, Loki and the Valheim server files. sanoid tries them every 15 "
             "minutes and logs a WARN each time; that is expected.",
             [loki(f'count(sum by (dataset) (count_over_time({sanoid_all} {gate} '
                   f'| regexp "skipping (?P<dataset>[^ ]+) " [1h]))) or vector(0)')],
             g(4, y + 1, 4, 5), decimals=0),
        timeseries("Daily snapshots taken", "Datasets snapshotted each day, for 14 days. A day with none is a day "
                   "with no new restore point.",
                   [loki(f"sum(count_over_time({SANOID} [1d]))", "Datasets", instant=False, step="1d")],
                   g(8, y + 1, 7, 5), "none", legend=False, draw="bars", time_from="14d", interval="1d",
                   overrides=[override("Datasets", color=BLUE)]),
        logs("sanoid", "What sanoid logged, without the routine lines (cache, the opted-out datasets).",
             f'{sanoid_all} != "INFO: cache" != "sanoid-snapshot-gate" != "executing pre_snapshot_script" '
             f'!= "pre_snapshot_script failed" != "INFO: taking snapshots..." != "INFO: pruning snapshots..."',
             g(15, y + 1, 9, 5)),
    ]

    # TrueNAS replication.
    y = 25
    panels.append(row("Copy at LINDS · linds-truenas-01 pulls from jd-proxmox-02", y))
    zr = '{job="syslog", appname="ZETTAREPL", hostname="linds-truenas-01.linds.com.au"}'
    errors = f'{zr} |~ `\\] (ERROR|CRITICAL) +\\[`'
    panels += [
        age_tile("Last pull started", "Time since the task last started to pull VM/truenas-nas. It runs at 00:00 "
                 "local time. A start is not a success: a failed pull logs ERROR (next tile).",
                 [loki(log_age(PULL))], g(0, y + 1, 4, 5), 26 * H, 50 * H, [], "✗ None in 7 days"),
        stat("Datasets pulled", "Datasets that the last run sent (each logs \"doing pull\").",
             [loki(f"sum(count_over_time({zr} |= \"doing pull from\" [26h])) or vector(0)")], g(4, y + 1, 4, 5),
             decimals=0, thresholds=steps(CRIT, (GOOD, 1))),
        stat("Errors, 7 days", "ERROR or CRITICAL lines from zettarepl in the last 7 days. "
             "StorageTrueNasReplicationErrors fires for a day after one.",
             [loki(f"sum(count_over_time({errors} [7d])) or vector(0)")], g(8, y + 1, 4, 5), decimals=0,
             mappings=[vmap({0: ("✓ None", GOOD)})], thresholds=steps(GOOD, (CRIT, 1))),
        bargauge("Target pool", "The pool on linds-truenas-01 that holds the copy (NAS). It is small, so watch its "
                 "free space. StorageTrueNasPoolNearlyFull fires at 85%.",
                 [prom('datasetUsedBytes{job="snmp", instance="linds-truenas-01", datasetDescr="NAS"} / '
                       '(datasetUsedBytes{job="snmp", instance="linds-truenas-01", datasetDescr="NAS"} + '
                       'datasetAvailableBytes{job="snmp", instance="linds-truenas-01", datasetDescr="NAS"})', "NAS")],
                 g(12, y + 1, 4, 5), "percentunit", max_=1, thresholds=steps(BLUE, (WARN, 0.8), (CRIT, 0.85))),
        logs("zettarepl", "The replication task's log, without the SSH lines.",
             f'{zr} != "paramiko"', g(16, y + 1, 8, 5)),
    ]

    # Postgres.
    y = 31
    panels.append(row("Postgres · CloudNativePG and barman-cloud to jd-s3-01", y))
    window = f"time() - max(barman_cloud_cloudnative_pg_io_first_recoverability_point{{{PG}}})"
    primary = f"and on (pod) (cnpg_pg_replication_in_recovery{{{PG}}} == 0)"
    panels += [
        stat("Restore window", "How far back a restore can reach: the oldest base backup that the 7-day retention "
             "keeps. A restore can go to any point from then to the last archived WAL.",
             [prom(window)], g(0, y + 1, 4, 5), unit="s", decimals=1, no_value="✗ No data",
             thresholds=steps(CRIT, (WARN, 0), (GOOD, 5 * D))),
        stat("WAL failures, 1 day", "WAL segments that the primary failed to archive in the last day. One "
             "failure that the next attempt fixes is normal (PostgreSQLWALArchivingFailing fires when they go on).",
             [prom(f"round(sum(increase(cnpg_pg_stat_archiver_failed_count{{{PG}}}[1d]) {primary})) or on () vector(0)")],
             g(4, y + 1, 4, 5), decimals=0, thresholds=steps(GOOD, (WARN, 1))),
        stat("Last failed base backup", "Time since barman-cloud-backup last failed (PostgreSQLBaseBackupFailed fires "
             "for a day after one).",
             [prom(f"time() - max(barman_cloud_cloudnative_pg_io_last_failed_backup_timestamp{{{PG}}} > 0) or on () vector(-1)")],
             g(8, y + 1, 4, 5), unit="s", decimals=1, thresholds=steps(CRIT, (GOOD, D)),
             mappings=[rmap(-1.5, -0.5, "✓ Never", GOOD)]),
        timeseries("Backup ages", "The age of the newest base backup (it drops at each nightly backup) and the "
                   "restore window.",
                   [prom(f"time() - max(barman_cloud_cloudnative_pg_io_last_available_backup_timestamp{{{PG}}})",
                         "Newest base backup", "A", instant=False),
                    prom(window, "Restore window", "B", instant=False)],
                   g(12, y + 1, 12, 5), "s", time_from="7d",
                   overrides=[override("Newest base backup", color=BLUE), override("Restore window", color=ORANGE)]),
    ]

    # Backblaze.
    y = 37
    panels.append(row("NAS → Backblaze · the weekly run on jd-proxmox-02", y))
    bb = BB
    panels += [
        stat("Last run", "The last run of backblaze-run: did it end without an error, and did Backblaze finish a "
             "backup in it. The metrics file is on /run, so a restart of the host removes it until the next run.",
             [prom(f"max(backblaze_run_last_ok{{{bb}}})", "No error", "A"),
              prom(f"max(backblaze_run_completed{{{bb}}})", "Backblaze finished", "B")],
             g(0, y + 1, 4, 5), text_mode="value_and_name", value_size=16, no_value="– No run since the host started",
             mappings=[vmap({1: ("✓ Yes", GOOD), 0: ("✗ No", CRIT)})]),
        stat("Last run ended", "Time since the last run ended, with or without a finished backup.",
             [prom(f"time() - max(backblaze_run_last_end_timestamp_seconds{{{bb}}})")], g(4, y + 1, 4, 5), unit="s",
             decimals=1, no_value="– No run since the host started"),
        stat("Left to upload", "What Backblaze had left at the end of the last run. NaN: the run could not read it.",
             [prom(f"max(backblaze_remaining_files{{{bb}}})", "Files", "A"),
              prom(f"max(backblaze_remaining_bytes{{{bb}}})", "Bytes", "B")],
             g(8, y + 1, 4, 5), text_mode="value_and_name", value_size=16, no_value="– Not known",
             overrides=[override("Bytes", extra=[{"id": "unit", "value": "decbytes"}])]),
        logs("backblaze-run", "Each run's steps, for 14 days: the snapshot, the clone, the VM, and how the run ended.",
             '{job="syslog", appname="backblaze-run", hostname="jd-proxmox-02"} != "swtpm"', g(12, y + 1, 12, 5),
             time_from="14d"),
    ]

    # DFS Replication.
    y = 43
    panels.append(row("NAS mirror · DFS Replication between jd-fs-01 and linds-dc", y))
    stopped = '| event_id=~"2213|2104|4012"'
    panels += [
        stat("Replication stopped", "Events that mean replication stopped and needs a person: 2213 (stopped "
             "after a dirty shutdown; resume it with the WMI command in the event), 2104 (database error), 4012 "
             "(a member was offline too long).",
             [loki(f"sum(count_over_time({DFSR} {stopped} [7d])) or vector(0)")], g(0, y + 1, 4, 5), decimals=0,
             mappings=[vmap({0: ("✓ None", GOOD)})], thresholds=steps(GOOD, (CRIT, 1))),
        table("Errors and warnings, 1 day", "Error and warning events in the last day, on each server. A partner "
              "that restarts or is frozen for a backup logs some (5002, 5008, 5014); 4202 is a staging area that "
              "filled up.", g(4, y + 1, 5, 5),
              [loki(f'sum by (hostname) (count_over_time({DFSR} | level=~"error|warning" [1d]))')],
              [organize({"hostname": "Server", "Value #A": "Events"})], no_value="✓ None"),
        timeseries("Events per day", "DFS Replication events per day, for 14 days.",
                   [loki(f'sum by (level) (count_over_time({DFSR} [1d]))', "{{level}}", instant=False, step="1d")],
                   g(9, y + 1, 6, 5), "none", draw="bars", time_from="14d", interval="1d",
                   overrides=[override("error", color=CRIT), override("warning", color=WARN), override("info", color=BLUE)]),
        logs("Errors and warnings", "The DFS Replication errors and warnings, for 7 days.",
             f'{DFSR} | level=~"error|warning" | json message="message", id="event_id" | line_format "{{{{.id}}}} {{{{.message}}}}"',
             g(15, y + 1, 9, 5), time_from="7d"),
    ]

    # Shadow copies.
    y = 49
    panels.append(row("NAS shadow copies · Previous Versions on jd-fs-01 D: and linds-dc E:", y))
    panels += [
        stat("VSS last ran", "Time since the Volume Shadow Copy service last started on each file server. The shadow "
             "copy tasks start it at 07:00 and 12:00 on weekdays; a Backblaze freeze starts it too. Indirect: no "
             "event says that a shadow copy was made.",
             [loki(VSS_AGE[h], h, chr(65 + i)) for i, h in enumerate(VSS_AGE)], g(0, y + 1, 5, 5), unit="s",
             decimals=1, text_mode="value_and_name", value_size=16,
             overrides=[by_ref("A", "jd-fs-01 D:"), by_ref("B", "linds-dc E:")],
             mappings=[{"type": "range", "options": {"from": 900000000, "to": 1e13,
                                                     "result": {"text": "✗ None in 7 days", "color": CRIT, "index": 0}}}],
             thresholds=steps(GOOD, (WARN, 3.5 * D))),
        stat("Volsnap errors, 7 days", "Windows deleted or aborted shadow copies (Volsnap error events, for example "
             "25: the shadow copy storage could not grow in time).",
             [loki(VOLSNAP_ERRORS)], g(5, y + 1, 4, 5),
             unit="suffix: lost", decimals=0, thresholds=steps(GOOD, (CRIT, 1)),
             mappings=[vmap({0: ("✓ None", GOOD), 999999: ("✗ No Windows logs", CRIT)})]),
        logs("Volsnap and VSS errors", "Volsnap and VSS error events on the file servers, for 7 days.",
             '{job="windows", level="error"} | source=~"Volsnap|VSS" | json message="message", id="event_id" '
             '| line_format "{{.id}} {{.message}}"', g(9, y + 1, 15, 5), time_from="7d"),
    ]

    # Proxmox guests.
    y = 55
    panels.append(row("Proxmox guests · vzdump", y))
    panels += [
        stat("Guests without a backup job", "Guests (not templates) that no vzdump job covers, on each host.",
             [prom('count by (instance) (pve_not_backed_up_info{job="pve"} and on (instance, id) '
                   'pve_guest_info{job="pve", template="0"})', "{{instance}}")],
             g(0, y + 1, 5, 7), text_mode="value_and_name", value_size=18, no_value="✓ None", decimals=0),
        table("The guests", "Each guest that no vzdump job covers.", g(5, y + 1, 19, 7),
              [prom('max by (instance, id, name) (pve_guest_info{job="pve", template="0"} and on (instance, id) '
                    'pve_not_backed_up_info{job="pve"})', "", "A", fmt="table"),
               prom('max by (instance, id, name) (pve_up{job="pve", id=~"(qemu|lxc)/.+"} * on (instance, id) '
                    'group_left (name) pve_guest_info{job="pve", template="0"})', "", "B", fmt="table")],
              [{"id": "merge", "options": {}},
               {"id": "filterByValue", "options": {"filters": [{"fieldName": "Value #A", "config": {"id": "isNull"}}],
                                                   "type": "exclude", "match": "any"}},
               organize({"instance": "Host", "name": "Guest", "id": "ID", "Value #A": None, "Value #B": "State"})],
              overrides=[override("State", extra=text_cells({1: ("✓ Running", "text"), 0: ("○ Stopped", "text")})),
                         *widths(Host=150, Guest=220, ID=100)]),
    ]

    # Gaps.
    y = 63
    panels.append(row("Not monitored", y))
    panels.append(text("Gaps", GAPS, g(0, y + 1, 24, 13)))

    return {
        "uid": "backups",
        "title": "Backups & data protection",
        "description": "Every backup, snapshot and replica, with the age of its newest good copy, and the data that "
                       "has none. Rules and generator: LINDS-Kubernetes monitoring-overview/ (README).",
        "tags": ["overview", "backups"],
        "timezone": "browser", "editable": True, "graphTooltip": 1, "schemaVersion": 39,
        "time": {"from": "now-24h", "to": "now"}, "refresh": "5m",
        "links": [{"title": t, "type": "link", "url": f"/d/{u}", "icon": "dashboard"} for t, u in (
            ("Homelab overview", "overview"), ("Hardware", "hardware"), ("CloudNativePG", "cloudnative-pg"),
            ("Logs · Windows", "logs-windows"), ("Logs · Syslog", "logs-syslog"))],
        "templating": {"list": []},
        "annotations": {"list": []},
        "panels": panels,
    }


GAPS = """\
| Data | What protects it | What is missing | Smallest change that closes it |
|---|---|---|---|
| Kubernetes control plane (etcd on talos-cp) | Nothing. The manifests are in git; the persistent volumes keep their data (Retain). | No etcd snapshot. Secrets and objects made by hand are lost with talos-cp's disk. | A timer that runs `talosctl etcd snapshot` into the S3 bucket, and a metric of its time (LINDS-Terraform or LINDS-Ansible). |
| Proxmox guests | Nothing at guest level (no vzdump job). Their data is on ZFS or in DFS-R; Terraform and Ansible make them. | Router, DC and Talos system disks have no copy. | A decision: vzdump of the few guests that are slow to rebuild, or none. pve_not_backed_up_* then measures it. |
| Domain controllers (AD) | Replication between the four DCs. | No system state backup, and AD replication health is not on a dashboard. | `wbadmin start systemstatebackup` on one DC, weekly, and its result in the event log that Alloy sends (LINDS-Ansible). |
| DFS Replication | Events: errors only. | No backlog count, so a stuck replication with no error shows nothing. | Alloy on the file servers: `prometheus.exporter.windows` with the dfsr collector, or a task that logs `Get-DfsrBacklog` (LINDS-Ansible windows_logs). |
| Shadow copies | Two per weekday on jd-fs-01 D: and linds-dc E:. | No event says that a copy was made; only the VSS start is seen. | The shadow copy task logs the count of copies (`vssadmin list shadows`) to the Application log (LINDS-Ansible windows_fileserver). |
| TrueNAS replication | zettarepl's log. | A successful pull logs nothing at the end, so success is "a pull started and no ERROR". | TrueNAS SNMP has no replication data; the TrueNAS API (`replication.query`) through a small exporter would. |
| LINDS media (ZFS_NAS) and JD HDD-20T | Nothing (media that can be downloaded again). | No snapshots. | A decision. If wanted: a sanoid policy (HDD-20T) or a TrueNAS snapshot task (ZFS_NAS). |
"""


def write(name, cm_name, folder, key, header, dashboard):
    out = [header, "apiVersion: v1", "kind: ConfigMap", "metadata:", f"  name: {cm_name}", "  labels:",
           '    grafana_dashboard: "1"', "  annotations:", f"    grafana_folder: {folder}", "data:", f"  {key}: |"]
    body = "\n".join("    " + line for line in json.dumps(dashboard, indent=2, ensure_ascii=False).splitlines())
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), name), "w") as f:
        f.write("\n".join(out) + "\n" + body + "\n")


HEADER = """---
# Grafana dashboard "{title}" (uid {uid}), folder Overview.
#
# GENERATED by dashboards.py. Edit that file and run it again:
#   python3 monitoring-overview/dashboards.py"""

write("overview-dashboard.yaml", "overview-dashboard", "Overview", "overview.json",
      HEADER.format(title="Homelab overview", uid="overview"), overview())
write("backups-dashboard.yaml", "backups-dashboard", "Overview", "backups.json",
      HEADER.format(title="Backups & data protection", uid="backups"), backups())
