"""Generate the DNS blocking Grafana dashboard (dns-blocking-dashboard.yaml).

    python3 base/monitoring/dns-blocking-dashboard.py > base/monitoring/dns-blocking-dashboard.yaml

Edit this file, not dns-blocking-dashboard.yaml.

Unbound on each router refuses the names on its blocklists (LINDS-Ansible
roles/router, "DNS blocklists"). Two sources:
  * Loki: one line for each refused question, from Unbound's log
    ({job="syslog", appname="unbound"} |= "rpz: applied"):
    "rpz: applied [LIST] TRIGGER rpz-nxdomain CLIENT@port NAME. TYPE IN".
  * Prometheus: the counters that `router metrics` writes (router_dns_*).
"""
import json
import sys

LOKI = {"type": "loki", "uid": "loki"}
PROM = {"type": "prometheus", "uid": "prometheus"}
# The categorical palette of the Router, Hardware and Suricata dashboards. A
# router keeps its colour on each dashboard; the lists take the next slots.
BLUE, ORANGE, AQUA, YELLOW, MAGENTA = "#3987e5", "#d95926", "#199e70", "#c98500", "#d55181"
ROUTER_COLOR = {"jd-router-01": BLUE, "linds-router-01": ORANGE}
LIST_COLOR = {"ads": AQUA, "malware": MAGENTA, "phishing": YELLOW}
LIST_NAME = {"ads": "Advertising and trackers", "malware": "Malware", "phishing": "Phishing"}

# One refused question, with its parts as labels. A device is the address
# that asked: a DNS forwarder (the cluster's DNS, a domain controller) shows
# in place of the devices behind it.
REFUSED = ('{job="syslog", appname="unbound", hostname=~"$router"} |= "rpz: applied" '
           '| pattern "<_>rpz: applied [<list>] <_> <action> <device>@<_> <name>. <qtype> IN" '
           '| action="rpz-nxdomain" | list=~"$list" | device=~"$device" | name=~"(?i).*$name.*"')
UNBLOCK = " | label_format unblock=`router unblock {{ .name }}`"

_ids = iter(range(1, 1000))


def g(x, y, w, h):
    return {"x": x, "y": y, "w": w, "h": h}


def fixed(color):
    return {"mode": "fixed", "fixedColor": color}


def color_override(name, color, display=None):
    props = [{"id": "color", "value": fixed(color)}]
    if display:
        props.append({"id": "displayName", "value": display})
    return {"matcher": {"id": "byName", "options": name}, "properties": props}


def width(name, px):
    return {"matcher": {"id": "byName", "options": name}, "properties": [{"id": "custom.width", "value": px}]}


def stat(title, desc, ds, expr, grid, unit="short", decimals=None):
    target = {"refId": "A", "datasource": ds, "expr": expr}
    target.update({"queryType": "instant"} if ds is LOKI else {"instant": True, "range": False})
    return {
        "type": "stat", "id": next(_ids), "title": title, "description": desc, "gridPos": grid, "datasource": ds,
        "targets": [target],
        "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                    "colorMode": "none", "graphMode": "none", "textMode": "value"},
        "fieldConfig": {"defaults": {"unit": unit, "decimals": decimals, "noValue": "0"}, "overrides": []},
    }


def bars(title, desc, expr, legend, grid, overrides):
    return {
        "type": "timeseries", "id": next(_ids), "title": title, "description": desc, "gridPos": grid,
        "datasource": LOKI,
        "targets": [{"refId": "A", "datasource": LOKI, "expr": expr, "legendFormat": legend, "queryType": "range"}],
        "options": {"legend": {"displayMode": "list", "placement": "bottom", "showLegend": True, "calcs": ["sum"]},
                    "tooltip": {"mode": "multi", "sort": "desc"}},
        "fieldConfig": {
            "defaults": {"unit": "short", "min": 0, "decimals": 0, "color": {"mode": "palette-classic"},
                         "custom": {"drawStyle": "bars", "fillOpacity": 80, "lineWidth": 0, "barWidthFactor": 0.8,
                                    "showPoints": "never", "stacking": {"mode": "normal", "group": "A"}}},
            "overrides": overrides},
    }


def events(title, desc, expr, grid, columns, widths, lines=1000):
    order = ["Time"] + list(columns)
    return {
        "type": "table", "id": next(_ids), "title": title, "description": desc, "gridPos": grid, "datasource": LOKI,
        "targets": [{"refId": "A", "datasource": LOKI, "expr": expr, "queryType": "range", "maxLines": lines,
                     "direction": "backward"}],
        "transformations": [
            {"id": "extractFields", "options": {"source": "labels", "format": "json", "replace": False,
                                                "keepTime": False}},
            {"id": "filterFieldsByName", "options": {"include": {"names": order}}},
            {"id": "organize", "options": {"indexByName": {name: i for i, name in enumerate(order)},
                                           "renameByName": columns}},
            {"id": "sortBy", "options": {"sort": [{"field": "Time", "desc": True}]}},
        ],
        "options": {"cellHeight": "sm", "showHeader": True, "footer": {"show": False}},
        "fieldConfig": {
            "defaults": {"custom": {"align": "left", "filterable": True, "inspect": True}, "noValue": ""},
            "overrides": [
                {"matcher": {"id": "byName", "options": "Time"},
                 "properties": [{"id": "custom.width", "value": 178}, {"id": "unit", "value": "dateTimeAsLocal"}]},
                {"matcher": {"id": "byName", "options": "List"},
                 "properties": [{"id": "custom.width", "value": 190},
                                {"id": "mappings", "value": [{"type": "value", "options": {
                                    k: {"text": v, "index": i} for i, (k, v) in enumerate(LIST_NAME.items())}}]}]},
            ] + [width(name, px) for name, px in widths.items()],
        },
    }


def top(title, desc, expr, grid, columns, count):
    rename = dict(columns)
    rename["Value #A"] = count
    list_mapping = [{"matcher": {"id": "byName", "options": "List"},
                     "properties": [{"id": "custom.width", "value": 190},
                                    {"id": "mappings", "value": [{"type": "value", "options": {
                                        k: {"text": v, "index": i} for i, (k, v) in enumerate(LIST_NAME.items())}}]}]}]
    return {
        "type": "table", "id": next(_ids), "title": title, "description": desc, "gridPos": grid, "datasource": LOKI,
        "targets": [{"refId": "A", "datasource": LOKI, "expr": expr, "queryType": "instant", "format": "table"}],
        "transformations": [
            {"id": "organize", "options": {"excludeByName": {"Time": True}, "renameByName": rename,
                                           "indexByName": {name: i for i, name in enumerate(columns)}}},
            {"id": "sortBy", "options": {"sort": [{"field": count, "desc": True}]}},
        ],
        "options": {"cellHeight": "sm", "showHeader": True, "footer": {"show": False}},
        "fieldConfig": {
            "defaults": {"unit": "short", "custom": {"align": "left", "filterable": True}},
            "overrides": list_mapping + [
                {"matcher": {"id": "byName", "options": count},
                 "properties": [{"id": "custom.width", "value": 120},
                                {"id": "custom.cellOptions",
                                 "value": {"type": "gauge", "mode": "basic", "valueDisplayMode": "text"}},
                                {"id": "color", "value": fixed(BLUE)}]}],
        },
    }


def count(by=None):
    inner = "count_over_time(%s [$__range])" % REFUSED
    return "sum by (%s) (%s)" % (by, inner) if by else "sum(%s)" % inner


UNBLOCK_HELP = """1. Find the name in the table above.
2. On the router of that row, run the command of the last column. Example:

       router unblock example.com

3. The name and its subdomains resolve at once. On jd-router-01 the command takes about half a minute, because Suricata loads its rules again.

| Command | What it does |
|---|---|
| `router blocked` | The last blocks, on the router |
| `router unblock` | The list of what is unblocked |
| `router reblock example.com` | Block it again |

Each router has its own list. A name that the two sites need: run the command on the two routers.
"""

METRIC = '{job="router-node", instance=~"$router"}'
panels = []
y = 0
panels += [
    stat("Refused", "DNS questions that a blocklist refused. The device gets \"no such name\" at once. One page "
         "can ask for the same name more than once, and for more than one record type.", LOKI, count(),
         g(0, y, 5, 4)),
    stat("Share of all lookups", "Refused questions as a part of all questions to the routers.", PROM,
         "sum(increase(router_dns_blocked_total%s[$__range])) / sum(increase(router_dns_queries_total%s[$__range]))"
         % (METRIC, METRIC), g(5, y, 5, 4), unit="percentunit", decimals=1),
    stat("Devices with a refused lookup", "Addresses that asked for a listed name. A DNS forwarder (the cluster's "
         "DNS, a domain controller) counts as one device.", LOKI, "count(%s)" % count("device"), g(10, y, 5, 4)),
    stat("Names on the lists", "The names of all lists of one router (the two routers have the same lists).", PROM,
         "max(sum by (instance) (router_dns_blocklist_names%s))" % METRIC, g(15, y, 5, 4)),
    stat("Oldest list", "The time since the list that changed longest ago was fetched with a change. The lists "
         "are fetched each day; most of them change each day.", PROM,
         "time() - min(router_dns_blocklist_changed_timestamp_seconds%s)" % METRIC, g(20, y, 4, 4), unit="s",
         decimals=0),
]
y += 4
panels += [
    bars("Refused, by list", "Refused questions for each interval.",
         "sum by (list) (count_over_time(%s [$__auto]))" % REFUSED, "{{list}}", g(0, y, 12, 7),
         [color_override(k, LIST_COLOR[k], LIST_NAME[k]) for k in LIST_COLOR]),
    bars("Refused, by router", "Refused questions for each interval.",
         "sum by (hostname) (count_over_time(%s [$__auto]))" % REFUSED, "{{hostname}}", g(12, y, 12, 7),
         [color_override(k, v) for k, v in ROUTER_COLOR.items()]),
]
y += 7
panels += [
    top("Most refused names", "The names that were refused most often in the time range.",
        "topk(30, %s)" % count("name, list"), g(0, y, 14, 11), {"name": "Name", "list": "List"}, "Refused"),
    top("Devices with the most refused lookups", "A device with many refused lookups has apps or pages with many "
        "trackers, or software that asks again and again. Put its address in \"Device\" to see what it asks for.",
        "topk(30, %s)" % count("device, hostname"), g(14, y, 10, 11), {"device": "Device", "hostname": "Router"},
        "Refused"),
]
y += 11
panels += [
    events("Refused lookups", "Each refused question, newest first (the last 1,000). To unblock a name: run the "
           "command of the last column on the router of that row.", REFUSED + UNBLOCK, g(0, y, 24, 11),
           {"hostname": "Router", "device": "Device", "name": "Name", "qtype": "Type", "list": "List",
            "unblock": "To unblock, on the router"},
           {"Router": 130, "Device": 260, "Type": 75, "To unblock, on the router": 420}),
]
y += 11
panels.append({"type": "text", "id": next(_ids), "title": "How to unblock", "gridPos": g(0, y, 24, 10),
               "options": {"mode": "markdown", "content": UNBLOCK_HELP}})


def textbox(name, label, default, desc):
    return {"name": name, "label": label, "description": desc, "type": "textbox", "query": default,
            "current": {"text": default, "value": default}, "options": []}


dashboard = {
    "uid": "dns-blocking",
    "title": "DNS blocking",
    "description": "The names that Unbound on the two routers refuses: advertising, trackers, malware and "
                   "phishing. Router side: LINDS-Ansible roles/router, \"DNS blocklists\".",
    "tags": ["dns", "network", "router", "logs"],
    "timezone": "browser", "editable": True, "graphTooltip": 1, "schemaVersion": 39, "refresh": "1m",
    "time": {"from": "now-24h", "to": "now"},
    "annotations": {"list": []},
    "links": [{"title": "Suricata", "type": "link", "url": "/d/suricata", "icon": "dashboard"},
              {"title": "Router", "type": "link", "url": "/d/router", "icon": "dashboard"}],
    "templating": {"list": [
        {"name": "router", "label": "Router", "description": "The router that refused the question.",
         "type": "query", "datasource": LOKI,
         "query": {"label": "hostname", "refId": "LokiVariableQueryEditor-VariableQuery",
                   "stream": '{job="syslog", appname="unbound"}', "type": 1},
         "definition": 'label_values({job="syslog", appname="unbound"}, hostname)', "refresh": 2, "sort": 1,
         "multi": True, "includeAll": True, "allValue": ".+", "current": {"text": "All", "value": "$__all"},
         "options": []},
        {"name": "list", "label": "List", "type": "custom",
         "query": "Advertising and trackers : ads,Malware : malware,Phishing : phishing", "multi": True,
         "includeAll": True, "allValue": ".+", "current": {"text": "All", "value": "$__all"}, "options": []},
        textbox("device", "Device", ".*", "The address that asked, as a regular expression. Example: "
                "192[.]168[.]1[.]20 for one device."),
        textbox("name", "Name contains", "", "Text in the name."),
    ]},
    "panels": panels,
}

HEADER = """---
# Grafana dashboard for the DNS blocklists of jd-router-01 and
# linds-router-01 (Unbound). The Grafana dashboard sidecar reads it (label
# grafana_dashboard).
#
# GENERATED. Edit dns-blocking-dashboard.py and make this file again:
#   python3 base/monitoring/dns-blocking-dashboard.py > base/monitoring/dns-blocking-dashboard.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: dns-blocking-dashboard
  namespace: monitoring
  labels:
    grafana_dashboard: "1"
  annotations:
    grafana_folder: Network
data:
  dns-blocking.json: |
"""

sys.stdout.write(HEADER)
for line in json.dumps(dashboard, indent=2, ensure_ascii=False).splitlines():
    sys.stdout.write("    " + line + "\n")
