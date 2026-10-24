"""Generate the Hardware Grafana dashboard (dashboard.yaml).

    python3 monitoring-hardware/dashboard.py > monitoring-hardware/dashboard.yaml

Edit this file, not dashboard.yaml.
"""
import json
import sys

DS = {"type": "prometheus", "uid": "prometheus"}
# Dark steps of the validated categorical palette, in slot order (same as the
# Router dashboard), and the status palette.
BLUE, ORANGE, AQUA, YELLOW, MAGENTA = "#3987e5", "#d95926", "#199e70", "#c98500", "#d55181"
GOOD, WARN, CRIT = "#0ca30c", "#fab219", "#d03b3b"
HOST_COLOR = {"jd-proxmox-02": BLUE, "linds-proxmox-01": ORANGE}

_ids = iter(range(1, 1000))


def target(expr, legend="", ref="A", instant=False, fmt=None):
    t = {"datasource": DS, "refId": ref, "expr": expr, "legendFormat": legend, "range": not instant, "instant": instant}
    if fmt:
        t["format"] = fmt
    return t


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


def thresholds(color="text"):
    return {"mode": "absolute", "steps": [{"color": color, "value": None}]}


# Component health, both hosts: 0 OK, 1 warning, 2 critical, 3 failed
# (Dell non-recoverable), below 0 Dell's "other"/"unknown", NaN no reading.
HEALTH_MAPPINGS = [
    {"type": "value", "options": {
        "0": {"text": "✓ OK", "color": GOOD, "index": 0},
        "1": {"text": "⚠ Warning", "color": WARN, "index": 1},
        "2": {"text": "✗ Critical", "color": CRIT, "index": 2},
        "3": {"text": "✗ Failed", "color": CRIT, "index": 3},
    }},
    {"type": "range", "options": {"from": -2, "to": -1, "result": {"text": "? Unknown", "color": "text", "index": 4}}},
    {"type": "special", "options": {"match": "nan", "result": {"text": "– No reading", "color": "text", "index": 5}}},
]


def stat(title, desc, targets, grid, unit="none", mappings=None, overrides=None, text_mode="auto",
         color_mode="value", graph="none", no_value=None, color=None, value_size=30, decimals=None,
         orientation="auto"):
    defaults = {"unit": unit, "color": color or {"mode": "thresholds"}, "mappings": mappings or [],
                "thresholds": thresholds()}
    if no_value:
        defaults["noValue"] = no_value
    if decimals is not None:
        defaults["decimals"] = decimals
    return {
        "type": "stat", "id": next(_ids), "title": title, "description": desc, "datasource": DS,
        "gridPos": grid, "targets": targets,
        "fieldConfig": {"defaults": defaults, "overrides": overrides or []},
        "options": {
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "colorMode": color_mode, "graphMode": graph, "justifyMode": "auto", "textMode": text_mode,
            "orientation": orientation, "wideLayout": True, "text": {"valueSize": value_size},
            "showPercentChange": False,
        },
    }


def timeseries(title, desc, targets, grid, unit, overrides=None, legend=True, fill=0, color=None, min_=0):
    defaults = {
        "unit": unit, "color": color or {"mode": "palette-classic"},
        "custom": {
            "drawStyle": "line", "lineWidth": 2, "lineInterpolation": "linear", "fillOpacity": fill,
            "gradientMode": "none", "showPoints": "never", "pointSize": 4, "spanNulls": False,
            "axisPlacement": "auto", "axisLabel": "", "axisBorderShow": False, "axisCenteredZero": False,
            "barAlignment": 0, "stacking": {"mode": "none", "group": "A"}, "thresholdsStyle": {"mode": "off"},
        },
        "thresholds": thresholds(),
    }
    if min_ is not None:
        defaults["min"] = min_
    return {
        "type": "timeseries", "id": next(_ids), "title": title, "description": desc, "datasource": DS,
        "gridPos": grid, "targets": targets,
        "fieldConfig": {"defaults": defaults, "overrides": overrides or []},
        "options": {
            "legend": {"showLegend": legend, "displayMode": "list", "placement": "bottom", "calcs": []},
            "tooltip": {"mode": "multi", "sort": "none"},
        },
    }


def bargauge(title, desc, targets, grid, unit, max_=None, overrides=None, no_value=None):
    defaults = {"unit": unit, "mappings": [], "color": fixed(BLUE), "thresholds": thresholds(BLUE), "min": 0}
    if max_ is not None:
        defaults["max"] = max_
    if no_value:
        defaults["noValue"] = no_value
    return {
        "type": "bargauge", "id": next(_ids), "title": title, "description": desc, "datasource": DS,
        "gridPos": grid, "targets": targets,
        "fieldConfig": {"defaults": defaults, "overrides": overrides or []},
        "options": {
            "orientation": "horizontal", "displayMode": "basic", "valueMode": "color", "namePlacement": "left",
            "showUnfilled": True, "sizing": "manual", "minVizHeight": 16, "minVizWidth": 8, "maxVizHeight": 22,
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "legend": {"showLegend": False, "displayMode": "list", "placement": "bottom"},
        },
    }


def table(title, desc, grid, queries, columns, overrides=None, sort=None):
    """One row per series: queries are [(expr, ref)], each cut down to the same
    key labels plus a value, so merge lines them up. columns maps a field
    (label name or "Value #<ref>") to its header, in display order; a field
    mapped to None is hidden."""
    return {
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


def text_states(states, other):
    """Mappings for a column that holds a state name: states maps a name to
    (text, color); any other name shows as other (a text with $1) in red."""
    return [{"id": "mappings", "value": [
        {"type": "value", "options": {k: {"text": t, "color": c, "index": i} for i, (k, (t, c)) in enumerate(states.items())}},
        {"type": "regex", "options": {"pattern": "(.+)", "result": {"text": other, "color": CRIT, "index": len(states)}}},
    ]}, {"id": "custom.cellOptions", "value": {"type": "color-text"}}]


def count_column(name, px=None):
    """A count of bad events: 0 shows as a dash, more as an amber "⚠ n" (the
    sign is a unit prefix: table cells do not fill in ${__value.raw}). The
    alerts judge whether a count matters (most fire on a rise, not a level)."""
    extra = [
        {"id": "decimals", "value": 0}, {"id": "unit", "value": "prefix:⚠ "},
        {"id": "mappings", "value": [{"type": "value", "options": {"0": {"text": "–", "color": "text", "index": 0}}},
                                     {"type": "range", "options": {"from": 1, "to": 1e15, "result": {
                                         "color": WARN, "index": 1}}}]},
        {"id": "custom.cellOptions", "value": {"type": "color-text"}}]
    if px:
        extra.append({"id": "custom.width", "value": px})
    return override(name, extra=extra)


def widths(**px):
    """Column widths in pixels, by header (underscores for spaces)."""
    return [override(k.replace("_", " "), extra=[{"id": "custom.width", "value": v}]) for k, v in px.items()]


def row(title, y):
    return {"type": "row", "id": next(_ids), "title": title, "collapsed": False,
            "gridPos": {"x": 0, "y": y, "w": 24, "h": 1}, "panels": []}


def g(x, y, w, h):
    return {"x": x, "y": y, "w": w, "h": h}


def relabel(expr, mapping):
    for to, regex in mapping:
        expr = f'label_replace({expr}, "component", "{to}", "component", "{regex}")'
    return expr


def switch_ports(grid):
    """One row per switch port: link, speed, traffic and errors, sorted by port number."""
    sw = 'job="snmp", instance="linds-switch-01", ifName=~"[0-9]+"'
    q = [
        (f"max by (ifName) (ifOperStatus{{{sw}}})", "A"),
        (f"max by (ifName) (ifHighSpeed{{{sw}}})", "B"),
        (f"sum by (ifName) (rate(ifHCInOctets{{{sw}}}[5m]) + rate(ifHCOutOctets{{{sw}}}[5m])) * 8", "C"),
        (f"sum by (ifName) (increase(ifInErrors{{{sw}}}[1h]) + increase(ifOutErrors{{{sw}}}[1h]))", "D"),
    ]
    return {
        "type": "table", "id": next(_ids), "title": "Switch ports",
        "description": "Every port of linds-switch-01: link (ifOperStatus), speed, traffic in and out together, and "
                       "damaged frames in the last hour.",
        "datasource": DS, "gridPos": grid,
        "targets": [target(e, "", ref, True, "table") for e, ref in q],
        "transformations": [
            {"id": "merge", "options": {}},
            {"id": "convertFieldType", "options": {"conversions": [{"targetField": "ifName", "destinationType": "number"}],
                                                   "fields": {}}},
            {"id": "organize", "options": {
                "excludeByName": {"Time": True},
                "indexByName": {"ifName": 0, "Value #A": 1, "Value #B": 2, "Value #C": 3, "Value #D": 4},
                "renameByName": {"ifName": "Port", "Value #A": "Link", "Value #B": "Speed", "Value #C": "Traffic",
                                 "Value #D": "Errors, 1 h"},
            }},
        ],
        "fieldConfig": {
            "defaults": {"custom": {"align": "auto", "cellOptions": {"type": "auto"}, "inspect": False},
                         "mappings": [], "thresholds": thresholds(), "color": {"mode": "thresholds"}},
            "overrides": [
                override("Link", extra=[
                    {"id": "mappings", "value": [{"type": "value", "options": {
                        "1": {"text": "✓ Up", "color": GOOD, "index": 0},
                        "2": {"text": "○ Down", "color": "text", "index": 1}}}]},
                    {"id": "custom.cellOptions", "value": {"type": "color-text"}}]),
                override("Speed", extra=[{"id": "unit", "value": "Mbits"}, {"id": "mappings", "value": [
                    {"type": "value", "options": {"0": {"text": "–", "index": 0}}}]}]),
                override("Traffic", extra=[
                    {"id": "unit", "value": "bps"}, {"id": "min", "value": 0}, {"id": "max", "value": 1e9},
                    {"id": "color", "value": fixed(BLUE)},
                    {"id": "custom.cellOptions", "value": {"type": "gauge", "mode": "basic", "valueDisplayMode": "text"}}]),
                override("Errors, 1 h", extra=[{"id": "decimals", "value": 0}]),
            ],
        },
        "options": {"showHeader": True, "cellHeight": "sm", "footer": {"show": False, "reducer": ["sum"], "fields": ""},
                    "sortBy": [{"displayName": "Port", "desc": False}]},
    }


JD = 'job="ipmi", instance="jd-proxmox-02"'
LI = 'job="snmp", instance="linds-proxmox-01"'

JD_COMPONENTS = "max by (component) (" + relabel(
    f'label_replace({{{JD}, __name__=~"ipmi_(temperature|fan_speed|voltage|current|power)_state"}}, '
    f'"component", "$1", "__name__", "ipmi_(.+)_state") or label_replace(ipmi_sensor_state{{{JD}, '
    f'type=~"Processor|Memory|Power Supply|Drive Slot|Critical Interrupt|Cable/Interconnect|Physical Security"}}, '
    f'"component", "$1", "type", "(.+)")',
    [("Temperatures", "temperature"), ("Fans", "fan_speed"), ("Voltages", "voltage"),
     ("Power", "current|power|Power Supply"), ("Processors", "Processor"), ("Drive bays", "Drive Slot"),
     ("PCIe errors", "Critical Interrupt"), ("Cables", "Cable/Interconnect"), ("Intrusion", "Physical Security")],
) + ")"

LI_COMPONENTS = "max by (component) (" + relabel(
    f'label_replace({{{LI}, __name__=~"(powerSupply|amperageProbe|coolingDevice|temperatureProbe|voltageProbe|'
    f'memoryDevice|processorDevice|systemBattery|intrusion)Status"}}, "component", "$1", "__name__", "(.+)Status")',
    [("Power", "powerSupply|amperageProbe"), ("Fans", "coolingDevice"), ("Temperatures", "temperatureProbe"),
     ("Voltages", "voltageProbe"), ("Memory", "memoryDevice"), ("Processors", "processorDevice"),
     ("Batteries", "systemBattery"), ("Intrusion", "intrusion")],
) + " - 3)"

GUESTS = '{job="pve", id=~"(qemu|lxc)/.+"}'

# Storage health (base/monitoring/proxmox-storage-health.yaml): a textfile
# collector on each Proxmox host. Its alerts decide what is wrong, so the
# status tiles here read ALERTS and cannot disagree with Discord.
SH = 'job="proxmox-storage-health"'


def storage_alerts(names):
    """2 for each firing critical storage alert whose name matches, 1 for any other."""
    sel = f'alertstate="firing", alertname=~"{names}"'
    return f'(ALERTS{{{sel}, severity="critical"}} * 2 or ALERTS{{{sel}, severity!="critical"}})'

panels = []

# --- At a glance --------------------------------------------------------------
panels += [
    stat("jd-proxmox-02", "Worst state of any sensor on the XCC (IPMI): temperatures, fans, voltages, power, memory, "
         "processors, drive bays, PCIe errors, cables, intrusion. The row below breaks it down.",
         [target(f"max({JD_COMPONENTS})")], g(0, 0, 3, 4), mappings=HEALTH_MAPPINGS, no_value="✗ No reading"),
    stat("linds-proxmox-01", "Worst state of any component the iDRAC reports over SNMP, disks and RAID left out "
         "(Storage has those). The row below breaks it down.",
         [target(f"max({LI_COMPONENTS})")], g(3, 0, 3, 4), mappings=HEALTH_MAPPINGS, no_value="✗ No reading"),
    stat("Storage", "The worst storage alert firing now: disks, ZFS pools, the PERC, thin pools, the NAS pools and "
         "the Proxmox root file systems. The Storage row breaks it down.",
         [target(f"max({storage_alerts('Storage.+')}) or vector(0)")], g(6, 0, 3, 4), mappings=HEALTH_MAPPINGS),
    stat("Power draw", "What each server draws from the wall: DCMI on the XCC, the system board power probe on the iDRAC.",
         [target(f"ipmi_dcmi_power_consumption_watts{{{JD}}}", "jd-proxmox-02"),
          target(f'amperageProbeReading{{{LI}, amperageProbeLocationName="System Board Pwr Consumption"}}',
                 "linds-proxmox-01", "B")],
         g(9, 0, 4, 4), unit="watt", text_mode="value_and_name", color_mode="none", graph="area", value_size=20,
         overrides=[override(h, color=c) for h, c in HOST_COLOR.items()]),
    stat("Inlet temperature", "The air going into each server, which is the room's temperature.",
         [target(f'ipmi_temperature_celsius{{{JD}, name="Inlet_Temp"}}', "jd-proxmox-02"),
          target(f'temperatureProbeReading{{{LI}, temperatureProbeLocationName="System Board Inlet Temp"}}',
                 "linds-proxmox-01", "B")],
         g(13, 0, 4, 4), unit="celsius", text_mode="value_and_name", color_mode="none", graph="area", value_size=20,
         overrides=[override(h, color=c) for h, c in HOST_COLOR.items()]),
    stat("Guests running", "Virtual machines and containers that Proxmox reports as running, per host.",
         [target(f"count by (instance) (pve_up{GUESTS} == 1)", "{{instance}}")],
         g(17, 0, 3, 4), text_mode="value_and_name", color_mode="none", value_size=20),
    stat("Devices not answering", "Hardware targets (BMCs, Proxmox APIs, SNMP devices, the storage health "
         "exporters) that Prometheus could not read on its last scrape. PrometheusTargetDown names them.",
         [target('count(up{job=~"snmp|ipmi|pve|proxmox-storage-health"} == 0) or vector(0)')], g(20, 0, 4, 4),
         mappings=[{"type": "value", "options": {"0": {"text": "✓ None", "color": GOOD, "index": 0}}},
                   {"type": "range", "options": {"from": 1, "to": 1000, "result": {"text": "✗ ${__value.raw}",
                                                                                    "color": CRIT, "index": 1}}}]),
]

# --- jd-proxmox-02 ---------------------------------------------------------------
y = 4
panels.append(row("jd-proxmox-02 · Lenovo SR655 · XCC over IPMI", y))
panels += [
    stat("Health by component", "The worst state among the sensors of each kind, by the XCC's own thresholds. "
         "HardwareSensorNotOk names the sensor.",
         [target(JD_COMPONENTS, "{{component}}")], g(0, y + 1, 6, 9), mappings=HEALTH_MAPPINGS,
         text_mode="value_and_name", value_size=16),
    timeseries("Temperatures", "The CPU, the air in and out, and the hottest DIMM and PCIe slot (each the warmest of "
               "its sensors).",
               [target(f'ipmi_temperature_celsius{{{JD}, name="CPU_Temp"}}', "CPU"),
                target(f'ipmi_temperature_celsius{{{JD}, name="Outlet_Temp"}}', "Outlet", "B"),
                target(f'ipmi_temperature_celsius{{{JD}, name="Inlet_Temp"}}', "Inlet", "C"),
                target(f'max(ipmi_temperature_celsius{{{JD}, name=~"DIMM.+_Temp"}})', "Hottest DIMM", "D"),
                target(f'max(ipmi_temperature_celsius{{{JD}, name=~"PCIe.+_Temp"}})', "Hottest PCIe slot", "E")],
               g(6, y + 1, 9, 9), "celsius",
               overrides=[override("CPU", color=BLUE), override("Outlet", color=ORANGE), override("Inlet", color=AQUA),
                          override("Hottest DIMM", color=YELLOW), override("Hottest PCIe slot", color=MAGENTA)]),
    timeseries("Power draw", "From the wall, as DCMI reports it.",
               [target(f"ipmi_dcmi_power_consumption_watts{{{JD}}}", "Power")], g(15, y + 1, 9, 9), "watt",
               legend=False, fill=10, color=fixed(BLUE)),
    timeseries("Fan speed", "The slowest and the fastest of the six fans. fan-control.service sets one duty for all, "
               "so a fan that stops or slows pulls the slowest line away from the fastest.",
               [target(f"min(ipmi_fan_speed_rpm{{{JD}}})", "Slowest fan"),
                target(f"max(ipmi_fan_speed_rpm{{{JD}}})", "Fastest fan", "B")],
               g(0, y + 10, 9, 8), "rotrpm",
               overrides=[override("Slowest fan", color=BLUE), override("Fastest fan", color=ORANGE)]),
    bargauge("Fans now", "Each fan's speed at the last scrape.",
             [target(f'label_replace(ipmi_fan_speed_rpm{{{JD}}}, "fan", "Fan $1", "name", "FAN([0-9]+)_F_Speed")',
                     "{{fan}}", instant=True)], g(9, y + 10, 9, 8), "rotrpm"),
    stat("Event log", "Entries in the BMC's event log (SEL), and the space left. HardwareEventLogged tells Discord "
         "when one is added; read them in the XCC (Events) or with `ipmitool sel elist` on the host.",
         [target(f"ipmi_sel_logs_count{{{JD}}}", "Entries"),
          target(f"ipmi_sel_free_space_bytes{{{JD}}}", "Free space", "B")],
         g(18, y + 10, 6, 8), text_mode="value_and_name", color_mode="none", value_size=24,
         overrides=[override("Free space", extra=[{"id": "unit", "value": "bytes"}])]),
]

# --- linds-proxmox-01 --------------------------------------------------------------
y = 22
panels.append(row("linds-proxmox-01 · Dell T630 · iDRAC8 over SNMP", y))
panels += [
    stat("Health by component", "The worst state among the components of each kind, as the iDRAC judges them. Disks "
         "and the PERC are left to storage health. HardwareSensorNotOk names the component.",
         [target(LI_COMPONENTS, "{{component}}")], g(0, y + 1, 6, 9), mappings=HEALTH_MAPPINGS,
         text_mode="value_and_name", value_size=16),
    timeseries("Temperatures", "Both CPUs and the air coming in.",
               [target(f"temperatureProbeReading{{{LI}}}", "{{temperatureProbeLocationName}}")],
               g(6, y + 1, 9, 9), "celsius",
               overrides=[override("CPU1 Temp", "CPU 1", BLUE), override("CPU2 Temp", "CPU 2", MAGENTA),
                          override("System Board Inlet Temp", "Inlet", AQUA)]),
    timeseries("Power draw", "From the wall: the iDRAC's system board power probe.",
               [target(f'amperageProbeReading{{{LI}, amperageProbeLocationName="System Board Pwr Consumption"}}',
                       "Power")], g(15, y + 1, 9, 9), "watt", legend=False, fill=10, color=fixed(BLUE)),
    timeseries("Fan speed", "The slowest and the fastest of the six fans. The iDRAC runs them in two groups, so "
               "the two lines differ; a fan that stops pulls the slowest line down.",
               [target(f"min(coolingDeviceReading{{{LI}}})", "Slowest fan"),
                target(f"max(coolingDeviceReading{{{LI}}})", "Fastest fan", "B")],
               g(0, y + 10, 12, 8), "rotrpm",
               overrides=[override("Slowest fan", color=BLUE), override("Fastest fan", color=ORANGE)]),
    bargauge("Fans now", "Each fan's speed at the last scrape.",
             [target(f'label_replace(coolingDeviceReading{{{LI}}}, "fan", "Fan $1", "coolingDeviceLocationName", '
                     f'"System Board Fan([0-9]+)")', "{{fan}}", instant=True)], g(12, y + 10, 12, 8), "rotrpm"),
]

# --- Storage ---------------------------------------------------------------------
y = 40
panels.append(row("Storage · disks, ZFS pools, PERC and thin pools · storage health", y))
STORAGE_PARTS = [
    ("Disks", "StorageSmart.+"), ("ZFS pools", "StorageZfs.+"), ("PERC", "StorageRaid.+"),
    ("Thin pools", "StorageThinPool.+"), ("NAS pools", "StorageTrueNas.+"), ("Proxmox local", "StorageProxmoxLocal.+"),
    ("Collector", "StorageHealth.+"),
]
panels += [
    stat("Health by part", "The worst storage alert firing now for each part. Disks is SMART on both hosts; ZFS pools "
         "and thin pools are the hosts' own; NAS pools is linds-truenas-01; Collector means a host stopped reporting.",
         [target(f"max({storage_alerts(names)}) or vector(0)", part, chr(65 + i))
          for i, (part, names) in enumerate(STORAGE_PARTS)],
         g(0, y + 1, 5, 9), mappings=HEALTH_MAPPINGS, text_mode="value_and_name", value_size=16,
         orientation="horizontal"),
    table("ZFS pools", "Each pool on the Proxmox hosts. Disk errors are the read, write and checksum errors of its "
          "disks since the last `zpool clear`. Last scrub is the time since the last scrub that ran to the end; "
          "StorageZfsScrubOverdue fires after nine days for a pool scrubbed weekly, forty for a monthly one.",
          g(5, y + 1, 13, 9), [
              (f"max by (instance, pool, state) (storage_zfs_pool_state{{{SH}}} == 1)", "A"),
              (f"max by (instance, pool) (storage_zfs_pool_allocated_bytes{{{SH}}} / storage_zfs_pool_size_bytes{{{SH}}})", "B"),
              (f"max by (instance, pool) (storage_zfs_pool_size_bytes{{{SH}}})", "C"),
              (f"max by (instance, pool) (storage_zfs_pool_data_errors{{{SH}}})", "D"),
              (f'sum by (instance, pool) (storage_zfs_vdev_errors{{{SH}, type="disk"}})', "E"),
              (f"max by (instance, pool) (time() - (storage_zfs_scrub_last_end_timestamp_seconds{{{SH}}} "
               f"or storage_zfs_scrub_last_start_timestamp_seconds{{{SH}}} or storage_zfs_pool_created_timestamp_seconds{{{SH}}}))", "F"),
              (f"max by (instance, pool) (storage_zfs_scrub_in_progress{{{SH}}})", "G"),
          ], {"instance": "Host", "pool": "Pool", "state": "State", "Value #A": None, "Value #B": "Used",
              "Value #C": "Size", "Value #D": "Data errors", "Value #E": "Disk errors", "Value #F": "Last scrub",
              "Value #G": "Scrub"},
          overrides=[
              override("State", extra=text_states({"ONLINE": ("✓ Online", GOOD)}, "✗ $1")),
              override("Used", extra=[
                  {"id": "unit", "value": "percentunit"}, {"id": "min", "value": 0}, {"id": "max", "value": 1},
                  {"id": "color", "value": fixed(BLUE)},
                  {"id": "custom.cellOptions", "value": {"type": "gauge", "mode": "basic", "valueDisplayMode": "text"}}]),
              override("Size", extra=[{"id": "unit", "value": "bytes"}]),
              count_column("Data errors"), count_column("Disk errors"),
              override("Last scrub", extra=[{"id": "unit", "value": "s"}, {"id": "decimals", "value": 1}]),
              override("Scrub", extra=[{"id": "mappings", "value": [{"type": "value", "options": {
                  "1": {"text": "◐ Running", "color": "text", "index": 0},
                  "0": {"text": "–", "color": "text", "index": 1}}}]}]),
              *widths(Host=130, Pool=90, State=90, Used=170, Size=80, Data_errors=95, Disk_errors=95, Last_scrub=95),
          ], sort=[{"displayName": "Pool", "desc": False}]),
    bargauge("Thin pools", "Each LVM thin pool's data and metadata space. A full thin pool does not fail writes: it "
             "silently zero-fills new chunks (StorageThinPoolNearlyFull).",
             [target(f'label_replace(storage_lvm_thin_used_ratio{{{SH}}}, "host", "$1", "instance", "([a-z]+)-.+")',
                     "{{host}} {{vg}} {{space}}", instant=True)],
             g(18, y + 1, 6, 9), "percentunit", max_=1),
]
DISK_KEY = "instance, device"
panels.append(table(
    "Disks", "Every drive SMART can read, on both hosts (the PERC passes its disks through as megaraid,N). Health is "
             "the drive's own verdict, a failing attribute or an NVMe critical warning. Wear is the share of rated "
             "endurance used (SSDs). Long test is the time since the last long self-test; "
             "StorageSmartSelfTestOverdue fires after 45 days.",
    g(0, y + 10, 24, 24), [
        (f"max by ({DISK_KEY}, model, serial, media) (storage_smart_device_info{{{SH}}})", "A"),
        (f"max by ({DISK_KEY}) ((storage_smart_healthy{{{SH}}} == 0) * 0 + 2 "
         f"or (storage_smart_attributes_failing{{{SH}}} > 0) * 0 + 2 "
         f"or (storage_smart_nvme_critical_warning{{{SH}}} > 0) * 0 + 2 or storage_smart_healthy{{{SH}}} * 0)", "B"),
        (f"max by ({DISK_KEY}) (storage_smart_temperature_celsius{{{SH}}})", "C"),
        (f"max by ({DISK_KEY}) (storage_smart_endurance_used_ratio{{{SH}}})", "D"),
        (f"max by ({DISK_KEY}) (storage_smart_reallocated_sectors{{{SH}}})", "E"),
        (f"max by ({DISK_KEY}) (storage_smart_pending_sectors{{{SH}}})", "F"),
        (f"max by ({DISK_KEY}) (storage_smart_uncorrectable_errors{{{SH}}})", "G"),
        (f"max by ({DISK_KEY}) (storage_smart_crc_errors{{{SH}}})", "H"),
        (f"max by ({DISK_KEY}) (storage_smart_power_on_hours{{{SH}}}) * 3600", "I"),
        (f"max by ({DISK_KEY}) (storage_smart_written_bytes{{{SH}}})", "J"),
        (f"max by ({DISK_KEY}) (storage_smart_selftest_long_age_seconds{{{SH}}})", "K"),
        (f"max by ({DISK_KEY}) ((storage_smart_selftest_in_progress{{{SH}}} == 1) * 0 + 2 "
         f"or storage_smart_selftest_last_passed{{{SH}}})", "L"),
    ], {"instance": "Host", "device": "Device", "model": "Model", "serial": "Serial", "media": "Type",
        "Value #A": None, "Value #B": "Health", "Value #C": "Temp", "Value #D": "Wear", "Value #E": "Reallocated",
        "Value #F": "Pending", "Value #G": "Uncorrectable", "Value #H": "CRC errors", "Value #I": "Powered on",
        "Value #J": "Written", "Value #K": "Long test", "Value #L": "Last test"},
    overrides=[
        override("Type", extra=[{"id": "mappings", "value": [{"type": "value", "options": {
            "hdd": {"text": "HDD", "index": 0}, "ssd": {"text": "SSD", "index": 1}, "nvme": {"text": "NVMe", "index": 2}}}]}]),
        override("Health", extra=[
            {"id": "mappings", "value": [{"type": "value", "options": {
                "0": {"text": "✓ OK", "color": GOOD, "index": 0}, "2": {"text": "✗ Failing", "color": CRIT, "index": 1}}}]},
            {"id": "custom.cellOptions", "value": {"type": "color-text"}}]),
        override("Temp", extra=[{"id": "unit", "value": "celsius"}]),
        override("Wear", extra=[{"id": "unit", "value": "percentunit"}, {"id": "decimals", "value": 0}]),
        count_column("Reallocated"), count_column("Pending"), count_column("Uncorrectable"), count_column("CRC errors"),
        *widths(Host=140, Device=100, Model=230, Serial=180, Type=70, Health=95, Temp=75, Wear=70, Reallocated=110,
                Pending=90, Uncorrectable=120, CRC_errors=100, Powered_on=105, Written=85, Long_test=90),
        override("Powered on", extra=[{"id": "unit", "value": "s"}, {"id": "decimals", "value": 1}, {"id": "mappings", "value": [
            {"type": "value", "options": {"0": {"text": "–", "index": 0}}}]}]),
        override("Written", extra=[{"id": "unit", "value": "decbytes"}, {"id": "decimals", "value": 0}]),
        override("Long test", extra=[{"id": "unit", "value": "s"}, {"id": "decimals", "value": 1}]),
        override("Last test", extra=[
            {"id": "mappings", "value": [{"type": "value", "options": {
                "1": {"text": "✓ Passed", "color": GOOD, "index": 0}, "0": {"text": "✗ Failed", "color": CRIT, "index": 1},
                "2": {"text": "◐ Running", "color": "text", "index": 2}}}]},
            {"id": "custom.cellOptions", "value": {"type": "color-text"}}]),
    ], sort=[{"displayName": "Device", "desc": False}]))
PERC_STATES = {"Optl": ("✓ Optimal", GOOD)}
panels += [
    table("PERC virtual disks", "The arrays on the PERC H730 of linds-proxmox-01. Bad blocks are the controller's "
          "list of unreadable blocks, per array. Patrol read and consistency check: whether the controller "
          "includes the array in its scheduled checks.",
          g(0, y + 34, 8, 13), [
              (f"max by (instance, vd, name, raid, state) (storage_raid_vd_state{{{SH}}} == 1)", "A"),
              (f"sum by (instance, vd) (storage_raid_vd_bad_blocks{{{SH}}})", "B"),
              (f"max by (instance, vd) (storage_raid_vd_patrol_read_scheduled{{{SH}}})", "C"),
              (f"max by (instance, vd) (storage_raid_vd_consistency_check_scheduled{{{SH}}})", "D"),
          ], {"instance": None, "vd": None, "name": "Array", "raid": "RAID", "state": "State", "Value #A": None,
              "Value #B": "Bad blocks", "Value #C": "Patrol read", "Value #D": "Consistency check"},
          overrides=[
              override("State", extra=text_states(PERC_STATES, "✗ $1")),
              count_column("Bad blocks"),
              *[override(c, extra=[{"id": "mappings", "value": [{"type": "value", "options": {
                  "1": {"text": "✓ Scheduled", "color": GOOD, "index": 0},
                  "0": {"text": "○ Not scheduled", "color": "text", "index": 1}}}]},
                  {"id": "custom.cellOptions", "value": {"type": "color-text"}}]) for c in ("Patrol read", "Consistency check")],
              *widths(Array=65, RAID=55, State=95, Bad_blocks=85, Patrol_read=130),
          ], sort=[{"displayName": "Array", "desc": False}]),
    table("PERC physical disks", "Each disk behind the PERC, by enclosure:slot, as the controller sees it. Its error "
          "counters are its own, beside the drive's SMART in Disks.",
          g(8, y + 34, 13, 13), [
              (f"max by (instance, slot, model, serial, state) (storage_raid_pd_state{{{SH}}} == 1)", "A"),
              (f"max by (instance, slot) (storage_raid_pd_media_errors{{{SH}}})", "B"),
              (f"max by (instance, slot) (storage_raid_pd_other_errors{{{SH}}})", "C"),
              (f"max by (instance, slot) (storage_raid_pd_predictive_failures{{{SH}}})", "D"),
              (f"max by (instance, slot) (storage_raid_pd_smart_alert{{{SH}}})", "E"),
          ], {"instance": None, "slot": "Slot", "model": "Model", "serial": "Serial", "state": "State", "Value #A": None,
              "Value #B": "Media errors", "Value #C": "Other errors", "Value #D": "Failure predicted",
              "Value #E": "SMART alert"},
          overrides=[
              override("State", extra=text_states({
                  "Onln": ("✓ Online", GOOD), "JBOD": ("✓ JBOD", GOOD), "GHS": ("○ Hot spare", "text"),
                  "DHS": ("○ Hot spare", "text"), "UGood": ("○ Unconfigured", "text"), "Rbld": ("◐ Rebuilding", WARN),
                  "Cpybck": ("◐ Copyback", WARN)}, "✗ $1")),
              count_column("Media errors"), count_column("Other errors"), count_column("Failure predicted"),
              count_column("SMART alert"),
              *widths(Slot=55, Model=165, Serial=150, State=120, Media_errors=105, Other_errors=100,
                      Failure_predicted=130),
          ], sort=[{"displayName": "Slot", "desc": False}]),
    stat("PERC", "The controller and its cache battery as the controller rates them, and its scheduled patrol "
         "reads and consistency checks (StorageRaidNotPatrolled, StorageRaidPatrolReadStalled, "
         "StorageRaidConsistencyCheckStalled).",
         [target(f'max((storage_raid_controller_state{{{SH}, state="Optimal"}} == 1) * 0 '
                 f'or (storage_raid_controller_state{{{SH}}} == 1) * 0 + 2)', "Controller"),
          target(f'max((storage_raid_battery_state{{{SH}, state="Optimal"}} == 1) * 0 '
                 f'or (storage_raid_battery_state{{{SH}}} == 1) * 0 + 2)', "Battery", "B"),
          target(f"max({storage_alerts('StorageRaid(NotPatrolled|PatrolReadStalled)')}) or vector(0)", "Patrol read", "C"),
          target(f"max({storage_alerts('StorageRaidConsistencyCheckStalled')}) or vector(0)", "Consistency check", "D")],
         g(21, y + 34, 3, 13), mappings=HEALTH_MAPPINGS, text_mode="value_and_name", value_size=16,
         no_value="– No reading", orientation="horizontal"),
]
MEDIA_TEMP = (f"max by (instance) (storage_smart_temperature_celsius{{{SH}}} * on (instance, device) "
              f"group_left (media) storage_smart_device_info{{{SH}, media=~\"{{m}}\"}})")
panels += [
    timeseries("Hottest disk", "The warmest hard disk and the warmest SSD on each host. Disks shows each drive; "
               "StorageSmartHot fires above the drive's own limit.",
               [target(MEDIA_TEMP.replace("{m}", "hdd"), "{{instance}} HDD"),
                target(MEDIA_TEMP.replace("{m}", "ssd|nvme"), "{{instance}} SSD", "B")],
               g(0, y + 47, 12, 8), "celsius", min_=None,
               overrides=[override("jd-proxmox-02 HDD", color=BLUE), override("linds-proxmox-01 HDD", color=ORANGE),
                          override("jd-proxmox-02 SSD", color=AQUA), override("linds-proxmox-01 SSD", color=YELLOW)]),
    timeseries("Written to disks, per day", "What the drives on each host report as written (SMART), at the rate of "
               "the last two hours, scaled to a day. RAID parity and ZFS copies are in it: this is what wears the "
               "drives, not what the guests write.",
               [target(f"sum by (instance) (rate(storage_smart_written_bytes{{{SH}}}[2h])) * 86400", "{{instance}}")],
               g(12, y + 47, 12, 8), "decbytes",
               overrides=[override(h, color=c) for h, c in HOST_COLOR.items()]),
]

# --- Proxmox ---------------------------------------------------------------------
y = 95
panels.append(row("Proxmox", y))
guests = {
    "type": "table", "id": next(_ids), "title": "Guests",
    "description": "Every virtual machine and container on both hosts, templates left out. CPU is the share of the "
                   "guest's own cores. A QEMU guest's memory comes from its balloon driver, which can read above its "
                   "size.",
    "datasource": DS, "gridPos": g(0, y + 1, 24, 11),
    "targets": [
        target(f'max by (instance, id, name, type) (pve_up{GUESTS} * on (instance, id) group_left (name, type) '
               f'pve_guest_info{{job="pve", template="0"}})', "", "A", True, "table"),
        *[target(f'max by (instance, id) ({metric}{GUESTS} and on (instance, id) pve_guest_info{{job="pve", template="0"}})',
                 "", ref, True, "table")
          for ref, metric in (("B", "pve_cpu_usage_ratio"), ("C", "pve_memory_usage_bytes"),
                              ("D", "pve_memory_size_bytes"), ("E", "pve_uptime_seconds"))],
    ],
    # One row per guest: every query is cut down to (instance, id) plus the
    # values, so merge lines them up. Templates are left out in each query.
    "transformations": [
        {"id": "merge", "options": {}},
        {"id": "organize", "options": {
            "excludeByName": {"Time": True},
            "indexByName": {"instance": 0, "name": 1, "id": 2, "type": 3, "Value #A": 4, "Value #B": 5,
                            "Value #C": 6, "Value #D": 7, "Value #E": 8},
            "renameByName": {"instance": "Host", "name": "Guest", "id": "ID", "type": "Type", "Value #A": "State",
                             "Value #B": "CPU", "Value #C": "Memory used", "Value #D": "Memory", "Value #E": "Up for"},
        }},
    ],
    "fieldConfig": {
        "defaults": {"custom": {"align": "auto", "cellOptions": {"type": "auto"}, "inspect": False},
                     "mappings": [], "thresholds": thresholds(), "color": {"mode": "thresholds"}},
        "overrides": [
            override("State", extra=[
                {"id": "mappings", "value": [{"type": "value", "options": {
                    "1": {"text": "✓ Running", "color": GOOD, "index": 0},
                    "0": {"text": "○ Stopped", "color": "text", "index": 1}}}]},
                {"id": "custom.cellOptions", "value": {"type": "color-text"}}]),
            override("CPU", extra=[{"id": "unit", "value": "percentunit"}, {"id": "decimals", "value": 1}]),
            override("Memory used", extra=[{"id": "unit", "value": "bytes"}]),
            override("Memory", extra=[{"id": "unit", "value": "bytes"}]),
            override("Up for", extra=[{"id": "unit", "value": "dtdurations"}, {"id": "mappings", "value": [
                {"type": "value", "options": {"0": {"text": "–", "index": 0}}}]}]),
        ],
    },
    "options": {"showHeader": True, "cellHeight": "sm", "footer": {"show": False, "reducer": ["sum"], "fields": ""},
                "sortBy": [{"displayName": "Guest", "desc": False}]},
}
panels.append(guests)
panels += [
    timeseries("Host CPU", "Each host's CPU use, as Proxmox reports it.",
               [target('pve_cpu_usage_ratio{job="pve", id=~"node/.+"}', "{{instance}}")], g(0, y + 12, 8, 8),
               "percentunit", overrides=[override(h, color=c) for h, c in HOST_COLOR.items()]),
    timeseries("Host memory", "Memory in use as Proxmox counts it, the ZFS ARC included on jd-proxmox-02, so a high "
               "figure there is the cache doing its job.",
               [target('pve_memory_usage_bytes{job="pve", id=~"node/.+"} / pve_memory_size_bytes{job="pve", id=~"node/.+"}',
                       "{{instance}}")], g(8, y + 12, 8, 8), "percentunit",
               overrides=[override(h, color=c) for h, c in HOST_COLOR.items()]),
    bargauge("Storage used", "Every Proxmox storage. local is the host's root file system "
             "(StorageProxmoxLocalNearlyFull); the ZFS pools and thin pools have storage health's alerts.",
             [target('(pve_disk_usage_bytes{job="pve"} / pve_disk_size_bytes{job="pve"}) * on (instance, id) '
                     'group_left (storage) pve_storage_info{job="pve"}', "{{instance}} · {{storage}}", instant=True)],
             g(16, y + 12, 8, 8), "percentunit", max_=1),
]

# --- LINDS network and NAS ----------------------------------------------------------
y = 115
NAS = 'job="snmp", instance="linds-truenas-01"'
SW = 'job="snmp", instance="linds-switch-01"'
VY = 'job="snmp", instance="linds-vyos-01"'
panels.append(row("LINDS · TrueNAS, switch and router over SNMP", y))
panels += [
    stat("NAS pools", "Each ZFS pool on linds-truenas-01. StorageTrueNasPoolNotOnline says which state it is in.",
         [target(f'(zpoolHealth{{{NAS}, zpoolHealth="ONLINE"}} * 0) or (zpoolHealth{{{NAS}, zpoolHealth!="ONLINE"}} * 2)',
                 "{{zpoolName}}")], g(0, y + 1, 6, 7), text_mode="value_and_name", value_size=16,
         mappings=[{"type": "value", "options": {"0": {"text": "✓ Online", "color": GOOD, "index": 0},
                                                 "2": {"text": "✗ Not online", "color": CRIT, "index": 1}}}],
         no_value="– No reading"),
    bargauge("NAS pool space", "Used over used plus available, for each pool's root dataset.",
             [target(f'datasetUsedBytes{{{NAS}, datasetDescr!~".+/.+"}} / (datasetUsedBytes{{{NAS}, datasetDescr!~".+/.+"}}'
                     f' + datasetAvailableBytes{{{NAS}, datasetDescr!~".+/.+"}})', "{{datasetDescr}}", instant=True)],
             g(6, y + 1, 6, 7), "percentunit", max_=1),
    timeseries("NAS throughput", "Read and written, all pools together.",
               [target(f"sum(rate(zpoolReadBytes{{{NAS}}}[5m]))", "Read"),
                target(f"sum(rate(zpoolWriteBytes{{{NAS}}}[5m]))", "Written", "B")],
               g(12, y + 1, 6, 7), "Bps",
               overrides=[override("Read", color=BLUE), override("Written", color=ORANGE)]),
    timeseries("NAS ARC", "The ZFS read cache in RAM, and the size ZFS is aiming for.",
               [target(f"zfsArcSize{{{NAS}}}", "Size"), target(f"zfsArcC{{{NAS}}}", "Target", "B")],
               g(18, y + 1, 6, 7), "bytes",
               overrides=[override("Size", color=BLUE), override("Target", color=ORANGE)]),
    stat("Switch", "linds-switch-01 (OfficeConnect 1920S): ports with a link, and how long since it started.",
         [target(f'count(ifOperStatus{{{SW}, ifName=~"[0-9]+"}} == 1)', "Ports up"),
          target(f"sysUpTime{{{SW}}} / 100", "Up for", "B")],
         g(0, y + 8, 4, 10), text_mode="value_and_name", color_mode="none", value_size=24,
         overrides=[override("Up for", extra=[{"id": "unit", "value": "dtdurations"}])]),
    switch_ports(g(4, y + 8, 12, 10)),
    bargauge("Damaged frames in the last hour", "Ethernet interfaces on the SNMP devices with receive or transmit "
             "errors in the last hour. NetworkInterfaceErrors fires above 100.",
             [target('sort_desc(((increase(ifInErrors{job="snmp"}[1h]) + increase(ifOutErrors{job="snmp"}[1h])) > 0) '
                     'and on (instance, ifIndex) ifType_info{job="snmp", ifType="ethernetCsmacd"})',
                     "{{instance}} · {{ifName}}", instant=True)],
             g(16, y + 8, 8, 10), "short", no_value="✓ None"),
    timeseries("linds-vyos-01: internet and tunnel", "The LINDS router's WAN (eth1) and the tunnel to JD (vti0). "
               "Until the cutover to linds-router-01, which the Router dashboard shows.",
               [target(f'rate(ifHCInOctets{{{VY}, ifName=~"eth1|vti0"}}[5m]) * 8', "{{ifName}} in"),
                target(f'rate(ifHCOutOctets{{{VY}, ifName=~"eth1|vti0"}}[5m]) * 8', "{{ifName}} out", "B")],
               g(0, y + 18, 24, 8), "bps",
               overrides=[override("eth1 in", "Internet in", BLUE), override("eth1 out", "Internet out", ORANGE),
                          override("vti0 in", "Tunnel in", AQUA), override("vti0 out", "Tunnel out", YELLOW)]),
]

dashboard = {
    "uid": "hardware",
    "title": "Hardware",
    "description": "Both hosts' BMCs, storage and Proxmox, and the LINDS NAS, switch and router. Exporters, "
                   "scrape jobs and alerts: LINDS-Kubernetes monitoring-hardware/ (README). The Storage row reads "
                   "storage health (base/monitoring/proxmox-storage-health.yaml).",
    "tags": ["hardware", "proxmox"],
    "timezone": "browser",
    "editable": True,
    "graphTooltip": 1,
    "schemaVersion": 39,
    "time": {"from": "now-24h", "to": "now"},
    "refresh": "1m",
    "templating": {"list": []},
    "annotations": {"list": [{
        "name": "Hardware alerts", "enable": True, "datasource": DS,
        "expr": 'ALERTS{alertname=~"Hardware.*|ProxmoxGuestStopped|NetworkInterfaceErrors|StorageTrueNas.*|'
                'StorageProxmoxLocalNearlyFull", alertstate="firing"} '
                'or ALERTS{alertname=~"Storage.+", severity="critical", alertstate="firing"}',
        "step": "60s", "titleFormat": "{{alertname}}",
        "textFormat": "{{instance}} {{sensor}}{{name}}{{pool}}{{device}}{{slot}}",
        "iconColor": CRIT, "useValueForTime": False,
    }]},
    "panels": panels,
}

HEADER = """---
# Grafana dashboard "Hardware": both hosts' BMCs, storage and Proxmox, and the
# LINDS NAS, switch and router. Picked up by the kube-prometheus grafana
# dashboard sidecar via the grafana_dashboard label; grafana_folder puts it in
# "Hardware".
#
# GENERATED by dashboard.py. Edit that file and run it again:
#   python3 monitoring-hardware/dashboard.py > monitoring-hardware/dashboard.yaml
#
# The data: the snmp, ipmi and pve jobs (scrape-configs.yaml) and storage
# health's proxmox-storage-health job. The alerts show as annotations. Like
# the Router dashboard: status tiles use the status colours with a text label
# (green "✓ OK", amber "⚠ Warning", red "✗ Critical"), and series use the
# same fixed colours in the same order, so jd-proxmox-02 is blue and
# linds-proxmox-01 orange wherever both are drawn.
apiVersion: v1
kind: ConfigMap
metadata:
  name: hardware-dashboard
  labels:
    grafana_dashboard: "1"
  annotations:
    grafana_folder: Hardware
data:
  hardware.json: |
"""
sys.stdout.write(HEADER)
for line in json.dumps(dashboard, indent=2, ensure_ascii=False).splitlines():
    sys.stdout.write("    " + line + "\n")
