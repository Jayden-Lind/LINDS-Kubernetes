# Workspace image for the in-cluster Claude Code session host.
#
# There is no official Anthropic container image (ghcr.io/anthropics/claude-code
# does not exist - only the devcontainer *feature* is published), so this builds
# one: the CLI plus the tooling this homelab actually drives (kubectl, talosctl,
# terraform, helm) behind a ttyd web terminal.
#
# Tool versions are ARGs with Renovate datasource comments so they get bumped by
# the same automation as the Helm charts in this repo.
FROM node:22-bookworm-slim

# renovate: datasource=github-releases depName=kubernetes/kubernetes
ARG KUBECTL_VERSION=v1.36.3
# renovate: datasource=github-releases depName=siderolabs/talos
ARG TALOSCTL_VERSION=v1.13.8
# renovate: datasource=github-releases depName=hashicorp/terraform
ARG TERRAFORM_VERSION=1.15.8
# renovate: datasource=github-releases depName=helm/helm
ARG HELM_VERSION=v3.21.3
# renovate: datasource=github-releases depName=tsl0922/ttyd
ARG TTYD_VERSION=1.7.7

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl git tmux openssh-client jq less ripgrep unzip \
      gnupg procps bash-completion vim-tiny iputils-ping dnsutils netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

RUN set -eux; \
    arch="$(dpkg --print-architecture)"; \
    case "$arch" in amd64) alt=x86_64 ;; arm64) alt=aarch64 ;; *) echo "unsupported arch $arch" >&2; exit 1 ;; esac; \
    curl -fsSL -o /usr/local/bin/kubectl \
      "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/${arch}/kubectl"; \
    curl -fsSL -o /usr/local/bin/talosctl \
      "https://github.com/siderolabs/talos/releases/download/${TALOSCTL_VERSION}/talosctl-linux-${arch}"; \
    curl -fsSL -o /usr/local/bin/ttyd \
      "https://github.com/tsl0922/ttyd/releases/download/${TTYD_VERSION}/ttyd.${alt}"; \
    chmod 0755 /usr/local/bin/kubectl /usr/local/bin/talosctl /usr/local/bin/ttyd; \
    curl -fsSL -o /tmp/terraform.zip \
      "https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_linux_${arch}.zip"; \
    unzip -q /tmp/terraform.zip -d /usr/local/bin; \
    curl -fsSL "https://get.helm.sh/helm-${HELM_VERSION}-linux-${arch}.tar.gz" \
      | tar -xz -C /tmp; \
    mv "/tmp/linux-${arch}/helm" /usr/local/bin/helm; \
    chmod 0755 /usr/local/bin/terraform /usr/local/bin/helm; \
    rm -rf /tmp/terraform.zip "/tmp/linux-${arch}"; \
    kubectl version --client=true; talosctl version --client; \
    terraform version; helm version --short; ttyd --version

# Baked-in copy is only a cold-start fallback so the pod boots with no network.
# The copy that actually runs is installed into the persistent volume at
# /home/claude/.npm-global (see entrypoint.sh), which is user-writable, so the
# CLI's own auto-updater keeps it current and the update survives restarts.
RUN npm install -g @anthropic-ai/claude-code \
    && npm cache clean --force

# The CLI refuses --dangerously-skip-permissions when euid is 0, so the pod must
# run as a normal user. uid 1001 avoids colliding with the base image's `node`.
RUN useradd --uid 1001 --create-home --shell /bin/bash claude

COPY entrypoint.sh rc-server.sh /usr/local/bin/
RUN chmod 0755 /usr/local/bin/entrypoint.sh /usr/local/bin/rc-server.sh

# ~/.claude.json lives OUTSIDE ~/.claude, so pointing CLAUDE_CONFIG_DIR at the
# persistent volume is what actually keeps the session authenticated across
# restarts - mounting ~/.claude alone is not enough.
#
# Deliberately NOT set: DISABLE_AUTOUPDATER (we want the CLI self-updating in
# the volume), and DISABLE_TELEMETRY / DO_NOT_TRACK /
# CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC / DISABLE_GROWTHBOOK - each of those
# disables the feature-flag evaluation that Remote Control depends on, which
# would break the phone/desktop handoff this image exists for.
ENV HOME=/home/claude \
    CLAUDE_CONFIG_DIR=/home/claude/.claude \
    NPM_CONFIG_PREFIX=/home/claude/.npm-global \
    PATH=/home/claude/.npm-global/bin:/usr/local/bin:/usr/bin:/bin \
    TERM=xterm-256color \
    EDITOR=vi

USER claude
WORKDIR /home/claude/workspace
EXPOSE 7681
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
