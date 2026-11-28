# Security monitoring

Two Grafana dashboards (folder Security) and the alerts on logins and on log
sources that stop. All data comes from Loki and Prometheus. Nothing here
changes a host.

## The dashboards

**Security overview** (uid `security-overview`) answers two questions: is
something attacking or failing now, and are the defences on? Each block links
to the dashboard that has the detail.

| Block | What it shows |
|---|---|
| Tiles | The IPS at JD (blocking or not), Suricata events of each router, the DNS blocklists that each router loaded and the age of the oldest one, the log sources that went quiet, the VPN users, the 401 and 403 answers of the ingress controllers |
| Security alerts firing now | The alerts with `category="security"` that fire now, from Loki's ruler and Prometheus |
| Logins in the time range | Successful and failed logins for each system |
| Threats | Suricata blocks and alerts by severity, the most frequent rules, DNS questions that the blocklists refused and the devices that asked them, Cilium drops by reason |
| Access | Successful and failed logins over time for each system, changes to Windows accounts and groups (last 7 days), Windows audit failures |
| Log sources and defence alerts | The last line from each syslog and Windows source, and the Prometheus alerts on the defences in the time range |

**Access and logins** (uid `security-access`) shows who logged in to what,
from where, and what failed. It has one section for each system: the
successful logins and the failures over time, a table of the events with
parsed columns, and the most frequent sources and users. The variables Host,
User and Source address filter the panels. User and Source address are
regular expressions; `.*` is all.

| Section | What it shows |
|---|---|
| SSH | Logins and failed connections on every host that sends syslog. "New source addresses" and "New user and host pairs" show what logged in during the time range and not in the 14 days before. |
| sudo and su | sudo commands by kind: Ansible (its become marker `BECOME-SUCCESS-`), Terminal (sudo saw a TTY) and No terminal (a command over SSH, or a script). The table shows each command outside Ansible. |
| Proxmox | Logins to the web interface and the API, failures with their address, and the tasks that a user started (host shells, VM consoles, changes). |
| VPN | Road-warrior logins with their address and identity, failures, the steps of each login, and the addresses that started IKE and never got a session (scanners). |
| Windows domain | Failed logons (4625, 4771, 4776), changes to accounts and to groups. A privileged group is marked. |
| Keycloak | Logins by client, failures by reason, the other events, and the changes made through the admin API. |
| Argo CD, Grafana and Vault | Argo CD logins through Keycloak and with a local account, Grafana's refused logins, and what Vault does not log. |

No query names a person, an account or an address: the panels find them in
the logs when they run.

## Alerts

`rules.yaml` holds the alerts. Loki's ruler runs them (see
`base/monitoring/windows-security-alerts.yaml` for how the ruler is set up).
They have the label `category="security"`, so Alertmanager sends each one to
the receiver `discord-security`, one time, with no "resolved" message.

| Alert | Severity | When | Base rate |
|---|---|---|---|
| `SSHPasswordLogin` | warning | An SSH login used a password or keyboard-interactive, not a key | 0 |
| `SSHLoginFromPublicAddress` | critical | An SSH login came from an address that is not private (not in 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, or an IPv6 link-local or ULA address) | 0 |
| `LoginFailureBurst` | warning | From one address in 10 minutes: 10 SSH failure lines (about five guesses), 5 failed Proxmox logins, or 5 failed Keycloak logins | 0 |
| `RootAccessRefused` | warning | sudo or su refused a user | 0 |
| `ADPasswordGuessing` | warning | 10 failed domain logons (4625, 4771) for user accounts from one address in 10 minutes | 0 |
| `LogSourceSilent` | warning | A router, a Proxmox host, TrueNAS or a Windows server sent no line for 2 hours, while the other sources still send | 0 |

The base rate is the number of times the alert would have fired on the logs
of 2026-10-30 to 2026-11-28, which is all that Loki keeps. Each rule in
`rules.yaml` has a comment that tells why the alert is there and why its limit
is what it is.

`LogSourceSilent` has the label `site`. While `RouterTunnelDown` fires for
the tunnel to LINDS, Alertmanager holds back the alerts for the LINDS hosts.
To watch one more host, add its name to both lists in the rule and to
`STEADY_HOSTS` in `dashboards.py`. Add only a host that sends logs all the
time: a host with hours of quiet makes a false alert.

## Where the logins come from

| System | Log | Success | Failure | Address of the source |
|---|---|---|---|---|
| SSH | syslog, `appname=~"sshd.*"` | `Accepted <method> for <user> from <address>` | `Failed`, `Invalid user`, `Connection closed by ... user`, `Disconnected from ... user` | Yes |
| sudo, su | syslog, `appname=~"sudo\|su"` | `<user> : TTY=... ; USER=... ; COMMAND=...` | `user NOT in sudoers`, `incorrect password attempts`, `FAILED SU` | No |
| Proxmox | syslog, `appname="pvedaemon"` | `successful auth for user` | `authentication failure; rhost=...` | Failures only |
| VPN | syslog, `appname="charon-systemd"` | `IKE_SA <conn>[n] established between` | `EAP-MS-CHAPv2 verification failed`, `no EAP key found` | Successes only |
| Windows | Loki push from Alloy, `job="windows"` | Not sent | 4625, 4771, 4776 | Yes (4625, 4771) |
| Keycloak | pod log, `org.keycloak.events` | `type="LOGIN"` | `type="LOGIN_ERROR"` | Yes |
| Argo CD | pod log, `argocd-server` | `Web login successful`, `session.SessionService/Create` | `Create` with an error | No |
| Grafana | pod log, warn level | Not logged | `Failed to authenticate request` | No |
| Vault | pod log | Not logged | Not logged | No |

Keycloak writes its login events because of `additionalOptions` in
`keycloak/keycloak.yaml` (the success level of the event listener
`jboss-logging`).

## Files

| File | What it is |
|---|---|
| `dashboards.py` | Makes both dashboard files. Edit it, then run `python3 monitoring-security/dashboards.py`. With `--check`, it only tells whether the files are up to date. |
| `security-overview-dashboard.yaml`, `security-access-dashboard.yaml` | The dashboards. Generated by `dashboards.py`; do not edit them by hand. |
| `rules.yaml` | The alerts, as a ConfigMap with the label `loki_rule`. |
| `kustomization.yaml` | The Argo CD application `monitoring-security` (`applications/monitoring-security.yaml`) syncs this directory. |

## Test the alerts

1. Get `lokitool` of the Loki version that runs (the `lokitool-linux-amd64`
   file of the Loki release on GitHub).
2. Write the rule file out of the ConfigMap:

   ```bash
   yq '.data["security.yaml"]' monitoring-security/rules.yaml > /tmp/security.yaml
   ```

3. Check the syntax and the LogQL:

   ```bash
   lokitool rules lint --dry-run --rule-files=/tmp/security.yaml
   ```

4. Run an expression in Grafana Explore (data source Loki) over a time range
   that has the event. Change the limit (for example `>= 10` to `>= 1`) to see
   what it counts.

## Limits

- Windows sends its failed logons and its changes to accounts and groups,
  not its successful logons (LINDS-Ansible role `windows_logs`).
- The domain has no lockout policy, so no account is locked out (4740).
- Vault has no audit device. It writes no line for a login or a secret read.
- Grafana logs at warn: it writes no line for a successful login.
- Loki's ruler does not store the history of its alerts. The overview shows
  the security alerts that fire now, and the history of the Prometheus alerts
  on the defences.
- `hubble_drop_total` has no pod or namespace, only the reason.
- The "new" panels of the SSH section compare with the 14 days before the
  time range. Loki keeps 30 days, so they are right for a time range of up to
  16 days.
