#!/usr/bin/env bash
# Seeds the persistent volume, materialises credentials that have to exist as
# files rather than env vars, keeps the CLI up to date, brings up the tmux
# session (Remote Control server + shell), then hands off to ttyd.
#
# Every credential is optional: an unset variable is skipped with a log line
# rather than failing the pod, so you can add secrets to Vault incrementally.
set -euo pipefail

log() { printf '[entrypoint] %s\n' "$*" >&2; }

HOME_DIR="${HOME:-/home/claude}"
WORKSPACE="${WORKSPACE:-${HOME_DIR}/workspace}"
export WORKSPACE

mkdir -p "${WORKSPACE}" "${HOME_DIR}/.ssh" "${HOME_DIR}/.talos" "${HOME_DIR}/bin" \
         "${CLAUDE_CONFIG_DIR:-${HOME_DIR}/.claude}" "${HOME_DIR}/.kube" \
         "${NPM_CONFIG_PREFIX:-${HOME_DIR}/.npm-global}"
chmod 700 "${HOME_DIR}/.ssh"

# materialise <ENV_VAR_HOLDING_BASE64> <destination path> [mode]
materialise() {
  local var="$1" path="$2" mode="${3:-0600}" value
  value="${!var:-}"
  if [[ -z "${value}" ]]; then
    log "skip ${path} (${var} not set)"
    return 0
  fi
  mkdir -p "$(dirname "${path}")"
  printf '%s' "${value}" | base64 -d > "${path}"
  chmod "${mode}" "${path}"
  log "wrote ${path} from ${var}"
}

# --- credentials that must be files -----------------------------------------
# kubectl needs nothing here: the pod's ServiceAccount token is picked up as
# in-cluster config automatically.
materialise TALOSCONFIG_B64     "${HOME_DIR}/.talos/config"
# Named for its role rather than its algorithm: the lab key is currently RSA,
# and a filename like id_ed25519 would be a lie that ssh silently ignores.
materialise SSH_PRIVATE_KEY_B64 "${HOME_DIR}/.ssh/id_lab"
materialise SSH_KNOWN_HOSTS_B64 "${HOME_DIR}/.ssh/known_hosts" 0644

# The lab's hosts are reached over the IPsec-linked private VLANs and their host
# keys aren't in any public trust store; relax strict checking only for those.
# Rewritten every boot so a key rename can't be shadowed by a stale copy on the
# volume.
cat > "${HOME_DIR}/.ssh/config" <<'EOF'
Host 10.* 192.168.* jd-* linds-* *.linds.com.au
    IdentityFile ~/.ssh/id_lab
    IdentitiesOnly yes
    StrictHostKeyChecking accept-new
    UserKnownHostsFile ~/.ssh/known_hosts
EOF
chmod 600 "${HOME_DIR}/.ssh/config"

# Remote Control refuses both of these, so flag them loudly rather than letting
# the phone/desktop handoff fail with an obscure error later.
if [[ -n "${CLAUDE_CODE_OAUTH_TOKEN:-}" || -n "${ANTHROPIC_API_KEY:-}" ]]; then
  log "WARNING: CLAUDE_CODE_OAUTH_TOKEN/ANTHROPIC_API_KEY is set - Remote Control"
  log "WARNING: will refuse to start. See claude-code/README.md."
fi

# --- git ---------------------------------------------------------------------
git config --global user.name  "${GIT_AUTHOR_NAME:-Claude Code}"
git config --global user.email "${GIT_AUTHOR_EMAIL:-claude@linds.com.au}"
git config --global --add safe.directory '*'

if [[ -n "${GITHUB_TOKEN:-}" ]]; then
  git config --global credential."https://github.com".helper \
    '!f() { echo username=x-access-token; echo "password=${GITHUB_TOKEN}"; }; f'
  log "configured github credential helper"
fi

# --- working repos ------------------------------------------------------------
for repo in ${WORKSPACE_REPOS:-}; do
  name="$(basename "${repo}" .git)"
  if [[ -d "${WORKSPACE}/${name}/.git" ]]; then
    log "repo ${name} already present"
  else
    log "cloning ${repo}"
    git clone --quiet "${repo}" "${WORKSPACE}/${name}" \
      || log "WARNING: clone of ${repo} failed; continuing"
  fi
done

# Terraform's tfvars and S3 backend creds are gitignored in LINDS-Terraform, so
# they arrive from Vault and get dropped into the clone after it exists.
materialise TF_TFVARS_B64       "${TF_TFVARS_PATH:-${WORKSPACE}/LINDS-Terraform/proxmox/terraform.tfvars}"
materialise TF_BACKEND_CONF_B64 "${TF_BACKEND_CONF_PATH:-${WORKSPACE}/LINDS-Terraform/proxmox/backend.conf}"

# --- keep the CLI current -----------------------------------------------------
# The image ships a copy under /usr/local as an offline fallback. The copy that
# actually runs lives in the volume and is user-writable, so both this update
# and the CLI's own auto-updater persist across restarts.
if [[ "${CLAUDE_UPDATE_ON_START:-true}" == "true" ]]; then
  log "updating claude-code in ${NPM_CONFIG_PREFIX}"
  npm install -g --silent @anthropic-ai/claude-code@latest \
    || log "WARNING: update failed; falling back to the image's copy"
fi
log "claude version: $(claude --version 2>/dev/null || echo unknown)"

# --- shell niceties -----------------------------------------------------------
if ! grep -q 'claude-code-workspace' "${HOME_DIR}/.bashrc" 2>/dev/null; then
  cat >> "${HOME_DIR}/.bashrc" <<'EOF'

# --- claude-code-workspace ---
alias k=kubectl
alias tf=terraform
# Session manager: the built-in picker. Ctrl-A widens to every project,
# Ctrl-R renames, Space previews.
alias ccm='claude --resume'
alias ccupdate='npm install -g @anthropic-ai/claude-code@latest && claude --version'
cd "${WORKSPACE:-${HOME}/workspace}" 2>/dev/null || true
EOF
fi

cat > "${HOME_DIR}/.tmux.conf" <<'EOF'
set -g mouse on
set -g history-limit 50000
set -g status-style 'bg=#313244 fg=#cdd6f4'
set -g status-left '#[bold] claude@linds #[default]'
set -g default-terminal 'tmux-256color'
# Desktop and phone attach to the SAME session. Without these, tmux clamps the
# window to the smallest attached client, so opening the phone would shrink the
# desktop to phone width. `latest` sizes to whichever client is active instead.
set -g window-size latest
setw -g aggressive-resize on
EOF

# --- tmux session -------------------------------------------------------------
# Written to /tmp rather than the volume so a stale copy can't outlive an image
# update. ttyd runs this, so the layout is rebuilt if the session is ever killed.
cat > /tmp/tmux-up.sh <<'EOF'
#!/usr/bin/env bash
set -uo pipefail
SESSION="${TMUX_SESSION:-main}"
if ! tmux has-session -t "${SESSION}" 2>/dev/null; then
  tmux new-session  -d -s "${SESSION}" -n shell -c "${WORKSPACE:-${HOME}/workspace}"
  if [[ "${RC_ENABLED:-true}" == "true" ]]; then
    tmux new-window -t "${SESSION}" -n remote-control /usr/local/bin/rc-server.sh
  fi
  tmux select-window -t "${SESSION}:shell"
fi
exec tmux attach-session -t "${SESSION}"
EOF
chmod 0755 /tmp/tmux-up.sh

# Start the session detached now, so the Remote Control server is up and the
# session is reachable from claude.ai and the phone without anyone first
# opening the web terminal.
TMUX_SESSION="${TMUX_SESSION:-main}" tmux new-session -d -s "${TMUX_SESSION:-main}" \
  -n shell -c "${WORKSPACE}" 2>/dev/null || true
if [[ "${RC_ENABLED:-true}" == "true" ]] \
   && ! tmux list-windows -t "${TMUX_SESSION:-main}" -F '#W' 2>/dev/null | grep -qx remote-control; then
  tmux new-window -t "${TMUX_SESSION:-main}" -n remote-control /usr/local/bin/rc-server.sh
  tmux select-window -t "${TMUX_SESSION:-main}:shell"
fi

log "starting ttyd on :7681 (tmux session '${TMUX_SESSION:-main}')"
exec ttyd \
  --writable \
  --port 7681 \
  --interface 0.0.0.0 \
  --max-clients "${TTYD_MAX_CLIENTS:-8}" \
  --ping-interval 30 \
  -t titleFixed="claude@linds" \
  -t fontSize=14 \
  -t 'theme={"background":"#1e1e2e","foreground":"#cdd6f4"}' \
  /tmp/tmux-up.sh
