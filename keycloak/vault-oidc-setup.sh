#!/usr/bin/env bash
# Configure Vault's OIDC auth method against the Keycloak `linds` realm.
#
# Vault has no Terraform or config operator in this repo, so this is the one
# piece of the Keycloak design that is imperative rather than GitOps-managed.
# It is idempotent: re-running it reconciles rather than duplicates.
#
# Requires: VAULT_ADDR, a Vault token with root/sudo, and kubectl access to
# read the client secret and CA from the cluster.
#
#   export VAULT_ADDR=https://vault.linds.com.au
#   ./keycloak/vault-oidc-setup.sh
set -euo pipefail

: "${VAULT_ADDR:?set VAULT_ADDR, e.g. https://vault.linds.com.au}"

REALM_URL="https://keycloak.linds.com.au/realms/linds"
CLIENT_ID="vault"

echo "==> reading client secret from the cluster"
CLIENT_SECRET=$(kubectl -n keycloak get secret keycloak-client-secrets \
  -o jsonpath='{.data.vault}' | base64 -d)
[ -n "$CLIENT_SECRET" ] || { echo "empty client secret"; exit 1; }

echo "==> reading linds-CA (Vault must trust Keycloak's cert to fetch discovery)"
CA_PEM=$(kubectl -n cert-manager get secret linds-ca-keypair \
  -o jsonpath='{.data.tls\.crt}' | base64 -d)

echo "==> ensuring the admin policy exists"
vault policy write admin - <<'EOF'
# Full administration of secrets, auth, policies and identity.
# Deliberately not root: the root token stays the break-glass path.
path "linds-keyvault/*"   { capabilities = ["create","read","update","delete","list"] }
path "secret/*"           { capabilities = ["create","read","update","delete","list"] }
path "auth/*"             { capabilities = ["create","read","update","delete","list","sudo"] }
path "sys/auth*"          { capabilities = ["create","read","update","delete","sudo"] }
path "sys/mounts*"        { capabilities = ["create","read","update","delete","list","sudo"] }
path "sys/policies/acl/*" { capabilities = ["create","read","update","delete","list"] }
path "identity/*"         { capabilities = ["create","read","update","delete","list"] }
path "sys/leases/*"       { capabilities = ["create","read","update","delete","list","sudo"] }
path "sys/capabilities-self" { capabilities = ["create","update"] }
path "sys/*"              { capabilities = ["read","list"] }
EOF

echo "==> enabling the oidc auth method (ignore error if already enabled)"
vault auth enable oidc 2>/dev/null || echo "    already enabled"

echo "==> configuring oidc against the linds realm"
vault write auth/oidc/config \
  oidc_discovery_url="$REALM_URL" \
  oidc_client_id="$CLIENT_ID" \
  oidc_client_secret="$CLIENT_SECRET" \
  oidc_discovery_ca_pem="$CA_PEM" \
  default_role="default"

echo "==> creating the default oidc role"
vault write auth/oidc/role/default \
  bound_audiences="$CLIENT_ID" \
  allowed_redirect_uris="https://vault.linds.com.au/ui/vault/auth/oidc/oidc/callback" \
  allowed_redirect_uris="http://localhost:8250/oidc/callback" \
  user_claim="preferred_username" \
  groups_claim="groups" \
  oidc_scopes="openid,profile,email,groups" \
  role_type="oidc" \
  token_policies="default" \
  token_ttl="1h" \
  token_max_ttl="8h"

echo "==> mapping the AD group k8s-vault-admins to the admin policy"
ACCESSOR=$(vault auth list -format=json | jq -r '."oidc/".accessor')
[ -n "$ACCESSOR" ] || { echo "could not find oidc accessor"; exit 1; }

# External group whose membership comes from the groups claim, not Vault.
vault write identity/group name="k8s-vault-admins" type="external" policies="admin" >/dev/null 2>&1 || true
GROUP_ID=$(vault read -format=json identity/group/name/k8s-vault-admins | jq -r .data.id)
vault write identity/group/id/"$GROUP_ID" policies="admin" type="external" >/dev/null

# The alias name must exactly match the group string in the token claim.
# Without the alias the group exists but nothing ever resolves into it, so
# logins succeed with only the default policy and the admin grant silently
# does nothing. Errors are NOT suppressed here - an earlier version hid the
# failure behind >/dev/null and left the alias unset.
ALIAS_ID=$(vault read -format=json "identity/group/id/$GROUP_ID" | jq -r '.data.alias.id // empty')
if [ -z "$ALIAS_ID" ]; then
  vault write identity/group-alias \
    name="k8s-vault-admins" \
    mount_accessor="$ACCESSOR" \
    canonical_id="$GROUP_ID"
else
  echo "    alias already present ($ALIAS_ID)"
fi

echo "==> verifying the alias actually bound"
vault read -format=json identity/group/name/k8s-vault-admins \
  | jq -e '.data.alias.name == "k8s-vault-admins"' >/dev/null \
  || { echo "FAILED: group alias not bound - OIDC logins would get no admin policy"; exit 1; }

echo
echo "done. verify with:"
echo "  vault login -method=oidc role=default"
echo
echo "Break-glass is unaffected: the root token still works, and the oidc"
echo "method can be removed with 'vault auth disable oidc'."
