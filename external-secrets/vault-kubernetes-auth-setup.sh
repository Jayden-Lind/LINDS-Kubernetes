#!/usr/bin/env bash
# Let External Secrets log in to Vault with its own Kubernetes service account,
# with read-only access to linds-keyvault.
#
# Before this, the ClusterSecretStore used the Vault root token from the
# Secret default/vault-token. With this, no long-lived Vault token is in the
# cluster: the operator's service account token is exchanged for a Vault token
# that expires after one hour and can only read.
#
# Vault has no Terraform or config operator in this repo (see
# keycloak/vault-oidc-setup.sh), so this part is imperative. It is idempotent:
# a second run changes nothing.
#
# Requires: VAULT_ADDR and VAULT_TOKEN (root or the admin policy).
#
#   kubectl -n vault port-forward vault-0 18200:8200 &
#   export VAULT_ADDR=http://127.0.0.1:18200
#   ./external-secrets/vault-kubernetes-auth-setup.sh
set -euo pipefail

: "${VAULT_ADDR:?set VAULT_ADDR, e.g. http://127.0.0.1:18200 through a port-forward}"
: "${VAULT_TOKEN:?set VAULT_TOKEN}"

SA_NAME="external-secrets-operator"
SA_NAMESPACE="external-secrets-system"
ROLE="external-secrets"
POLICY="external-secrets-read"

echo "==> enabling the kubernetes auth method (if it is not enabled)"
if ! vault auth list -format=json | grep -q '"kubernetes/"'; then
  vault auth enable kubernetes
fi

# Vault runs in the cluster, so it reviews tokens with its own service account
# (vault/vault has system:auth-delegator) and the cluster CA from its pod.
echo "==> configuring it for this cluster"
vault write auth/kubernetes/config kubernetes_host="https://kubernetes.default.svc:443"

echo "==> writing the read-only policy"
vault policy write "$POLICY" - <<'EOF'
# External Secrets: read the keys that ExternalSecrets extract. Nothing else.
path "linds-keyvault/data/*"     { capabilities = ["read"] }
path "linds-keyvault/metadata/*" { capabilities = ["read", "list"] }
EOF

echo "==> writing the role for the operator's service account"
vault write "auth/kubernetes/role/$ROLE" \
  bound_service_account_names="$SA_NAME" \
  bound_service_account_namespaces="$SA_NAMESPACE" \
  audience="vault" \
  token_policies="$POLICY" \
  token_ttl=1h \
  token_max_ttl=4h

echo "done: ClusterSecretStore vault-backend can use auth.kubernetes, role $ROLE"
