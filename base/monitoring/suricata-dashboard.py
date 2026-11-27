"""Generate the Suricata Grafana dashboard (suricata-dashboard.yaml).

    python3 base/monitoring/suricata-dashboard.py > base/monitoring/suricata-dashboard.yaml

Edit this file, not suricata-dashboard.yaml.

The layout is one section for each question, in this order: what did the
router block, what did it only report, then the ordinary traffic (DNS
lookups, TLS and QUIC sessions, plain HTTP). Each section has a table of the
events, newest first, and the totals next to it. The Router variable applies
to all panels.
"""
import json
import sys

DS = {"type": "loki", "uid": "loki"}
# Dark steps of the categorical palette that the Router and Hardware
# dashboards use. A router keeps its colour on each dashboard.
BLUE, ORANGE, AQUA, YELLOW, MAGENTA = "#3987e5", "#d95926", "#199e70", "#c98500", "#d55181"
ROUTER_COLOR = {"jd-router-01": BLUE, "linds-router-01": ORANGE}
# Status colours, for the alert severities only.
WARN, SERIOUS, CRIT = "#fab219", "#e8703a", "#d03b3b"

SEL = '{job="suricata", hostname=~"$router"%s}'
# `=~".*"` also matches an event that does not have the field.
BY_IP = ' | src_ip=~"$ip" or dest_ip=~"$ip"'

_ids = iter(range(1, 1000))


def sel(event_type):
    return SEL % (', event_type%s' % event_type)


def g(x, y, w, h):
    return {"x": x, "y": y, "w": w, "h": h}


def fixed(color):
    return {"mode": "fixed", "fixedColor": color}


def row(title, y, collapsed=False, panels=None):
    return {"type": "row", "id": next(_ids), "title": title, "gridPos": g(0, y, 24, 1), "collapsed": collapsed,
            "panels": panels or []}


def stat(title, desc, expr, grid):
    return {
        "type": "stat", "id": next(_ids), "title": title, "description": desc, "gridPos": grid, "datasource": DS,
        "targets": [{"refId": "A", "datasource": DS, "expr": expr, "queryType": "instant"}],
        "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                    "colorMode": "none", "graphMode": "none", "textMode": "value"},
        "fieldConfig": {"defaults": {"unit": "short", "noValue": "0"}, "overrides": []},
    }


def bars(title, desc, expr, legend, grid, overrides, decimals=None):
    """Events for each interval, stacked. One colour for each series, by name."""
    return {
        "type": "timeseries", "id": next(_ids), "title": title, "description": desc, "gridPos": grid,
        "datasource": DS,
        "targets": [{"refId": "A", "datasource": DS, "expr": expr, "legendFormat": legend, "queryType": "range"}],
        "options": {"legend": {"displayMode": "list", "placement": "bottom", "showLegend": True, "calcs": ["sum"]},
                    "tooltip": {"mode": "multi", "sort": "desc"}},
        "fieldConfig": {
            "defaults": {"unit": "short", "min": 0, "decimals": decimals, "color": {"mode": "palette-classic"},
                         "custom": {"drawStyle": "bars", "fillOpacity": 80, "lineWidth": 0, "barWidthFactor": 0.8,
                                    "showPoints": "never", "stacking": {"mode": "normal", "group": "A"}}},
            "overrides": overrides},
    }


def color_override(name, color, display=None):
    props = [{"id": "color", "value": fixed(color)}]
    if display:
        props.append({"id": "displayName", "value": display})
    return {"matcher": {"id": "byName", "options": name}, "properties": props}


ROUTER_OVERRIDES = [color_override(name, color) for name, color in ROUTER_COLOR.items()]


def width(name, px):
    return {"matcher": {"id": "byName", "options": name}, "properties": [{"id": "custom.width", "value": px}]}


def events(title, desc, expr, grid, columns, widths, overrides=None, lines=500):
    """A table of events, newest first. `columns` maps a field of the event to
    its heading, in display order; all other fields are hidden."""
    order = ["Time"] + list(columns)
    return {
        "type": "table", "id": next(_ids), "title": title, "description": desc, "gridPos": grid, "datasource": DS,
        "targets": [{"refId": "A", "datasource": DS, "expr": expr, "queryType": "range", "maxLines": lines,
                     "direction": "backward"}],
        "transformations": [
            # The labels and the structured metadata of each line become columns.
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
                width("Router", 130),
            ] + [width(name, px) for name, px in widths.items()] + (overrides or []),
        },
    }


def top(title, desc, expr, grid, columns, count="Events"):
    """The most frequent values in the time range, with a bar for the count."""
    rename = dict(columns)
    rename["Value #A"] = count
    return {
        "type": "table", "id": next(_ids), "title": title, "description": desc, "gridPos": grid, "datasource": DS,
        "targets": [{"refId": "A", "datasource": DS, "expr": expr, "queryType": "instant", "format": "table"}],
        "transformations": [
            {"id": "organize", "options": {"excludeByName": {"Time": True}, "renameByName": rename}},
            {"id": "sortBy", "options": {"sort": [{"field": count, "desc": True}]}},
        ],
        "options": {"cellHeight": "sm", "showHeader": True, "footer": {"show": False}},
        "fieldConfig": {
            "defaults": {"unit": "short", "custom": {"align": "left", "filterable": True}},
            "overrides": [{"matcher": {"id": "byName", "options": count},
                           "properties": [{"id": "custom.width", "value": 110},
                                          {"id": "custom.cellOptions",
                                           "value": {"type": "gauge", "mode": "basic", "valueDisplayMode": "text"}},
                                          {"id": "color", "value": fixed(BLUE)}]}],
        },
    }


SEVERITY = {"matcher": {"id": "byName", "options": "Severity"}, "properties": [
    {"id": "custom.width", "value": 95},
    {"id": "mappings", "value": [{"type": "value", "options": {
        "1": {"text": "▲ High", "color": CRIT, "index": 0},
        "2": {"text": "● Medium", "color": SERIOUS, "index": 1},
        "3": {"text": "▽ Low", "color": WARN, "index": 2}}}]},
    {"id": "custom.cellOptions", "value": {"type": "color-text"}}]}

blocked = sel('="alert"') + ' | alert_action="blocked"' + BY_IP
reported = sel('="alert"') + ' | alert_action!="blocked" | alert_severity=~"$severity"' + BY_IP
dns = sel('="dns"') + ' | dns_type!="response" | dns_rrname=~"(?i).*$name.*"' + BY_IP
tls = sel('=~"tls|quic"') + ' | tls_sni=~"(?i).*$name.*" or quic_sni=~"(?i).*$name.*"' + BY_IP
http = sel('="http"') + ' | http_hostname=~"(?i).*$name.*"' + BY_IP
# A block has a device on this side and a thing that was blocked: the name
# that the device asked for, or the address on the internet. The alert has a
# source and a destination; which one is the device depends on the direction.
# LOCAL matches an address on this side: private, link-local, or in the IPv6
# prefix of JD (change it if the ISP delegates another prefix). `[.]`, not a
# backslash: the text goes through JSON, Grafana and a Go template.
LOCAL = "^(10[.]|192[.]168[.]|172[.](1[6-9]|2[0-9]|3[01])[.]|fe80:|2001:8003:dc6f:63).*"
SRC_IS_LOCAL = '(eq (regexReplaceAll "%s" .src_ip "") "")' % LOCAL
THING = ("{{ if .dns_rrname }}{{ .dns_rrname }}{{ else if .tls_sni }}{{ .tls_sni }}"
         "{{ else if .http_hostname }}{{ .http_hostname }}{{ else if .quic_sni }}{{ .quic_sni }}"
         "{{ else if %s }}{{ .dest_ip }}{{ else }}{{ .src_ip }}{{ end }}" % SRC_IS_LOCAL)
BLOCK_FIELDS = (" | label_format device=`{{ if %s }}{{ .src_ip }}{{ else }}{{ .dest_ip }}{{ end }}`, "
                "blocked=`%s`, unblock=`router unblock %s`" % (SRC_IS_LOCAL, THING, THING))
UNBLOCK_HELP = """1. Find the block in the table above. **Blocked** is the name or the address.
2. On jd-router-01, run the command of the last column. Example:

       router unblock example.com

3. Wait about half a minute. The name and its subdomains (or the address) are not blocked any more. They are still logged.

| Command | What it does |
|---|---|
| `router blocked` | The last blocks, on the router |
| `router unblock` | The list of what is unblocked |
| `router reblock example.com` | Block it again |
| `router ips off 10` | Stop Suricata for 10 minutes, if a page fails and no block shows here |
"""
# One "name" column for a TLS and for a QUIC session.
SERVER_NAME = ' | label_format server_name=`{{ if .tls_sni }}{{ .tls_sni }}{{ else }}{{ .quic_sni }}{{ end }}`'


def count(query, by=None):
    inner = "count_over_time(%s [$__range])" % query
    return "sum by (%s) (%s)" % (by, inner) if by else "sum(%s)" % inner


def per_interval(query, by):
    return "sum by (%s) (count_over_time(%s [$__auto]))" % (by, query)


panels = []
y = 0
panels += [
    stat("Blocked", "What jd-router-01 stopped: traffic of an address on a list of hostile addresses, a DNS "
         "question or a connection for a name on a malware or phishing list, and traffic that matches a "
         "malware signature. linds-router-01 does not block.", count(blocked), g(0, y, 4, 4)),
    stat("Alerts", "Events that a rule reported and the router let through.", count(reported), g(4, y, 4, 4)),
    stat("High severity", "The alerts with severity 1.",
         count(sel('="alert"') + ' | alert_action!="blocked" | alert_severity="1"' + BY_IP), g(8, y, 4, 4)),
    stat("DNS lookups", "Names that devices asked the router for.", count(dns), g(12, y, 4, 4)),
    stat("TLS and QUIC sessions", "Encrypted sessions to and from the internet. Suricata reads the server name "
         "at the start of the session.", count(tls), g(16, y, 4, 4)),
    stat("HTTP requests", "Requests that were not encrypted.", count(http), g(20, y, 4, 4)),
]
y += 4
panels += [
    bars("Blocked and alerts", "Blocked connections and alerts for each interval, for each router.",
         per_interval(sel('="alert"') + BY_IP, "hostname"), "{{hostname}}", g(0, y, 12, 7), ROUTER_OVERRIDES,
         decimals=0),
    bars("Events", "All stored events for each interval, for each router. DNS answers and the engine's "
         "statistics are not stored.", per_interval(SEL % "", "hostname"), "{{hostname}}", g(12, y, 12, 7),
         ROUTER_OVERRIDES),
]
y += 7

panels.append(row("Blocked by the router", y))
y += 1
panels += [
    events("Blocked", "Each block, newest first. \"Device\" is the device on this side: the one that asked, or the "
           "published service that an outside address came to. \"Blocked\" is the name that the device asked "
           "for, or the address on the internet.\n\nTo unblock: run the command of the last column on "
           "jd-router-01 (it takes about half a minute). `router unblock` alone shows the list, and "
           "`router reblock` takes a name out again.", blocked + BLOCK_FIELDS, g(0, y, 24, 9),
           {"hostname": "Router", "device": "Device", "blocked": "Blocked", "dest_port": "Port",
            "alert_signature": "Why (the rule)", "unblock": "To unblock, on the router"},
           {"Device": 215, "Blocked": 250, "Port": 65, "To unblock, on the router": 330}),
    top("Most blocked", "The names and addresses that the router blocked most often in the time range.",
        "topk(20, %s)" % count(blocked + BLOCK_FIELDS, "blocked, hostname"), g(0, y + 9, 12, 9),
        {"blocked": "Blocked", "hostname": "Router"}, "Blocks"),
    {"type": "text", "id": next(_ids), "title": "How to unblock", "gridPos": g(12, y + 9, 12, 9),
     "options": {"mode": "markdown", "content": UNBLOCK_HELP}},
]
y += 18

panels.append(row("Alerts (reported, not blocked)", y))
y += 1
panels += [
    events("Alerts", "Each event that a rule reported, newest first. The router let these through.", reported,
           g(0, y, 16, 10),
           {"hostname": "Router", "alert_severity": "Severity", "src_ip": "From", "dest_ip": "To",
            "dest_port": "Port", "alert_signature": "Rule", "alert_category": "Category"},
           {"From": 200, "To": 200, "Port": 70, "Category": 180}, [SEVERITY]),
    top("Most frequent rules", "The rules with the most alerts in the time range.",
        "topk(20, %s)" % count(reported, "alert_signature, hostname"), g(16, y, 8, 10),
        {"alert_signature": "Rule", "hostname": "Router"}, "Alerts"),
]
y += 10

panels.append(row("DNS lookups", y))
y += 1
panels += [
    events("DNS lookups", "Each name that a device asked the router for, newest first (the last 500). A device "
           "that uses a different resolver is not shown. To see one device, put its address in \"Address\".",
           dns, g(0, y, 12, 11), {"hostname": "Router", "src_ip": "Device", "dns_rrname": "Name"}, {"Device": 250}),
    top("Most requested names", "", "topk(25, %s)" % count(dns, "dns_rrname"), g(12, y, 7, 11),
        {"dns_rrname": "Name"}, "Lookups"),
    top("Devices with the most lookups", "", "topk(25, %s)" % count(dns, "src_ip"), g(19, y, 5, 11),
        {"src_ip": "Device"}, "Lookups"),
]
y += 11

panels.append(row("TLS and QUIC sessions", y))
y += 1
panels += [
    events("TLS and QUIC sessions", "Each encrypted session, newest first (the last 500). \"Server name\" is the "
           "name that the device asked for (SNI). Suricata sees the WAN traffic only.", tls + SERVER_NAME,
           g(0, y, 15, 11),
           {"hostname": "Router", "src_ip": "From", "server_name": "Server name", "dest_port": "Port",
            "event_type": "Kind", "dest_ip": "To"},
           {"From": 235, "Server name": 260, "Port": 65, "Kind": 65}),
    top("Most frequent server names", "", "topk(25, %s)" % count(tls + SERVER_NAME, "server_name"),
        g(15, y, 5, 11), {"server_name": "Server name"}, "Sessions"),
    top("Devices with the most sessions", "", "topk(25, %s)" % count(tls, "src_ip"), g(20, y, 4, 11),
        {"src_ip": "From"}, "Sessions"),
]
y += 11

panels.append(row("HTTP requests (not encrypted)", y))
y += 1
panels += [
    events("HTTP requests", "Each request that was not encrypted, newest first (the last 500).", http,
           g(0, y, 16, 9),
           {"hostname": "Router", "src_ip": "From", "http_method": "Method", "http_hostname": "Host",
            "http_status": "Status", "dest_ip": "To", "dest_port": "Port"},
           {"From": 250, "Method": 85, "Status": 75, "To": 250, "Port": 70}),
    top("Most frequent hosts", "", "topk(20, %s)" % count(http, "http_hostname"), g(16, y, 8, 9),
        {"http_hostname": "Host"}, "Requests"),
]
y += 9

panels.append(row("Raw events", y, collapsed=True, panels=[{
    "type": "logs", "id": next(_ids), "title": "Raw events ($event_type)", "gridPos": g(0, y + 1, 24, 16),
    "datasource": DS,
    "description": "The event as Suricata wrote it (EVE JSON). Open a line to see all its fields.",
    "targets": [{"refId": "A", "datasource": DS, "queryType": "range", "maxLines": 1000,
                 "expr": sel('=~"$event_type"') + BY_IP + ' |~ "(?i)$name"'}],
    "options": {"showTime": True, "wrapLogMessage": True, "enableLogDetails": True, "sortOrder": "Descending",
                "dedupStrategy": "none", "prettifyLogMessage": True, "showLabels": False,
                "showCommonLabels": False, "enableInfiniteScrolling": True},
}]))


def textbox(name, label, default, desc):
    return {"name": name, "label": label, "description": desc, "type": "textbox", "query": default,
            "current": {"text": default, "value": default}, "options": []}


def label_values(name, label, label_name, desc, multi=True):
    return {"name": name, "label": label, "description": desc, "type": "query", "datasource": DS,
            "query": {"label": label_name, "refId": "LokiVariableQueryEditor-VariableQuery",
                      "stream": '{job="suricata"}', "type": 1},
            "definition": 'label_values({job="suricata"}, %s)' % label_name, "refresh": 2, "sort": 1,
            "multi": multi, "includeAll": True, "allValue": ".+", "current": {"text": "All", "value": "$__all"},
            "options": []}


dashboard = {
    "uid": "suricata",
    "title": "Suricata",
    "description": "What Suricata on the two routers blocked, reported and saw. Events go from the router to "
                   "Alloy (syslog, 172.16.1.23:1515) and then to Loki. Router side: LINDS-Ansible roles/router.",
    "tags": ["suricata", "network", "router", "logs"],
    "timezone": "browser", "editable": True, "graphTooltip": 1, "schemaVersion": 39, "refresh": "1m",
    "time": {"from": "now-6h", "to": "now"},
    "annotations": {"list": []},
    "links": [{"title": "DNS blocking", "type": "link", "url": "/d/dns-blocking", "icon": "dashboard"},
              {"title": "Router", "type": "link", "url": "/d/router", "icon": "dashboard"},
              {"title": "Network devices", "type": "link", "url": "/d/network-devices", "icon": "dashboard"}],
    "templating": {"list": [
        label_values("router", "Router", "hostname", "The router that saw the event."),
        textbox("ip", "Address", ".*", "An address at one end of the event, as a regular expression. "
                "Example: 192[.]168[.]1[.]20 for one device, 192[.]168[.]1[.].* for a network."),
        textbox("name", "Name contains", "", "Text in the DNS name, the server name or the HTTP host."),
        {"name": "severity", "label": "Alert severity", "type": "custom",
         "query": "High : 1,Medium : 2,Low : 3", "multi": True, "includeAll": True, "allValue": ".*",
         "current": {"text": "All", "value": "$__all"}, "options": []},
        label_values("event_type", "Raw events: type", "event_type", "For the section \"Raw events\" only."),
    ]},
    "panels": panels,
}

HEADER = """---
# Grafana dashboard for the Suricata events of jd-router-01 and
# linds-router-01: router -> rsyslog -> Alloy (172.16.1.23:1515/tcp) -> Loki.
# The Grafana dashboard sidecar reads it (label grafana_dashboard).
#
# GENERATED. Edit suricata-dashboard.py and make this file again:
#   python3 base/monitoring/suricata-dashboard.py > base/monitoring/suricata-dashboard.yaml
#
# The panels use the labels hostname and event_type and the structured
# metadata that Alloy attaches (applications/monitoring-loki.yaml: alert_*,
# src_ip, dest_ip, dns_*, tls_sni, quic_sni, http_*). No panel runs `| json`
# on the whole stream.
apiVersion: v1
kind: ConfigMap
metadata:
  name: suricata-dashboard
  namespace: monitoring
  labels:
    grafana_dashboard: "1"
  annotations:
    grafana_folder: Logs
data:
  suricata.json: |
"""

sys.stdout.write(HEADER)
for line in json.dumps(dashboard, indent=2, ensure_ascii=False).splitlines():
    sys.stdout.write("    " + line + "\n")
