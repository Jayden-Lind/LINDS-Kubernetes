# Keycloak

Keycloak 26.5.7, deployed by the official operator, federated **read-only** to
the `linds.com.au` Active Directory over LDAPS. Fronts the cluster services
that speak OIDC or SAML natively.

Design: [`docs/superpowers/specs/2026-08-15-keycloak-ad-sso-design.md`](../docs/superpowers/specs/2026-08-15-keycloak-ad-sso-design.md)

## How the pieces fit

- **`kustomization.yaml`** pulls the pinned operator release straight from
  `keycloak-k8s-resources`. The operator pins the *server* version through its
  own `RELATED_IMAGE_KEYCLOAK` env var, so bumping the three URLs upgrades both.
- **`keycloak.yaml`** is the `Keycloak` CR. **Do not set `spec.image`** —
  supplying a custom image makes the operator start the server with
  `--optimized`, which fails to boot on the stock image.
- **`realm/linds.yaml`** is the whole realm: LDAP federation, attribute and
  group mappers, the `groups` client scope, and every OIDC client.
- **`config-cli-job.yaml`** reconciles that file into Keycloak on every Argo CD
  sync, as a `PostSync` hook. It reconciles rather than imports, so re-running
  is safe and a bad realm surfaces as a failed sync rather than silent drift.

The database is a `Database` CR plus a managed role in
[`postgresql/postgres-cluster.yaml`](../postgresql/postgres-cluster.yaml), not
here — this kustomization sets `namespace: keycloak` globally, and those
objects belong in `postgresql-linds`.

## Realm file format

`realm/linds.yaml` uses Keycloak's realm-export shape. The trap: **every value
inside a component `config` block is a list of strings, never a scalar.**

```yaml
editMode: ["READ_ONLY"]     # correct
editMode: READ_ONLY         # silently wrong
```

`$(env:NAME)` placeholders are substituted at run time from the Job's
environment, so no secret is committed. `IMPORT_VARSUBSTITUTION_UNDEFINEDISERROR`
is `true`, so a placeholder with no matching env var fails the Job loudly
instead of writing the literal string into the realm.

## AD specifics

- **Email comes from `userPrincipalName`, not `mail`.** No account in this
  domain populates `mail` — there is no Exchange. Mapping from `mail` imports
  every user with an empty email, which Grafana and Immich both key on.
- **`k8s-users` membership is the access gate.** The provider's
  `customUserSearchFilter` requires it, so adding or removing someone from that
  one AD group grants or revokes all homelab access.
- **Trust:** `linds-CA` is simultaneously the AD Certificate Services CA and
  the cluster's `linds-ca` ClusterIssuer, so the ESO-synced `linds-ca-cert`
  secret doubles as the LDAPS truststore. Connect to DCs **by FQDN** — the
  certs are issued to names, so an IP can never validate.
- DCs, in the order the provider tries them: `jd-dc-01` (local to the `jd`
  workers where these pods run), then `linds-dc` and `linds-dc2` across the
  site link.

## Secrets

All from Vault via External Secrets
([`external-secrets/secrets.yaml`](../external-secrets/secrets.yaml)):

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
`keycloak-bootstrap-admin` credentials from Vault:

```bash
kubectl -n keycloak get secret keycloak-bootstrap-admin \
  -o jsonpath='{.data.username}' | base64 -d; echo
kubectl -n keycloak get secret keycloak-bootstrap-admin \
  -o jsonpath='{.data.password}' | base64 -d; echo
```

Every integrated service also keeps its own local login. That is deliberate:
Keycloak is a single point of failure for all of them.

## Adding a service

1. Add a `clients:` entry to `realm/linds.yaml` with
   `secret: $(env:CLIENT_SECRET_<APP>)`.
2. Add that key to `linds-keyvault/keycloak-client-secrets` in Vault.
3. Add the matching `env:` entry to `config-cli-job.yaml`.
4. Give the app its own key with an explicit `data:` ExternalSecret — never
   `dataFrom: extract`, which would hand it every other client's secret.

## Troubleshooting

| Symptom | Cause |
|---|---|
| Login loops, or redirects to `http://` | `proxy.headers: xforwarded` missing |
| HTTP 400 at login | Large OIDC cookies; set `nginx.org/proxy-buffer-size` on the Ingress |
| `PKIX path building failed` in sync logs | `linds-ca-cert` absent from this namespace, or holding base64 instead of raw PEM |
| Pod `CrashLoopBackOff` mentioning `--optimized` | `spec.image` was set on the CR; remove it |
| Roles never match in an app | Group claim has a leading `/`; set `full.path: ["false"]` |
| Users import with no email | Email mapper reading `mail` instead of `userPrincipalName` |

## Vault OIDC (manual)

Vault has no Terraform or config operator in this repo, so its auth method is
configured imperatively. This is a known, accepted gap rather than an
oversight. The runbook lands here when phase 5 is implemented; until then Vault
uses token auth only.
