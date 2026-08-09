#!/usr/bin/env bash
# Supervises `claude remote-control` in server mode.
#
# Server mode is the session manager: it serves many concurrent sessions from
# one process, each listed by name at claude.ai/code and in the Claude mobile
# app, so a session started here can be picked up from any device.
#
# It needs supervising because the docs are explicit that the process exits if
# the machine can't reach the network for ~10 minutes - which, given the lab's
# cross-site IPsec tunnel, is a question of when rather than if.
set -uo pipefail

log() { printf '[rc-server] %s\n' "$*"; }

WORKSPACE="${WORKSPACE:-${HOME}/workspace}"
# Server mode must start from a project directory: the startup trust dialog
# never saves trust for a home directory.
PROJECT_DIR="${RC_PROJECT_DIR:-${WORKSPACE}/LINDS-Terraform}"
[[ -d "${PROJECT_DIR}" ]] || PROJECT_DIR="${WORKSPACE}"

cd "${PROJECT_DIR}" || exit 1

if [[ -n "${CLAUDE_CODE_OAUTH_TOKEN:-}" || -n "${ANTHROPIC_API_KEY:-}" ]]; then
  cat <<'EOF'

  !! CLAUDE_CODE_OAUTH_TOKEN or ANTHROPIC_API_KEY is set.

  Remote Control rejects both: a setup-token can only make model requests and
  cannot establish a Remote Control session, and API keys are unsupported.
  Remove the key from linds-keyvault/claude-code-secret and restart, then run
  `claude` + /login in the shell window to authenticate with claude.ai.

EOF
fi

backoff=15
while true; do
  log "starting server in ${PROJECT_DIR} (spawn=${RC_SPAWN:-worktree}, capacity=${RC_CAPACITY:-8})"
  claude remote-control \
    --name "${RC_NAME:-linds}" \
    --remote-control-session-name-prefix "${RC_PREFIX:-linds}" \
    --spawn "${RC_SPAWN:-worktree}" \
    --capacity "${RC_CAPACITY:-8}"
  rc=$?
  log "server exited (${rc})"

  # The common first-run failure is "not signed in": there is nothing to retry
  # until a human runs /login in the shell window, so back off rather than spin.
  if [[ ! -f "${CLAUDE_CONFIG_DIR:-${HOME}/.claude}/.credentials.json" ]]; then
    cat <<'EOF'

  Not signed in yet. Remote Control needs a full-scope claude.ai login.
  Switch to the `shell` window (Ctrl-b 0), run `claude`, then `/login`.
  This window retries automatically once that is done.

EOF
    sleep 30
    continue
  fi

  log "retrying in ${backoff}s"
  sleep "${backoff}"
  backoff=$(( backoff < 240 ? backoff * 2 : 240 ))
done
