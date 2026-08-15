# Keycloak SSO federated to Active Directory

Date: 2026-08-15
Status: Approved, not yet implemented

## Goal

Run Keycloak in the cluster as the single identity provider for the homelab
services that speak OIDC or SAML natively, with users and groups federated
read-only from the Windows AD domain `linds.com.au`.

A secondary goal is deliberate: this mirrors how Keycloak is deployed and
federated in enterprise environments, so the design favours patterns that
transfer to work over shortcuts that only suit a homelab.

## Scope

In scope: Keycloak runtime, AD federation, realm and client configuration,
and integration with Argo CD, Grafana, Immich, Vault and Zabbix.

Out of scope: services with no native OIDC/SAML support. No `oauth2-proxy`
or forward-auth layer is introduced. Apps that cannot federate keep their
current local authentication.

## Environment facts

Verified on 2026-08-15 rather than assumed:

- Domain controllers, all answering LDAPS on 636:
  `jd-dc-01.linds.com.au` (10.0.50.200), `linds-dc.linds.com.au` (10.3.1.200),
  `linds-dc2.linds.com.au` (10.3.1.201).
- All three LDAPS certificates are issued by `DC=au, DC=com, DC=linds, CN=linds-CA`.
- That CA is the **same** CA as the cluster's `linds-ca` ClusterIssuer — the
  `linds-ca-keypair` secret in `cert-manager` holds a self-signed cert with
  subject `DC=au, DC=com, DC=linds, CN=linds-CA`, valid to 2029-12-01.
- CoreDNS resolves all three DC FQDNs from inside pods, and pods can open TCP
  636 to all three, including across the site link.
- Base DN is `DC=linds,DC=com,DC=au`.

Two consequences follow from the shared CA. Keycloak's LDAPS truststore is
the CA the cluster already syncs from Vault, so no new trust material is
needed. And Keycloak's own ingress certificate, issued by `linds-ca`, is
already trusted by domain-joined Windows clients through the AD-distributed
root store, so the login page presents no warning.

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Deployment | Keycloak Operator + `Keycloak` CR | Declarative; matches enterprise practice |
| Realm config | `keycloak-config-cli` | Reconciles (not just imports) and substitutes secrets from env, so nothing sensitive lands in git |
| AD binding | LDAPS 636, `editMode: READ_ONLY` | Encrypted; Keycloak never writes to the real directory |
| Authorization | Dedicated `k8s-*` AD groups | Separates directory identity from homelab entitlement |
| Exposure | Internal nginx + mTLS mirror | Keeps external Immich OIDC logins working, still client-cert gated |

### Rejected alternatives

- **`KeycloakRealmImport` CR.** Operator-native, but it is a one-shot import
  Job with no drift reconciliation, and it has no secret substitution, so
  client secrets and the AD bind password would sit in git in plaintext.
- **Terraform in LINDS-Terraform.** Good provider coverage, but it splits
  homelab config across two repos and two workflows, removes auth config from
  Argo CD's view, and replaces `selfHeal` with a manual `apply`.
- **Plain LDAP on 389.** Simpler, but sends bind credentials in cleartext and
  teaches the wrong habit.
- **Kerberos/SPNEGO desktop SSO.** Attractive, but adds an SPN, a keytab and
  per-browser configuration. Can be added later on top of this design.

## Versions

- Keycloak server and operator: **26.5.7**
- `keycloak-config-cli`: **6.5.1-26.5.5**

`keycloak-config-cli` lags upstream Keycloak; its newest build targets 26.5.5
while Keycloak upstream is at 26.7.1. **Keycloak's minor line must never move
ahead of config-cli's.** A Renovate rule groups the two so they are bumped in
the same PR instead of drifting apart silently.

The server version is pinned *by the operator*: the operator Deployment sets
`RELATED_IMAGE_KEYCLOAK=quay.io/keycloak/keycloak:26.5.7`, so bumping the
operator bumps the server. **`spec.image` must never be set on the `Keycloak`
CR.** Supplying a custom image makes the operator assume a pre-augmented build
and start the server with `--optimized`, which fails to boot on the stock
image.

Operator manifests come from `keycloak/keycloak-k8s-resources` at the matching
tag:

```
https://raw.githubusercontent.com/keycloak/keycloak-k8s-resources/26.5.7/kubernetes/keycloaks.k8s.keycloak.org-v1.yml
https://raw.githubusercontent.com/keycloak/keycloak-k8s-resources/26.5.7/kubernetes/keycloakrealmimports.k8s.keycloak.org-v1.yml
https://raw.githubusercontent.com/keycloak/keycloak-k8s-resources/26.5.7/kubernetes/kubernetes.yml
```

## Architecture

### Repository layout

```
applications/keycloak.yaml       Argo CD Application, path: keycloak/
keycloak/kustomization.yaml      remote operator manifests + local resources
keycloak/keycloak.yaml           Keycloak CR (incl. operator-managed Ingress)
keycloak/config-cli-job.yaml     PostSync hook Job
keycloak/realm/linds.yaml        declarative realm: LDAP provider, groups, clients
keycloak/README.md               Vault seeding + Vault OIDC runbook
```

Remote release manifests referenced from a local kustomization follows the
existing pattern in `postgresql/kustomization.yaml` and `bootstrap/`.

The CNPG `Database` CR and managed role are added to
`postgresql/postgres-cluster.yaml`, not to `keycloak/`, because the
kustomization sets `namespace: keycloak` globally and the database objects
belong in `postgresql-linds`. This also matches how Immich and catcrawl are
already wired.

### Runtime

`Keycloak` CR in namespace `keycloak`, `instances: 2`, `nodeSelector:
datacenter=jd` to sit alongside Postgres. Notable fields:

- `db`: `postgres`, host `linds-postgres-rw.postgresql-linds.svc.cluster.local`,
  database `keycloak`, credentials from the `keycloak-auth` secret.
- `http.httpEnabled: true` — TLS terminates at nginx, as Argo CD already does.
- `ingress.enabled: true` with `className: nginx`. The CRD exposes
  `ingress.annotations` and `ingress.labels`, so the operator-managed Ingress
  can carry the `cert-manager.io/cluster-issuer: linds-ca` annotation and the
  `linds.com.au/mtls-mirror: "true"` label directly. No hand-written Ingress is
  needed, and external-dns creates the DNS record from it with no further
  configuration. (An earlier draft of this design hand-wrote the Ingress and
  set `ingress.enabled: false`; inspecting the 26.5.7 CRD showed the operator
  supports everything required, so the extra file was dropped.)
- `proxy.headers: xforwarded` — required behind the nginx.org controller.
  Without it Keycloak builds redirect URLs with the wrong scheme and every
  login loops.
- `hostname.hostname: https://keycloak.linds.com.au`
- `truststores.linds-ca.secret.name: linds-ca-cert` — the existing ESO secret
  carrying raw-PEM `ca.crt`. Its `ClusterExternalSecret` `namespaceSelectors`
  is extended to include the `keycloak` namespace.
- `bootstrapAdmin.user.secret: keycloak-bootstrap-admin` — break-glass admin,
  local to the `master` realm, never federated.

### Secrets

All new secrets follow house style: `ClusterExternalSecret` from the
`vault-backend` ClusterSecretStore, `creationPolicy: Orphan`,
`deletionPolicy: Retain`, `refreshPolicy: OnChange`, `refreshTime: 1h`.

| Vault key (`linds-keyvault/…`) | Namespaces | Contents |
|---|---|---|
| `keycloak-auth` | `postgresql-linds`, `keycloak` | `username`, `password` for the CNPG role |
| `keycloak-bootstrap-admin` | `keycloak` | `username`, `password` |
| `keycloak-ldap` | `keycloak` | `bindDn`, `bindCredential` for `svc-keycloak` |
| `keycloak-client-secrets` | `keycloak`, `monitoring`, `immich` | keys `argocd`, `grafana`, `immich`, `vault` |

Only the `keycloak` namespace uses `dataFrom: extract` to pull the whole
entry, because config-cli needs every client secret. `monitoring` and `immich`
use an explicit `data:` list selecting only their own key, so no application
namespace ever holds another application's client secret. `argocd` is absent
deliberately — see below. `vault` is absent because that secret is consumed by
a human following the runbook, not by a pod. Zabbix uses SAML and has no
client secret; it exchanges signing certificates instead.

The `argocd` client secret is added as an extra key on the **existing**
`argocd-admin` ClusterExternalSecret, which already targets `argocd-secret`
with `creationPolicy: Merge`. A separate `Orphan` secret pointed at
`argocd-secret` would prune runtime-generated keys such as `server.secretkey`
and break Argo CD.

`refreshPolicy: OnChange` does not notice Vault-side edits; after seeding or
rotating a value, force a sync with the ESO force-sync annotation rather than
waiting.

### Realm and AD federation

A dedicated `linds` realm holds all federation and clients. The `master` realm
holds only the bootstrap admin and is never federated to AD, so an AD outage,
a site-link failure or a bad mapper edit cannot lock the operator out of the
IdP itself.

LDAP user federation provider, `vendor: ad`:

```
connectionUrl: ldaps://jd-dc-01.linds.com.au:636 ldaps://linds-dc.linds.com.au:636 ldaps://linds-dc2.linds.com.au:636
usersDn:       DC=linds,DC=com,DC=au
bindDn:        $(env:LDAP_BIND_DN)
bindCredential:$(env:LDAP_BIND_CREDENTIAL)
editMode:      READ_ONLY
importEnabled: true
syncRegistrations: false
trustEmail:    true
pagination:    true
connectionPooling: true
usernameLDAPAttribute: sAMAccountName
rdnLDAPAttribute:      cn
uuidLDAPAttribute:     objectGUID
userObjectClasses:     person, organizationalPerson, user
customUserSearchFilter: (memberOf=CN=k8s-users,OU=Kubernetes,OU=Groups,DC=linds,DC=com,DC=au)
fullSyncPeriod:           86400
changedSyncPeriod:        900
```

`jd-dc-01` is listed first because the Keycloak pods are pinned to
`datacenter=jd` and that DC is local to them; the other two are cross-site
failover. FQDNs are used rather than IPs because the LDAPS certificates are
issued to names and truststore validation is name-based.

`trustEmail: true` is set because AD is authoritative for mail and the cluster
has no SMTP configured, so verification email would dead-end.

The `customUserSearchFilter` gates import on membership of `k8s-users` rather
than carving an OU subtree. Service accounts, computer objects and disabled
leavers are therefore never imported, and revoking all homelab access is a
single AD group removal.

Group mapper (`group-ldap-mapper`):

```
groupsDn:                  OU=Kubernetes,OU=Groups,DC=linds,DC=com,DC=au
groupObjectClasses:        group
groupNameLDAPAttribute:    cn
membershipLDAPAttribute:   member
membershipAttributeType:   DN
mode:                      READ_ONLY
userRolesRetrieveStrategy: LOAD_GROUPS_BY_MEMBER_ATTRIBUTE_RECURSIVELY
preserveGroupInheritance:  false
```

The recursive strategy uses AD's `LDAP_MATCHING_RULE_IN_CHAIN`, so nested
groups resolve. `preserveGroupInheritance: false` keeps groups flat inside
Keycloak; nesting still resolves through the recursive lookup, and this avoids
the multi-parent sync errors the inheritance-preserving mode raises on real
directories.

A `groups` client scope with a Group Membership mapper (full path off) is
attached to every client, so every token carries a flat `groups` claim such as
`["k8s-users","k8s-grafana-admins"]`.

### AD groups

Created under `OU=Kubernetes,OU=Groups,DC=linds,DC=com,DC=au`:

| Group | Grants |
|---|---|
| `k8s-users` | the import gate; required to exist in Keycloak at all |
| `k8s-admins` | admin in every integrated app |
| `k8s-argocd-admins` | Argo CD `role:admin` |
| `k8s-grafana-admins` | Grafana `Admin` |
| `k8s-grafana-editors` | Grafana `Editor` |
| `k8s-immich-users` | Immich user |
| `k8s-immich-admins` | Immich admin |
| `k8s-vault-admins` | Vault `admin` policy |
| `k8s-zabbix-admins` | Zabbix Super admin |
| `k8s-zabbix-users` | Zabbix User |

### Clients

All confidential (client authentication enabled), standard authorization code
flow, with secrets injected into config-cli via `$(env:...)`.

| Client | Protocol | Redirect URIs |
|---|---|---|
| `argocd` | OIDC | `https://argocd.linds.com.au/auth/callback`, `http://localhost:8085/auth/callback` |
| `grafana` | OIDC | `https://grafana.linds.com.au/login/generic_oauth` |
| `immich` | OIDC | `https://photos.linds.com.au/auth/login`, `app.immich:///oauth-callback` |
| `vault` | OIDC | `https://vault.linds.com.au/ui/vault/auth/oidc/oidc/callback`, `http://localhost:8250/oidc/callback` |
| `zabbix` | SAML 2.0 | `https://zabbix.linds.com.au/index_sso.php?acs` |

### Config delivery

`keycloak-config-cli` runs as a Job registered as an Argo CD `PostSync` hook
with `hook-delete-policy: BeforeHookCreation`. It reads the realm definition
from a ConfigMap generated by kustomize from `keycloak/realm/linds.yaml`, and
takes the AD bind credential and every client secret from the ESO-synced
secrets as environment variables. Because it reconciles rather than imports,
it is safe to re-run on every sync, and a failed realm apply surfaces as a
failed Argo CD sync rather than silent drift.

## Per-app integration

**Argo CD.** Two more patches in `bootstrap/kustomization.yaml`. `argocd-cm`
gains `url: https://argocd.linds.com.au` (required for the OIDC redirect) and
an `oidc.config` block with issuer
`https://keycloak.linds.com.au/realms/linds`, `clientID: argocd`,
`clientSecret: $oidc.keycloak.clientSecret` and requested scopes
`openid, profile, email, groups`. `argocd-rbac-cm` gains
`policy.default: role:readonly` plus `g, k8s-argocd-admins, role:admin` and
`g, k8s-admins, role:admin`. The local `admin` account stays enabled.

**Grafana.** `grafana.ini` values under `grafana` in
`applications/kube-prometheus.yml`: `auth.generic_oauth` enabled, endpoints
under `https://keycloak.linds.com.au/realms/linds/protocol/openid-connect/`,
scopes `openid email profile groups`, and `server.root_url` set to
`https://grafana.linds.com.au`. The client secret is injected with
`envValueFrom` → `secretKeyRef` rather than `envFromSecret`, so only that key
enters the pod. Role mapping is a JMESPath `role_attribute_path` over the
`groups` claim:

```
contains(groups[*], 'k8s-admins') && 'Admin'
  || contains(groups[*], 'k8s-grafana-admins') && 'Admin'
  || contains(groups[*], 'k8s-grafana-editors') && 'Editor'
  || 'Viewer'
```

The trailing `'Viewer'` is the fallback, so anyone in `k8s-users` without a
Grafana-specific group still gets read access; `role_attribute_strict` stays
`false`. The login form stays enabled so the local admin remains usable.

**Immich.** OAuth settings move into the JSON config file referenced by
`IMMICH_CONFIG_FILE`, which additionally makes them read-only in the UI and so
prevents click-ops drift. Auto-registration is enabled.

**Vault.** The `oidc` auth method, configured against the `linds` realm with
`groups_claim: groups`, and an external group alias mapping
`k8s-vault-admins` to the `admin` policy.

**Zabbix.** SAML 2.0 via the frontend's `ZBX_SSO_*` environment variables,
with the Keycloak IdP signing certificate mounted into the web container, and
JIT provisioning mapping the SAML group attribute to Zabbix user groups.

## Known gaps and risks

**Vault configuration is not declarative.** This repo has no Terraform or
config operator for Vault, so its auth methods are configured imperatively.
Vault's OIDC setup is therefore a documented, repeatable `vault` CLI runbook in
`keycloak/README.md` rather than declarative config. This is a genuine
inconsistency with the rest of the repository and is accepted knowingly rather
than hidden.

**Immich group-to-admin mapping is unverified.** OIDC auto-registration is
well supported, but whether the deployed Immich version can promote an admin
from a token claim varies by release. This is to be verified against the
running version during implementation. If unsupported, Immich admin remains a
local per-user flag, set once.

**Keycloak becomes a new single point of failure** for five services. Mitigated
by two replicas, and by the break-glass paths below.

**Large OIDC cookies and headers** can produce HTTP 400 login loops behind the
nginx.org controller. The remedy is `nginx.org/proxy-buffer-size` on the
affected Ingress.

**Chicken-and-egg on bootstrap.** Keycloak's secrets come from Vault, and
Vault human login will come from Keycloak. This is not circular in practice,
because ESO authenticates to Vault with a token rather than OIDC, and the
Vault root token remains a break-glass path.

## Break-glass

Every integrated service retains a local authentication path, and this is a
requirement rather than a convenience. Each rollout phase is verified by
confirming the local path still works *after* the change.

| Service | Local path |
|---|---|
| Keycloak | `master` realm bootstrap admin (`keycloak-bootstrap-admin`) |
| Argo CD | local `admin`; `admin.enabled: false` is never set |
| Grafana | `grafana-credentials` admin; login form left enabled |
| Vault | root token |
| Zabbix | local `Admin` |

## Rollout

One phase per commit, each independently revertible.

1. **Keycloak + AD federation only.** No application is modified. Success
   criterion: an AD user logs into the Keycloak account console, and the
   issued token carries the expected `groups` claim.
2. **Grafana.** Lowest blast radius.
3. **Argo CD.** Highest stakes, since it is the engine running everything
   else; done third deliberately, once the pattern has been proven twice.
4. **Immich.**
5. **Vault.** Manual runbook.
6. **Zabbix SAML.** Fiddliest, last.

Phases 1 and 2 are the scope of the first implementation plan: they stand up
Keycloak, prove AD federation end to end, and prove the group-to-role pattern
against the lowest-risk consumer. Phases 3 to 6 are each a repeat of the same
shape against a different app and are planned separately once phase 2 has been
verified in the running cluster, so that a wrong assumption about the client
pattern is caught once rather than baked into five integrations.

## Prerequisites (manual, outside this repo)

1. Create AD service account `svc-keycloak@linds.com.au`: password never
   expires, no privileges beyond Domain Users read.
2. Create `OU=Kubernetes,OU=Groups,DC=linds,DC=com,DC=au` and the `k8s-*`
   groups listed above; add intended users to `k8s-users`.
3. Seed the four Vault paths under `linds-keyvault/`, generating a distinct
   random secret per OIDC client.

Everything else is delivered by commit and Argo CD sync. Nothing in this
design is applied with `kubectl`.

## Verification

- Keycloak pods ready, both replicas joined to the Infinispan cluster.
- Keycloak logs show a successful LDAPS sync with a non-zero imported user
  count and no certificate validation errors.
- `https://keycloak.linds.com.au/realms/linds/.well-known/openid-configuration`
  serves valid discovery over a `linds-ca`-issued certificate.
- An AD user in `k8s-users` authenticates; the token contains the expected
  `groups`.
- A user *not* in `k8s-users` cannot authenticate.
- Per phase: the app's SSO login succeeds with correct role mapping, and the
  break-glass local login still succeeds.
