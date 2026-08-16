# Zabbix configuration as code

Zabbix is the last substantial service in this cluster whose *configuration*
lives only in its own database. The Helm release is fully declared in
[`applications/zabbix.yaml`](../../../applications/zabbix.yaml), but every host,
action, media type and discovery rule was created by clicking in the frontend.
This design brings that configuration into the repository and reconciles it on
every Argo CD sync, using the same shape as
[`keycloak/`](../../../keycloak/README.md).

It also disables the Proxmox VM high-memory alerts, which are noise.

## Goals

1. **Rebuild from scratch.** If the Zabbix database is lost, an Argo CD sync
   recreates the monitoring configuration without anyone reading a runbook.
2. **Reviewable change history.** Adding a host or changing an action becomes a
   commit with a diff, not an undated click.

## Non-goals

- **Reverting UI drift.** The reconciler creates what is missing and updates the
  fields the repository declares. Anything changed in the frontend survives
  until someone promotes it to git. Experimenting in the UI stays cheap; that is
  deliberate.

  One exception, and it is inherent rather than chosen: `zabbix_settings`,
  `zabbix_housekeeping` and `zabbix_authentication` write instance-wide
  singletons, so every field they manage is set on every run. A GUI or
  housekeeping setting changed in the frontend *is* reverted within the hour.
  `globals.yml` therefore declares only the fields actually being managed, and
  every field added to it is a field taken away from the UI.
- **Owning upstream templates.** See [Template boundary](#template-boundary).
- **Rotating the SNMP community.** See [Known gaps](#known-gaps).

## What exists today

Read from the `zabbix` database on 2026-08-16, Zabbix 7.4.11.

| Object | Count | Notes |
|---|---|---|
| Hosts | 7 | plus LLD-discovered hosts, which are not configuration |
| Host groups | 7 | 4 of them empty |
| Templates | 314 | **all** stock or community imports; none hand-built |
| Actions | 7 | 2 enabled: `Alert ZBX`, `Discord webhook` |
| Media types | 37 | 2 enabled, both custom webhooks: `Discord`, `ZBX Viewer` |
| Discovery rules | 1 | `Local network`, `10.0.50.0/24` |
| Users | 3 | `Admin`, `Discord` (alert target), `guest` |
| User groups / roles | 5 / 4 | all stock |
| Global macros | 1 | `{$SNMP_COMMUNITY}` = `public` |
| Maintenance, proxies, services | 0 | nothing to codify |

The hosts:

| Host | Interface | Templates |
|---|---|---|
| `JD-Proxmox-02` | 10.0.50.246 SNMPv2 | Proxmox VE by HTTP |
| `LINDS-Proxmox-01` | 192.168.6.205 SNMPv2 | Proxmox VE by HTTP |
| `jd-proxmox-02` | 10.0.50.240 IPMI + SNMPv3 | Chassis by IPMI |
| `LINDS-TrueNAS-01` | 10.3.1.50 SNMPv2 | TrueNAS SNMP |
| `LINDS-Switch-01` | 192.168.6.210 SNMPv2, no GETBULK | Template SNMP OfficeConnect 19XX |
| `LINDS-ESXi-02-iDrac` | 192.168.6.240 SNMPv2 + IPMI | Dell iDrac SNMPV2 |
| `192.168.6.1` (shows as LINDS-OPNSense-01) | 192.168.6.1 SNMPv2 | Template OS VyOS SNMPv2 |
| `jd-opnsense-01.linds.com.au` (JD-OPNSense-01) | 10.0.50.1 SNMPv2 | Template OS VyOS SNMPv2 |

No host runs a Zabbix agent: the agent DaemonSet monitors the Kubernetes nodes
and is unrelated to these. Both routers run OPNsense despite the template's
VyOS name, which is historical.

`JD-Proxmox-02` and `jd-proxmox-02` differ only in case and are different
machines' different faces — the hypervisor's API and the same chassis' BMC. The
repository captures the names as they are; renaming is a separate decision with
history consequences, and is not attempted here.

## Decisions

Recorded with the reasoning, because each of these closes off an alternative
that will look attractive again later.

| Decision | Rationale |
|---|---|
| Ansible `community.zabbix` 4.2.0 as the reconciler | The only off-the-shelf tool covering the whole object surface. Zabbix's own `configuration.export` cannot represent actions, discovery rules, users, user groups, roles or global macros — roughly half of what goal 1 needs — so an export/import job would need a second mechanism bolted alongside it. |
| Reconcile as `state: present`, never prune | Matches the non-goal above. These modules update only declared fields, so UI experiments are not clobbered. |
| Argo CD `PostSync` hook on the existing `zabbix` Application | Guarantees the reconciler runs after the server is up, and surfaces a bad configuration as a failed sync rather than silent drift. Identical reasoning to the comment in `keycloak/config-cli-job.yaml`. |
| Stock Ansible image, collection installed at run time | No GHCR image or CI workflow to maintain. Cost is stated in [Known gaps](#known-gaps). |
| Authenticate as `Admin` with a Vault password, with a default-credential fallback | The instance has no API tokens, and a freshly initialised database has none either. See [Bootstrap](#bootstrap). |
| Only non-stock templates in git | See [Template boundary](#template-boundary). |

## Architecture

### Layout

```
zabbix/
├── kustomization.yaml          # four configMapGenerators over config/
├── config-job.yaml             # PostSync Job
├── saml/idp.crt                # Keycloak realm signing cert (public)
├── config/
│   ├── site.yml                # playbook; imports the rest in order
│   ├── inventory.yml
│   ├── bootstrap.yml
│   ├── hostgroups.yml
│   ├── hosts.yml
│   ├── templates.yml           # imports templates/*.yaml
│   ├── template_tweaks.yml     # local item/trigger status overrides
│   ├── tweak_apply.yml         # applies one tweak; included per entry
│   ├── alerting.yml            # media types, actions, the Discord alert user
│   ├── discovery.yml
│   ├── access.yml              # user groups, roles, SAML user directory, auth
│   ├── globals.yml             # global macros, housekeeping, GUI settings
│   └── media/
│       ├── discord.js
│       └── zbx-viewer.js
├── config/templates/
│   ├── vyos-snmpv2.yaml
│   ├── dell-idrac-snmpv2.yaml
│   ├── officeconnect-19xx.yaml
│   └── truenas-snmp.yaml
└── README.md
```

`applications/zabbix.yaml` already uses the plural `sources:` key, so wiring
this in is one added entry pointing at `path: zabbix` of this repository. The
Helm release and its configuration then sync as a single unit.

### The Job

A `PostSync` hook with `hook-delete-policy: BeforeHookCreation`, mirroring
`keycloak/config-cli-job.yaml`. It runs on `alpine/ansible` (tag pinned; the tag
is the ansible-core version), and its command is:

```sh
ansible-galaxy collection install community.zabbix:==4.2.0 &&
ansible-playbook /config/site.yml
```

`community.zabbix` is not part of ansible-core — it ships in the `ansible`
community package, which this image does not include — so the install step is
required.

Pinned to `datacenter: jd`, as every other job in this repository is: the API
calls are chatty and the frontend the Job talks to lives at `jd`.

`backoffLimit: 3`, `ttlSecondsAfterFinished: 600`.

### Connection

The `community.zabbix.zabbix` httpapi connection plugin, with:

- `ansible_zabbix_url_path: ""` — the frontend is served at `/`, not `/zabbix`.
  The plugin defaults to `zabbix` and every call 404s if this is left alone.
- `ansible_httpapi_use_ssl: false`, targeting
  `zabbix-zabbix-web.zabbix.svc.cluster.local` in cluster. TLS terminates at the
  ingress and this traffic never leaves the cluster network — the same argument
  already made for `KEYCLOAK_URL` in the Keycloak job.

### Bootstrap

`Admin`'s password comes from Vault. On a freshly initialised database it is
still the shipped default, so a plain Vault-password login would fail and the
rebuild would stall at exactly the moment nobody wants to be reading
documentation.

The first play therefore:

1. Attempts `user.login` as `Admin` with the Vault password.
2. On failure, attempts it with the shipped default.
3. If the second succeeds, calls `user.update` to set the Vault password, then
   continues.
4. If both fail, aborts with a clear message — that state means the password was
   changed to something not in Vault, and guessing further is wrong.

Steps 1–3 use `ansible.builtin.uri` against the JSON-RPC endpoint directly, with
`no_log: true`. This is the one place the playbook talks to the API by hand;
everything after it uses the collection's modules.

## Configuration coverage

| File | Modules | Objects |
|---|---|---|
| `hostgroups.yml` | `zabbix_group` | the 7 host groups |
| `templates.yml` | `zabbix_template` | the 4 template imports |
| `template_tweaks.yml` | `uri` | local item and trigger status overrides |
| `hosts.yml` | `zabbix_host` | 7 hosts: interfaces, group membership, template links, macros |
| `alerting.yml` | `zabbix_mediatype`, `zabbix_user`, `zabbix_action` | `Discord` and `ZBX Viewer` media types, the `Discord` user and its media, the `Alert ZBX` and `Discord webhook` actions |
| `discovery.yml` | `zabbix_discovery_rule` | `Local network` |
| `access.yml` | `zabbix_usergroup`, `zabbix_user_role`, `zabbix_user_directory`, `zabbix_authentication` | stock groups and roles as declared state, plus SAML |
| `globals.yml` | `zabbix_globalmacro`, `zabbix_housekeeping`, `zabbix_settings` | `{$SNMP_COMMUNITY}`, 90-day retention, GUI settings |

Ordering matters and is enforced by `site.yml`: groups before templates before
hosts (a host cannot link a template that does not exist), and media types
before users before actions (an action's operation references both).

### Webhook scripts

The `Discord` and `ZBX Viewer` media types are webhooks whose bodies are 6840
and 1559 characters of JavaScript. These live as
`config/media/discord.js` and `config/media/zbx-viewer.js` and are read with
`lookup('file', ...)`, not pasted into YAML. A 200-line script embedded in a
scalar block is unreviewable, and any indentation accident silently changes the
program.

## Secrets

Four values are currently readable in plaintext by anyone with frontend access
or a `psql` prompt:

| Value | Where it is now |
|---|---|
| `{$PVE.TOKEN.SECRET}` on `JD-Proxmox-02` | plaintext host macro |
| `{$PVE.TOKEN.SECRET}` on `LINDS-Proxmox-01` | plaintext host macro |
| `{$IPMI.PASSWORD}` on `jd-proxmox-02` | plaintext host macro |
| Discord webhook URL | media type param, and `Admin`'s user media `sendto` |
| ZBX Viewer push token | media type param, and `Admin`'s user media `sendto` |

All move to Vault under `linds-keyvault/zabbix-config`, reach the Job as
environment variables through an ExternalSecret added to
[`external-secrets/secrets.yaml`](../../../external-secrets/secrets.yaml), and
are referenced in the configuration files as
`{{ lookup('env', 'PVE_TOKEN_SECRET_JD') }}`. This is the `$(env:...)` contract
from the realm file in Ansible's spelling.

Two consequences worth stating:

- Tasks touching them carry `no_log: true`. Ansible prints module arguments on
  failure by default, and a failed `zabbix_hostmacro` would otherwise put a
  Proxmox API token in the Job log, which Argo CD renders in the UI.
- The host macros stay Zabbix's ordinary `text` type. `secret` was the intent
  and was tried; it does not work here. Zabbix never returns a secret macro's
  value over the API, so `zabbix_host` has nothing to compare against and
  reports the host changed on *every* run — verified against 7.4.13 — which
  would make a real change indistinguishable from a no-op in the Job log. The
  values are no more exposed than they were before this existed, and getting
  them out of git was the actual requirement.

  The correct fix is a Vault-type macro: Zabbix stores a path, resolves the
  value itself, and the macro diffs cleanly because the path is not a secret.
  That needs `VaultURL`/`VaultToken` on the server and a Vault token to manage,
  which is its own piece of work rather than a rider on this one.

## Template boundary

All 314 templates are stock or community imports. Git carries the four that
Zabbix does not ship:

- `Template OS VyOS SNMPv2` (used by both routers)
- `Dell iDrac SNMPV2`
- `Template SNMP OfficeConnect 19XX`
- `TrueNAS SNMP`

The remaining 310 are recreated by Zabbix's own schema initialisation on a
rebuild, so they are already reproducible. Committing them would add six figures
of upstream YAML that regenerates a vast unreviewable diff on every Zabbix minor
upgrade, and would pin the instance to whatever template versions happened to be
current on the day of the export.

### Template tweaks

The boundary leaves a gap: four items are disabled on *stock* templates, and two
triggers are disabled at *host* level on stock-template-derived objects. These
are local decisions that would be lost in a rebuild.

| Object | Kind | Where |
|---|---|---|
| `proxmox.qemu.uptime` | item prototype | template `Proxmox VE by HTTP` |
| `proxmox.qemu.vmstatus` | item prototype | template `Proxmox VE by HTTP` |
| `proxmox.lxc.discovery` | discovery rule | template `Proxmox VE by HTTP` |
| `vmware.vm.discovery` | discovery rule | template `VMware` |
| `vmware.datastore.discovery` | discovery rule | template `VMware` |
| `vmware.cluster.discovery` | discovery rule | template `VMware` |
| `vmware.hv.discovery` | discovery rule | template `VMware` |
| `zabbix[host,snmp,available]` | item | template `HP iLO SNMP` |
| `pgsql.custom.query[...]` | item | template `PostgreSQL by Zabbix agent 2` |
| `proxmox.cluster.discovery` | discovery rule | host `JD-Proxmox-02` |
| `Proxmox: VM [...]: has been restarted` | trigger prototype | host `JD-Proxmox-02` |
| `TrueNAS: High memory utilization` | trigger | host `LINDS-TrueNAS-01` |

All four VMware discovery rules are off, which means VMware monitoring is
effectively disabled — worth knowing, and not obvious from anywhere else.

These are expressed as a declarative list in `config/template_tweaks.yml` and
applied with `ansible.builtin.uri` calls to `<object>.update`, resolving objects
by key or description within an explicitly resolved host or template ID. The dedicated `zabbix_item` and `zabbix_trigger`
modules are create/delete oriented and are the wrong instrument for flipping
`status` on an object the module does not own.

Each entry carries a comment explaining why it is off. Most were undocumented,
and reconstructing intent later is much harder than recording it now.

Note `TrueNAS: High memory utilization`, already disabled by hand for the same
reason this design disables the Proxmox VM equivalents.
`JD-Proxmox-02` has the restart trigger disabled while `LINDS-Proxmox-01` does
not — the asymmetry is captured as-is rather than quietly normalised, because
which of the two is correct is not knowable from the database.

## Disabling the VM high-memory alerts

The alerts come from the trigger prototype
`Proxmox: VM [{#NODE.NAME}/{#QEMU.NAME} ({#QEMU.ID})] high memory usage` on the
stock `Proxmox VE by HTTP` template:

```
mem / maxmem * 100 > {$PVE.VM.MEMORY.PUSE.MAX.WARN:"{#QEMU.ID}"}
```

with the macro at `98`. Proxmox reports `mem` for a QEMU guest from the balloon
driver, which by design sits close to the assigned maximum on a healthy VM, so
the ratio is near 100% whenever the guest is doing its job. 126 events across
both nodes, including 44 for `talos-cp-01` alone; none corresponded to a real
problem.

`hosts.yml` sets `{$PVE.VM.MEMORY.PUSE.MAX.WARN}` to `101` on `JD-Proxmox-02`
and `LINDS-Proxmox-01`. The condition becomes unreachable, since the ratio
cannot exceed 100.

Chosen over disabling the trigger prototype because the prototype belongs to an
upstream template. A future template update can silently re-enable it, and the
change would be invisible in the repository. A host macro is owned by us, is one
line, and reads as intent rather than as suppression.

**`Node` and `LXC` variants stay at `98`.** Node-level memory pressure on a
hypervisor is a genuine signal, and the LXC figure is not balloon-derived.

## Finishing SAML

`keycloak/realm/linds.yaml` already contains a complete `zabbix` SAML client —
signing attributes, ACS and SLS URLs, and username / email / groups protocol
mappers, with a comment stating the groups attribute feeds "Zabbix JIT
provisioning". On the Zabbix side, `saml_auth_enabled` is `0` and no user
directory exists. The integration has been half-built and inert.

Three pieces close it.

**1. The IdP certificate is a file, not an API field.** Zabbix reads
`/etc/zabbix/web/certs/idp.crt`; the frontend image's `zabbix.conf.php` resolves
it as `$SSO['IDP_CERT']` with that default, overridable by `ZBX_SSO_IDP_CERT`.
The directory exists in the running pods and is empty. Keycloak's realm signing
certificate goes into a ConfigMap and is mounted there through
`zabbixWeb.extraVolumes` / `extraVolumeMounts` in `applications/zabbix.yaml` —
the same mechanism already used for `zabbix-web-nginx-gzip`.

`sp.key` and `sp.crt` are **not** needed. The Keycloak client sets
`saml.client.signature: "false"`, so Zabbix is not required to sign its
requests, and no SP keypair has to be provisioned. This is what the existing
comment in the realm file is describing.

**2. The user directory**, via `zabbix_user_directory`: `idp_type: saml`,
`sp_entityid: zabbix` (must equal the Keycloak `clientId`), IdP entity ID and
SSO URL from the `linds` realm, `username_attribute: username`, assertion and
message signing expected, request signing off.

**3. JIT provisioning**, following the group convention already established in
the Keycloak design document:

| AD group | Zabbix role |
|---|---|
| `k8s-admins` | Super admin |
| `k8s-zabbix-admins` | Super admin |
| `k8s-zabbix-users` | User |

Members of `k8s-users` without a Zabbix-specific group get no access, matching
how the other integrations gate. `zabbix_authentication` then sets
`saml_auth_enabled: true` while leaving internal authentication on.

**Break-glass is unchanged and deliberate.** `Admin` remains a local super admin
with its password in Vault. Keycloak is a single point of failure for every
integrated service, and the Keycloak README makes the same argument for every
other app.

## Small corrections

Both are one-liners, both are currently wrong, and both are only visible in
alert output:

- The global `url` setting (Administration → General → GUI, "Frontend URL") is
  `https://172.16.10.5` — a stale address that nothing serves. Set to
  `https://zabbix.linds.com.au`.
- The `Discord` media type's `zabbix_url` parameter is
  `http://zabbix.linds.com.au`. Set to `https`.

## Known gaps

**`{$SNMP_COMMUNITY}` is `public`.** Every SNMP device — the switch, the iDrac,
TrueNAS, and both routers — answers to the default community string, on segments
reachable from the LAN. Rotating it requires changing Zabbix and all five
devices in lockstep, with monitoring blind for whatever is missed. Recorded here
as a known risk and a candidate for its own piece of work; this design changes
nothing about it, and the value stays in git because it is not a secret in any
meaningful sense while it is `public`.

**Ansible Galaxy is a run-time dependency.** Installing the collection at Job
start means a sync fails if `galaxy.ansible.com` is unreachable, and a
disaster-recovery rebuild needs working internet. Accepted in exchange for not
maintaining an image and a CI workflow. If it becomes a nuisance, the escape
hatch is a pinned image built the way `claude-code/` already is.

**`community.zabbix` is tested through Zabbix 7.2, not 7.4.** The known gaps are
in the agent-installation roles, which this design does not use; the API modules
speak the version-stable JSON-RPC interface. The first implementation step is
nonetheless to prove one host, one action and one media type apply cleanly
against the live 7.4.11 instance, before anything else is written. If they do
not, the design falls back to `ansible.builtin.uri` against the API for the
affected object types — the playbook structure does not change.

**Dashboards are not covered.** Zabbix cannot export global dashboards through
any API, so the three custom ones (`Global view`, `Zabbix server`,
`Zabbix server health`) stay manual. All three are stock defaults, so nothing is
lost in a rebuild.

## Verification

The Job failing a sync is the primary signal. Beyond that:

- `ansible-playbook --syntax-check` over `zabbix/config/` added to
  `.github/workflows/validate.yaml`. Structure only; nothing in CI can reach the
  cluster.
- **Idempotency is the acceptance test.** The configuration was extracted from
  the live instance, so a correct migration converges to `changed=0`. Anything
  else means git and the frontend disagree about something.

Results of the first real apply against 7.4.13:

| Check | Result |
|---|---|
| Full playbook, steady state | 79 tasks, `changed=0`, `failed=0` |
| Job in-cluster, real image and ConfigMaps | succeeded in 1m46s |
| Hosts, groups, templates, actions, media, discovery | unchanged from pre-migration state |
| `{$PVE.VM.MEMORY.PUSE.MAX.WARN}` | `101` on both Proxmox hosts |
| Secrets in the Job log | none |
| Local `Admin` login | still works with SAML enabled |
| SAML user directory and JIT group mappings | present, `disabled_usrgrpid` set |

Still outstanding, because they need elapsed time or a person:

- No new `high memory usage` events on either Proxmox host after 24 hours.
- A SAML login by a `k8s-zabbix-users` member landing in the User role.

## Rollout order

Each step is independently revertible, and the risky ones come after the
mechanism is known to work.

1. Prove `community.zabbix` against 7.4.11 (one host, one action, one media
   type, applied and rolled back by hand).
2. Vault entries and the ExternalSecret.
3. `zabbix/` skeleton, the Job, and the Application source — with a playbook
   that reconciles only host groups. A trivial first sync proves the wiring.
4. Templates, then hosts, then template tweaks.
5. Alerting, discovery, globals, and the two URL corrections.
6. The VM memory macro.
7. Access and SAML, last, because it is the only step that can lock someone out
   and the only one needing a Helm values change.
