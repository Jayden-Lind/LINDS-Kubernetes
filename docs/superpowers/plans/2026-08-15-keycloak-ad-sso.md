# Keycloak AD SSO Implementation Plan (Phases 1–2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up Keycloak in the cluster, federate users and groups read-only from the `linds.com.au` Active Directory over LDAPS, and prove the group-to-role pattern end to end by putting Grafana behind it.

**Architecture:** The official Keycloak Operator runs the server from a `Keycloak` CR; realm, LDAP federation and clients are reconciled by a `keycloak-config-cli` Job registered as an Argo CD `PostSync` hook. Postgres comes from the existing CNPG cluster, every secret from Vault via External Secrets, and TLS from the `linds-ca` ClusterIssuer — which is the same CA that issued the domain controllers' LDAPS certificates.

**Tech Stack:** Keycloak Operator 26.5.7, keycloak-config-cli 6.5.1-26.5.5, CloudNativePG, External Secrets Operator, Argo CD, kustomize, nginx.org ingress controller, cert-manager.

**Spec:** `docs/superpowers/specs/2026-08-15-keycloak-ad-sso-design.md`

## Global Constraints

- Keycloak server and operator version: **26.5.7**. Sourced from `https://raw.githubusercontent.com/keycloak/keycloak-k8s-resources/26.5.7/kubernetes/`.
- keycloak-config-cli image: **`quay.io/adorsys/keycloak-config-cli:6.5.1-26.5.5`**. Keycloak's minor line must never move ahead of config-cli's.
- **Never set `spec.image` on the `Keycloak` CR.** The operator supplies `quay.io/keycloak/keycloak:26.5.7` via its own `RELATED_IMAGE_KEYCLOAK` env var. Setting `spec.image` makes the operator assume a pre-augmented image and start with `--optimized`, which fails to boot on the stock image.
- Realm name: `linds`. The `master` realm is never federated to AD.
- AD base DN: `DC=linds,DC=com,DC=au`. Groups OU: `OU=Kubernetes,DC=linds,DC=com,DC=au`.
- LDAP `editMode` is `READ_ONLY` in every component. Keycloak must never write to AD.
- Every ESO secret uses `creationPolicy: Orphan`, `deletionPolicy: Retain`, `refreshPolicy: OnChange`, `refreshTime: 1h`, store `vault-backend` / `ClusterSecretStore` — except `argocd-secret`, which stays `Merge`.
- Nothing is applied with `kubectl apply`. Argo CD syncs `targetRevision: master` from GitHub, so a change is only live once merged to `master` and synced.
- Every phase must leave the app's local break-glass login working. `admin.enabled: false` is never set on Argo CD; Grafana's login form stays enabled.

---

## Working method

All work happens on branch `keycloak-ad-sso`. Argo CD tracks `master`, so each task is: write manifests, validate locally, commit; then at the phase gate, merge to `master` and verify against the live cluster.

Local validation available: `kustomize` v5.8.1, `kubectl` (cluster access), `helm`, `yq`, `jq`, `vault`. There is no `kubeconform`; use `kubectl apply --dry-run=server` instead, which is stronger since it validates against the cluster's real schemas.

---

## Task 0: Active Directory prerequisites — COMPLETE (2026-08-15)

Done directly over LDAPS with `ldap3`, binding as `LINDS\Administrator` from
`~/.adcred`. Recorded here rather than as instructions, because the directory
turned out not to match what the spec assumed and the differences matter.

**What changed from the original plan**

- **Groups OU.** The spec assumed `OU=Kubernetes,OU=Groups,DC=linds,DC=com,DC=au`.
  There is no top-level `OU=Groups` in this domain — the existing one is
  `OU=Groups,OU=Linds - Users`. Creating the specified DN would have added a
  second, competing top-level `OU=Groups`. Now a new top-level
  **`OU=Kubernetes,DC=linds,DC=com,DC=au`**.
- **Email attribute.** **Not a single account in this domain has `mail`
  populated** — there is no Exchange here. Every real user does have a UPN
  (`jayden@linds.com.au`). The email LDAP mapper therefore reads
  `userPrincipalName`, not `mail`; see Task 4. Mapping `email <- mail` would
  have imported every user with an empty email, which Grafana and Immich both
  key on.

**What exists now**

| Object | DN |
|---|---|
| OU | `OU=Kubernetes,DC=linds,DC=com,DC=au` |
| Groups (10) | `CN=k8s-{users,admins,argocd-admins,grafana-admins,grafana-editors,immich-users,immich-admins,vault-admins,zabbix-admins,zabbix-users},OU=Kubernetes,DC=linds,DC=com,DC=au` |
| Bind account | `CN=svc-keycloak,CN=Users,DC=linds,DC=com,DC=au` |
| Members | `jayden` in `k8s-users` and `k8s-admins` |

`svc-keycloak` is enabled, `PASSWD_NOTREQD` clear, `DONT_EXPIRE_PASSWORD` set
(`userAccountControl: 66048`), and holds no group membership beyond
`Domain Users` — READ_ONLY federation needs nothing more.

**Vault paths seeded** (`linds-keyvault/`), each generated fresh and never
printed. The seeding refused to run if any path already existed, so a re-run
cannot silently rotate a live credential:

| Path | Keys |
|---|---|
| `keycloak-auth` | `username`, `password` |
| `keycloak-bootstrap-admin` | `username`, `password` |
| `keycloak-ldap` | `bindDn`, `bindCredential` |
| `keycloak-client-secrets` | `argocd`, `grafana`, `immich`, `vault` |

**Verification performed** — all passed:

- Bound as `svc-keycloak` over LDAPS with **full certificate validation against
  `linds-CA`**, connecting by FQDN. This is the same trust path Keycloak's
  truststore will use, so it is direct evidence that Task 3's LDAPS config will
  work. (Binding by the IP in `~/.adcred` cannot validate — the DC cert is
  issued to `JD-DC-01.linds.com.au`.)
- Ran Keycloak's exact `customUserSearchFilter` as `svc-keycloak`: returns
  exactly one user, `jayden`, with `givenName` and `sn` present.
- Ran Keycloak's exact group query: all ten `k8s-*` groups visible,
  `k8s-users` and `k8s-admins` with one member each.
- **Gate exclusion proven:** user `bl` exists in AD but does not match the gate
  filter. The filter genuinely excludes, rather than merely including.
- Re-read `bindDn`/`bindCredential` **back out of Vault** and bound to AD with
  those values — so what Keycloak will read is confirmed working, not just what
  was generated.

**Re-running:** `scratchpad/ad_provision.py` is idempotent — it checks for each
object before creating it and leaves an existing `svc-keycloak` password
untouched.

**Two observations, not blockers.** `~/.adcred` holds Domain Administrator
credentials at mode `0644`; `chmod 600` is worth doing, and a delegated account
scoped to `OU=Kubernetes` would suit a tool-read credential better. Separately,
adding a user to `k8s-users` is now the single action that grants homelab
access — worth remembering when onboarding anyone else in the family.

---

## Task 1: External Secrets for Keycloak

**Files:**
- Modify: `external-secrets/secrets.yaml` (append four `ClusterExternalSecret`s; extend one existing)

**Interfaces:**
- Consumes: the four Vault paths from Task 0.
- Produces: secrets `keycloak-auth` (ns `postgresql-linds`, `keycloak`), `keycloak-bootstrap-admin` (ns `keycloak`), `keycloak-ldap` (ns `keycloak`), `keycloak-client-secrets` (ns `keycloak`), `grafana-oidc` (ns `monitoring`), and `linds-ca-cert` additionally in ns `keycloak`. Task 2 consumes `keycloak-auth`; Task 3 consumes `keycloak-auth`, `keycloak-bootstrap-admin`, `linds-ca-cert`; Task 4 consumes `keycloak-bootstrap-admin`, `keycloak-ldap`, `keycloak-client-secrets`; Task 6 consumes `grafana-oidc`.

- [ ] **Step 1: Extend the existing `linds-ca-cert` secret to the keycloak namespace**

In `external-secrets/secrets.yaml`, find the `linds-ca-cert` `ClusterExternalSecret` and add one selector. Change:

```yaml
  namespaceSelectors:
    - matchLabels:
        kubernetes.io/metadata.name: nginx-ingress-mtls
```

to:

```yaml
  namespaceSelectors:
    - matchLabels:
        kubernetes.io/metadata.name: nginx-ingress-mtls
    # Keycloak trusts this same CA when validating the domain controllers'
    # LDAPS certificates - linds-CA issued both the cluster certs and the
    # DC certs, so no separate trust material is needed.
    - matchLabels:
        kubernetes.io/metadata.name: keycloak
```

Leave everything else in that block, including `decodingStrategy: Base64`, untouched — Vault stores this PEM base64-encoded and the operator needs raw PEM.

- [ ] **Step 2: Append the four new ClusterExternalSecrets**

Append to the end of `external-secrets/secrets.yaml`:

```yaml
---
# CNPG role password for the keycloak database. Needed in postgresql-linds so
# the Cluster's managed role can consume it, and in keycloak so the server can
# authenticate with it.
apiVersion: external-secrets.io/v1
kind: ClusterExternalSecret
metadata:
  name: keycloak-auth
spec:
  externalSecretName: keycloak-auth
  namespaceSelectors:
    - matchLabels:
        kubernetes.io/metadata.name: postgresql-linds
    - matchLabels:
        kubernetes.io/metadata.name: keycloak
  refreshTime: 1h
  externalSecretSpec:
    secretStoreRef:
      name: vault-backend
      kind: ClusterSecretStore
    refreshPolicy: OnChange
    target:
      name: keycloak-auth
      creationPolicy: Orphan
      deletionPolicy: Retain
    dataFrom:
      - extract:
          key: linds-keyvault/keycloak-auth
---
# Break-glass admin for the master realm. Also the account keycloak-config-cli
# authenticates as, so the realm can be reconciled without a second identity.
apiVersion: external-secrets.io/v1
kind: ClusterExternalSecret
metadata:
  name: keycloak-bootstrap-admin
spec:
  externalSecretName: keycloak-bootstrap-admin
  namespaceSelectors:
    - matchLabels:
        kubernetes.io/metadata.name: keycloak
  refreshTime: 1h
  externalSecretSpec:
    secretStoreRef:
      name: vault-backend
      kind: ClusterSecretStore
    refreshPolicy: OnChange
    target:
      name: keycloak-bootstrap-admin
      creationPolicy: Orphan
      deletionPolicy: Retain
    dataFrom:
      - extract:
          key: linds-keyvault/keycloak-bootstrap-admin
---
# AD bind account for the LDAP user federation provider. Read-only rights.
apiVersion: external-secrets.io/v1
kind: ClusterExternalSecret
metadata:
  name: keycloak-ldap
spec:
  externalSecretName: keycloak-ldap
  namespaceSelectors:
    - matchLabels:
        kubernetes.io/metadata.name: keycloak
  refreshTime: 1h
  externalSecretSpec:
    secretStoreRef:
      name: vault-backend
      kind: ClusterSecretStore
    refreshPolicy: OnChange
    target:
      name: keycloak-ldap
      creationPolicy: Orphan
      deletionPolicy: Retain
    dataFrom:
      - extract:
          key: linds-keyvault/keycloak-ldap
---
# Every OIDC client secret, extracted whole because keycloak-config-cli needs
# all of them to reconcile the realm. Application namespaces get only their own
# key (see grafana-oidc below) so no app can read another app's secret.
apiVersion: external-secrets.io/v1
kind: ClusterExternalSecret
metadata:
  name: keycloak-client-secrets
spec:
  externalSecretName: keycloak-client-secrets
  namespaceSelectors:
    - matchLabels:
        kubernetes.io/metadata.name: keycloak
  refreshTime: 1h
  externalSecretSpec:
    secretStoreRef:
      name: vault-backend
      kind: ClusterSecretStore
    refreshPolicy: OnChange
    target:
      name: keycloak-client-secrets
      creationPolicy: Orphan
      deletionPolicy: Retain
    dataFrom:
      - extract:
          key: linds-keyvault/keycloak-client-secrets
---
# Grafana gets only its own client secret, not the whole set.
apiVersion: external-secrets.io/v1
kind: ClusterExternalSecret
metadata:
  name: grafana-oidc
spec:
  externalSecretName: grafana-oidc
  namespaceSelectors:
    - matchLabels:
        kubernetes.io/metadata.name: monitoring
  refreshTime: 1h
  externalSecretSpec:
    secretStoreRef:
      name: vault-backend
      kind: ClusterSecretStore
    refreshPolicy: OnChange
    target:
      name: grafana-oidc
      creationPolicy: Orphan
      deletionPolicy: Retain
    data:
      - secretKey: client-secret
        remoteRef:
          key: linds-keyvault/keycloak-client-secrets
          property: grafana
```

- [ ] **Step 3: Validate the YAML parses and every document is well formed**

```bash
yq -e 'true' external-secrets/secrets.yaml > /dev/null && echo "YAML OK"
yq -N 'select(.kind == "ClusterExternalSecret") | .metadata.name' external-secrets/secrets.yaml | sort | uniq -d
```

Expected: `YAML OK`, and the second command prints **nothing** — duplicate `ClusterExternalSecret` names would silently overwrite each other.

- [ ] **Step 4: Server-side dry-run against the live cluster**

```bash
kubectl apply --dry-run=server -f external-secrets/secrets.yaml
```

Expected: every resource reports `configured` or `created (server dry run)`, with no schema errors. This validates against the real ESO CRDs.

- [ ] **Step 5: Commit**

```bash
git add external-secrets/secrets.yaml
git commit -m "feat(keycloak): external secrets for Keycloak, LDAP bind and OIDC clients"
```

---

## Task 2: Keycloak database in the CNPG cluster

**Files:**
- Modify: `postgresql/postgres-cluster.yaml` (add a managed role and a `Database` CR)

**Interfaces:**
- Consumes: secret `keycloak-auth` in `postgresql-linds` from Task 1.
- Produces: database `keycloak` owned by role `keycloak`, reachable at `linds-postgres-rw.postgresql-linds.svc.cluster.local:5432`. Task 3 consumes this.

- [ ] **Step 1: Add the managed role**

In `postgresql/postgres-cluster.yaml`, in the `Cluster` resource under `spec.managed.roles`, append after the existing `immich` entry:

```yaml
      - name: keycloak
        ensure: present
        login: true
        passwordSecret:
          name: keycloak-auth
```

Do not add `superuser: true`. Keycloak only needs ownership of its own database.

- [ ] **Step 2: Add the Database CR**

Append a new document to `postgresql/postgres-cluster.yaml`, after the `linds-postgres-immich` Database and before the `ScheduledBackup`:

```yaml
---
apiVersion: postgresql.cnpg.io/v1
kind: Database
metadata:
  name: linds-postgres-keycloak
  namespace: postgresql-linds
spec:
  cluster:
    name: linds-postgres
  name: keycloak
  owner: keycloak
```

- [ ] **Step 3: Validate**

```bash
kustomize build postgresql/ > /dev/null && echo "kustomize OK"
yq -N 'select(.kind == "Database") | .spec.name' postgresql/postgres-cluster.yaml
yq -N 'select(.kind == "Cluster") | .spec.managed.roles[].name' postgresql/postgres-cluster.yaml
```

Expected: `kustomize OK`; the Database list includes `keycloak`; the roles list is `catcrawl`, `immich`, `keycloak`.

- [ ] **Step 4: Commit**

```bash
git add postgresql/postgres-cluster.yaml
git commit -m "feat(keycloak): add keycloak database and role to the CNPG cluster"
```

---

## Task 3: Keycloak operator and server

**Files:**
- Create: `keycloak/kustomization.yaml`
- Create: `keycloak/keycloak.yaml`
- Create: `applications/keycloak.yaml`

**Interfaces:**
- Consumes: database from Task 2; secrets `keycloak-auth`, `keycloak-bootstrap-admin`, `linds-ca-cert` from Task 1.
- Produces: a running Keycloak at `https://keycloak.linds.com.au`, service `keycloak-service.keycloak.svc.cluster.local:8080`. Task 4 posts to that service.

- [ ] **Step 1: Create `keycloak/kustomization.yaml`**

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

namespace: keycloak

resources:
  # Pinned operator release. The operator also pins the SERVER version through
  # its RELATED_IMAGE_KEYCLOAK env var (quay.io/keycloak/keycloak:26.5.7), so
  # bumping these three URLs upgrades both. The upstream manifest already
  # targets the "keycloak" namespace in its ClusterRoleBinding subject.
  - https://raw.githubusercontent.com/keycloak/keycloak-k8s-resources/26.5.7/kubernetes/keycloaks.k8s.keycloak.org-v1.yml
  - https://raw.githubusercontent.com/keycloak/keycloak-k8s-resources/26.5.7/kubernetes/keycloakrealmimports.k8s.keycloak.org-v1.yml
  - https://raw.githubusercontent.com/keycloak/keycloak-k8s-resources/26.5.7/kubernetes/kubernetes.yml
  - keycloak.yaml
```

- [ ] **Step 2: Create `keycloak/keycloak.yaml`**

```yaml
apiVersion: k8s.keycloak.org/v2alpha1
kind: Keycloak
metadata:
  name: keycloak
  namespace: keycloak
  annotations:
    # The CRDs land in the same sync; wave 1 keeps the CR from being applied
    # before the CustomResourceDefinition that validates it exists.
    argocd.argoproj.io/sync-wave: "1"
spec:
  instances: 2

  # NOTE: spec.image is deliberately NOT set. The operator supplies
  # quay.io/keycloak/keycloak:26.5.7 itself. Setting spec.image makes the
  # operator assume a pre-augmented image and start it with --optimized,
  # which fails to boot on the stock image.

  db:
    vendor: postgres
    host: linds-postgres-rw.postgresql-linds.svc.cluster.local
    port: 5432
    database: keycloak
    usernameSecret:
      name: keycloak-auth
      key: username
    passwordSecret:
      name: keycloak-auth
      key: password

  hostname:
    hostname: https://keycloak.linds.com.au

  # TLS terminates at nginx, exactly as Argo CD does. Without proxy.headers
  # Keycloak builds redirect URLs with the wrong scheme and every login loops.
  http:
    httpEnabled: true
  proxy:
    headers: xforwarded

  ingress:
    enabled: true
    className: nginx
    tlsSecret: keycloak-linds-tls
    annotations:
      cert-manager.io/cluster-issuer: linds-ca
    labels:
      # Kyverno mirrors this onto the nginx-mtls class so external Immich
      # OIDC redirects can reach Keycloak behind a client certificate.
      linds.com.au/mtls-mirror: "true"

  # linds-CA issued both the cluster certificates and the domain controllers'
  # LDAPS certificates, so this one CA is all Keycloak needs to validate LDAPS.
  truststores:
    linds-ca:
      secret:
        name: linds-ca-cert

  # Break-glass admin in the master realm. Never federated to AD.
  bootstrapAdmin:
    user:
      secret: keycloak-bootstrap-admin

  # Sit next to Postgres, matching Prometheus and Loki.
  unsupported:
    podTemplate:
      spec:
        nodeSelector:
          datacenter: jd
```

- [ ] **Step 3: Create `applications/keycloak.yaml`**

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: keycloak
  namespace: argocd
spec:
  project: default
  sources:
    - repoURL: https://github.com/Jayden-Lind/LINDS-Kubernetes
      targetRevision: master
      path: keycloak
  destination:
    server: https://kubernetes.default.svc
    namespace: keycloak
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
      - ServerSideApply=true
      # The operator CRDs and the Keycloak CR arrive in the same sync; without
      # this the CR fails validation because its CRD is not yet established.
      - SkipDryRunOnMissingResource=true
```

- [ ] **Step 4: Validate the kustomization builds and pins the right version**

```bash
kustomize build keycloak/ > /tmp/kc-build.yaml && echo "kustomize OK"
grep -c "keycloak-operator:26.5.7" /tmp/kc-build.yaml
yq -N 'select(.kind == "Keycloak") | .spec.image // "unset"' /tmp/kc-build.yaml
kubectl apply --dry-run=server -f applications/keycloak.yaml
```

Expected: `kustomize OK`; the operator image grep returns `1`; `spec.image` prints `unset` — if it prints an image, remove it, the pod will not boot; the Application dry-run succeeds.

- [ ] **Step 5: Confirm the CRDs and the CR agree**

The `Keycloak` CRD is in the build output, so validate the CR against it rather than against the cluster, which does not have the CRD yet:

```bash
yq -N 'select(.kind == "CustomResourceDefinition") | .metadata.name' /tmp/kc-build.yaml
yq -N 'select(.kind == "Keycloak") | .spec | keys' /tmp/kc-build.yaml
```

Expected: both `keycloaks.k8s.keycloak.org` and `keycloakrealmimports.k8s.keycloak.org` present; the CR's keys are exactly `instances, db, hostname, http, proxy, ingress, truststores, bootstrapAdmin, unsupported`.

- [ ] **Step 6: Commit**

```bash
git add keycloak/kustomization.yaml keycloak/keycloak.yaml applications/keycloak.yaml
git commit -m "feat(keycloak): deploy Keycloak 26.5.7 via the official operator"
```

---

## Task 4: Realm, AD federation and clients via keycloak-config-cli

**Files:**
- Create: `keycloak/realm/linds.yaml`
- Create: `keycloak/config-cli-job.yaml`
- Modify: `keycloak/kustomization.yaml` (add the ConfigMap generator and the Job)
- Create: `keycloak/README.md`

**Interfaces:**
- Consumes: the running Keycloak from Task 3; secrets `keycloak-bootstrap-admin`, `keycloak-ldap`, `keycloak-client-secrets` from Task 1.
- Produces: realm `linds` with the AD federation provider, a `groups` client scope emitting a flat `groups` claim, and the `grafana` client. Task 6 consumes the `grafana` client.

- [ ] **Step 1: Create `keycloak/realm/linds.yaml`**

Note the format: this is Keycloak's realm export shape, so every value inside a component `config` block is a **list of strings**, not a scalar. `$(env:NAME)` placeholders are substituted by config-cli at run time from the Job's environment.

```yaml
realm: linds
displayName: LINDS
enabled: true
sslRequired: external
loginTheme: keycloak
registrationAllowed: false
resetPasswordAllowed: false
editUsernameAllowed: false
bruteForceProtected: true
permanentLockout: false
maxFailureWaitSeconds: 900
failureFactor: 10

# Tokens: short access token, 10h session. Grafana and Argo CD both refresh.
accessTokenLifespan: 300
ssoSessionIdleTimeout: 3600
ssoSessionMaxLifespan: 36000

clientScopes:
  - name: groups
    description: AD group membership
    protocol: openid-connect
    attributes:
      include.in.token.scope: "true"
      display.on.consent.screen: "false"
    protocolMappers:
      - name: groups
        protocol: openid-connect
        protocolMapper: oidc-group-membership-mapper
        consentRequired: false
        config:
          # full.path false emits "k8s-admins", not "/k8s-admins" - every
          # consumer in this cluster matches on the bare name.
          full.path: "false"
          claim.name: groups
          id.token.claim: "true"
          access.token.claim: "true"
          userinfo.token.claim: "true"

clients:
  - clientId: grafana
    name: Grafana
    enabled: true
    protocol: openid-connect
    publicClient: false
    bearerOnly: false
    standardFlowEnabled: true
    implicitFlowEnabled: false
    directAccessGrantsEnabled: false
    serviceAccountsEnabled: false
    secret: $(env:CLIENT_SECRET_GRAFANA)
    rootUrl: https://grafana.linds.com.au
    baseUrl: https://grafana.linds.com.au
    redirectUris:
      - https://grafana.linds.com.au/login/generic_oauth
    webOrigins:
      - https://grafana.linds.com.au
    defaultClientScopes:
      - basic
      - acr
      - profile
      - email
      - roles
      - web-origins
      - groups
    optionalClientScopes:
      - offline_access

components:
  org.keycloak.storage.UserStorageProvider:
    - name: linds-ad
      providerId: ldap
      config:
        enabled: ["true"]
        priority: ["0"]
        vendor: ["ad"]
        # jd-dc-01 first: the Keycloak pods are pinned to datacenter=jd and
        # that DC is local to them. The other two are cross-site failover.
        # FQDNs, not IPs - the LDAPS certs are issued to names.
        connectionUrl: ["ldaps://jd-dc-01.linds.com.au:636 ldaps://linds-dc.linds.com.au:636 ldaps://linds-dc2.linds.com.au:636"]
        usersDn: ["DC=linds,DC=com,DC=au"]
        authType: ["simple"]
        bindDn: ["$(env:LDAP_BIND_DN)"]
        bindCredential: ["$(env:LDAP_BIND_CREDENTIAL)"]
        useTruststoreSpi: ["always"]
        connectionPooling: ["true"]
        pagination: ["true"]
        batchSizeForSync: ["1000"]
        # READ_ONLY: Keycloak never writes to the real directory.
        editMode: ["READ_ONLY"]
        importEnabled: ["true"]
        syncRegistrations: ["false"]
        # AD is authoritative for mail, and there is no SMTP in this cluster,
        # so verification email would dead-end.
        trustEmail: ["true"]
        usernameLDAPAttribute: ["sAMAccountName"]
        rdnLDAPAttribute: ["cn"]
        uuidLDAPAttribute: ["objectGUID"]
        userObjectClasses: ["person, organizationalPerson, user"]
        searchScope: ["2"]
        # The import gate. Only members of k8s-users ever become Keycloak
        # users, so service accounts, computer objects and disabled leavers
        # are never imported, and revoking all access is one group removal.
        customUserSearchFilter: ["(memberOf=CN=k8s-users,OU=Kubernetes,DC=linds,DC=com,DC=au)"]
        fullSyncPeriod: ["86400"]
        changedSyncPeriod: ["900"]
        cachePolicy: ["DEFAULT"]
      subComponents:
        org.keycloak.storage.ldap.mappers.LDAPStorageMapper:
          - name: username
            providerId: user-attribute-ldap-mapper
            config:
              user.model.attribute: ["username"]
              ldap.attribute: ["sAMAccountName"]
              read.only: ["true"]
              always.read.value.from.ldap: ["false"]
              is.mandatory.in.ldap: ["true"]
          - name: first name
            providerId: user-attribute-ldap-mapper
            config:
              user.model.attribute: ["firstName"]
              ldap.attribute: ["givenName"]
              read.only: ["true"]
              always.read.value.from.ldap: ["true"]
              is.mandatory.in.ldap: ["false"]
          - name: last name
            providerId: user-attribute-ldap-mapper
            config:
              user.model.attribute: ["lastName"]
              ldap.attribute: ["sn"]
              read.only: ["true"]
              always.read.value.from.ldap: ["true"]
              is.mandatory.in.ldap: ["true"]
          # userPrincipalName, NOT mail. Verified 2026-08-15: not a single
          # account in this domain has `mail` populated - there is no Exchange
          # here - while every real user has a UPN of the form
          # jayden@linds.com.au. Mapping email<-mail would import every user
          # with an empty email, and both Grafana and Immich key on it.
          - name: email
            providerId: user-attribute-ldap-mapper
            config:
              user.model.attribute: ["email"]
              ldap.attribute: ["userPrincipalName"]
              read.only: ["true"]
              always.read.value.from.ldap: ["true"]
              is.mandatory.in.ldap: ["false"]
          - name: groups
            providerId: group-ldap-mapper
            config:
              groups.dn: ["OU=Kubernetes,DC=linds,DC=com,DC=au"]
              group.name.ldap.attribute: ["cn"]
              group.object.classes: ["group"]
              membership.ldap.attribute: ["member"]
              membership.attribute.type: ["DN"]
              membership.user.ldap.attribute: ["sAMAccountName"]
              memberof.ldap.attribute: ["memberOf"]
              mode: ["READ_ONLY"]
              # Uses AD's LDAP_MATCHING_RULE_IN_CHAIN so nested groups resolve.
              user.roles.retrieve.strategy: ["LOAD_GROUPS_BY_MEMBER_ATTRIBUTE_RECURSIVELY"]
              # Keep groups flat in Keycloak. Nesting still resolves via the
              # recursive strategy above, and this avoids the multi-parent
              # sync errors the inheritance-preserving mode raises.
              preserve.group.inheritance: ["false"]
              ignore.missing.groups: ["false"]
              drop.non.existing.groups.during.sync: ["false"]
```

- [ ] **Step 2: Create `keycloak/config-cli-job.yaml`**

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: keycloak-config-cli
  namespace: keycloak
  annotations:
    # Runs after Keycloak itself is healthy. Because config-cli reconciles
    # rather than imports, re-running on every sync is safe and a failed
    # realm apply surfaces as a failed Argo CD sync instead of silent drift.
    argocd.argoproj.io/hook: PostSync
    argocd.argoproj.io/hook-delete-policy: BeforeHookCreation
spec:
  backoffLimit: 3
  ttlSecondsAfterFinished: 600
  template:
    metadata:
      name: keycloak-config-cli
    spec:
      restartPolicy: Never
      nodeSelector:
        datacenter: jd
      containers:
        - name: config-cli
          image: quay.io/adorsys/keycloak-config-cli:6.5.1-26.5.5
          imagePullPolicy: IfNotPresent
          env:
            # In-cluster plaintext: TLS terminates at the ingress, and this
            # never leaves the cluster network.
            - name: KEYCLOAK_URL
              value: http://keycloak-service.keycloak.svc.cluster.local:8080
            - name: KEYCLOAK_LOGINREALM
              value: master
            - name: KEYCLOAK_CLIENTID
              value: admin-cli
            - name: KEYCLOAK_USER
              valueFrom:
                secretKeyRef:
                  name: keycloak-bootstrap-admin
                  key: username
            - name: KEYCLOAK_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: keycloak-bootstrap-admin
                  key: password
            # The operator may still be rolling pods when the hook fires.
            - name: KEYCLOAK_AVAILABILITYCHECK_ENABLED
              value: "true"
            - name: KEYCLOAK_AVAILABILITYCHECK_TIMEOUT
              value: 300s
            - name: IMPORT_FILES_LOCATIONS
              value: /config/*.yaml
            # Enables $(env:NAME) placeholders. Off by default.
            - name: IMPORT_VARSUBSTITUTION_ENABLED
              value: "true"
            # Fail loudly if a placeholder has no matching env var, rather
            # than writing the literal string into the realm.
            - name: IMPORT_VARSUBSTITUTION_UNDEFINEDISERROR
              value: "true"
            - name: LDAP_BIND_DN
              valueFrom:
                secretKeyRef:
                  name: keycloak-ldap
                  key: bindDn
            - name: LDAP_BIND_CREDENTIAL
              valueFrom:
                secretKeyRef:
                  name: keycloak-ldap
                  key: bindCredential
            - name: CLIENT_SECRET_GRAFANA
              valueFrom:
                secretKeyRef:
                  name: keycloak-client-secrets
                  key: grafana
          volumeMounts:
            - name: realm
              mountPath: /config
              readOnly: true
      volumes:
        - name: realm
          configMap:
            name: keycloak-realm
```

- [ ] **Step 3: Wire the ConfigMap generator and the Job into the kustomization**

Replace `keycloak/kustomization.yaml` with:

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

namespace: keycloak

resources:
  # Pinned operator release. The operator also pins the SERVER version through
  # its RELATED_IMAGE_KEYCLOAK env var (quay.io/keycloak/keycloak:26.5.7), so
  # bumping these three URLs upgrades both. The upstream manifest already
  # targets the "keycloak" namespace in its ClusterRoleBinding subject.
  - https://raw.githubusercontent.com/keycloak/keycloak-k8s-resources/26.5.7/kubernetes/keycloaks.k8s.keycloak.org-v1.yml
  - https://raw.githubusercontent.com/keycloak/keycloak-k8s-resources/26.5.7/kubernetes/keycloakrealmimports.k8s.keycloak.org-v1.yml
  - https://raw.githubusercontent.com/keycloak/keycloak-k8s-resources/26.5.7/kubernetes/kubernetes.yml
  - keycloak.yaml
  - config-cli-job.yaml

configMapGenerator:
  - name: keycloak-realm
    files:
      - realm/linds.yaml

# A hashed ConfigMap name would leave the Job referencing a name that the
# generator changes on every realm edit; the Job is recreated per sync anyway,
# and a stable name keeps the volume reference valid.
generatorOptions:
  disableNameSuffixHash: true
```

- [ ] **Step 4: Validate the build, the substitution placeholders and the Job wiring**

```bash
kustomize build keycloak/ > /tmp/kc-build.yaml && echo "kustomize OK"

# Every $(env:X) in the realm must have a matching env var in the Job.
#
# Do NOT strip comments before this check. config-cli substitutes variables
# over the RAW FILE TEXT before any YAML parsing, so a placeholder inside a
# `#` comment is still resolved - and with
# IMPORT_VARSUBSTITUTION_UNDEFINEDISERROR=true an undefined one aborts the
# entire import. A hit inside a comment is a real failure, not a false
# positive. (This was learned the hard way: an explanatory comment containing
# the literal placeholder syntax failed the first live run with
# "Cannot resolve variable 'env:NAME'".)
grep -o '\$(env:[A-Z_]*)' keycloak/realm/linds.yaml | sed 's/\$(env:\(.*\))/\1/' | sort -u > /tmp/kc-placeholders
yq -N 'select(.kind == "Job") | .spec.template.spec.containers[0].env[].name' /tmp/kc-build.yaml | sort -u > /tmp/kc-envs
comm -23 /tmp/kc-placeholders /tmp/kc-envs
```

Expected: `kustomize OK`, and the `comm` prints **nothing**. Anything listed is a placeholder with no environment variable behind it, which fails the Job at run time because `IMPORT_VARSUBSTITUTION_UNDEFINEDISERROR` is `true`.

- [ ] **Step 5: Verify the realm file is valid YAML and the component config values are lists**

The single most common mistake in this file format is writing a scalar where Keycloak expects a one-element list.

```bash
yq -e 'true' keycloak/realm/linds.yaml > /dev/null && echo "YAML OK"
yq '.components["org.keycloak.storage.UserStorageProvider"][0].config
     | to_entries | map(select(.value | tag != "!!seq")) | .[].key' keycloak/realm/linds.yaml
yq '.components["org.keycloak.storage.UserStorageProvider"][0].subComponents["org.keycloak.storage.ldap.mappers.LDAPStorageMapper"][]
     | .config | to_entries | map(select(.value | tag != "!!seq")) | .[].key' keycloak/realm/linds.yaml
```

Expected: `YAML OK`, and both `yq` commands print **nothing**. Any key listed is a scalar that must be wrapped in `[ ]`.

- [ ] **Step 6: Confirm the ConfigMap actually carries the realm**

```bash
yq -N 'select(.kind == "ConfigMap" and .metadata.name == "keycloak-realm") | .data | keys' /tmp/kc-build.yaml
```

Expected: `- linds.yaml`. The Job mounts `/config/*.yaml`, so the key must end in `.yaml`.

- [ ] **Step 7: Write `keycloak/README.md`**

```markdown
# Keycloak

Keycloak 26.5.7, deployed by the official operator, federated read-only to the
`linds.com.au` Active Directory over LDAPS.

Design: `docs/superpowers/specs/2026-08-15-keycloak-ad-sso-design.md`

## How the pieces fit

- `kustomization.yaml` pulls the pinned operator release straight from
  `keycloak-k8s-resources`. The operator pins the *server* version through its
  own `RELATED_IMAGE_KEYCLOAK` env var, so bumping the three URLs upgrades both.
- `keycloak.yaml` is the `Keycloak` CR. **Do not set `spec.image`** — supplying
  a custom image makes the operator start the server with `--optimized`, which
  fails to boot on the stock image.
- `realm/linds.yaml` is the whole realm: LDAP federation, group mapper, the
  `groups` client scope, and every OIDC client.
- `config-cli-job.yaml` reconciles that file into Keycloak on every Argo CD
  sync, as a `PostSync` hook. It reconciles rather than imports, so re-running
  is safe and a bad realm surfaces as a failed sync.

## Secrets

All from Vault via External Secrets (`external-secrets/secrets.yaml`):

| Secret | Contents |
|---|---|
| `keycloak-auth` | CNPG role username/password |
| `keycloak-bootstrap-admin` | master-realm admin; also config-cli's login |
| `keycloak-ldap` | `bindDn`, `bindCredential` for `svc-keycloak` |
| `keycloak-client-secrets` | one key per OIDC client |

`refreshPolicy: OnChange` does not notice Vault-side edits. After rotating a
value, force a sync rather than waiting:

```bash
kubectl annotate externalsecret keycloak-ldap -n keycloak \
  force-sync=$(date +%s) --overwrite
```

## Break-glass

The `master` realm is never federated to AD. If AD, the site link, or a realm
edit breaks login, sign in at `https://keycloak.linds.com.au/admin` with the
`keycloak-bootstrap-admin` credentials from Vault.

## Adding a service

1. Add a `clients:` entry to `realm/linds.yaml`, with
   `secret: $(env:CLIENT_SECRET_<APP>)`.
2. Add that key to `linds-keyvault/keycloak-client-secrets` in Vault.
3. Add the matching `env:` entry to `config-cli-job.yaml`.
4. Give the app its own key with an explicit `data:` ExternalSecret — never
   `dataFrom: extract`, which would hand it every other client's secret.

## Vault OIDC (manual)

Vault has no Terraform or config operator in this repo, so its auth method is
configured imperatively. This is a known, accepted gap. Runbook to follow when
phase 5 is implemented.
```

- [ ] **Step 8: Commit**

```bash
git add keycloak/realm/linds.yaml keycloak/config-cli-job.yaml keycloak/kustomization.yaml keycloak/README.md
git commit -m "feat(keycloak): AD LDAPS federation and realm config via keycloak-config-cli"
```

---

## Task 5: Phase 1 gate — merge and verify against the live cluster

Nothing so far has touched the cluster. This task merges phases 1's manifests to `master`, lets Argo CD sync, and proves federation works before any application is modified.

**Files:** none — this is verification.

**Interfaces:**
- Consumes: Tasks 1–4.
- Produces: a verified-working Keycloak. Task 6 depends on this having passed.

- [ ] **Step 1: Merge to master and push**

```bash
git checkout master && git merge --no-ff keycloak-ad-sso -m "feat: Keycloak SSO federated to Active Directory (phase 1)"
git push origin master
git checkout keycloak-ad-sso
```

- [ ] **Step 2: Watch Argo CD pick it up**

Argo CD's reconciliation is relaxed to one hour in this cluster, so trigger it rather than waiting:

Reconciliation is relaxed to one hour here (`timeout.reconciliation: 3600s` in
`bootstrap/kustomization.yaml`), so refresh the root app, wait for the new
child Application to be created, then refresh that one too — refreshing `root`
only makes Argo notice the new `Application` object, not sync its contents.

```bash
kubectl -n argocd annotate app root argocd.argoproj.io/refresh=hard --overwrite

# Wait for the root sync to create the child Application.
until kubectl -n argocd get app keycloak >/dev/null 2>&1; do sleep 5; done
kubectl -n argocd annotate app keycloak argocd.argoproj.io/refresh=hard --overwrite

kubectl -n argocd get app keycloak \
  -o custom-columns=SYNC:.status.sync.status,HEALTH:.status.health.status -w
```

Expected: the `keycloak` Application appears and reaches `Synced` / `Healthy`.
Ctrl-C once it does.

First sync commonly shows `Progressing` for a minute or two while the operator
starts and the CRDs establish. If it settles on `Degraded`, go straight to
Step 4 and read the pod logs — do not re-sync repeatedly, since `selfHeal` is
already retrying.

- [ ] **Step 3: Verify the database was created**

```bash
kubectl -n postgresql-linds get database linds-postgres-keycloak \
  -o jsonpath='{.status.applied}{"\n"}'
```

Expected: `true`. If it is `false`, read `.status.message` — the usual cause is the `keycloak-auth` secret not yet present in `postgresql-linds`.

- [ ] **Step 4: Verify both Keycloak pods are running and clustered**

```bash
kubectl -n keycloak get pods
kubectl -n keycloak logs statefulset/keycloak -c keycloak | grep -i "ISPN000094\|Received new cluster view"
```

Expected: two `keycloak-N` pods `Running` and `1/1` ready, and a cluster-view log line listing both members. If pods are `CrashLoopBackOff`, check `spec.image` is unset and read the logs for `--optimized`.

- [ ] **Step 5: Verify TLS and discovery**

```bash
curl -s https://keycloak.linds.com.au/realms/linds/.well-known/openid-configuration | jq -r '.issuer, .token_endpoint'
curl -sI https://keycloak.linds.com.au/ | head -1
openssl s_client -connect keycloak.linds.com.au:443 -servername keycloak.linds.com.au </dev/null 2>/dev/null | openssl x509 -noout -issuer
```

Expected: issuer `https://keycloak.linds.com.au/realms/linds`, HTTP `200`, and the certificate issuer is `DC=au, DC=com, DC=linds, CN=linds-CA`.

If discovery 404s, the config-cli hook has not run or failed — see Step 6.

- [ ] **Step 6: Verify the config-cli hook succeeded**

```bash
kubectl -n keycloak get jobs
kubectl -n keycloak logs job/keycloak-config-cli | tail -30
```

Expected: the Job is `Complete`, and the log ends with an import-success line for realm `linds`. A failure here is deliberately loud: read the last error, fix the realm file, re-commit, re-merge.

- [ ] **Step 7: Verify the AD sync imported users**

```bash
kubectl -n keycloak logs statefulset/keycloak -c keycloak | grep -i "sync\|ldap" | tail -20
```

Expected: a successful full sync line naming `linds-ad`, with a non-zero added/updated count and **no** certificate validation errors. `PKIX path building failed` means the truststore is wrong — confirm `linds-ca-cert` exists in the `keycloak` namespace and holds raw PEM, not base64.

- [ ] **Step 8: Verify the gate filter works — the most important check**

This proves both that AD users import *and* that non-members are excluded.

```bash
KCADMIN=$(kubectl -n keycloak get secret keycloak-bootstrap-admin -o jsonpath='{.data.username}' | base64 -d)
KCPASS=$(kubectl -n keycloak get secret keycloak-bootstrap-admin -o jsonpath='{.data.password}' | base64 -d)

TOKEN=$(curl -s -d "client_id=admin-cli" -d "username=$KCADMIN" -d "password=$KCPASS" \
  -d "grant_type=password" \
  https://keycloak.linds.com.au/realms/master/protocol/openid-connect/token | jq -r .access_token)

# Imported users
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://keycloak.linds.com.au/admin/realms/linds/users?max=200" | jq -r '.[].username'

# Synced groups
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://keycloak.linds.com.au/admin/realms/linds/groups" | jq -r '.[].name'
```

Expected: the user list contains only members of `k8s-users` — your own account should be there, and accounts like `svc-keycloak` and computer objects must **not** be. The group list contains the ten `k8s-*` groups.

- [ ] **Step 9: Verify an AD user can authenticate and the token carries groups**

The obvious probe — a password grant against the `grafana` client — does not
work here, and should not: that client has `directAccessGrantsEnabled: false`
by design. Rather than weakening the client to test it, use Keycloak's
scope-evaluation endpoint, which renders exactly the token a real login would
issue, using only the admin token from Step 8:

```bash
# Reuse $TOKEN from Step 8.
CID=$(curl -s -H "Authorization: Bearer $TOKEN" \
  "https://keycloak.linds.com.au/admin/realms/linds/clients?clientId=grafana" | jq -r '.[0].id')
UID=$(curl -s -H "Authorization: Bearer $TOKEN" \
  "https://keycloak.linds.com.au/admin/realms/linds/users?username=jayden&exact=true" | jq -r '.[0].id')

curl -s -H "Authorization: Bearer $TOKEN" \
  "https://keycloak.linds.com.au/admin/realms/linds/clients/$CID/evaluate-scopes/generate-example-access-token?scope=groups&userId=$UID" \
  | jq '{user: .preferred_username, email, groups}'
```

Replace `jayden` with your own `sAMAccountName` if it differs.

Expected: your username and email, and a `groups` array containing `k8s-users`
and `k8s-admins` as **bare names** with no leading slash. A leading `/` means
`full.path` is not `false` on the group mapper, and every downstream role match
in Grafana and Argo CD will silently fail to match.

If `groups` is absent entirely, the `groups` client scope is not attached to
the client — check `defaultClientScopes` on the `grafana` client in
`realm/linds.yaml` against the scopes the realm actually has:

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://keycloak.linds.com.au/admin/realms/linds/client-scopes" | jq -r '.[].name' | sort
```

- [ ] **Step 10: Verify break-glass still works**

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://keycloak.linds.com.au/admin/master/console/
```

Expected: `200`, and signing in at that URL with the `keycloak-bootstrap-admin` credentials succeeds. Do this by hand in a browser — it is the path you will need when something is broken, so confirm it now.

---

## Task 6: Grafana OIDC (phase 2)

**Files:**
- Modify: `applications/kube-prometheus.yml` (Grafana values, around lines 95–131)
- Modify: `keycloak/realm/linds.yaml` — no change needed; the `grafana` client already exists from Task 4

**Interfaces:**
- Consumes: the `grafana` client and `groups` claim from Task 4; secret `grafana-oidc` in `monitoring` from Task 1.
- Produces: Grafana login via Keycloak with AD-group-driven roles.

- [ ] **Step 1: Add the OIDC configuration to the Grafana values**

In `applications/kube-prometheus.yml`, inside the `grafana:` block, after the existing `admin:` key and before `nodeSelector:`, insert:

```yaml
          # Break-glass: the local admin from grafana-credentials stays usable.
          # Do not set disable_login_form - Keycloak is a new single point of
          # failure for this cluster and Grafana must keep a local path.
          envValueFrom:
            GF_AUTH_GENERIC_OAUTH_CLIENT_SECRET:
              secretKeyRef:
                name: grafana-oidc
                key: client-secret
          grafana.ini:
            server:
              # Required, or OAuth redirects are built against the pod address.
              root_url: https://grafana.linds.com.au
            auth:
              # Signing out of Grafana returns to Grafana's own login page,
              # leaving the break-glass form one click away.
              oauth_auto_login: false
              signout_redirect_url: https://grafana.linds.com.au/login
            auth.generic_oauth:
              enabled: true
              name: Keycloak
              icon: signin
              allow_sign_up: true
              client_id: grafana
              scopes: openid email profile groups
              email_attribute_path: email
              login_attribute_path: preferred_username
              name_attribute_path: name
              auth_url: https://keycloak.linds.com.au/realms/linds/protocol/openid-connect/auth
              token_url: https://keycloak.linds.com.au/realms/linds/protocol/openid-connect/token
              api_url: https://keycloak.linds.com.au/realms/linds/protocol/openid-connect/userinfo
              # Roles come from the flat `groups` claim the client scope emits.
              # The trailing 'Viewer' is the fallback, so anyone in k8s-users
              # without a Grafana group still gets read access.
              role_attribute_path: "contains(groups[*], 'k8s-admins') && 'Admin' || contains(groups[*], 'k8s-grafana-admins') && 'Admin' || contains(groups[*], 'k8s-grafana-editors') && 'Editor' || 'Viewer'"
              role_attribute_strict: false
              use_refresh_token: true
```

- [ ] **Step 2: Validate the values block parses and the secret is not inlined**

This Application holds its Helm values as a **block-scalar string** under
`.spec.sources[0].helm.values`, not as a `valuesObject` map. So validating it
means parsing that string as YAML in a second pass:

```bash
yq -e 'true' applications/kube-prometheus.yml > /dev/null && echo "outer YAML OK"

# Parse the values string as YAML in its own right - this is what catches a
# broken indent inside the block scalar, which the outer parse cannot see.
yq '.spec.sources[0].helm.values' applications/kube-prometheus.yml \
  | yq -e '.grafana["grafana.ini"]["auth.generic_oauth"].client_id' -

yq '.spec.sources[0].helm.values' applications/kube-prometheus.yml \
  | yq '.grafana["grafana.ini"].server.root_url' -

grep -c "GF_AUTH_GENERIC_OAUTH_CLIENT_SECRET" applications/kube-prometheus.yml
grep -iE "client_secret: *[^$]" applications/kube-prometheus.yml || echo "no inline client_secret - correct"
```

Expected: `outer YAML OK`; `client_id` prints `grafana`; `root_url` prints
`https://grafana.linds.com.au`; the env-var grep returns `1`; the last command
prints `no inline client_secret - correct`. A literal secret in this file would
be committed to a public repository.

The indentation matters and is easy to get wrong: inside the `values: |` block
the top-level keys sit at 8 spaces (`        grafana:`) and the keys under
`grafana:` sit at 10 (`          admin:`). The insert in Step 1 uses 10, matching
`admin:`. If the second `yq` errors with a null, the indent is wrong — not the
path.

- [ ] **Step 3: Dry-run the Application**

```bash
kubectl apply --dry-run=server -f applications/kube-prometheus.yml
```

Expected: `application.argoproj.io/monitoring configured (server dry run)`.

- [ ] **Step 4: Commit**

```bash
git add applications/kube-prometheus.yml
git commit -m "feat(grafana): sign in with Keycloak, roles from AD groups"
```

- [ ] **Step 5: Merge and sync**

```bash
git checkout master && git merge --no-ff keycloak-ad-sso -m "feat: Grafana OIDC via Keycloak (phase 2)"
git push origin master
git checkout keycloak-ad-sso
kubectl -n argocd patch app root --type merge \
  -p '{"metadata":{"annotations":{"argocd.argoproj.io/refresh":"hard"}}}'
kubectl -n argocd get app monitoring -w
```

Expected: `monitoring` returns to `Synced` / `Healthy` and the Grafana pod restarts.

- [ ] **Step 6: Verify Grafana picked up the config**

```bash
kubectl -n monitoring get secret grafana-oidc -o jsonpath='{.data.client-secret}' | base64 -d | wc -c
kubectl -n monitoring logs deploy/monitoring-kube-prometheus-stack-grafana -c grafana | grep -i "generic_oauth\|oauth" | tail -10
```

Expected: the secret is 32 bytes, and the logs show the generic OAuth provider registered with no configuration errors.

- [ ] **Step 7: Verify SSO login end to end, in a browser**

Go to `https://grafana.linds.com.au`. Expected:

1. A **"Sign in with Keycloak"** button appears *alongside* the username/password form.
2. Clicking it redirects to `keycloak.linds.com.au` with no certificate warning.
3. Signing in as your AD account returns you to Grafana, signed in.
4. Your role is **Admin** (you are in `k8s-admins`). Check under your profile.

- [ ] **Step 8: Verify role mapping actually discriminates**

The fallback is the easiest thing to get wrong — a `role_attribute_path` that always returns `Admin` looks identical to a correct one when tested with one admin account.

In AD, temporarily remove yourself from `k8s-admins` (keeping `k8s-users`), then in Grafana sign out, and sign in again:

```powershell
Remove-ADGroupMember -Identity "k8s-admins" -Members "jayden" -Confirm:$false
```

Expected: you are signed in as **Viewer**, not Admin. Then restore:

```powershell
Add-ADGroupMember -Identity "k8s-admins" -Members "jayden"
```

Sign out and in again; expected: **Admin** returns. Group changes propagate on the next login because Keycloak re-reads membership at authentication time, so no sync wait is needed.

- [ ] **Step 9: Verify break-glass still works**

Sign out of Grafana. On the login page, sign in with the local `admin` account from the `grafana-credentials` secret:

```bash
kubectl -n monitoring get secret grafana-credentials -o jsonpath='{.data.admin-password}' | base64 -d; echo
```

Expected: the local login succeeds. **This is a required gate** — if the login form is gone or the local account is rejected, revert the Grafana commit before going further, because the same pattern is about to be applied to Argo CD.

---

## Task 7: Renovate grouping for the paired versions

**Files:**
- Modify: `renovate.json5`

**Interfaces:**
- Consumes: the pinned versions from Tasks 3 and 4.
- Produces: coupled upgrade PRs.

**Important context, established by reading the existing config:** this repo
enables **only** the `argocd` manager, scoped to `/^applications/[^/]+\.ya?ml$/`,
and the file's own comment states that container image tags are
argocd-image-updater's job. Nothing currently scans `keycloak/`. A plain
`packageRules` entry naming the Keycloak images would therefore match nothing
and produce a false sense of coverage. Two `customManagers` entries are needed
to bring these versions into scope at all.

- [ ] **Step 1: Read the existing config to match its style**

```bash
cat renovate.json5
```

Note the style: unquoted keys, double-quoted values, `//` comments explaining
*why*. Match it.

- [ ] **Step 2: Add customManagers so the two versions are seen at all**

Add a top-level `customManagers` array to `renovate.json5`, after the `argocd`
block and before `packageRules`:

```json5
  // The argocd manager only reads applications/*.yaml targetRevision, so
  // neither of the Keycloak versions below is visible to Renovate by default:
  // one lives in a remote kustomize URL, the other in a Job's image tag.
  // These two regex managers bring them into scope.
  customManagers: [
    {
      customType: "regex",
      managerFilePatterns: ["/^keycloak/kustomization\\.yaml$/"],
      // Matches the tag in the three raw.githubusercontent.com URLs. All
      // three carry the same version, so currentValue is captured once per
      // line and Renovate bumps them together.
      matchStrings: [
        "keycloak/keycloak-k8s-resources/(?<currentValue>[0-9.]+)/kubernetes/",
      ],
      depNameTemplate: "keycloak/keycloak-k8s-resources",
      datasourceTemplate: "github-releases",
    },
    {
      customType: "regex",
      managerFilePatterns: ["/^keycloak/config-cli-job\\.yaml$/"],
      matchStrings: [
        "image: (?<depName>quay\\.io/adorsys/keycloak-config-cli):(?<currentValue>\\S+)",
      ],
      datasourceTemplate: "docker",
    },
  ],
```

- [ ] **Step 3: Group the two into a single PR**

Add to the `packageRules` array:

```json5
    {
      // keycloak-config-cli lags upstream Keycloak: its newest build targets
      // 26.5.x while Keycloak itself is already at 26.7.x. Keycloak's minor
      // line must never move ahead of config-cli's.
      //
      // Renovate CANNOT enforce that ordering - the two use different
      // versioning schemes (26.5.7 vs 6.5.1-26.5.5) and there is no
      // constraint expressing "wait for a matching build". Grouping only
      // puts them in one PR so the pair is reviewed together. Before merging
      // a Keycloak MINOR bump, check by hand that a config-cli tag exists for
      // that line:
      //   curl -s "https://quay.io/api/v1/repository/adorsys/keycloak-config-cli/tag/?limit=100&onlyActiveTags=true" | jq -r '.tags[].name' | sort -u
      groupName: "keycloak",
      matchPackageNames: [
        "keycloak/keycloak-k8s-resources",
        "quay.io/adorsys/keycloak-config-cli",
      ],
    },
```

- [ ] **Step 4: Validate the file**

There is **no** JSON5 validator available on this machine — `node`, `npm` and
`npx` are all absent, and `yq` cannot parse JSON5's unquoted keys and comments.
So validate structurally instead, then let Renovate confirm:

```bash
# Bracket and brace balance - catches the realistic failure, a missing comma
# or an unclosed array after a hand edit.
python3 - <<'EOF'
import re
src = open('renovate.json5').read()
# Blank STRINGS FIRST, then comments. Order matters: existing rules contain
# regexes like "/(^|/)nginx-ingress$/" whose // would otherwise be stripped
# as a comment, taking the rest of the line - and its closing brace - with it,
# reporting a phantom imbalance.
src = re.sub(r'"(?:[^"\\]|\\.)*"', '""', src)
src = re.sub(r'//[^\n]*', '', src)
for open_c, close_c in (('{','}'), ('[',']')):
    if src.count(open_c) != src.count(close_c):
        raise SystemExit(f"UNBALANCED {open_c}{close_c}: {src.count(open_c)} vs {src.count(close_c)}")
print("balanced OK")
EOF

# Confirm the new keys are present exactly once each.
grep -c "customManagers:" renovate.json5
grep -c 'groupName: "keycloak"' renovate.json5
```

Expected: `balanced OK`, and both greps return `1`.

A malformed `renovate.json5` does not fail silently — Renovate raises a config
error on its next run and posts it to the Dependency Dashboard issue. Check
there after the next Renovate run to confirm the managers are live, and confirm
positively by looking for a `keycloak` entry in the dashboard's detected
dependencies.

- [ ] **Step 4: Commit and merge**

```bash
git add renovate.json5
git commit -m "chore(renovate): group Keycloak with keycloak-config-cli"
git checkout master && git merge --no-ff keycloak-ad-sso -m "chore: renovate grouping for Keycloak"
git push origin master
git checkout keycloak-ad-sso
```

---

## Task 8: Update the repository README

**Files:**
- Modify: `README.MD`

- [ ] **Step 1: Add Keycloak to the Key Features list**

In `README.MD`, in the `## Key Features` bullet list, after the mTLS-only ingress bullet, add:

```markdown
* **AD-backed SSO:** Keycloak federates users and groups read-only from the `linds.com.au` Active Directory over LDAPS, and fronts the services that speak OIDC/SAML natively — see [keycloak/](keycloak/README.md).
```

- [ ] **Step 2: Verify the link target exists**

```bash
test -f keycloak/README.md && echo "link OK"
```

Expected: `link OK`.

- [ ] **Step 3: Commit and merge**

```bash
git add README.MD
git commit -m "docs: mention Keycloak SSO in the README"
git checkout master && git merge --no-ff keycloak-ad-sso -m "docs: Keycloak in README"
git push origin master
git checkout keycloak-ad-sso
```

---

## Done criteria for phases 1–2

- Keycloak runs two clustered replicas at `https://keycloak.linds.com.au`, on a `linds-ca`-issued certificate.
- Only AD accounts in `k8s-users` exist in the `linds` realm; `svc-keycloak` and computer objects do not.
- Tokens carry a flat `groups` claim of bare `k8s-*` names.
- Grafana signs in via Keycloak, and role assignment demonstrably differs between an account in `k8s-admins` and one that is not.
- Grafana's local admin and Keycloak's `master`-realm bootstrap admin both still work.
- The realm — federation, mappers, client scope and client — is entirely in git, with no secret in it.

Phases 3–6 (Argo CD, Immich, Vault, Zabbix) are planned separately once these criteria are met, per the spec's rollout section.
