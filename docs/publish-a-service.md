# Publish a service to the internet

This page tells you how to make a Kubernetes Service reachable from the
internet through jd-router-01, with a public DNS name in Cloudflare.

## What happens

1. Cilium gives the LoadBalancer Service an address in `172.16.1.0/24` and
   advertises it to jd-router-01 over BGP.
2. `k8s-port-forward` on jd-router-01 reads the annotation
   `public.linds.com.au/ports`. In 20 seconds it forwards those WAN ports to
   the Service's address (LINDS-Ansible `roles/router`, "Port forwards").
3. `external-dns-public` writes the name in `public.linds.com.au/hostname` to
   Cloudflare, as a CNAME to `jd.linds.com.au`. This takes 1 minute
   (`applications/external-dns-public.yaml`).
4. `ddclient` on jd-router-01 keeps `jd.linds.com.au` on the WAN address. It
   has an A record only, so an IPv6 client does not try an address that goes
   nowhere.
5. The internal `external-dns` writes the same name in the AD zone with the
   Service's own address. Clients at home go straight to the Service, not
   through the WAN.

## Publish a Service

Add these annotations to a Service of type `LoadBalancer`:

```yaml
apiVersion: v1
kind: Service
metadata:
  name: game
  annotations:
    # The WAN ports that the router forwards to this Service.
    public.linds.com.au/ports: "2456-2457/udp"
    # The public name. Leave out both lines for no public name.
    public.linds.com.au/hostname: game.linds.com.au
    public.linds.com.au/target: jd.linds.com.au
    # The same name in the internal DNS, with the Service's own address.
    external-dns.kubernetes.io/hostname: game.linds.com.au
spec:
  type: LoadBalancer
  externalTrafficPolicy: Local
  ports:
    - name: game
      port: 2456
      protocol: UDP
    - name: query
      port: 2457
      protocol: UDP
```

The value of `public.linds.com.au/ports` is a list of items, separated by
commas:

| Item | What the router does |
|---|---|
| `443/tcp` | Forwards WAN port 443 to Service port 443. |
| `2456-2457/udp` | Forwards each port in the range (64 ports at most). |
| `25565/tcp,25565/udp` | Forwards the port for each protocol. |
| `8443:443/tcp` | Forwards WAN port 8443 to Service port 443. |

Each port must be a port of the Service, with the same protocol.

Use `externalTrafficPolicy: Local`. Then the application sees the address of
each client, and Cilium advertises the Service only from the nodes that run
its pods. With `Cluster`, a connection that arrives on another node is
source-NATed to that node's address.

Give the pods a network policy that stops them from reaching the LAN and the
rest of the cluster.

## Publish a web application

Do not forward a port for a web application. Put it behind the mTLS ingress:

1. Give its Ingress the label or annotation `linds.com.au/mtls-mirror: "true"`.
2. Kyverno makes a copy of the Ingress on the class `nginx-mtls`
   (`kyverno/mirror-mtls-ingress.yaml`).
3. The router forwards WAN port 443 to the mTLS ingress (172.16.1.12).
4. `external-dns-public` writes each host of the copy to Cloudflare as a
   CNAME to `jd.linds.com.au`.

A client must have a client certificate from `linds-ca`
(`nginx-ingress-mtls/README.md`).

## Check a published service

1. On jd-router-01, run `router forwards`. It shows each forward, its packet
   count and each request that the router refused, with the reason.
2. Read the log of the public DNS:
   `kubectl -n external-dns-public logs deploy/external-dns-public`.
3. Look up the public name:
   `dig +short @1.1.1.1 game.linds.com.au`. The answer is
   `jd.linds.com.au.` and the WAN address.
4. Connect from outside the LAN, for example from a phone on mobile data.

## Remove a published service

Remove the annotations, or delete the Service. The router removes the
forward in 20 seconds. `external-dns-public` deletes the record in 1 minute.

## Limits

* IPv4 only. The cluster has no IPv6 addresses.
* The router does not forward 500/udp and 4500/udp. It uses these ports for
  IPsec.
* The router forwards only to addresses in `172.16.1.0/24`.
* One Service has a WAN port and protocol. If two Services ask for the same
  one, the older Service keeps it, and the router refuses the other request
  (alert `RouterPortForwardRefused`).
* A record made by hand in Cloudflare with the same name stops
  `external-dns-public`. Delete the record made by hand first.
* The forwards are only at JD. linds-router-01 does not have them.

## When something is wrong

| Symptom | Do this |
|---|---|
| `router forwards` shows a refused request | Read the reason. Correct the annotation or the Service. |
| `router forwards` does not show the Service | Is the Service of type `LoadBalancer`, with an address? `kubectl get svc -A` |
| The name does not resolve | Read the `external-dns-public` log. Look for a record made by hand in Cloudflare. |
| The name resolves, but there is no connection | Is the pod ready? Does its network policy let `world` in on that port? `router trace ADDRESS` on jd-router-01 shows the path of one client's packets. |
