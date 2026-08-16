# Zabbix configuration

The Helm release lives in
[`applications/zabbix.yaml`](../applications/zabbix.yaml). This directory holds
everything *inside* Zabbix: hosts, host groups, non-stock templates, alerting,
network discovery, global settings, and SSO.

Design: [`docs/superpowers/specs/2026-08-16-zabbix-config-as-code-design.md`](../docs/superpowers/specs/2026-08-16-zabbix-config-as-code-design.md)

## How the pieces fit

- **`config/site.yml`** is an Ansible playbook that reconciles this directory
  into the running Zabbix over the JSON-RPC API, using
  [`community.zabbix`](https://github.com/ansible-collections/community.zabbix)
  4.2.0.
- **`config-job.yaml`** runs it as an Argo CD `PostSync` hook, so it fires after
  the server is up and a bad configuration fails the sync instead of drifting
  silently.
- **`kustomization.yaml`** turns `config/` into ConfigMaps. It generates four,
  because ConfigMap keys cannot contain a slash and the playbook expects
  `templates/`, `media/` and `vars/` subdirectories.
- **`saml/idp.crt`** is Keycloak's realm signing certificate, mounted into the
  *frontend* pods rather than applied through the API — see [SSO](#sso).

The Application in `applications/zabbix.yaml` carries two sources: the upstream
chart and this directory. They sync as one unit deliberately, so the hook
cannot run before the server exists.

## Semantics: create and update, never prune

Objects that are not described here are left alone. Add a host in the frontend
and it survives; the playbook only creates what is missing and updates the
fields these files actually name. Experimenting in the UI stays cheap, and
promoting an experiment to code is a commit.

**Three exceptions**, each for a structural reason rather than a choice:

| Where | Why |
|---|---|
| `globals.yml`, and `zabbix_authentication` in `access.yml` | These write instance-wide singletons. The API replaces the whole object, so every field named there is reset on every run and can no longer be changed in the frontend. |
| `hosts.yml` | Runs with `force: true`. A template linked or a macro added to a managed host through the UI is removed on the next sync. This is the trade for "a rebuild reproduces the hosts exactly". |
| `template_tweaks.yml` | Only ever disables. It never re-enables anything, so enabling one of those objects by hand sticks until the entry is removed here. |

## Running it by hand

Everything is env-driven, so a checkout runs identically to the Job:

```bash
kubectl port-forward -n zabbix svc/zabbix-zabbix-web 18080:80 &

cd zabbix/config
export ZBX_API_HOST=127.0.0.1 ZBX_API_PORT=18080
V() { vault kv get -field="$1" linds-keyvault/zabbix-config; }
export ZBX_ADMIN_PASSWORD="$(V admin_password)"
export PVE_TOKEN_SECRET_JD="$(V pve_token_secret_jd)"
export PVE_TOKEN_SECRET_LINDS="$(V pve_token_secret_linds)"
export IPMI_PASSWORD="$(V ipmi_password)"
export SNMPV3_AUTH_PASSPHRASE="$(V snmpv3_auth_passphrase)"
export DISCORD_WEBHOOK_URL="$(V discord_webhook_url)"
export ZBX_VIEWER_TOKEN="$(V zbx_viewer_token)"
export DISCORD_USER_PASSWORD="$(V discord_user_password)"

ansible-galaxy collection install community.zabbix:==4.2.0
ansible-playbook -i inventory.yml site.yml --tags hosts   # or omit --tags
```

A steady-state run reports `changed=0`. Anything else means the frontend and
git disagree.

## Adding a host

1. Add an entry to the matching block in `config/hosts.yml`.
2. If it needs a template Zabbix does not ship, export that template from the
   frontend (Data collection → Templates → Export, YAML), drop the file in
   `config/templates/`, and list it in `config/templates.yml` **and** in
   `kustomization.yaml`.
3. Any credential goes to `linds-keyvault/zabbix-config` in Vault, gets a key in
   the `zabbix-config-secrets` ExternalSecret
   ([`external-secrets/secrets.yaml`](../external-secrets/secrets.yaml)), an
   `env:` entry in `config-job.yaml`, and is read with `lookup('env', ...)`.
4. Commit. Never `kubectl apply` — Argo CD self-heals from git HEAD.

## Two sites, one proxy

The active server follows Postgres and therefore lives at **jd**, so every check
against a linds-side host used to cross the inter-site link. A Zabbix proxy runs
at linds (`zabbixProxy` in `applications/zabbix.yaml`, pinned to
`datacenter: linds`) and polls those hosts locally.

Measured ICMP averages from each site:

| target | from linds | from jd |
|---|---|---|
| 192.168.6.1 / .205 / .210 | 0.42 / 0.48 / 1.94 ms | 13.10 / 12.79 / 13.99 ms |
| 10.3.1.50 | 0.40 ms | 12.92 ms |
| 10.0.50.246 | 14.71 ms | 0.19 ms |

Everything is routed and reachable from both sites, so this buys latency and
link resilience, not connectivity. The proxy is **active mode** — it dials out
to the server, so nothing is exposed at the linds end, and it buffers locally
while the link is down.

Three things about it are deliberate and easy to undo by accident:

- **It runs `ol-7.4-latest`, not the global alpine tag.** `LINDS-Proxmox-01`
  polls the Proxmox API over TLS, so the proxy is exposed to the same Alpine
  libcurl leak already worked around on the server.
- **SQLite is ephemeral.** The only storage class here is democratic-csi iSCSI
  backed by `10.0.50.246` *at jd*, so a persistent proxy database would write
  every sample back across the link the proxy exists to avoid.
- **`proxies.yml` must be registered before hosts reference it**, and the name
  there must match `ZBX_HOSTNAME` exactly — Zabbix compares case-sensitively and
  rejects an unknown proxy.

Which side each host sits on is the `monitored_by` field in `hosts.yml`. Today:
five hosts on the proxy (`192.168.6.1`, `LINDS-Proxmox-01`, `LINDS-Switch-01`,
`LINDS-ESXi-02-iDrac`, `LINDS-TrueNAS-01`) and three on the server
(`JD-Proxmox-02`, `jd-proxmox-02`, `jd-opnsense-01`).

## Discovery

Three rules, each running next to what it scans: `Local network` (10.0.50.0/24)
on the server, and `linds - 192.168.6.0/24` and `linds - 10.3.1.0/24` on the
proxy. `10.0.80.0/24` (management and UniFi) is deliberately not scanned yet —
adding it is one more entry in the loop in `discovery.yml`.

**The linds rules carry an SNMP check as well as ICMP, and that is load-bearing.**
Zabbix matches a discovered device to an existing host on IP **plus interface
type plus discovery source** — all three. Every host already monitored on those
subnets has an SNMP interface, so an ICMP-only scan would match none of them and
the auto-create action would build duplicate agent-interface copies of hosts that
already exist. There is an open Zabbix bug on this shape
([ZBX-24965](https://support.zabbix.com/browse/ZBX-24965)). Verified in practice:
after the first run, 28 hosts were created and no IP ended up on two hosts.

`host_source` is **IP** on the linds rules, not DNS. The proxy runs inside
Kubernetes, so its reverse lookups are answered by CoreDNS — `10.3.1.100` comes
back as `10-3-1-100.cilium-agent.kube-system.svc.k8s.linds.com.au`, which would
otherwise become the host's technical name.

**Auto-creating hosts is off.** It was enabled briefly and the result was
noise: those subnets carry phones, laptops and other things that come and go, so
each became a host with an ICMP Ping template and then alerted "Unavailable by
ICMP ping" as it left the network — 28 hosts created, four alerting within the
hour. It also reached into managed hosts, linking ICMP Ping to four of them and
adding agent interfaces that `hosts.yml` could not then remove, because Zabbix
refuses to delete an interface an item is bound to.

The rules still scan, so Monitoring → Discovery shows what is on the network;
nothing is created from it. Hosts worth monitoring go into `hosts.yml` by hand,
which is also what keeps this repository authoritative.

The action is kept as an explicit `state: absent` task rather than deleted from
`discovery.yml` — the playbook never prunes, so removing the block would leave
the action running in Zabbix forever.

One caveat that bites when changing any of this: Zabbix fires discovery events
on *status change*, so enabling an action after a rule has already run does
nothing for devices it has already seen. Changing a rule's checks gives every
device a new `dcheckid` and re-triggers discovery, which is the practical way to
make an action apply to the current inventory.

## Templates

Only the four templates Zabbix does not ship are here: VyOS/OPNsense, Dell
iDrac, OfficeConnect, and TrueNAS. The other 310 come from Zabbix's own schema
initialisation on a rebuild.

Committing all of them would add six figures of upstream YAML, regenerate an
unreviewable diff on every minor upgrade, and pin this instance to whatever
template versions were current on the day of the export.

The gap that leaves is `config/template_tweaks.yml`: a dozen items, discovery
rules and triggers that are deliberately disabled on templates this repository
does not own, or on a single host rather than its template. Each entry carries a
comment saying why. Objects are matched by key or description and the playbook
fails loudly if a match is not unique, which is the right outcome — it means
upstream renamed something and the decision needs revisiting.

## Secrets

Nothing sensitive is in git. Values are injected from Vault at apply time, the
same contract as `$(env:...)` in the Keycloak realm file.

| Vault key | Used for |
|---|---|
| `admin_password` | the reconciler's own login |
| `pve_token_secret_jd`, `pve_token_secret_linds` | Proxmox API tokens |
| `ipmi_password`, `snmpv3_auth_passphrase` | jd-proxmox-02's BMC |
| `discord_webhook_url` | Discord media type and Admin's media |
| `zbx_viewer_token` | ZBX Viewer media type and Admin's media |
| `discord_user_password` | creation only; that account cannot log in |

Tasks handling them set `no_log: true`, because Ansible prints module arguments
on failure and Argo CD renders the Job log in its UI.

**The macros are `text`, not `secret`, on purpose.** Zabbix does not return a
secret macro's value over the API, so `zabbix_host` has nothing to compare
against and reports the host changed on *every* run — which would make a real
change indistinguishable from a no-op. The values are no more exposed than they
were before this existed.

The proper fix is a Vault-type macro, where Zabbix stores a path and fetches the
value itself: idempotent *and* the secret never enters the Zabbix database. That
needs `VaultURL`/`VaultToken` on the server plus a Vault token to manage, so it
is deliberately left as a follow-up rather than smuggled into this change.

`refreshPolicy: OnChange` does not notice Vault-side edits. After rotating a
value:

```bash
kubectl annotate externalsecret zabbix-config-secrets -n zabbix \
  force-sync=$(date +%s) --overwrite
```

## SSO

Keycloak fronts Zabbix over **SAML 2.0**, not OIDC. The client is defined in
[`keycloak/realm/linds.yaml`](../keycloak/realm/linds.yaml); the Zabbix half is
`config/access.yml`.

**The IdP certificate is a file, not an API field.** The frontend image's
`zabbix.conf.php` resolves `$SSO['IDP_CERT']` to
`/etc/zabbix/web/certs/idp.crt`, and there is no UI or API setting for it. It is
mounted from the `zabbix-saml-idp` ConfigMap by `zabbixWeb.extraVolumeMounts` in
`applications/zabbix.yaml`. A SAML login that fails with a signature error while
the user directory looks perfectly correct in the frontend is this mount.

No SP keypair is needed: the Keycloak client sets `saml.client.signature`
false, so Zabbix never signs its requests and `sp.key` / `sp.crt` stay absent.

Access is gated on AD group membership, following the convention in the
[Keycloak design](../docs/superpowers/specs/2026-08-15-keycloak-ad-sso-design.md):

| AD group | Zabbix role |
|---|---|
| `k8s-admins` | Super admin |
| `k8s-zabbix-admins` | Super admin |
| `k8s-zabbix-users` | User |

A member of `k8s-users` in none of these matches no mapping and is not
provisioned. Users who lose their groups are moved to the `Disabled` group.

### Refreshing the IdP certificate

Only needed if the realm's signing key is rotated:

```bash
curl -s https://keycloak.linds.com.au/realms/linds/protocol/saml/descriptor \
  | grep -oP '(?<=<ds:X509Certificate>)[^<]+' | tr -d '[:space:]' \
  | fold -w64 \
  | sed '1i -----BEGIN CERTIFICATE-----' | sed '$a -----END CERTIFICATE-----' \
  > zabbix/saml/idp.crt
```

Then commit. The web pods pick it up on the next rollout.

## Break-glass

`Admin` stays a local super admin and internal authentication stays enabled.
Keycloak is a single point of failure for every service it fronts, so this is
deliberate — the same argument the Keycloak README makes for every other app.

```bash
kubectl -n zabbix get secret zabbix-config-secrets \
  -o jsonpath='{.data.admin_password}' | base64 -d; echo
```

The playbook also recovers a freshly initialised database on its own: it tries
the Vault password, falls back to the shipped default, and sets the Vault
password if the fallback worked. A rebuild needs no manual first step.

## Troubleshooting

| Symptom | Cause |
|---|---|
| Job fails with `Missing end of comment tag` | An LLD macro (`{#NAME}`) in a string Ansible templates. Mark the scalar `!unsafe`. |
| Every sync reports the same host changed | A macro was given `type: secret`. See [Secrets](#secrets). |
| `Expected exactly one <object> ... found 0` | Upstream renamed or removed it; revisit the entry in `template_tweaks.yml`. |
| `Expected exactly one <object> ... found 2` | The scope is ambiguous — check `scope_kind`, and remember `VMware` and `VMware FQDN` share item keys. |
| Every API call 404s | `ansible_zabbix_url_path` is not `""`. The plugin defaults to `zabbix`, this frontend serves at `/`. |
| SAML login fails on signature | `saml/idp.crt` is not mounted, or is stale after a realm key rotation. |
| Job fails resolving `galaxy.ansible.com` | The collection is installed at start-up. See the note in `config-job.yaml`. |

## Known gaps

- **`{$SNMP_COMMUNITY}` is `public`.** Every SNMP device answers to the default
  community string. Rotating it means changing Zabbix and five devices in
  lockstep, so it is recorded here rather than done quietly.
- **Dashboards are not covered.** Zabbix cannot export global dashboards through
  any API. All three here are stock, so nothing is lost in a rebuild.
- **Ansible Galaxy is a run-time dependency**, so a rebuild needs working
  internet. The escape hatch is a purpose-built image, the way `claude-code/`
  does it.
