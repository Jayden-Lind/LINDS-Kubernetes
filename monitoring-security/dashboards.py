"""Generate the two security dashboards of this directory.

    python3 monitoring-security/dashboards.py

The script writes security-overview-dashboard.yaml and
security-access-dashboard.yaml next to itself. Edit this file, not the YAML
files. With --check it writes nothing and fails if a YAML file is not what the
script makes.

- "Security overview" (uid security-overview): is something attacking or
  failing now, and are the defences on? Each block links to the dashboard
  that has the detail.
- "Access and logins" (uid security-access): who logged in to what, from
  where, and what failed: SSH, sudo, Proxmox, the VPN, the Windows domain,
  Keycloak, Argo CD, Grafana and Vault.

No query names a person, an account or an address. The panels find them in
the logs when they run. The variables "User" and "Source address" are empty
patterns until someone types in them.
"""
import json
import pathlib
import sys

LOKI = {"type": "loki", "uid": "loki"}
PROM = {"type": "prometheus", "uid": "prometheus"}

# The dark steps of the categorical palette that the Router, Hardware,
# Suricata and DNS blocking dashboards use. A thing keeps its colour on each
# panel. Status colours are for states only.
BLUE, ORANGE, AQUA, YELLOW, MAGENTA = "#3987e5", "#d95926", "#199e70", "#c98500", "#d55181"
GREEN, VIOLET, RED = "#0ca30c", "#9085e9", "#e66767"
GOOD, WARN, SERIOUS, CRIT = "#0ca30c", "#fab219", "#ec835a", "#d03b3b"
GREY = "#8e8e8e"

HOST_COLOR = {
    "jd-router-01": BLUE, "linds-router-01": ORANGE, "jd-proxmox-02": AQUA, "linds-proxmox-01": YELLOW,
    "JD-Torrent-01": MAGENTA, "LINDS-Torrent-02": GREEN, "LINDS-Plex-01": VIOLET,
    "linds-truenas-01.linds.com.au": RED,
    # The Windows servers are on their own panels.
    "jd-dc-01": BLUE, "linds-dc": ORANGE, "jd-fs-01": AQUA, "linds-dc2": YELLOW,
}
SYSTEMS = ["SSH", "sudo and su", "Proxmox", "VPN", "Windows domain", "Keycloak", "Argo CD", "Grafana"]
SYSTEM_COLOR = dict(zip(SYSTEMS, [BLUE, ORANGE, AQUA, YELLOW, MAGENTA, GREEN, VIOLET, RED]))

HERE = pathlib.Path(__file__).resolve().parent

# The other dashboards, by uid.
D = {
    "overview": "/d/security-overview", "access": "/d/security-access", "suricata": "/d/suricata",
    "dns": "/d/dns-blocking", "devices": "/d/network-devices", "windows": "/d/logs-windows", "router": "/d/router",
    "home": "/d/overview", "availability": "/d/availability", "backups": "/d/backups",
    "ingress": "/d/ingress-traffic",
}


# --- Panel helpers -----------------------------------------------------------

class Ids:
    def __init__(self):
        self.n = 0

    def __call__(self):
        self.n += 1
        return self.n


def g(x, y, w, h):
    return {"x": x, "y": y, "w": w, "h": h}


def fixed(color):
    return {"mode": "fixed", "fixedColor": color}


def link(title, url):
    return {"title": title, "url": url + "?${__url_time_range}"}


def color_overrides(colors):
    return [{"matcher": {"id": "byName", "options": name}, "properties": [{"id": "color", "value": fixed(c)}]}
            for name, c in colors.items()]


def width(name, px):
    return {"matcher": {"id": "byName", "options": name}, "properties": [{"id": "custom.width", "value": px}]}


def mapping_override(name, values, px=None, color_text=True):
    """Value mappings for one table column: {value: (text, colour or None)}."""
    opts = {}
    for i, (v, (text, color)) in enumerate(values.items()):
        opts[v] = {"text": text, "index": i}
        if color:
            opts[v]["color"] = color
    props = [{"id": "mappings", "value": [{"type": "value", "options": opts}]}]
    if color_text:
        # A value without a colour of its own keeps the text colour.
        props += [{"id": "custom.cellOptions", "value": {"type": "color-text"}},
                  {"id": "color", "value": fixed("text")}]
    if px:
        props.append({"id": "custom.width", "value": px})
    return {"matcher": {"id": "byName", "options": name}, "properties": props}


class Builder:
    def __init__(self):
        self.ids = Ids()

    def row(self, title, y, collapsed=False, panels=None):
        return {"type": "row", "id": self.ids(), "title": title, "gridPos": g(0, y, 24, 1),
                "collapsed": collapsed, "panels": panels or []}

    def text(self, title, content, grid):
        return {"type": "text", "id": self.ids(), "title": title, "gridPos": grid,
                "options": {"mode": "markdown", "content": content}}

    def stat(self, title, desc, targets, grid, ds=LOKI, unit="short", mappings=None, steps=None,
             no_value="0", links=None, color_mode="value", decimals=None, text_mode="value_and_name"):
        """One number, or one tile for each series. `steps` are threshold steps
        [(value, colour)]; without them the number is in the text colour."""
        steps = steps or [(None, "text")]
        return {
            "type": "stat", "id": self.ids(), "title": title, "description": desc, "gridPos": grid, "datasource": ds,
            "targets": [dict(t, datasource=ds) for t in targets],
            "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                        "colorMode": color_mode, "graphMode": "none", "textMode": text_mode,
                        "justifyMode": "center", "orientation": "auto", "wideLayout": True,
                        "showPercentChange": False},
            "fieldConfig": {
                "defaults": {"unit": unit, "noValue": no_value, "decimals": decimals,
                             "mappings": mappings or [],
                             "color": {"mode": "thresholds"},
                             "thresholds": {"mode": "absolute",
                                            "steps": [{"value": v, "color": c} for v, c in steps]}},
                "overrides": []},
            "links": links or [],
        }

    def bars(self, title, desc, targets, grid, ds=LOKI, colors=None, unit="short", links=None, decimals=None,
             hidden=None):
        """Counts for each interval, stacked, one colour for each series."""
        return {
            "type": "timeseries", "id": self.ids(), "title": title, "description": desc, "gridPos": grid,
            "datasource": ds, "targets": [dict(t, datasource=ds) for t in targets],
            "options": {"legend": {"displayMode": "list", "placement": "bottom", "showLegend": True,
                                   "calcs": ["sum"]},
                        "tooltip": {"mode": "multi", "sort": "desc"}},
            "fieldConfig": {
                "defaults": {"unit": unit, "min": 0, "decimals": decimals, "color": {"mode": "palette-classic"},
                             "custom": {"drawStyle": "bars", "fillOpacity": 80, "lineWidth": 0,
                                        "barWidthFactor": 0.8, "showPoints": "never",
                                        "stacking": {"mode": "normal", "group": "A"},
                                        # Counts: at least 0 to 5, so that a small count has whole
                                        # numbers on the axis (and an empty panel is not 0 to 0).
                                        "axisSoftMax": 5}},
                "overrides": color_overrides(colors or {}) + [
                    # In the legend and the tooltip, not drawn: a series that would flatten the others.
                    {"matcher": {"id": "byName", "options": name},
                     "properties": [{"id": "custom.hideFrom", "value": {"legend": False, "tooltip": False,
                                                                        "viz": True}}]}
                    for name in (hidden or [])]},
            "links": links or [],
        }

    def lines(self, title, desc, targets, grid, ds=PROM, colors=None, unit="short", links=None):
        """Rates or levels over time, one line for each series."""
        p = self.bars(title, desc, targets, grid, ds, colors, unit, links, decimals=None)
        p["fieldConfig"]["defaults"]["custom"].update(
            {"drawStyle": "line", "fillOpacity": 10, "lineWidth": 2, "stacking": {"mode": "none", "group": "A"}})
        p["options"]["legend"]["calcs"] = ["mean", "max"]
        return p

    def events(self, title, desc, expr, grid, columns, widths=None, overrides=None, lines=500, links=None):
        """A table of log lines, newest first. `columns` maps a label of the
        line (stream label, structured metadata or parsed label) to its heading,
        in display order. All other fields are hidden."""
        order = ["Time"] + list(columns)
        return {
            "type": "table", "id": self.ids(), "title": title, "description": desc, "gridPos": grid,
            "datasource": LOKI,
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
                     "properties": [{"id": "custom.width", "value": 182},
                                    {"id": "unit", "value": "dateTimeAsLocal"}]},
                ] + [width(name, px) for name, px in (widths or {}).items()] + (overrides or []),
            },
            "links": links or [],
        }

    def top(self, title, desc, expr, grid, columns, count="Events", ds=LOKI, overrides=None, links=None,
            unit="short"):
        """The most frequent values in the time range, with a bar for the count."""
        rename = dict(columns)
        value = "Value #A" if ds == LOKI else "Value"
        rename[value] = count
        return {
            "type": "table", "id": self.ids(), "title": title, "description": desc, "gridPos": grid,
            "datasource": ds,
            "targets": [{"refId": "A", "datasource": ds, "expr": expr, "queryType": "instant", "instant": True,
                         "range": False, "format": "table"}],
            "transformations": [
                {"id": "organize", "options": {"excludeByName": {"Time": True}, "renameByName": rename,
                                               "indexByName": {name: i for i, name in
                                                               enumerate(list(columns) + [value])}}},
                {"id": "sortBy", "options": {"sort": [{"field": count, "desc": True}]}},
            ],
            "options": {"cellHeight": "sm", "showHeader": True, "footer": {"show": False}},
            "fieldConfig": {
                "defaults": {"unit": unit, "custom": {"align": "left", "filterable": True}, "noValue": ""},
                "overrides": [{"matcher": {"id": "byName", "options": count},
                               "properties": [{"id": "custom.width", "value": 110},
                                              {"id": "custom.cellOptions",
                                               "value": {"type": "gauge", "mode": "basic",
                                                         "valueDisplayMode": "text"}},
                                              {"id": "color", "value": fixed(BLUE)}]}] + (overrides or []),
            },
            "links": links or [],
        }


def range_count(expr, by=None, interval="$__range"):
    inner = "count_over_time(%s [%s])" % (expr, interval)
    return "sum by (%s) (%s)" % (by, inner) if by else "sum(%s)" % inner


def per_interval(expr, by):
    return "sum by (%s) (count_over_time(%s [$__auto]))" % (by, expr)


def loki_target(expr, legend="", instant=False, ref="A"):
    t = {"refId": ref, "expr": expr, "legendFormat": legend, "queryType": "instant" if instant else "range"}
    if instant:
        t.update({"instant": True, "range": False})
    return t


def prom_target(expr, legend="", instant=False, ref="A", interval=""):
    t = {"refId": ref, "expr": expr, "legendFormat": legend, "range": not instant, "instant": instant,
         "editorMode": "code"}
    if interval:
        t["interval"] = interval
    return t


# --- What the logs say: the LogQL of each kind of event ---------------------
#
# Each function takes the filters of the dashboard (`f`): for the overview they
# are empty, for "Access and logins" they are the variables. An empty pattern
# (".*") also matches a line that does not have the field.

class Filters:
    def __init__(self, host='".+"', user=None, source=None):
        self.host = host
        self.user = user      # a label filter on "user", or None
        self.source = source  # the same for the source address

    def u(self, label="user"):
        return ' | %s=~"(?i)%s"' % (label, self.user) if self.user else ""

    def s(self, label="src"):
        return ' | %s=~"%s"' % (label, self.source) if self.source else ""


NONE = Filters()
VARS = Filters('"$host"', "$user", "$source")


def ssh_sel(f):
    return '{job="syslog", appname=~"sshd.*", hostname=~%s}' % f.host


# OpenSSH writes "Accepted <method> for <user> from <address> port <port> ssh2"
# and, for a key, the key type and fingerprint after it.
def ssh_ok(f):
    return (ssh_sel(f) + ' |= "Accepted "'
            ' | regexp `Accepted (?P<method>\\S+) for (?P<user>\\S+) from (?P<src>\\S+) port \\d+(?: ssh2(?:: (?P<key>.+))?)?`'
            + f.u() + f.s())


# A connection that ends before a login writes one of these lines; a guess of
# a password also writes "Failed password ...", and an unknown user "Invalid
# user ..." before it. Counting the last line counts connections.
SSH_FAIL_END = "(Connection closed by|Disconnected from|Disconnecting) (authenticating|invalid) user |Access denied for user "
SSH_FAIL_ANY = ("Failed \\S+ for |Invalid user |" + SSH_FAIL_END +
                "|maximum authentication attempts|not allowed because|ROOT LOGIN REFUSED")
SSH_FAIL_PARSE = (
    ' | regexp `(?:for|user) (?P<user>\\S+) (?:from )?[0-9A-Fa-f.:]+(?: port| not allowed|$)`'
    ' | regexp `User (?P<user>\\S+) from \\S+ not allowed`'
    ' | regexp `Access denied for user (?P<user>\\S+)`'
    ' | regexp `(?:from|user \\S*) (?P<src>[0-9A-Fa-f.:]+)(?: port|:| not allowed|$)`'
    ' | label_format reason=`{{ if or (contains "Invalid user" __line__) (contains "invalid user" __line__) }}unknown user'
    '{{ else if contains "Failed password" __line__ }}wrong password'
    '{{ else if contains "Failed keyboard-interactive" __line__ }}wrong password'
    '{{ else if contains "Failed publickey" __line__ }}key refused'
    '{{ else if contains "Failed " __line__ }}login refused'
    '{{ else if or (contains "maximum authentication" __line__) (contains "Too many authentication" __line__) }}too many attempts'
    '{{ else if contains "not allowed because" __line__ }}user not allowed'
    '{{ else if contains "Access denied" __line__ }}refused by PAM'
    '{{ else if contains "REFUSED" __line__ }}root refused'
    '{{ else }}no key or password accepted{{ end }}`')


def ssh_fail(f, every_line=False):
    return (ssh_sel(f) + ' |~ `%s`' % (SSH_FAIL_ANY if every_line else SSH_FAIL_END) + SSH_FAIL_PARSE
            + f.u() + f.s())


# sudo writes "<user> : TTY=<tty> ; PWD=<dir> ; USER=<target> ; COMMAND=<command>".
# Without a terminal there is no TTY= (the hosts that send on UDP 1514 keep its
# space: "<user> :  PWD="), and sometimes no PWD=. Ansible's become runs
# "/bin/sh -c 'echo BECOME-SUCCESS-<random> ; ...'", which marks its commands.
# A line that does not parse keeps its whole text as the command, so that a
# new format shows here and is not lost.
def sudo(f):
    return ('{job="syslog", appname="sudo", hostname=~%s} |= " COMMAND="'
            ' | regexp `(?P<user>[^ ]+) : +(?:[A-Z]+=[^;]*; +)*COMMAND=(?P<command>.*)`'
            ' | regexp ` : +TTY=(?P<tty>[^ ]+) ;`'
            ' | regexp `(?: : +|; )USER=(?P<run_as>[^ ]+) ;`'
            ' | label_format command=`{{ if .command }}{{ .command }}{{ else }}{{ __line__ }}{{ end }}`'
            ' | label_format kind=`{{ if contains "BECOME-SUCCESS-" .command }}Ansible'
            '{{ else if .tty }}Terminal{{ else }}No terminal{{ end }}`' % f.host + f.u())


SUDO_KIND_COLOR = {"Ansible": GREY, "Terminal": BLUE, "No terminal": ORANGE}


# A refusal, and su: "FAILED SU (to root) <user> on <tty>", "(to root) <user> on <tty>".
def root_refused(f):
    return ('{job="syslog", appname=~"sudo|su", hostname=~%s}'
            ' |~ ` : (user NOT in sudoers|[0-9]+ incorrect password attempts?|a password is required|command not allowed)|FAILED SU `'
            ' | regexp `(?P<user>[^ ]+) : (?P<reason>user NOT in sudoers|[0-9]+ incorrect password attempts?|a password is required|command not allowed)`'
            ' | regexp `FAILED SU \\(to (?P<run_as>\\S+)\\) (?P<user>\\S+) on`'
            ' | label_format reason=`{{ if .reason }}{{ .reason }}{{ else }}su refused{{ end }}`' % f.host + f.u())


def su_sessions(f):
    return ('{job="syslog", appname="su", hostname=~%s} |~ `(FAILED SU )?[(]to \\S+[)] \\S+ on `'
            ' | regexp `(?P<failed>FAILED SU )?\\(to (?P<run_as>\\S+)\\) (?P<user>\\S+) on (?P<tty>\\S+)`'
            ' | label_format result=`{{ if .failed }}refused{{ else }}opened{{ end }}`' % f.host + f.u())


# pvedaemon: "<root@pam> successful auth for user 'root@pam'" (no address) and
# "authentication failure; rhost=::ffff:<address> user=<user> msg=<reason>".
def pve_ok(f):
    return ('{job="syslog", appname="pvedaemon", hostname=~%s} |= "successful auth for user"'
            " | regexp `successful auth for user '(?P<user>[^']+)'`" % f.host + f.u())


def pve_fail(f):
    return ('{job="syslog", appname="pvedaemon", hostname=~%s} |= "authentication failure;"'
            ' | regexp `rhost=(?:::ffff:)?(?P<src>\\S*) user=(?P<user>\\S*) msg=(?P<reason>.*)`' % f.host
            + f.u() + f.s())


# "<root@pam> starting task UPID:<node>:<pid>:<start>:<time>:<type>:<id>:<user>:"
def pve_tasks(f):
    return ('{job="syslog", appname="pvedaemon", hostname=~%s} |= "starting task UPID:"'
            ' | regexp `<(?P<user>[^>]+)> starting task UPID:[^:]+:[^:]+:[^:]+:[^:]+:(?P<task>[^:]+):(?P<vmid>[^:]*):`'
            % f.host + f.u())


PVE_TASK = {
    "vncshell": ("▲ Host shell", SERIOUS), "termproxy": ("▲ Host shell", SERIOUS),
    "vncproxy": ("VM console", None), "spiceproxy": ("VM console (SPICE)", None),
    "qmstart": ("Start VM", None), "qmshutdown": ("Shut down VM", None), "qmreboot": ("Reboot VM", None),
    "qmstop": ("Stop VM", None), "qmcreate": ("Create VM", None), "qmdestroy": ("Destroy VM", SERIOUS),
    "qmconfig": ("Change VM", None), "qmtemplate": ("Make template", None), "qmclone": ("Clone VM", None),
    "vzdump": ("Backup", None), "imgdel": ("Delete disk image", None), "imgcopy": ("Copy disk image", None),
    "aptupdate": ("Package list update", None),
}


# charon: "IKE_SA <conn>[<n>] established between <here>[<id>]...<address>[<identity>]".
# LINDS is the tunnel between the sites; every other connection is a person.
def vpn_ok(f):
    return ('{job="syslog", appname="charon-systemd", hostname=~%s} |= " established between "'
            ' | regexp `IKE_SA (?P<conn>[^\\[ ]+)\\[\\d+\\] established between [^\\[]+\\[[^\\]]*\\]\\.\\.\\.(?P<src>[^\\[]+)\\[(?P<user>[^\\]]*)\\]`'
            ' | conn!="LINDS"' % f.host + f.u() + f.s())


# A failed password: "EAP-MS-CHAPv2 verification failed, retry (1)", with no
# address or user; an unknown user: "no EAP key found for hosts '<here>' - '<identity>'".
VPN_FAIL_LINES = "EAP-MS-CHAPv2 verification failed|no EAP key found|EAP method EAP_[A-Z0-9]+ failed|with EAP failed"


def vpn_fail(f):
    return ('{job="syslog", appname="charon-systemd", hostname=~%s} |~ `%s`'
            " | regexp `no EAP key found for hosts '[^']*' - '(?P<user>[^']*)'`"
            ' | label_format reason=`{{ if contains "no EAP key" __line__ }}unknown user'
            '{{ else if contains "verification failed" __line__ }}wrong password{{ else }}EAP failed{{ end }}`'
            % (f.host, VPN_FAIL_LINES) + f.u())


# The steps of a road-warrior login, in order: who (EAP identity), the result.
def vpn_steps(f):
    return ('{job="syslog", appname="charon-systemd", hostname=~%s}'
            ' |~ `received EAP identity|%s|with EAP successful|assigning virtual IP`'
            " | regexp `(?:received EAP identity|no EAP key found for hosts '[^']*' -|with EAP successful|to peer) '(?P<user>[^']*)'`"
            " | regexp `authentication of '(?P<user>[^']*)' with EAP successful`"
            ' | regexp `assigning virtual IP (?P<vip>\\S+) to peer`'
            ' | label_format step=`{{ if contains "received EAP identity" __line__ }}1. user name received'
            '{{ else if contains "no EAP key" __line__ }}▲ unknown user'
            '{{ else if contains "verification failed" __line__ }}▲ wrong password'
            '{{ else if contains "EAP successful" __line__ }}2. password accepted'
            '{{ else if contains "assigning virtual IP" __line__ }}3. address given'
            '{{ else }}▲ EAP failed{{ end }}`' % (f.host, VPN_FAIL_LINES) + f.u())


# Any address that starts IKE: clients, and scanners that get no further.
def ike_start(f):
    return ('{job="syslog", appname="charon-systemd", hostname=~%s} |= "is initiating an IKE_SA"'
            ' | regexp `(?P<src>\\S+) is initiating an IKE_SA`' % f.host + f.s())


# Every IKE_SA that came up, the tunnel between the sites too, with the
# address of the other end.
def ike_up(f):
    return ('{job="syslog", appname="charon-systemd", hostname=~%s} |= " established between "'
            ' | regexp `\\.\\.\\.(?P<src>[^\\[]+)\\[`' % f.host)


# Windows Security events (LINDS-Ansible role windows_logs sends the audit
# failures and the changes to accounts and groups; not the successful logons).
# Each line is the JSON event; event_data is the XML of its fields.
def win(f, ids, fields):
    """fields: {label: EventData field name}"""
    expr = ('{job="windows", channel="Security", hostname=~%s} | event_id=~"%s"'
            ' | json event_data="event_data" | line_format "{{.event_data}}"' % (f.host, ids))
    for label, name in fields.items():
        if label == "client":
            expr += " | regexp \"<Data Name='%s'>(?:::ffff:)?(?P<%s>[^<]*)</Data>\"" % (name, label)
        else:
            expr += " | regexp \"<Data Name='%s'>(?P<%s>[^<]*)</Data>\"" % (name, label)
    return expr


WIN_FAIL_IDS = "4625|4771|4776"


def win_fail(f):
    return (win(f, WIN_FAIL_IDS, {"user": "TargetUserName", "domain": "TargetDomainName", "client": "IpAddress",
                                  "workstation": "WorkstationName", "logon_type": "LogonType",
                                  "status": "Status", "substatus": "SubStatus"})
            # 4776 calls it Workstation, not WorkstationName.
            + " | regexp \"<Data Name='Workstation'>(?P<workstation>[^<]*)</Data>\""
            ' | label_format reason=`{{ if and .substatus (ne .substatus "0x0") }}{{ .substatus }}{{ else }}{{ .status }}{{ end }}`'
            ', client=`{{ if and .client (ne .client "-") }}{{ .client }}{{ else }}(no address){{ end }}`'
            ', event=`{{ if eq .event_id "4625" }}4625 failed logon{{ else if eq .event_id "4771" }}4771 Kerberos'
            ' pre-auth failed{{ else }}4776 NTLM check failed{{ end }}`'
            + f.u() + f.s("client"))


WIN_ACCOUNT_IDS = "4720|4722|4723|4724|4725|4726|4738|4740|4767|4781|4794"
WIN_GROUP_IDS = "4727|4728|4729|4730|4731|4732|4733|4734|4735|4737|4754|4755|4756|4757|4758"


def win_account(f):
    return win(f, WIN_ACCOUNT_IDS, {"user": "TargetUserName", "actor": "SubjectUserName"}) + f.u()


# Privileged: the groups of ADPrivilegedGroupMemberAdded
# (base/monitoring/windows-security-alerts.yaml), by SID, and DnsAdmins.
PRIVILEGED = ('{{ if and .group_sid (eq (regexReplaceAll '
              '"^S-1-5-21-[0-9-]+-(512|518|519|520|526|527)|^S-1-5-32-(544|548|549|550|551)" .group_sid "") "") }}'
              '▲ yes{{ else if eq .group "DnsAdmins" }}▲ yes{{ end }}')


def win_group(f):
    return (win(f, WIN_GROUP_IDS, {"group": "TargetUserName", "group_sid": "TargetSid", "member": "MemberName",
                                   "actor": "SubjectUserName"})
            # MemberName is the member's DN: keep its first part.
            + ' | label_format member=`{{ regexReplaceAll "^CN=" (regexReplaceAll ",.*" .member "") "" }}`'
            + ', privileged=`%s`' % PRIVILEGED + f.u("member"))


WIN_EVENT = {
    "4625": ("Failed logon", None), "4771": ("Kerberos pre-auth failed", None), "4776": ("NTLM check failed", None),
    "4720": ("Account created", None), "4722": ("Account enabled", None), "4723": ("Password change", None),
    "4724": ("Password reset", None), "4725": ("Account disabled", None), "4726": ("Account deleted", None),
    "4738": ("Account changed", None), "4740": ("▲ Account locked out", SERIOUS),
    "4767": ("Account unlocked", None), "4781": ("Account renamed", None),
    "4794": ("▲ DSRM password set", SERIOUS),
    "4727": ("Global group created", None), "4728": ("Added to global group", None),
    "4729": ("Removed from global group", None), "4730": ("Global group deleted", None),
    "4731": ("Local group created", None), "4732": ("Added to local group", None),
    "4733": ("Removed from local group", None), "4734": ("Local group deleted", None),
    "4735": ("Local group changed", None), "4737": ("Global group changed", None),
    "4754": ("Universal group created", None), "4755": ("Universal group changed", None),
    "4756": ("Added to universal group", None), "4757": ("Removed from universal group", None),
    "4758": ("Universal group deleted", None),
    "4769": ("Service ticket refused", None), "4768": ("TGT refused", None), "5061": ("Key operation failed", None),
    "4662": ("Directory object access", None), "4719": ("Audit policy changed", SERIOUS),
    "1102": ("▲ Security log cleared", CRIT),
}
# NTSTATUS codes of 4625 and 4776, and Kerberos codes of 4771.
WIN_REASON = {
    "0xc000006a": "wrong password", "0xc0000064": "unknown user", "0xc000006d": "wrong user or password",
    "0xc0000234": "account locked out", "0xc0000072": "account disabled", "0xc000006f": "outside logon hours",
    "0xc0000070": "workstation not allowed", "0xc0000071": "password expired", "0xc0000193": "account expired",
    "0xc0000133": "clocks differ", "0xc0000224": "must change password", "0xc000015b": "logon type not allowed",
    "0xc0000413": "authentication firewall", "0xc000005e": "no logon server",
    "0x18": "wrong password", "0x12": "account disabled, locked or expired", "0x17": "password expired",
    "0x25": "clocks differ", "0x6": "unknown user", "0x10": "smart card logon not supported",
}
LOGON_TYPE = {"2": "Interactive", "3": "Network", "4": "Batch", "5": "Service", "7": "Unlock",
              "8": "Network, clear text", "9": "New credentials", "10": "Remote desktop", "11": "Cached"}


# Keycloak's jboss-logging event listener (keycloak/keycloak.yaml):
# 'type="LOGIN", realmId="...", realmName="linds", clientId="grafana", userId="...",
# ipAddress="...", [error="..."], ..., username="..."'. Admin events have
# operationType= instead of type=.
KC_SEL = '{namespace="keycloak", container="keycloak"} |= "[org.keycloak.events]"'
KC_ROUTINE = "CODE_TO_TOKEN|REFRESH_TOKEN|LOGOUT|INTROSPECT_TOKEN|USER_INFO_REQUEST|TOKEN_EXCHANGE|PERMISSION_TOKEN"


def kc_events(f):
    return (KC_SEL + ' |= `type="`'
            ' | regexp `type="(?P<kc_event>[^"]*)"`'
            ' | regexp `clientId="(?P<client>[^"]*)"`'
            ' | regexp `ipAddress="(?P<src>[^"]*)"`'
            ' | regexp `error="(?P<error>[^"]*)"`'
            ' | regexp `username="(?P<user>[^"]*)"`' + f.u() + f.s())


def kc_login(f):
    return kc_events(f) + ' | kc_event="LOGIN"'


def kc_fail(f):
    return kc_events(f) + ' | kc_event="LOGIN_ERROR"'


def kc_admin(f):
    return (KC_SEL + ' |= "operationType="'
            ' | regexp `operationType="(?P<operation>[^"]*)"`'
            ' | regexp `realmName="(?P<realm>[^"]*)"`'
            ' | regexp `ipAddress="(?P<src>[^"]*)"`'
            ' | regexp `resourceType="(?P<resource>[^"]*)"`'
            ' | regexp `resourcePath="(?P<path>[^"]*)"`'
            ' | regexp `error="(?P<error>[^"]*)"`' + f.s())


# Argo CD: "Web login successful" after a login through Keycloak; a local
# login (the admin account) is a call to session.SessionService/Create.
def argo_web(f):
    return ('{namespace="argocd", container="argocd-server"} |= "Web login successful"'
            ' | json login_type="[\\"login.type\\"]", claims="claims" | line_format "{{.claims}}"'
            ' | json user="preferred_username"' + f.u())


def argo_local(f):
    return ('{namespace="argocd", container="argocd-server"} |= "finished call" |= "session.SessionService"'
            ' | json method="[\\"grpc.method\\"]", code="[\\"grpc.code\\"]", error="[\\"grpc.error\\"]"'
            ' | method="Create"')


# Grafana logs at warn: a failed login is "Failed to authenticate request" with
# the client that refused it. An expired session cookie (auth.client.session)
# is not a login.
def grafana_fail(f):
    return ('{namespace="monitoring", container="grafana"} |= "Failed to authenticate request"'
            ' | logfmt client, error | client!="auth.client.session"')


INGRESS_REFUSED = '{namespace=~"nginx-ingress|nginx-ingress-mtls"} |~ `" (401|403) `'


# --- The summaries: one number for each system and result --------------------

def by_system(parts, interval="$__range", by="system, result"):
    """parts: [(system, result, expr)]. One query: a series for each part."""
    return "\nor\n".join(
        'sum by (%s) (count_over_time(%s | label_format system="%s", result="%s" [%s]))'
        % (by, expr, system, result, interval) for system, result, expr in parts)


def login_parts(f):
    return [
        ("SSH", "Succeeded", ssh_ok(f)), ("SSH", "Failed", ssh_fail(f)),
        ("sudo and su", "Succeeded", sudo(f) + ' | kind!="Ansible"'), ("sudo and su", "Failed", root_refused(f)),
        ("Proxmox", "Succeeded", pve_ok(f)), ("Proxmox", "Failed", pve_fail(f)),
        ("VPN", "Succeeded", vpn_ok(f)), ("VPN", "Failed", vpn_fail(f)),
        ("Windows domain", "Failed", win_fail(f)),
        ("Keycloak", "Succeeded", kc_login(f)), ("Keycloak", "Failed", kc_fail(f)),
        ("Argo CD", "Succeeded", argo_web(f)),
        ("Argo CD", "Succeeded", argo_local(f) + ' | code="OK"'),
        ("Argo CD", "Failed", argo_local(f) + ' | code!="OK"'),
        ("Grafana", "Failed", grafana_fail(f)),
    ]


# --- Security overview ---------------------------------------------------------

ON_OFF = [{"type": "value", "options": {"1": {"text": "● Blocking", "color": GOOD, "index": 0},
                                        "0": {"text": "▲ Not blocking", "color": CRIT, "index": 1}}}]
STEADY_HOSTS = ("jd-router-01|linds-router-01|jd-proxmox-02|linds-proxmox-01|linds-truenas-01.linds.com.au|"
                "jd-dc-01|jd-fs-01|linds-dc|linds-dc2")
# The same test as the alert LogSourceSilent (rules.yaml), without the 6 hours
# before: a steady source with no line for 2 hours.
QUIET_NOW = ('count(sum by (job, hostname) (count_over_time({job=~"syslog|windows", hostname=~"%s"}[1d]))'
             ' unless on (job, hostname) sum by (job, hostname) (count_over_time({job=~"syslog|windows", hostname=~"%s"}[2h])))'
             % (STEADY_HOSTS, STEADY_HOSTS))
LAST_LINE = ('max by (job, hostname) (max_over_time({job=~"syslog|windows"}'
             ' | label_format ts=`{{ unixEpoch __timestamp__ }}` | unwrap ts [7d])) * 1000')


def overview():
    b = Builder()
    p = []
    y = 0
    det = [link("Access and logins", D["access"])]
    p += [
        b.stat("IPS at JD", "Suricata on jd-router-01 is inline: it blocks. \"Not blocking\" means it is off or "
               "not on its queue (alerts RouterIPSOff, RouterIPSNotAttached). linds-router-01 only reports.",
               [prom_target("router_ips_enabled * on (instance) router_ips_attached", "{{instance}}", True)],
               g(0, y, 3, 4), PROM, mappings=ON_OFF, steps=[(None, CRIT), (1, GOOD)], no_value="▲ No data",
               links=[link("Router", D["router"]), link("Suricata", D["suricata"])], text_mode="value"),
        b.stat("Suricata, 15 min", "EVE lines in the last 15 minutes from each router's Suricata. 0 means it, or the relay "
               "to Loki, stopped (alert RouterSuricataNoLogs).",
               [prom_target("sum by (hostname) (increase(loki_process_custom_suricata_eve_lines_total[15m]))",
                            "{{hostname}}", True)],
               g(3, y, 4, 4), PROM, steps=[(None, CRIT), (1, GOOD)], no_value="▲ 0",
               mappings=[{"type": "value", "options": {"0": {"text": "▲ 0", "color": CRIT}}}],
               links=[link("Suricata", D["suricata"])]),
        b.stat("DNS lists", "The RPZ blocklists that Unbound loaded on each router.",
               [prom_target("count by (instance) (router_dns_blocklist_names > 0)", "{{instance}}", True)],
               g(7, y, 3, 4), PROM, steps=[(None, CRIT), (1, GOOD)], no_value="▲ 0",
               links=[link("DNS blocking", D["dns"])]),
        b.stat("Oldest DNS list", "Time since the oldest list of each router last changed. The lists change "
               "every day (dns-blocklist-update, about 04:40). More than 2 days: the download fails.",
               [prom_target("max by (instance) (time() - router_dns_blocklist_changed_timestamp_seconds)",
                            "{{instance}}", True)],
               g(10, y, 4, 4), PROM, unit="s", steps=[(None, GOOD), (172800, WARN), (345600, CRIT)],
               no_value="▲ No data", links=[link("DNS blocking", D["dns"])]),
        b.stat("Quiet sources", "Log sources that always send logs (the routers, the Proxmox hosts, TrueNAS, the "
               "Windows servers) and sent nothing for 2 hours. The alert LogSourceSilent is the same test. See "
               "\"Log sources\" below.", [loki_target(QUIET_NOW, instant=True)], g(14, y, 3, 4),
               steps=[(None, GOOD), (1, CRIT)], no_value="● 0",
               mappings=[{"type": "value", "options": {"0": {"text": "● 0", "color": GOOD}}}], text_mode="value"),
        b.stat("VPN users", "Road-warrior VPN sessions that are up now (router_ipsec_road_warriors).",
               [prom_target("sum(router_ipsec_road_warriors)", "", True)], g(17, y, 3, 4), PROM,
               links=det + [link("Router", D["router"])], text_mode="value"),
        b.stat("Ingress 401 and 403", "HTTP answers 401 and 403 of the two ingress controllers in the time "
               "range: a request without a login or a client certificate. The dashboard \"Ingress traffic\" has "
               "the detail.", [loki_target(range_count(INGRESS_REFUSED), instant=True)], g(20, y, 4, 4),
               links=[link("Ingress traffic", D["ingress"])], text_mode="value"),
    ]
    y += 4
    p += [
        {"type": "alertlist", "id": b.ids(), "title": "Security alerts firing now", "gridPos": g(0, y, 9, 9),
         "description": "The alerts with category=security that fire now, from Loki's ruler "
                        "(windows-security-alerts, router-vpn-alerts, monitoring-security/rules.yaml). Alertmanager "
                        "sends each one to Discord once. These alerts have no history: Loki's ruler does not store "
                        "them. Empty: none fires.",
         "options": {"viewMode": "list", "groupMode": "default", "groupBy": [], "maxItems": 20, "sortOrder": 1,
                     "dashboardAlerts": False, "alertName": "", "alertInstanceLabelFilter": "{category=\"security\"}",
                     "datasource": "", "folder": None,
                     "stateFilter": {"firing": True, "pending": True, "noData": False, "normal": False,
                                     "error": True},
                     "showInstances": True}},
        {"type": "table", "id": b.ids(), "title": "Logins in the time range", "gridPos": g(9, y, 15, 9),
         "description": "Successful and failed logins for each system. Windows sends its failed logons only; "
                        "Keycloak's logins are in the log since the change of keycloak/keycloak.yaml. \"sudo and su\": "
                        "sudo outside Ansible, and the refusals. Open \"Access and logins\" for each event.",
         "datasource": LOKI,
         "targets": [{"refId": "A", "datasource": LOKI, "expr": by_system(login_parts(NONE)), "queryType": "instant",
                      "instant": True, "range": False, "format": "table"}],
         "transformations": [
             {"id": "groupingToMatrix", "options": {"columnField": "result", "rowField": "system",
                                                    "valueField": "Value #A", "emptyValue": "null"}},
             {"id": "organize", "options": {"renameByName": {"system\\result": "System"},
                                            "indexByName": {"system\\result": 0, "Succeeded": 1, "Failed": 2}}},
             {"id": "sortBy", "options": {"sort": [{"field": "System"}]}},
         ],
         "options": {"cellHeight": "md", "showHeader": True, "footer": {"show": False}},
         "fieldConfig": {"defaults": {"unit": "short", "noValue": "", "custom": {"align": "left"}},
                         "overrides": [
                             # A failure count is in the serious colour; no failure is blank.
                             {"matcher": {"id": "byName", "options": "Failed"},
                              "properties": [{"id": "custom.cellOptions", "value": {"type": "color-text"}},
                                             {"id": "color", "value": {"mode": "thresholds"}},
                                             {"id": "thresholds", "value": {"mode": "absolute", "steps": [
                                                 {"value": None, "color": "text"}, {"value": 1, "color": SERIOUS}]}}]},
                             width("System", 170)]},
         "links": det},
    ]
    y += 9

    p.append(b.row("Threats: what the routers blocked and saw", y))
    y += 1
    suricata_kind = ('{job="suricata", event_type="alert"} | label_format kind=`{{ if eq .alert_action "blocked" }}'
                     'Blocked{{ else if eq .alert_severity "1" }}Alert, high{{ else if eq .alert_severity "2" }}'
                     'Alert, medium{{ else }}Alert, low{{ end }}`')
    p += [
        b.bars("Suricata: blocked and reported", "Each Suricata alert event of both routers, by what it is: blocked "
               "(jd-router-01 only), or reported and let through, by severity.",
               [loki_target(per_interval(suricata_kind, "kind"), "{{kind}}")], g(0, y, 12, 8),
               colors={"Blocked": BLUE, "Alert, high": CRIT, "Alert, medium": SERIOUS, "Alert, low": WARN},
               links=[link("Suricata", D["suricata"])]),
        b.bars("DNS questions refused by the blocklists", "Answers that Unbound refused with a blocklist "
               "(router_dns_blocked_total), for each router.",
               [prom_target("sum by (instance) (increase(router_dns_blocked_total[$__interval]))", "{{instance}}",
                            interval="5m")],
               g(12, y, 12, 8), PROM, colors={"jd-router-01": BLUE, "linds-router-01": ORANGE},
               links=[link("DNS blocking", D["dns"])]),
    ]
    y += 8
    p += [
        b.top("Most frequent Suricata rules", "The rules with the most alert events in the time range, blocked "
              "and reported.",
              "topk(15, %s)" % range_count('{job="suricata", event_type="alert"}', "alert_signature, alert_action"),
              g(0, y, 9, 9), {"alert_signature": "Rule", "alert_action": "Action"}, "Events",
              overrides=[mapping_override("Action", {"blocked": ("Blocked", None), "allowed": ("Reported", None)},
                                          90, False)],
              links=[link("Suricata", D["suricata"])]),
        b.top("Devices with the most refused DNS questions", "The devices that asked for the most names on a "
              "blocklist. A DNS server or a cluster node asks for its clients.",
              "topk(15, %s)" % range_count(
                  '{job="syslog", appname="unbound"} |= "rpz: applied"'
                  ' | pattern "<_>rpz: applied [<list>] <_> <action> <device>@<_> <name>. <qtype> IN"',
                  "device, hostname"),
              g(9, y, 7, 9), {"device": "Device", "hostname": "Router"}, "Refused",
              links=[link("DNS blocking", D["dns"])]),
        b.bars("Cilium drops by reason", "Packets that Cilium dropped in the cluster (hubble_drop_total). "
               "POLICY_DENIED is a NetworkPolicy refusal. The metric has no pod or namespace.",
               [prom_target("sum by (reason) (increase(hubble_drop_total[$__interval]))", "{{reason}}",
                            interval="5m")],
               g(16, y, 8, 9), PROM,
               colors={"POLICY_DENIED": BLUE, "UNSUPPORTED_L3_PROTOCOL": ORANGE, "TTL_EXCEEDED": AQUA,
                       "CT_UNKNOWN_L4_PROTOCOL": YELLOW, "FIB_LOOKUP_FAILED": MAGENTA}),
    ]
    y += 9

    p.append(b.row("Access: logins and changes to accounts", y))
    y += 1
    ok_parts = [(s, r, e) for s, r, e in login_parts(NONE) if r == "Succeeded"]
    fail_parts = [(s, r, e) for s, r, e in login_parts(NONE) if r == "Failed"]
    p += [
        b.bars("Successful logins", "Logins for each system. \"sudo and su\" counts sudo outside Ansible.",
               [loki_target(by_system(ok_parts, "$__auto", "system"), "{{system}}")], g(0, y, 12, 8),
               colors=SYSTEM_COLOR, links=det),
        b.bars("Failed logins", "Failed logins and refusals for each system. SSH counts connections that closed "
               "before a login.",
               [loki_target(by_system(fail_parts, "$__auto", "system"), "{{system}}")], g(12, y, 12, 8),
               colors=SYSTEM_COLOR, links=det),
    ]
    y += 8
    changes = ('{job="windows", channel="Security"} | event_id=~"%s|%s"'
               ' | json event_data="event_data" | line_format "{{.event_data}}"'
               " | regexp \"<Data Name='TargetUserName'>(?P<target>[^<]*)</Data>\""
               " | regexp \"<Data Name='MemberName'>(?P<member>[^<]*)</Data>\""
               " | regexp \"<Data Name='SubjectUserName'>(?P<actor>[^<]*)</Data>\""
               " | regexp \"<Data Name='TargetSid'>(?P<group_sid>[^<]*)</Data>\""
               ' | label_format member=`{{ regexReplaceAll "^CN=" (regexReplaceAll ",.*" .member "") "" }}`'
               ', group=`{{ .target }}`, privileged=`%s`' % (WIN_ACCOUNT_IDS, WIN_GROUP_IDS, PRIVILEGED))
    p += [
        b.events("Windows: changes to accounts and groups", "Accounts made, enabled, disabled, deleted or locked "
                 "out, passwords reset, and members added to groups, newest first, in the last 7 days whatever the "
                 "time range. \"Privileged\": a group that controls the domain (the groups of the alert "
                 "ADPrivilegedGroupMemberAdded).", changes,
                 g(0, y, 16, 9),
                 {"hostname": "Server", "event_id": "Event", "target": "Account or group", "member": "Member",
                  "privileged": "Privileged", "actor": "By"},
                 {"Server": 95, "Event": 190, "Privileged": 85, "Member": 190, "By": 170},
                 [mapping_override("Event", WIN_EVENT, 190)], lines=200,
                 links=[link("Access and logins", D["access"]), link("Logs / Windows", D["windows"])]) | {
                     "timeFrom": "7d"},
        b.top("Windows: audit failures by event", "Security events with the keyword Audit Failure in the time "
              "range. 4769 with status 0xd (a ticket renewal that the KDC refused) is routine.",
              range_count('{job="windows", channel="Security"} | json keywords="keywords" | keywords="Audit Failure"',
                          "event_id"),
              g(16, y, 8, 9), {"event_id": "Event"}, "Events",
              overrides=[mapping_override("Event", WIN_EVENT, None, False)],
              links=[link("Logs / Windows", D["windows"])]),
    ]
    y += 9

    p.append(b.row("Log sources and defence alerts", y))
    y += 1
    p += [
        {"type": "table", "id": b.ids(), "title": "Log sources: the last line from each", "gridPos": g(0, y, 12, 10),
         "description": "Each host that sent syslog or Windows logs in the last 7 days, the oldest first. A source "
                        "that stops sending logs is blind: the alerts on its logs cannot fire. The routers, the "
                        "Proxmox hosts, TrueNAS and the Windows servers send at least every hour (alert "
                        "LogSourceSilent after 2 hours); the torrent VMs, the Plex VM and the switches can be quiet "
                        "for hours. Suricata: the tiles at the top.",
         "datasource": LOKI,
         "targets": [{"refId": "A", "datasource": LOKI, "expr": LAST_LINE, "queryType": "instant", "instant": True,
                      "range": False, "format": "table"}],
         "transformations": [
             {"id": "organize", "options": {"excludeByName": {"Time": True},
                                            "indexByName": {"hostname": 0, "job": 1, "Value #A": 2},
                                            "renameByName": {"hostname": "Host", "job": "Kind",
                                                             "Value #A": "Last line"}}},
             {"id": "sortBy", "options": {"sort": [{"field": "Last line"}]}},
         ],
         "options": {"cellHeight": "sm", "showHeader": True, "footer": {"show": False}},
         "fieldConfig": {"defaults": {"custom": {"align": "left"}, "noValue": ""},
                         "overrides": [{"matcher": {"id": "byName", "options": "Last line"},
                                        "properties": [{"id": "unit", "value": "dateTimeFromNow"}]},
                                       width("Kind", 90)]}},
        {"type": "state-timeline", "id": b.ids(), "title": "Defence alerts in the time range", "gridPos": g(12, y, 12, 10),
         "description": "Prometheus alerts on the defences and on the log pipeline: Suricata, the IPS, DNS, Loki, "
                        "the tunnel. \"None firing\" fills the time when no such alert fired. The security alerts of "
                        "Loki's ruler are not here: they have no history.",
         "datasource": PROM,
         "targets": [{"refId": "A", "datasource": PROM, "editorMode": "code", "range": True, "instant": False,
                      "expr": 'max by (alertname, instance, hostname) (ALERTS{alertstate="firing", '
                              'alertname=~"RouterIPS.*|RouterSuricata.*|RouterDNS.*|LokiNotIngesting|RouterTunnelDown"})'
                              ' or on () label_replace(vector(0), "alertname", "None firing", "", "")',
                      "legendFormat": "{{alertname}} {{instance}}{{hostname}}"}],
         "options": {"showValue": "never", "mergeValues": True, "rowHeight": 0.5, "alignValue": "left",
                     "legend": {"showLegend": False}, "tooltip": {"mode": "single"}},
         "fieldConfig": {"defaults": {"color": fixed(SERIOUS), "custom": {"fillOpacity": 50, "lineWidth": 0},
                                      "mappings": [{"type": "value",
                                                    "options": {"1": {"text": "▲ Firing", "color": SERIOUS},
                                                                "0": {"text": "● None firing", "color": GOOD}}}]},
                         "overrides": []},
         "links": [link("Router", D["router"])]},
    ]

    return {
        "uid": "security-overview",
        "title": "Security overview",
        "description": "Is something attacking or failing now, and are the defences on? Each block links to the "
                       "dashboard with the detail. Source: LINDS-Kubernetes monitoring-security/.",
        "tags": ["security", "logins", "suricata", "dns"],
        "timezone": "browser", "editable": True, "graphTooltip": 1, "schemaVersion": 39, "refresh": "5m",
        "time": {"from": "now-24h", "to": "now"},
        "annotations": {"list": []},
        "links": [{"title": "Access and logins", "type": "link", "url": D["access"], "icon": "dashboard",
                   "keepTime": True},
                  {"title": "Suricata", "type": "link", "url": D["suricata"], "icon": "dashboard", "keepTime": True},
                  {"title": "DNS blocking", "type": "link", "url": D["dns"], "icon": "dashboard", "keepTime": True},
                  {"title": "Network devices", "type": "link", "url": D["devices"], "icon": "dashboard",
                   "keepTime": True},
                  {"title": "Logs / Windows", "type": "link", "url": D["windows"], "icon": "dashboard",
                   "keepTime": True},
                  {"title": "Router", "type": "link", "url": D["router"], "icon": "dashboard", "keepTime": True},
                  {"title": "Ingress traffic", "type": "link", "url": D["ingress"], "icon": "dashboard",
                   "keepTime": True},
                  {"title": "Availability", "type": "link", "url": D["availability"], "icon": "dashboard"},
                  {"title": "Backups", "type": "link", "url": D["backups"], "icon": "dashboard"},
                  {"title": "Overview", "type": "link", "url": D["home"], "icon": "dashboard"}],
        "templating": {"list": []},
        "panels": p,
    }


# --- Access and logins ---------------------------------------------------------

def access():
    b = Builder()
    f = VARS
    p = []
    y = 0

    p.append(b.row("SSH", y))
    y += 1
    p += [
        b.bars("SSH logins", "Successful SSH logins on each host.", [loki_target(per_interval(ssh_ok(f), "hostname"),
                                                                                 "{{hostname}}")],
               g(0, y, 8, 7), colors=HOST_COLOR),
        b.bars("SSH connections that failed", "Connections that closed before a login, on each host: an unknown "
               "user, a key or password that was not accepted, too many attempts.",
               [loki_target(per_interval(ssh_fail(f), "hostname"), "{{hostname}}")], g(8, y, 8, 7),
               colors=HOST_COLOR),
        b.top("Logins by source address", "", "topk(15, %s)" % range_count(ssh_ok(f), "src"), g(16, y, 4, 7),
              {"src": "Source"}, "Logins"),
        b.top("Logins by user", "", "topk(15, %s)" % range_count(ssh_ok(f), "user"), g(20, y, 4, 7),
              {"user": "User"}, "Logins"),
    ]
    y += 7
    p += [
        b.events("SSH logins", "Each successful login, newest first. \"Method\" is publickey for a key; anything "
                 "else fires the alert SSHPasswordLogin.", ssh_ok(f), g(0, y, 12, 9),
                 {"hostname": "Host", "user": "User", "src": "Source", "method": "Method", "key": "Key"},
                 {"Host": 150, "User": 90, "Source": 150, "Method": 90},
                 [mapping_override("Method", {"publickey": ("publickey", None)}, 90, False)]),
        b.events("SSH failures", "Each line of a failed login, newest first. One guess can write two lines "
                 "(for example \"Invalid user\", then \"Connection closed\").", ssh_fail(f, every_line=True),
                 g(12, y, 12, 9), {"hostname": "Host", "user": "User", "src": "Source", "reason": "Reason"},
                 {"Host": 150, "User": 100, "Source": 200}),
    ]
    y += 9
    prior = "[14d] offset $__range"
    p += [
        b.top("New source addresses", "Addresses with a successful login in the time range and none in the 14 days "
              "before it. Loki keeps 30 days, so this is right for a time range of up to 16 days.",
              "%s unless on (src) sum by (src) (count_over_time(%s %s))"
              % (range_count(ssh_ok(f), "src, hostname, user"), ssh_ok(NONE), prior),
              g(0, y, 8, 7), {"src": "Source", "hostname": "Host", "user": "User"}, "Logins",
              overrides=[width("Source", 130), width("Host", 130)]),
        b.top("New user and host pairs", "Users who logged in to a host in the time range and not in the 14 days "
              "before it.",
              "%s unless on (hostname, user) sum by (hostname, user) (count_over_time(%s %s))"
              % (range_count(ssh_ok(f), "hostname, user"), ssh_ok(NONE), prior),
              g(8, y, 8, 7), {"hostname": "Host", "user": "User"}, "Logins"),
        b.top("Failures by source address", "The addresses with the most failed connections. The alert "
              "LoginFailureBurst fires at 10 failure lines from one address in 10 minutes.",
              "topk(15, %s)" % range_count(ssh_fail(f), "src, hostname"), g(16, y, 8, 7),
              {"src": "Source", "hostname": "Host"}, "Failures"),
    ]
    y += 7

    p.append(b.row("sudo and su", y))
    y += 1
    not_ansible = sudo(f) + ' | kind!="Ansible"'
    p += [
        b.bars("sudo commands by kind", "\"Ansible\": a command with Ansible's become marker (BECOME-SUCCESS-). "
               "\"Terminal\": a command typed in a terminal (sudo saw a TTY). \"No terminal\": a command sent "
               "over SSH without a terminal, or by a script. Ansible is in the legend with its total, and not "
               "drawn: it is about 3,000 commands a day.",
               [loki_target(per_interval(sudo(f), "kind"), "{{kind}}")], g(0, y, 12, 7), colors=SUDO_KIND_COLOR,
               hidden=["Ansible"]),
        b.top("Commands, not Ansible", "The most frequent sudo commands outside Ansible.",
              "topk(20, %s)" % range_count(not_ansible, "command, run_as"), g(12, y, 12, 7),
              {"command": "Command", "run_as": "As"}, "Times", overrides=[width("As", 80)]),
    ]
    y += 7
    p += [
        b.events("sudo, not Ansible", "Each sudo command outside Ansible, newest first.", not_ansible,
                 g(0, y, 15, 9),
                 {"hostname": "Host", "user": "User", "kind": "Kind", "tty": "TTY", "run_as": "As",
                  "command": "Command"},
                 {"Host": 140, "User": 90, "Kind": 105, "TTY": 70, "As": 70},
                 [mapping_override("Kind", {k: (k, c) for k, c in SUDO_KIND_COLOR.items()}, 105)]),
        b.events("su sessions", "Each su to another user, newest first.", su_sessions(f), g(15, y, 9, 5),
                 {"hostname": "Host", "user": "User", "run_as": "To", "result": "Result"},
                 {"Host": 125, "User": 80, "To": 55, "Result": 85},
                 [mapping_override("Result", {"opened": ("opened", None), "refused": ("▲ refused", CRIT)}, 80)]),
        b.events("Refused by sudo or su", "Each refusal: the user may not use sudo, typed a wrong password, or asked "
                 "for a command that it may not run (alert RootAccessRefused). Empty: none in the time range.",
                 root_refused(f), g(15, y + 5, 9, 4),
                 {"hostname": "Host", "user": "User", "reason": "Reason"}, {"Host": 130, "User": 90}),
    ]
    y += 9

    p.append(b.row("Proxmox web interface and API", y))
    y += 1
    p += [
        b.bars("Proxmox logins", "Successful logins to the web interface or the API (a new ticket). Terraform logs "
               "in with the root password too. pvedaemon does not log the address of a successful login.",
               [loki_target(per_interval(pve_ok(f), "hostname"), "{{hostname}}")], g(0, y, 8, 7), colors=HOST_COLOR),
        b.bars("Proxmox failed logins", "Wrong passwords and unknown users, on each host.",
               [loki_target(per_interval(pve_fail(f), "hostname"), "{{hostname}}")], g(8, y, 8, 7), colors=HOST_COLOR),
        b.top("Logins by user", "", "topk(10, %s)" % range_count(pve_ok(f), "user, hostname"), g(16, y, 8, 7),
              {"user": "User", "hostname": "Host"}, "Logins"),
    ]
    y += 7
    p += [
        b.events("Proxmox failed logins", "Each failed login, newest first, with its address. The alert "
                 "LoginFailureBurst fires at 5 from one address in 10 minutes.", pve_fail(f), g(0, y, 10, 8),
                 {"hostname": "Host", "user": "User", "src": "Source"},
                 {"Host": 140, "User": 110}),
        b.events("Proxmox tasks: shells, consoles and changes", "Each task that a user started in the web "
                 "interface or through the API, newest first. \"Host shell\" is a root shell on the Proxmox host "
                 "itself.", pve_tasks(f), g(10, y, 14, 8),
                 {"hostname": "Host", "user": "User", "task": "Task", "vmid": "VM"},
                 {"Host": 140, "User": 100, "Task": 200, "VM": 80}, [mapping_override("Task", PVE_TASK, 200)]),
    ]
    y += 8

    p.append(b.row("VPN (road warriors)", y))
    y += 1
    p += [
        b.bars("VPN logins", "Road-warrior IKE sessions that started (not the tunnel between the sites, and not the "
               "hourly rekeys).", [loki_target(per_interval(vpn_ok(f), "hostname"), "{{hostname}}")], g(0, y, 8, 7),
               colors=HOST_COLOR),
        b.bars("VPN failed logins", "Wrong passwords and unknown users (alerts RouterVPNLoginFailed, "
               "RouterVPNUnknownUser).", [loki_target(per_interval(vpn_fail(f), "reason"), "{{reason}}")],
               g(8, y, 8, 7), colors={"wrong password": ORANGE, "unknown user": MAGENTA, "EAP failed": YELLOW}),
        b.stat("Connected now", "Road-warrior sessions that are up now, on each router.",
               [prom_target("router_ipsec_road_warriors", "{{instance}}", True)], g(16, y, 4, 7), PROM),
        b.top("IKE without a session", "Addresses that started IKE in the time range and never got an IKE "
              "session up: scanners, and clients that failed. The VPN clients and the other site's router are "
              "left out.",
              "topk(10, %s unless on (src) %s)" % (range_count(ike_start(f), "src"), range_count(ike_up(f), "src")),
              g(20, y, 4, 7), {"src": "Address"}, "IKE starts"),
    ]
    y += 7
    p += [
        b.events("VPN logins", "Each road-warrior login, newest first: the address it came from and the identity "
                 "it used.", vpn_ok(f), g(0, y, 12, 8),
                 {"hostname": "Router", "user": "Identity", "src": "Source", "conn": "Connection"},
                 {"Router": 130, "Identity": 140, "Source": 260}),
        b.events("VPN login steps", "The steps of each EAP login, newest first. A failed password has no address "
                 "or user in its line: read the user name in the line below it.", vpn_steps(f), g(12, y, 12, 8),
                 {"hostname": "Router", "step": "Step", "user": "User", "vip": "VPN address"},
                 {"Router": 130, "Step": 190, "User": 140},
                 [mapping_override("Step", {"▲ wrong password": ("▲ wrong password", CRIT),
                                            "▲ unknown user": ("▲ unknown user", CRIT),
                                            "▲ EAP failed": ("▲ EAP failed", CRIT)}, 190)]),
    ]
    y += 8

    p.append(b.row("Windows domain", y))
    y += 1
    win_status = mapping_override("Reason", {k: (v, None) for k, v in WIN_REASON.items()}, 170, False)
    p += [
        b.bars("Failed logons", "4625 failed logon, 4771 Kerberos pre-authentication failed, 4776 NTLM check "
               "failed. Successful logons are not sent to Loki.",
               [loki_target(per_interval(win_fail(f), "event"), "{{event}}")], g(0, y, 12, 7),
               colors={"4625 failed logon": BLUE, "4771 Kerberos pre-auth failed": ORANGE,
                       "4776 NTLM check failed": AQUA}),
        b.top("Failed logons by account", "", "topk(15, %s)" % range_count(win_fail(f), "user"), g(12, y, 6, 7),
              {"user": "Account"}, "Failures"),
        b.top("Failed logons by source address", "The alert ADPasswordGuessing fires at 10 failures for user "
              "accounts from one address in 10 minutes.",
              "topk(15, %s)" % range_count(win_fail(f), "client"), g(18, y, 6, 7), {"client": "Source"}, "Failures"),
    ]
    y += 7
    p += [
        b.events("Failed logons", "Each failure, newest first. A domain controller that is not the PDC sends a "
                 "wrong password on to jd-dc-01, so one try can show on two servers. An account that ends in $ is "
                 "a computer: its machine password is out of date.", win_fail(f), g(0, y, 24, 9),
                 {"hostname": "Server", "event_id": "Event", "user": "Account", "domain": "Domain",
                  "client": "Source", "workstation": "Workstation", "logon_type": "Logon type", "reason": "Reason"},
                 {"Server": 95, "Event": 180, "Account": 150, "Domain": 110, "Source": 140, "Workstation": 140,
                  "Logon type": 120},
                 [mapping_override("Event", WIN_EVENT, 180, False), win_status,
                  mapping_override("Logon type", {k: (v, None) for k, v in LOGON_TYPE.items()}, 120, False)]),
    ]
    y += 9
    p += [
        b.events("Changes to accounts", "Accounts made, enabled, disabled, deleted, unlocked or locked out, and "
                 "passwords reset, newest first. The domain has no lockout policy, so no account is locked out.",
                 win_account(f), g(0, y, 12, 8),
                 {"hostname": "Server", "event_id": "Event", "user": "Account", "actor": "By"},
                 {"Server": 95, "Event": 180, "Account": 170},
                 [mapping_override("Event", WIN_EVENT, 180)]),
        b.events("Changes to groups", "Members added to or removed from groups, and groups made or deleted, newest "
                 "first. \"Privileged\": a group that controls the domain.", win_group(f), g(12, y, 12, 8),
                 {"hostname": "Server", "event_id": "Event", "group": "Group", "member": "Member",
                  "privileged": "Privileged", "actor": "By"},
                 {"Server": 85, "Event": 165, "Group": 150, "Member": 130, "Privileged": 80},
                 [mapping_override("Event", WIN_EVENT, 170),
                  mapping_override("Privileged", {"▲ yes": ("▲ yes", SERIOUS)}, 85)]),
    ]
    y += 8

    p.append(b.row("Keycloak (single sign-on)", y))
    y += 1
    kc_note = ("Keycloak logs each login since `additionalOptions` in `keycloak/keycloak.yaml` (success level "
               "INFO of the event listener jboss-logging). Before that change these panels are empty. Grafana, "
               "Argo CD, Immich and Vault send their users here, so a login to them through single sign-on is a "
               "Keycloak LOGIN with the client's name.")
    p += [
        b.bars("Keycloak logins by client", kc_note, [loki_target(per_interval(kc_login(f), "client"), "{{client}}")],
               g(0, y, 8, 7), colors={"grafana": BLUE, "argocd": ORANGE, "immich": AQUA, "vault": YELLOW,
                                      "account-console": MAGENTA, "security-admin-console": VIOLET}),
        b.bars("Keycloak failed logins by reason", "LOGIN_ERROR events. invalid_user_credentials: a wrong "
               "password; user_not_found: an unknown user; user_temporarily_disabled: locked for a while after 10 "
               "failures.", [loki_target(per_interval(kc_fail(f), "error"), "{{error}}")], g(8, y, 8, 7),
               colors={"invalid_user_credentials": ORANGE, "user_not_found": MAGENTA,
                       "user_temporarily_disabled": YELLOW}),
        b.top("Keycloak logins by source address", "", "topk(15, %s)" % range_count(kc_login(f), "src, user"),
              g(16, y, 8, 7), {"src": "Source", "user": "User"}, "Logins"),
    ]
    y += 7
    p += [
        b.events("Keycloak events", "Logins, failures and the other events, newest first. Token refreshes, code "
                 "exchanges and logouts are left out.", kc_events(f) + ' | kc_event!~"%s"' % KC_ROUTINE,
                 g(0, y, 15, 8),
                 {"kc_event": "Event", "client": "Client", "user": "User", "src": "Source", "error": "Error"},
                 {"Event": 150, "Client": 120, "User": 110, "Source": 140},
                 [mapping_override("Event", {"LOGIN": ("LOGIN", None), "LOGIN_ERROR": ("▲ LOGIN_ERROR", CRIT)},
                                   150)]),
        b.events("Keycloak admin changes", "Changes made in the admin console or the admin API, newest first. "
                 "keycloak-config-cli makes changes at each Argo CD sync of the keycloak app.", kc_admin(f),
                 g(15, y, 9, 8),
                 {"realm": "Realm", "operation": "Change", "resource": "What", "path": "Path", "src": "Source"},
                 {"Realm": 70, "Change": 80, "What": 120}),
    ]
    y += 8

    p.append(b.row("Argo CD, Grafana and Vault", y))
    y += 1
    vault_note = """**Vault** writes no line for a login or a secret read: it has no audit device. Its log has only
the expiry of each Kubernetes-auth lease. To see who used Vault, enable an audit device to stdout, for example
`vault audit enable file file_path=stdout`. Alloy then sends it to Loki like any pod log.

**Grafana** logs at warn, so a successful login leaves no line. A login through Keycloak is a Keycloak LOGIN
(client grafana). **Argo CD** logs a login through Keycloak, but not the address."""
    p += [
        b.events("Argo CD web logins", "Logins through Keycloak, newest first.", argo_web(f), g(0, y, 8, 8),
                 {"user": "User", "login_type": "Kind"}, {"Kind": 70}),
        b.events("Argo CD local logins", "Logins with a local Argo CD account (admin), newest first: "
                 "session.SessionService/Create. OK: the login worked.", argo_local(f), g(8, y, 8, 8),
                 {"code": "Result", "error": "Error"}, {"Result": 120},
                 [mapping_override("Result", {"OK": ("OK", None), "Unauthenticated": ("▲ Unauthenticated", CRIT)},
                                   120)]),
        b.events("Grafana failed logins", "Logins that Grafana refused (a wrong password, an unknown user, a bad "
                 "API key), newest first. Expired session cookies are left out.", grafana_fail(f), g(16, y, 8, 8),
                 {"client": "Client", "error": "Error"}, {"Client": 150}),
    ]
    y += 8
    p.append(b.text("Not logged", vault_note, g(0, y, 24, 4)))

    host_var = {"name": "host", "label": "Host", "type": "query", "datasource": LOKI,
                "description": "The host or Windows server. It applies to SSH, sudo, Proxmox, the VPN and the "
                               "Windows domain.",
                "query": {"label": "hostname", "refId": "LokiVariableQueryEditor-VariableQuery",
                          "stream": '{job=~"syslog|windows"}', "type": 1},
                "definition": 'label_values({job=~"syslog|windows"}, hostname)', "refresh": 2, "sort": 1,
                "multi": True, "includeAll": True, "allValue": ".+", "current": {"text": "All", "value": "$__all"},
                "options": []}

    def textbox(name, label, desc):
        return {"name": name, "label": label, "description": desc, "type": "textbox", "query": ".*",
                "current": {"text": ".*", "value": ".*"}, "options": []}

    return {
        "uid": "security-access",
        "title": "Access and logins",
        "description": "Who logged in to what, from where, and what failed: SSH, sudo, Proxmox, the VPN, the Windows "
                       "domain, Keycloak, Argo CD, Grafana. Source: LINDS-Kubernetes monitoring-security/.",
        "tags": ["security", "logins", "ssh", "windows", "keycloak"],
        "timezone": "browser", "editable": True, "graphTooltip": 1, "schemaVersion": 39, "refresh": "5m",
        "time": {"from": "now-24h", "to": "now"},
        "annotations": {"list": []},
        "links": [{"title": "Security overview", "type": "link", "url": D["overview"], "icon": "dashboard",
                   "keepTime": True},
                  {"title": "Logs / Windows", "type": "link", "url": D["windows"], "icon": "dashboard",
                   "keepTime": True},
                  {"title": "Router", "type": "link", "url": D["router"], "icon": "dashboard", "keepTime": True},
                  {"title": "Suricata", "type": "link", "url": D["suricata"], "icon": "dashboard", "keepTime": True}],
        "templating": {"list": [
            host_var,
            textbox("user", "User", "A user or account name, as a regular expression (not case-sensitive). "
                                    "Example: admin.* for every name that starts with admin."),
            textbox("source", "Source address", "The address that the login came from, as a regular expression. "
                                                "Example: 192[.]168[.]1[.].* for a network."),
        ]},
        "panels": p,
    }


# --- Output --------------------------------------------------------------------

HEADER = """---
# Grafana dashboard "{title}" (folder Security, uid {uid}).
# The Grafana dashboard sidecar reads it (label grafana_dashboard).
#
# GENERATED. Edit dashboards.py and make this file again:
#   python3 monitoring-security/dashboards.py
#
# See monitoring-security/README.md.
apiVersion: v1
kind: ConfigMap
metadata:
  name: {name}
  namespace: monitoring
  labels:
    grafana_dashboard: "1"
  annotations:
    grafana_folder: Security
data:
  {key}: |
"""


def render(dashboard, name, key):
    out = HEADER.format(title=dashboard["title"], uid=dashboard["uid"], name=name, key=key)
    for line in json.dumps(dashboard, indent=2, ensure_ascii=False).splitlines():
        out += "    " + line + "\n"
    return out


def main():
    files = {
        "security-overview-dashboard.yaml": render(overview(), "security-overview-dashboard", "security-overview.json"),
        "security-access-dashboard.yaml": render(access(), "security-access-dashboard", "security-access.json"),
    }
    stale = []
    for name, text in files.items():
        path = HERE / name
        if "--check" in sys.argv[1:]:
            if not path.exists() or path.read_text() != text:
                stale.append(name)
        else:
            path.write_text(text)
    if stale:
        sys.exit("Not up to date, run python3 monitoring-security/dashboards.py: " + ", ".join(stale))


if __name__ == "__main__":
    main()
