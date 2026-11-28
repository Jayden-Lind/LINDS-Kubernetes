"""Generate the Ingress traffic Grafana dashboard (dashboard.yaml).

    python3 monitoring-ingress/dashboard.py > monitoring-ingress/dashboard.yaml

Edit this file, not dashboard.yaml.

The panels read the JSON access log of the two ingress controllers from Loki
(README.md lists the fields). Every log query starts with the same pipeline:
the access lines only, | json with the fields the panel needs, then the
filters of the variables Site, Source and Client. The last row reads the
controllers' own Prometheus metrics, which exist without the JSON log.
"""
import json
import sys

LOKI = {"type": "loki", "uid": "loki"}
PROM = {"type": "prometheus", "uid": "prometheus"}
# Dark steps of the categorical palette (as the Router, Suricata and Hardware
# dashboards). The controller keeps its colour on every panel: nginx blue,
# nginx-mtls (the internet endpoint) orange, as are public clients.
BLUE, ORANGE, AQUA, YELLOW, MAGENTA = "#3987e5", "#d95926", "#199e70", "#c98500", "#d55181"
# Status colours, for 4xx and 5xx and for the tripwire only.
GOOD, WARN, SERIOUS, CRIT = "#0ca30c", "#fab219", "#e8703a", "#d03b3b"

NS = {"nginx-ingress": "nginx (internal)", "nginx-ingress-mtls": "nginx-mtls (internet)"}
NS_COLOR = {"nginx-ingress": BLUE, "nginx-ingress-mtls": ORANGE}

# The access lines start with {"t":. The error log and the controller's own
# log lines in the same streams do not.
STREAM = '{namespace=~"$controller", container="nginx-ingress"}'
MTLS_STREAM = '{namespace="nginx-ingress-mtls", container="nginx-ingress"}'
ACCESS_LINE = ' |= "{\\"t\\":"'
# An address in a private range (or loopback) is internal; every other one is
# a client on the internet. `[.]`, not a backslash: the text goes through
# JSON, Grafana and a Go template.
PRIVATE = "^(10|127)[.].*|^192[.]168[.].*|^172[.](1[6-9]|2[0-9]|3[01])[.].*"
SOURCE = (' | label_format src=`{{ if eq (regexReplaceAll "%s" .ip "") "" }}internal{{ else }}public{{ end }}`'
          % PRIVATE)
# IDs in paths (UUIDs, long hex, timestamps, numbers) become placeholders, so
# a path is an endpoint, not one object. It also hides webhook IDs.
NORMALIZE = (' | label_format path=`{{ regexReplaceAll "/[0-9]+" (regexReplaceAll "[0-9a-fA-F]{16,}" '
             '(regexReplaceAll "[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}" '
             '(regexReplaceAll "[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:.]+(Z|[+-][0-9:]+)?" .path "{time}") "{uuid}") '
             '"{hex}") "/{n}" }}`')
# Requests that common scanners send. No app behind these ingresses runs PHP,
# so any .php is a probe. Families: secrets and version-control files,
# WordPress, PHP tools, path traversal, router/IoT exploits, Java and
# Exchange admin pages.
SCANNER = ('(?i).*(/[.](env|git|svn|hg|aws|ssh|ds_store|htpasswd|vscode)|wp-(login|admin|content|includes|config)'
           '|xmlrpc[.]php|[.]php([/?]|$)|phpmyadmin|/cgi-bin/|/etc/passwd|[.][.]/|%2e%2e|/actuator|/hnap1|/boaform'
           '|/manager/html|/owa/|/autodiscover|/vendor/phpunit|/solr/|/server-status).*')

_ids = iter(range(1, 1000))


def access(*fields, stream=STREAM):
    """The common pipeline: access lines, | json, then the variable filters."""
    names = ["sn", "ip"] + [f for f in fields if f not in ("sn", "ip")]
    js = ", ".join('%s="%s"' % (f, f) for f in names)
    return stream + ACCESS_LINE + " | json " + js + ' | sn=~"$site" | ip=~"$client"' + SOURCE + ' | src=~"$source"'


def mtls(*fields):
    return access(*fields, stream=MTLS_STREAM)


def count(query, by, rng="$__range"):
    return "sum by (%s) (count_over_time(%s [%s]))" % (by, query, rng)


def g(x, y, w, h):
    return {"x": x, "y": y, "w": w, "h": h}


def fixed(color):
    return {"mode": "fixed", "fixedColor": color}


def override(name, display=None, color=None, extra=None):
    props = []
    if display:
        props.append({"id": "displayName", "value": display})
    if color:
        props.append({"id": "color", "value": fixed(color)})
    props.extend(extra or [])
    return {"matcher": {"id": "byName", "options": name}, "properties": props}


NS_OVERRIDES = [override(ns, NS[ns], NS_COLOR[ns]) for ns in NS]


def target(expr, legend="", ref="A", instant=False, ds=LOKI, fmt=None):
    t = {"refId": ref, "datasource": ds, "expr": expr, "legendFormat": legend}
    if ds is LOKI:
        t["queryType"] = "instant" if instant else "range"
    else:
        t["range"] = not instant
        t["instant"] = instant
    if fmt:
        t["format"] = fmt
    return t


def row(title, y, collapsed=False, panels=None):
    return {"type": "row", "id": next(_ids), "title": title, "gridPos": g(0, y, 24, 1), "collapsed": collapsed,
            "panels": panels or []}


def stat(title, desc, targets, grid, unit="short", decimals=None, overrides=None, ds=LOKI, calc="lastNotNull",
         no_value="0", color=None, thresholds=None, mappings=None, text_mode="value_and_name"):
    defaults = {"unit": unit, "noValue": no_value, "color": color or {"mode": "fixed", "fixedColor": "text"},
                "mappings": mappings or []}
    if decimals is not None:
        defaults["decimals"] = decimals
    if thresholds:
        defaults["thresholds"] = thresholds
    return {
        "type": "stat", "id": next(_ids), "title": title, "description": desc, "gridPos": grid, "datasource": ds,
        "targets": targets,
        "options": {"reduceOptions": {"calcs": [calc], "fields": "", "values": False}, "colorMode": "value",
                    "graphMode": "none", "textMode": text_mode, "justifyMode": "auto", "orientation": "vertical",
                    "wideLayout": True, "text": {"valueSize": 22, "titleSize": 11}, "showPercentChange": False},
        "fieldConfig": {"defaults": defaults, "overrides": overrides or []},
    }


def series(title, desc, targets, grid, unit="short", overrides=None, ds=LOKI, bars=False, stack=False,
           decimals=None, soft_max=None, legend_calcs=None, color_mode="palette-classic"):
    custom = {"drawStyle": "bars" if bars else "line", "lineWidth": 0 if bars else 2,
              "fillOpacity": 80 if bars else 0, "showPoints": "never", "spanNulls": False,
              "stacking": {"mode": "normal" if stack else "none", "group": "A"}}
    if bars:
        custom["barWidthFactor"] = 0.8
    if soft_max is not None:
        custom["axisSoftMax"] = soft_max
    defaults = {"unit": unit, "min": 0, "color": {"mode": color_mode}, "custom": custom}
    if decimals is not None:
        defaults["decimals"] = decimals
    return {
        "type": "timeseries", "id": next(_ids), "title": title, "description": desc, "gridPos": grid,
        "datasource": ds, "targets": targets,
        "options": {"legend": {"displayMode": "table" if legend_calcs else "list", "placement": "bottom" if not legend_calcs else "right",
                               "showLegend": True, "calcs": legend_calcs or []},
                    "tooltip": {"mode": "multi", "sort": "desc"}},
        "fieldConfig": {"defaults": defaults, "overrides": overrides or []},
    }


def width(name, px):
    return override(name, extra=[{"id": "custom.width", "value": px}])


def bar_cell(name, color=BLUE):
    return override(name, color=color, extra=[
        {"id": "custom.cellOptions", "value": {"type": "gauge", "mode": "basic", "valueDisplayMode": "text"}},
        {"id": "custom.width", "value": 130}])


NS_CELL = override("Controller", extra=[{"id": "mappings", "value": [{"type": "value", "options": {
    ns: {"text": NS[ns], "color": NS_COLOR[ns], "index": i} for i, ns in enumerate(NS)}}]},
    {"id": "custom.cellOptions", "value": {"type": "color-text"}}, {"id": "custom.width", "value": 165}])
SRC_CELL = override("Source", extra=[{"id": "mappings", "value": [{"type": "value", "options": {
    "public": {"text": "internet", "color": ORANGE, "index": 0},
    "internal": {"text": "internal", "color": BLUE, "index": 1}}}]},
    {"id": "custom.cellOptions", "value": {"type": "color-text"}}, {"id": "custom.width", "value": 85}])
STATUS_CELL = override("Status", extra=[{"id": "mappings", "value": [
    {"type": "regex", "options": {"pattern": "^5..$", "result": {"color": CRIT, "index": 0}}},
    {"type": "regex", "options": {"pattern": "^4..$", "result": {"color": WARN, "index": 1}}}]},
    {"id": "custom.cellOptions", "value": {"type": "color-text"}}, {"id": "custom.width", "value": 70}])


def table(title, desc, targets, grid, columns, sort=None, overrides=None, ds=LOKI, merge=False, units=None):
    """Instant metric queries as a table. `columns` maps a field to its heading,
    in display order; every other field is hidden."""
    transformations = []
    if merge:
        transformations.append({"id": "merge", "options": {}})
    columns = dict(columns)
    if len(targets) == 1 and "Value #A" in columns:
        columns["Value"] = columns["Value #A"]
    transformations += [
        {"id": "filterFieldsByName", "options": {"include": {"names": list(columns)}}},
        {"id": "organize", "options": {"indexByName": {n: i for i, n in enumerate(columns)},
                                       "renameByName": columns}},
    ]
    if sort:
        transformations.append({"id": "sortBy", "options": {"sort": [{"field": sort, "desc": True}]}})
    ovr = list(overrides or [])
    for name, unit in (units or {}).items():
        ovr.append(override(name, extra=[{"id": "unit", "value": unit}]))
    return {
        "type": "table", "id": next(_ids), "title": title, "description": desc, "gridPos": grid, "datasource": ds,
        "targets": targets, "transformations": transformations,
        "options": {"cellHeight": "sm", "showHeader": True, "footer": {"show": False}},
        "fieldConfig": {"defaults": {"custom": {"align": "left", "filterable": True}, "noValue": ""},
                        "overrides": ovr},
    }


def tq(expr, ref="A"):
    """An instant Loki query for a table."""
    return target(expr, ref=ref, instant=True, fmt="table")


def events(title, desc, expr, grid, columns, widths, overrides=None, lines=500):
    """A table of log lines, newest first: each | json field is a column."""
    order = ["Time"] + list(columns)
    return {
        "type": "table", "id": next(_ids), "title": title, "description": desc, "gridPos": grid, "datasource": LOKI,
        "targets": [{"refId": "A", "datasource": LOKI, "expr": expr, "queryType": "range", "maxLines": lines,
                     "direction": "backward"}],
        "transformations": [
            {"id": "extractFields", "options": {"source": "labels", "format": "json", "replace": False,
                                                "keepTime": False}},
            {"id": "filterFieldsByName", "options": {"include": {"names": order}}},
            {"id": "organize", "options": {"indexByName": {n: i for i, n in enumerate(order)},
                                           "renameByName": columns}},
            {"id": "sortBy", "options": {"sort": [{"field": "Time", "desc": True}]}},
        ],
        "options": {"cellHeight": "sm", "showHeader": True, "footer": {"show": False}},
        "fieldConfig": {
            "defaults": {"custom": {"align": "left", "filterable": True, "inspect": True}, "noValue": ""},
            "overrides": [override("Time", extra=[{"id": "custom.width", "value": 165},
                                                  {"id": "unit", "value": "dateTimeAsLocal"}])]
            + [width(n, px) for n, px in widths.items()] + (overrides or []),
        },
    }


def text(title, content, grid):
    return {"type": "text", "id": next(_ids), "title": title, "gridPos": grid,
            "options": {"mode": "markdown", "content": content}}


ALL = access()
S = access("s")
FIVE = access("s") + ' | s=~"5.."'
FOUR = access("s") + ' | s=~"4.."'
RT = access("rt", "s") + ' | s!="101" | unwrap rt | __error__=""'
TTFB = access("uht") + ' | unwrap uht | __error__=""'
CLASS = access("s") + ' | label_format cls=`{{ printf "%.1sxx" .s }}`'
CLASS_OVERRIDES = [override("1xx", "1xx (websocket)", MAGENTA), override("2xx", color=BLUE),
                   override("3xx", color=AQUA), override("4xx", color=WARN), override("5xx", color=CRIT)]
ERROR_KIND = (access("s", "up") + ' | s=~"5.." | label_format kind=`{{ if hasPrefix "unix:" .up }}no ready pod (502)'
              '{{ else if eq .s "502" }}502 bad gateway{{ else if eq .s "503" }}503 unavailable'
              '{{ else if eq .s "504" }}504 timeout{{ else }}other 5xx (from the app){{ end }}`')
REFUSAL = (mtls("s", "cv", "allowed", "tls") + ' | s=~"400|408|421|444|495|496|497"'
           ' | label_format reason=`{{ if eq .s "444" }}{{ if eq .cv "NONE" }}no certificate'
           '{{ else if hasPrefix "FAILED" .cv }}certificate not trusted{{ else if eq .allowed "0" }}subject not allowed'
           '{{ else }}refused{{ end }}{{ else if eq .tls "" }}plain HTTP to port 443{{ else }}bad request{{ end }}`')
UNVERIFIED = mtls("s", "cv", "allowed") + ' | s=~"2..|101" | cv!="SUCCESS" or allowed!="1"'


def ratio(part):
    """part / all, by controller; 0 when part is empty."""
    p = count(part, "namespace")
    a = count(ALL, "namespace")
    return "(%s or %s * 0) / %s" % (p, a, a)


panels = []
y = 0
panels += [
    stat("Requests per second", "Average requests per second in the time range, by controller.",
         [target("sum by (namespace) (rate(%s [$__range]))" % ALL, "{{namespace}}", instant=True)],
         g(0, y, 4, 4), unit="reqps", decimals=2, overrides=NS_OVERRIDES),
    stat("Server errors (5xx)", "The share of requests answered with 5xx.",
         [target(ratio(FIVE), "{{namespace}}", instant=True)], g(4, y, 4, 4), unit="percentunit", decimals=2,
         overrides=NS_OVERRIDES),
    stat("Client errors (4xx)", "The share of requests answered with 4xx. On nginx-mtls this includes 444: a "
         "request without an allowed client certificate, closed with no answer.",
         [target(ratio(FOUR), "{{namespace}}", instant=True)], g(8, y, 4, 4), unit="percentunit", decimals=1,
         overrides=NS_OVERRIDES),
    stat("Request time p50", "Half of the requests took less than this (websockets left out).",
         [target("quantile_over_time(0.5, %s [$__range]) by (namespace)" % RT, "{{namespace}}", instant=True)],
         g(12, y, 4, 4), unit="s", decimals=3, overrides=NS_OVERRIDES, no_value="-"),
    stat("Request time p95", "95% of the requests took less than this (websockets left out). A long download "
         "or a stream counts its whole time: see time to first byte in \"Sites by latency\".",
         [target("quantile_over_time(0.95, %s [$__range]) by (namespace)" % RT, "{{namespace}}", instant=True)],
         g(16, y, 4, 4), unit="s", decimals=3, overrides=NS_OVERRIDES, no_value="-"),
    stat("Client addresses", "Different client addresses in the time range.",
         [target("count by (namespace) (%s)" % count(ALL, "namespace, ip"), "{{namespace}}", instant=True)],
         g(20, y, 4, 4), overrides=NS_OVERRIDES),
]
y += 4
panels += [
    table("Sites by server errors", "Each site (the server name that answered) in the time range, the most 5xx "
          "first. \"_\" is the default server: a host that no Ingress has.",
          [tq(count(ALL, "namespace, sn"), "A"), tq(count(FIVE, "namespace, sn"), "B"),
           tq("%s / %s" % (count(FIVE, "namespace, sn"), count(ALL, "namespace, sn")), "C")],
          g(0, y, 12, 8), {"sn": "Site", "namespace": "Controller", "Value #A": "Requests", "Value #B": "5xx",
                           "Value #C": "5xx share"}, sort="5xx", merge=True,
          overrides=[NS_CELL, bar_cell("5xx share", CRIT)], units={"5xx share": "percentunit"}),
    table("Sites by latency", "Request time is the whole request, to the last byte. Time to first byte is how "
          "long the app took to start its answer: the better sign of a slow app, because long downloads and "
          "streams do not count.",
          [tq(count(ALL, "namespace, sn"), "A"),
           tq("quantile_over_time(0.5, %s [$__range]) by (namespace, sn)" % RT, "B"),
           tq("quantile_over_time(0.95, %s [$__range]) by (namespace, sn)" % RT, "C"),
           tq("quantile_over_time(0.95, %s [$__range]) by (namespace, sn)" % TTFB, "D")],
          g(12, y, 12, 8), {"sn": "Site", "namespace": "Controller", "Value #A": "Requests",
                            "Value #B": "Request p50", "Value #C": "Request p95", "Value #D": "First byte p95"},
          sort="First byte p95", merge=True, overrides=[NS_CELL, bar_cell("First byte p95", YELLOW)],
          units={"Request p50": "s", "Request p95": "s", "First byte p95": "s"}),
]
y += 8

panels.append(row("Sites (the Site variable selects them)", y))
y += 1
panels += [
    series("Requests by status class", "Requests for each interval, stacked by status class.",
           [target(count(CLASS, "cls", "$__auto"), "{{cls}}")], g(0, y, 12, 8), bars=True, stack=True,
           overrides=CLASS_OVERRIDES, decimals=0),
    series("Server errors by kind", "\"no ready pod\": the Service had no ready pod, so nginx answered 502 "
           "itself. 502, 504: nginx could not reach the app or it did not answer in time. 503 and other 5xx "
           "mostly come from the app.",
           [target(count(ERROR_KIND, "kind", "$__auto"), "{{kind}}")], g(12, y, 12, 8), bars=True, stack=True,
           decimals=0, overrides=[override("no ready pod (502)", color=CRIT), override("502 bad gateway", color=SERIOUS),
                                  override("503 unavailable", color=MAGENTA), override("504 timeout", color=YELLOW),
                                  override("other 5xx (from the app)", color=AQUA)]),
]
y += 8
panels += [
    series("Request time", "Quantiles of the request time for each interval (websockets left out).",
           [target("quantile_over_time(0.5, %s [$__auto]) by (namespace)" % RT, "p50 {{namespace}}", "A"),
            target("quantile_over_time(0.95, %s [$__auto]) by (namespace)" % RT, "p95 {{namespace}}", "B"),
            target("quantile_over_time(0.99, %s [$__auto]) by (namespace)" % RT, "p99 {{namespace}}", "C")],
           g(0, y, 12, 8), unit="s",
           overrides=[override("p50 nginx-ingress", "p50 nginx", AQUA), override("p95 nginx-ingress", "p95 nginx", BLUE),
                      override("p99 nginx-ingress", "p99 nginx", MAGENTA),
                      override("p50 nginx-ingress-mtls", "p50 nginx-mtls", YELLOW),
                      override("p95 nginx-ingress-mtls", "p95 nginx-mtls", ORANGE),
                      override("p99 nginx-ingress-mtls", "p99 nginx-mtls", "#9085e9")]),
    series("Time to first byte p95, by site", "How long each site's app took to start its answer (95% of "
           "requests were faster). Pick sites with the Site variable to compare a few.",
           [target("quantile_over_time(0.95, %s [$__auto]) by (sn)" % TTFB, "{{sn}}")], g(12, y, 12, 8), unit="s",
           legend_calcs=["mean", "max"]),
]
y += 8
panels += [
    table("Paths with the most 5xx", "Paths that got 5xx in the time range. IDs in a path show as {uuid}, {hex}, "
          "{n} or {time}. 4xx are left out on purpose: a scan asks for thousands of different paths, and Loki "
          "refuses a query with more than 2000 series.",
          [tq("topk(20, %s)" % count(access("s", "path") + ' | s=~"5.."' + NORMALIZE, "sn, path, s"))],
          g(0, y, 12, 9), {"sn": "Site", "path": "Path", "s": "Status", "Value #A": "Requests"}, sort="Requests",
          overrides=[STATUS_CELL, bar_cell("Requests", CRIT), width("Site", 190)]),
    table("Paths with slow answers", "Requests whose app took more than 1 second to start its answer (time to "
          "first byte), by path. Long downloads and streams do not count, because their first byte is quick.",
          [tq("topk(20, %s)" % count(access("uht", "path") + ' | uht > 1 | __error__=""' + NORMALIZE, "sn, path"))],
          g(12, y, 12, 9), {"sn": "Site", "path": "Path", "Value #A": "Slow answers"}, sort="Slow answers",
          overrides=[bar_cell("Slow answers", YELLOW), width("Site", 190)]),
]
y += 9

panels.append(row("Clients", y))
y += 1
panels += [
    series("Internet and internal clients", "Requests for each interval by where the client is. Internal: a "
           "private address (LAN, VPN, pods). Internet: every other address. nginx sees the real address of an "
           "internet client: the router forwards port 443 without NAT and Cloudflare only serves DNS.",
           [target(count(ALL, "src", "$__auto"), "{{src}}")], g(0, y, 8, 8), bars=True, stack=True, decimals=0,
           overrides=[override("public", "internet", ORANGE), override("internal", color=BLUE)]),
    table("Clients with the most requests", "", [tq("topk(20, %s)" % count(ALL, "ip, src, namespace"))],
          g(8, y, 8, 8), {"ip": "Client", "src": "Source", "namespace": "Controller", "Value #A": "Requests"},
          sort="Requests", overrides=[SRC_CELL, NS_CELL, bar_cell("Requests")]),
    table("Clients with the most 4xx", "Many 401, 403 or 404 from one address is the shape of a scan or of "
          "password guessing. 444 and 400 on nginx-mtls are refused requests.",
          [tq("topk(20, %s)" % count(FOUR, "ip, src, s"))], g(16, y, 8, 8),
          {"ip": "Client", "src": "Source", "s": "Status", "Value #A": "Requests"}, sort="Requests",
          overrides=[SRC_CELL, STATUS_CELL, bar_cell("Requests", WARN)]),
]
y += 8
panels += [
    table("User agents", "", [tq("topk(20, %s)" % count(access("ua"), "ua, src"))], g(0, y, 12, 8),
          {"ua": "User agent", "src": "Source", "Value #A": "Requests"}, sort="Requests",
          overrides=[SRC_CELL, bar_cell("Requests")]),
    table("Unknown hosts", "Requests that no Ingress matched, so the default server answered (404, or 400 for a "
          "request without a Host). The host is what the client asked for. A TLS connection for an unknown name "
          "is refused in the handshake and leaves no line.",
          [tq("topk(20, %s)" % count(access("host", "s") + ' | sn="_"', "host, ip, src, s"))], g(12, y, 12, 8),
          {"host": "Host asked for", "ip": "Client", "src": "Source", "s": "Status", "Value #A": "Requests"},
          sort="Requests", overrides=[SRC_CELL, STATUS_CELL, bar_cell("Requests")]),
]
y += 8
panels += [
    events("Scanner requests", "Requests for paths that scanners try: secrets files (.env, .git), WordPress, "
           "PHP (no app here runs PHP), path traversal, router exploits, admin pages. The regex is SCANNER in "
           "monitoring-ingress/dashboard.py.",
           access("s", "m", "path", "host", "ua") + ' | path=~"%s"' % SCANNER, g(0, y, 16, 9),
           {"namespace": "Controller", "ip": "Client", "src": "Source", "host": "Host", "m": "Method", "path": "Path",
            "s": "Status", "ua": "User agent"},
           {"Client": 130, "Host": 170, "Method": 70, "Path": 300}, [NS_CELL, SRC_CELL, STATUS_CELL]),
    table("Scanner clients", "", [tq("topk(20, %s)" % count(access("path") + ' | path=~"%s"' % SCANNER, "ip, src"))],
          g(16, y, 8, 9), {"ip": "Client", "src": "Source", "Value #A": "Requests"}, sort="Requests",
          overrides=[SRC_CELL, bar_cell("Requests", WARN)]),
]
y += 9

panels.append(row("Logins and client certificates", y))
y += 1
panels += [
    series("401 and 403 by site", "Answers that mean \"log in first\" (401) or \"not allowed\" (403). The alert "
           "IngressAuthFailureBurst fires at 20 from one client to one site in 10 minutes.",
           [target(count(access("s") + ' | s=~"401|403"', "sn", "$__auto"), "{{sn}}")], g(0, y, 12, 8),
           bars=True, stack=True, decimals=0),
    series("nginx-mtls: refused requests by reason", "Why nginx-mtls refused a request. 444 closes the "
           "connection with no answer: no certificate, a certificate that linds-ca did not sign, or a subject "
           "that is not in the allow map. A plain HTTP request to port 443 and a request without a Host get 400.",
           [target(count(REFUSAL, "reason", "$__auto"), "{{reason}}")], g(12, y, 12, 8), bars=True, stack=True,
           decimals=0, overrides=[override("no certificate", color=BLUE), override("certificate not trusted", color=ORANGE),
                                  override("subject not allowed", color=AQUA), override("plain HTTP to port 443", color=YELLOW),
                                  override("bad request", color=MAGENTA)]),
]
y += 8
panels += [
    stat("Served without a verified certificate", "Requests that nginx-mtls served (2xx or 101) with no "
         "verified, allowed client certificate. This must be 0. The alert IngressMTLSPassedWithoutCertificate "
         "fires on one.",
         [target("sum(count_over_time(%s [$__range]))" % UNVERIFIED, "served", instant=True)], g(0, y, 4, 8),
         text_mode="value", color={"mode": "thresholds"},
         thresholds={"mode": "absolute", "steps": [{"color": GOOD, "value": None}, {"color": CRIT, "value": 1}]},
         mappings=[{"type": "value", "options": {"0": {"text": "✓ 0", "index": 0}}},
                   {"type": "range", "options": {"from": 1, "to": 1e12, "result": {"text": "✗ ${__value.text}", "index": 1}}}]),
    table("nginx-mtls requests by client certificate", "The subject of each client certificate that was "
          "presented, with the result of the check. Only subjects in the allow map (applications/"
          "nginx-ingress-mtls.yaml) get through.",
          [tq(count(mtls("dn", "cv", "allowed") + ' | cv!="NONE" | cv!=""', "dn, cv, allowed"))], g(4, y, 12, 8),
          {"dn": "Subject", "cv": "Check", "allowed": "Allowed", "Value #A": "Requests"}, sort="Requests",
          overrides=[bar_cell("Requests"), override("Allowed", extra=[{"id": "mappings", "value": [{"type": "value", "options": {
              "1": {"text": "yes", "color": GOOD, "index": 0}, "0": {"text": "no", "color": CRIT, "index": 1}}}]},
              {"id": "custom.cellOptions", "value": {"type": "color-text"}}, {"id": "custom.width", "value": 80}])]),
    table("Refused clients (nginx-mtls)", "Addresses that nginx-mtls refused most (444 and 400).",
          [tq("topk(20, %s)" % count(mtls("s") + ' | s=~"400|444"', "ip, src"))], g(16, y, 8, 8),
          {"ip": "Client", "src": "Source", "Value #A": "Refused"}, sort="Refused",
          overrides=[SRC_CELL, bar_cell("Refused", WARN)]),
]
y += 8

panels.append(row("Requests", y))
y += 1
panels.append(events(
    "Recent requests", "The newest 500 requests that match the variables. \"Status\" and \"Path contains\" "
    "apply only here. Time is the request time in seconds; Upstream is the app's status.",
    access("host", "m", "path", "proto", "s", "rt", "ups", "bytes", "tls", "cv", "ua")
    + ' | s=~"$status" | path=~"(?i).*$path.*"', g(0, y, 24, 14),
    {"namespace": "Controller", "ip": "Client", "src": "Source", "sn": "Site", "m": "Method", "path": "Path",
     "s": "Status", "rt": "Time", "ups": "Upstream", "bytes": "Bytes", "proto": "Protocol", "tls": "TLS",
     "cv": "Certificate", "ua": "User agent"},
    {"Client": 125, "Site": 180, "Method": 70, "Path": 320, "Time": 70, "Upstream": 80, "Bytes": 80,
     "Protocol": 85, "TLS": 75, "Certificate": 95}, [NS_CELL, SRC_CELL, STATUS_CELL]))
y += 14

# --- The controllers' own Prometheus metrics --------------------------------
PNS = 'namespace=~"$controller"'
LAT = 'nginx_ingress_controller_upstream_server_response_latency_ms'
panels.append(row("From the controllers' metrics (Prometheus)", y))
y += 1
panels += [
    series("Requests per second (nginx counter)", "From nginx's own counter. It also counts the exporter's "
           "scrape of each pod, about one request a minute per pod.",
           [target('sum by (namespace) (rate(nginx_ingress_nginx_http_requests_total{%s}[$__rate_interval]))' % PNS,
                   "{{namespace}}", ds=PROM)], g(0, y, 8, 8), unit="reqps", ds=PROM, overrides=NS_OVERRIDES),
    series("Upstream 5xx share by Ingress", "The share of the app's answers that were 5xx, for each Ingress. "
           "This counts only requests that reached an app: a site with no ready pod is not here.",
           [target('sum by (resource_namespace, resource_name) (rate(%s_count{%s, code=~"5.."}[$__rate_interval])) / '
                   'sum by (resource_namespace, resource_name) (rate(%s_count{%s}[$__rate_interval]))' % (LAT, PNS, LAT, PNS),
                   "{{resource_namespace}}/{{resource_name}}", ds=PROM)], g(8, y, 8, 8), unit="percentunit", ds=PROM,
           soft_max=0.05),
    series("Upstream response time p95 by Ingress", "From the controllers' latency histogram (the time to the "
           "app's whole answer). Websockets push it to the top bucket.",
           [target('histogram_quantile(0.95, sum by (le, resource_namespace, resource_name) (rate(%s_bucket{%s}[$__rate_interval]))) / 1000' % (LAT, PNS),
                   "{{resource_namespace}}/{{resource_name}}", ds=PROM)], g(16, y, 8, 8), unit="s", ds=PROM),
]
y += 8
panels += [
    table("Ingresses in the time range", "Requests that reached an app, by Ingress, from the latency histogram.",
          [target('sum by (class, resource_namespace, resource_name) (increase(%s_count{%s}[$__range]))' % (LAT, PNS),
                  ref="A", instant=True, ds=PROM, fmt="table"),
           target('sum by (class, resource_namespace, resource_name) (increase(%s_count{%s, code=~"5.."}[$__range])) / '
                  'sum by (class, resource_namespace, resource_name) (increase(%s_count{%s}[$__range]))' % (LAT, PNS, LAT, PNS),
                  ref="B", instant=True, ds=PROM, fmt="table"),
           target('histogram_quantile(0.95, sum by (le, class, resource_namespace, resource_name) (increase(%s_bucket{%s}[$__range]))) / 1000' % (LAT, PNS),
                  ref="C", instant=True, ds=PROM, fmt="table")],
          g(0, y, 10, 9), {"resource_namespace": "Namespace", "resource_name": "Ingress", "class": "Class",
                           "Value #A": "Requests", "Value #B": "5xx share", "Value #C": "p95"},
          sort="Requests", merge=True, ds=PROM, overrides=[bar_cell("Requests")],
          units={"5xx share": "percentunit", "p95": "s", "Requests": "short"}),
    table("Sites on the internet", "Hosts with an Ingress of class nginx-mtls: the mTLS mirrors that "
          "external-dns-public publishes in Cloudflare. The router forwards port 443 to nginx-mtls.",
          [target('max by (host, namespace, ingress) (kube_ingress_path * on (namespace, ingress) group_left '
                  'kube_ingress_info{ingressclass="nginx-mtls"})', ref="A", instant=True, ds=PROM, fmt="table")],
          g(10, y, 7, 9), {"host": "Host", "namespace": "Namespace", "ingress": "Mirror Ingress"}, ds=PROM),
    series("Active connections and reloads", "Open client connections per controller, and each nginx reload "
           "(the controller reloads nginx when an Ingress or its pods change).",
           [target('sum by (namespace) (nginx_ingress_nginx_connections_active{%s})' % PNS, "{{namespace}}", "A", ds=PROM),
            target('sum by (namespace) (increase(nginx_ingress_controller_nginx_reloads_total{%s}[$__rate_interval]))' % PNS,
                   "reloads {{namespace}}", "B", ds=PROM)],
           g(17, y, 7, 9), ds=PROM, overrides=NS_OVERRIDES + [
               override("reloads nginx-ingress", "reloads nginx", AQUA, [{"id": "custom.drawStyle", "value": "bars"}, {"id": "custom.fillOpacity", "value": 80}]),
               override("reloads nginx-ingress-mtls", "reloads nginx-mtls", YELLOW, [{"id": "custom.drawStyle", "value": "bars"}, {"id": "custom.fillOpacity", "value": 80}])]),
]
y += 9


def textbox(name, label, default, desc):
    return {"name": name, "label": label, "description": desc, "type": "textbox", "query": default,
            "current": {"text": default, "value": default}, "options": []}


dashboard = {
    "uid": "ingress-traffic",
    "title": "Ingress traffic",
    "description": "Requests through the two ingress controllers: nginx (LAN, VPN, pods) and nginx-mtls (the "
                   "internet endpoint, client certificate required). Read from their JSON access logs in Loki; "
                   "the last row from their Prometheus metrics. See monitoring-ingress/README.md.",
    "tags": ["ingress", "nginx", "network", "security", "logs"],
    "timezone": "browser", "editable": True, "graphTooltip": 1, "schemaVersion": 39, "refresh": "1m",
    "time": {"from": "now-24h", "to": "now"},
    "annotations": {"list": []},
    "links": [{"title": t, "type": "link", "url": "/d/" + u, "icon": "dashboard"} for t, u in [
        ("Overview", "overview"), ("Availability", "availability"), ("Security overview", "security-overview"),
        ("Security access", "security-access"), ("Suricata", "suricata"), ("Router", "router"),
        ("Logs / Kubernetes", "logs-kubernetes")]],
    "templating": {"list": [
        {"name": "controller", "label": "Controller", "type": "custom",
         "description": "nginx serves the LAN, the VPN and the pods. nginx-mtls is the internet endpoint: the "
                        "router forwards port 443 to it, and it requires a client certificate.",
         "query": "nginx (internal) : nginx-ingress,nginx-mtls (internet) : nginx-ingress-mtls",
         "multi": True, "includeAll": True, "allValue": "nginx-ingress|nginx-ingress-mtls",
         "current": {"text": "All", "value": "$__all"}, "options": []},
        {"name": "site", "label": "Site", "type": "query", "datasource": PROM,
         "description": "The host of an Ingress. All also includes \"_\", the default server.",
         "query": {"qryType": 1, "query": "label_values(kube_ingress_path, host)",
                   "refId": "PrometheusVariableQueryEditor-VariableQuery"},
         "definition": "label_values(kube_ingress_path, host)", "refresh": 2, "sort": 1, "multi": True,
         "includeAll": True, "allValue": ".*", "current": {"text": "All", "value": "$__all"}, "options": []},
        {"name": "source", "label": "Source", "type": "custom",
         "description": "Internal: a private address (LAN, VPN, pods). Internet: any other address.",
         "query": "internet : public,internal : internal", "multi": False, "includeAll": True, "allValue": ".*",
         "current": {"text": "All", "value": "$__all"}, "options": []},
        textbox("client", "Client", ".*", "Client address, as a regular expression. Example: 10[.]0[.]50[.]10"),
        textbox("status", "Status", ".*", "For \"Recent requests\": the status, as a regular expression. "
                "Example: 5.. or 401|403"),
        textbox("path", "Path contains", "", "For \"Recent requests\": text in the path."),
    ]},
    "panels": panels,
}

HEADER = """---
# Grafana dashboard "Ingress traffic" (uid ingress-traffic, folder Network):
# requests through the nginx and nginx-mtls controllers, by site, client,
# status and latency, and the client-certificate gate of nginx-mtls. Picked
# up by the Grafana dashboard sidecar (label grafana_dashboard).
#
# GENERATED by dashboard.py. Edit that file and run it again:
#   python3 monitoring-ingress/dashboard.py > monitoring-ingress/dashboard.yaml
#
# The data: the JSON access logs of both controllers in Loki (README.md lists
# the fields), parsed at query time with | json; the last row reads the
# controllers' Prometheus metrics.
apiVersion: v1
kind: ConfigMap
metadata:
  name: ingress-traffic-dashboard
  labels:
    grafana_dashboard: "1"
  annotations:
    grafana_folder: Network
data:
  ingress-traffic.json: |
"""

if __name__ == "__main__":
    sys.stdout.write(HEADER)
    for line in json.dumps(dashboard, indent=2, ensure_ascii=False).splitlines():
        sys.stdout.write("    " + line + "\n")
