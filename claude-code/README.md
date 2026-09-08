# Claude Code session host

A long-lived Claude Code host running *inside* the cluster, so it can actually
reach the lab: Proxmox on VLAN 50, the Talos nodes on VLAN 53 and 10.3.1.0/24,
the MinIO tfstate backend, and the Kubernetes API.

It exposes **two surfaces onto the same sessions**:

```
              ┌─ Remote Control ──────────────────────────────────┐
              │  claude.ai/code  ·  Claude iOS/Android app        │
              │  outbound HTTPS only — no VPN, no inbound ports   │
              └───────────────────────▲───────────────────────────┘
                                      │
   phone/laptop ──IPsec VPN──> nginx-mtls (172.16.1.12)
        (raw terminal)                │  client cert required (linds-ca)
                                      ▼
                      ttyd ──> tmux ──> claude remote-control (server mode)
                                      │
                       kubectl · talosctl · terraform · helm · ssh
```

Anthropic publishes no official Claude Code container image — only a
[devcontainer *feature*](https://github.com/anthropics/devcontainer-features/tree/main/src/claude-code)
— so [`Dockerfile`](Dockerfile) builds one, pinning the CLI alongside the tooling
this lab is driven with.

## Seamless desktop ↔ phone

This is [Remote Control](https://code.claude.com/docs/en/remote-control), not
something hand-rolled. The pod runs `claude remote-control` in **server mode**
([`rc-server.sh`](rc-server.sh)), which is Claude Code's own session manager:

- it serves up to `RC_CAPACITY` concurrent sessions from one process, each
  listed by name at [claude.ai/code](https://claude.ai/code) and under **Code**
  in the Claude mobile app
- conversation state, subagent progress and workflow progress stay in sync
  across every connected device, so you can type from the web terminal, the
  browser and your phone interchangeably
- `--spawn worktree` gives each on-demand session its own
  [git worktree](https://code.claude.com/docs/en/worktrees), so parallel
  sessions don't fight over the same files
- `remoteControlAtStartup: true` in managed settings means sessions you start
  by hand in the web terminal also register automatically

Because Remote Control is **outbound HTTPS only** and never opens an inbound
port, the phone surface works with no VPN at all. The mTLS web terminal is for
the things Remote Control can't do — `/login`, `/resume`, `/plugin` are
local-only — plus raw `kubectl`/`terraform`/`ssh` work.

The supervisor restarts the server automatically: the docs are explicit that
the process exits after roughly ten minutes without network, which the
cross-site IPsec tunnel makes a question of when rather than if.

### Session manager in the terminal

In the web terminal, `ccm` (`claude --resume`) opens the built-in picker —
`Ctrl+A` widens to every project, `Ctrl+W` to every worktree, `Ctrl+R` renames,
`Space` previews. Name sessions with `claude -n <name>` or `/rename` and resume
them by name. Transcripts live on the volume under `$CLAUDE_CONFIG_DIR`, with
retention raised to 90 days.

## Authentication — read this first

**Remote Control cannot be used with `CLAUDE_CODE_OAUTH_TOKEN` or
`ANTHROPIC_API_KEY`.** A `claude setup-token` token can only make model
requests, and API keys are unsupported; both produce *"Remote Control requires a
full-scope login token"*. So authentication is a one-time interactive step whose
result persists on the volume:

1. Open `https://claude.linds.com.au` and land in the `shell` tmux window.
2. `cd ~/workspace/LINDS-Terraform && claude` — accept the workspace trust
   prompt (the trust dialog never saves trust for a home directory, which is why
   this starts from a project directory).
3. Run `/login`, complete the browser flow, and paste the code back if the
   callback doesn't reach the pod.
4. The `remote-control` window (`Ctrl-b 1`) picks it up within 30s.

Credentials land in `$CLAUDE_CONFIG_DIR` on the PVC, so this survives restarts
and image updates. Do **not** add either token key to Vault.

Also deliberately unset in the image: `DISABLE_TELEMETRY`, `DO_NOT_TRACK`,
`CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC`, `DISABLE_GROWTHBOOK`. Each disables
the feature-flag evaluation Remote Control availability depends on.

## Access to the terminal

`https://claude.linds.com.au`, on the `nginx-mtls` ingress class **only**. There
is no plain-`nginx` Ingress and the `linds.com.au/mtls-mirror` opt-in is
deliberately not used, because that pattern keeps an unauthenticated Ingress
alongside the mirror. Connections without a valid `linds-ca` client certificate
are rejected with HTTP 400 by the controller before they reach ttyd.

Enrol a device by adding a `Certificate` to
[`../nginx-ingress-mtls/pki.yaml`](../nginx-ingress-mtls/pki.yaml) and importing
the generated `.p12` (password `home-mtls`) — see
[that README](../nginx-ingress-mtls/README.md).

Desktop and phone attach to the *same* tmux session. `window-size latest` plus
`aggressive-resize` make tmux size the window to whichever client is active;
without them tmux clamps to the smallest attached client and opening the phone
would shrink the desktop to phone width.

## Blast radius

A deliberate choice, not an oversight:

- the pod's ServiceAccount is bound to **`cluster-admin`**
- Claude Code runs with **`bypassPermissions`**, set declaratively through
  `/etc/claude-code/managed-settings.json` rather than a CLI flag —
  `bypassPermissions` is never restored by session resume, so it has to come
  from settings
- the Proxmox API token and the lab SSH key are injected from Vault

Two independent paths reach that: a `linds-ca` client certificate over the VPN,
and your claude.ai account via Remote Control. Revoke the first by removing a
`Certificate` from `pki.yaml`; revoke the second at
[claude.ai/settings/account](https://claude.ai/settings/account), or set
`RC_ENABLED=false` to drop the surface entirely.

`--dangerously-skip-permissions` is rejected by the CLI when euid is 0, which is
why the image creates and runs as uid 1001.

## Credentials

Everything else comes from one Vault entry,
`linds-keyvault/claude-code-secret`, synced by the `claude-code-secret`
`ClusterExternalSecret` in
[`../external-secrets/secrets.yaml`](../external-secrets/secrets.yaml) and
consumed with `envFrom`. **Adding a credential is a Vault write — no change to
this repo.** Every key is optional; the entrypoint logs and skips what is unset.

| Vault key | Purpose |
|---|---|
| `GITHUB_TOKEN` | Optional — both repos are public, so cloning works without it. Needed only to push. Wired into a git credential helper. |
| `TALOSCONFIG_B64` | base64 of `proxmox/talosconfig` → `~/.talos/config`. |
| `SSH_PRIVATE_KEY_B64` | base64 of the key that reaches the Proxmox hosts, VyOS routers and storage host → `~/.ssh/id_lab`. |
| `SSH_KNOWN_HOSTS_B64` | Optional; base64 of a `known_hosts` file. |
| `TF_TFVARS_B64` | base64 of `proxmox/terraform.tfvars` (gitignored) → dropped into the clone. |
| `TF_BACKEND_CONF_B64` | base64 of `proxmox/backend.conf`, the MinIO S3 state credentials. |

No kubeconfig is needed: `kubectl` picks up the pod's ServiceAccount as
in-cluster config automatically.

`vault` and `VAULT_ADDR` come from `home/common.nix` in the `shell-env` repo.
Values are passed on stdin rather than as arguments so the private key never
appears in the process table:

```bash
vault login   # once
jq -n \
  --arg talos   "$(base64 -w0 ~/git/LINDS-Terraform/proxmox/talosconfig)" \
  --arg sshkey  "$(base64 -w0 ~/.ssh/id_rsa)" \
  --arg tfvars  "$(base64 -w0 ~/git/LINDS-Terraform/proxmox/terraform.tfvars)" \
  --arg backend "$(base64 -w0 ~/git/LINDS-Terraform/proxmox/backend.conf)" \
  '{TALOSCONFIG_B64:$talos, SSH_PRIVATE_KEY_B64:$sshkey,
    TF_TFVARS_B64:$tfvars, TF_BACKEND_CONF_B64:$backend}' \
  | vault kv put linds-keyvault/claude-code-secret -
```

`refreshPolicy: OnChange` means the Secret updates within the hour, but the pod
only picks up new values on restart:
`kubectl rollout restart -n claude-code statefulset/claude-code`.

## Staying on the latest Claude Code

Three layers, so you're never blocked on a rebuild:

1. **Per-restart** — `CLAUDE_UPDATE_ON_START=true` reinstalls the latest CLI
   into `/home/claude/.npm-global` on the volume at boot.
2. **In place** — that prefix is user-writable and the auto-updater is *not*
   disabled, so the CLI keeps itself current mid-session and the update persists.
3. **On demand** — `ccupdate` in the terminal.

The copy baked into the image under `/usr/local` is only a cold-start fallback
so the pod still boots with no registry access; the volume copy wins on `PATH`.
Because of that, the Dockerfile no longer pins a CLI version — the *tools*
around it (kubectl, talosctl, terraform, helm, ttyd) are pinned as `ARG`s with
Renovate datasource comments.

## Storage

One 50Gi `zfs-iscsi` PVC at `/home/claude`, holding the cloned repos, the npm
prefix, `~/.claude` and `~/.claude.json`. Both of the latter matter:
`~/.claude.json` lives *outside* `~/.claude`, so `CLAUDE_CONFIG_DIR` is pointed
at the volume to keep the login persistent.

The pod is pinned `datacenter: jd` — the iSCSI target and the S3 tfstate backend
both live at that site, and the cross-site IPsec tunnel is only ~52 Mbit/s.

## Image

Built by [`../.github/workflows/build-claude-code.yaml`](../.github/workflows/build-claude-code.yaml)
and pushed to `ghcr.io/jayden-lind/claude-code-workspace:latest` (plus a SHA
tag), pulled with the existing `ghcr-pull-secret`.

## Gotcha: WebSockets

ttyd is entirely WebSocket after the initial page load, and this cluster runs
the F5/NGINX Inc controller, which does **not** auto-upgrade connections. The
Ingress therefore carries `nginx.org/websocket-services: "claude-code"`. Without
it the page loads and the terminal hangs with no error.
