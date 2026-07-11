# mTLS-only Ingress (`nginx-mtls`)

A second NGINX (F5) Ingress Controller instance ([applications/nginx-ingress-mtls.yaml](../applications/nginx-ingress-mtls.yaml))
that serves the `nginx-mtls` ingress class on its own VIP **172.16.1.12**, HTTPS only.
Every server block it generates enforces client-certificate verification against
**linds-ca** (via a global `server-snippets` in its ConfigMap), so anything on this
class is unreachable without a valid client certificate — safe to publish to the
internet. Connections without a cert are rejected with HTTP 400 before reaching any app.

The CA public cert is synced from Vault (`linds-keyvault/linds-ca-keypair` → secret
`linds-ca-cert`) by external-secrets. Client certificates are issued by cert-manager
from the `linds-ca` ClusterIssuer ([pki.yaml](pki.yaml)) and auto-renew at ~2/3 of
their 2-year lifetime.

## Fetch a client certificate

cert-manager bakes a ready-to-import PKCS#12 bundle into each client-cert secret:

```bash
kubectl get secret -n nginx-ingress-mtls mtls-client-jayden \
  -o jsonpath='{.data.keystore\.p12}' | base64 -d > jayden.p12
```

Import the `.p12` on the device (password: `home-mtls`). For the Home Assistant
companion app, add it under the connection/security settings and use the mTLS host
(e.g. `https://home-mtls.linds.com.au`) as the external URL.

When cert-manager renews a certificate (roughly every 16 months), re-run the fetch
and re-import on the device.

## Enrol a new device

Copy the `Certificate` block in [pki.yaml](pki.yaml) with a new name
(`mtls-client-<name>`), commit, then fetch its `.p12` as above.

## Expose a service on the mTLS class

Add a second Ingress for the service with `ingressClassName: nginx-mtls` and a
distinct `<name>-mtls.linds.com.au` host — see
[base/home-assistant/mtls.yml](../base/home-assistant/mtls.yml) for the template.
DNS is created automatically by external-dns; the internal (non-mTLS) Ingress on
the `nginx` class is unaffected.
