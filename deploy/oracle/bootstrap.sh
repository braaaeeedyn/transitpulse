#!/usr/bin/env bash
# Install or update TransitPulse's Dagster services on the Oracle VM (ARM, Oracle Linux or Ubuntu).
#
#   sudo bash deploy/oracle/bootstrap.sh          # first install, and again for every update
#
# Idempotent: re-running pulls the latest code, re-syncs dependencies and restarts the services. It never
# overwrites /etc/transitpulse/transitpulse.env and never prints the service-account key. Services are only
# started once the key file is in place with owner transitpulse and mode 600. Runbook: docs/ORACLE_VM.md.
set -euo pipefail

REPO_URL="${TP_REPO_URL:-https://github.com/braaaeeedyn/transitpulse.git}"
BRANCH="${TP_BRANCH:-main}"
APP_USER=transitpulse
APP_DIR=/opt/transitpulse
STATE_DIR=/var/lib/transitpulse
ETC_DIR=/etc/transitpulse
ENV_FILE="$ETC_DIR/transitpulse.env"
KEY_FILE="$ETC_DIR/sa-pipeline-key.json"
UNITS=(transitpulse-dagster-daemon.service transitpulse-dagster-web.service)

log() { printf '==> %s\n' "$*"; }
warn() { printf 'warning: %s\n' "$*" >&2; }
die() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}
# run as the service user, with its own HOME (uv, git and dbt keep their caches there)
as_app() { runuser -u "$APP_USER" -- env HOME="$STATE_DIR" "$@"; }

[[ $EUID -eq 0 ]] || die "run as root: sudo bash $0"

# --- machine checks ----------------------------------------------------------------------------------
arch="$(uname -m)"
if [[ "$arch" != "aarch64" ]]; then
  warn "expected an ARM (aarch64) VM, found $arch; continuing, but this setup is only tested on aarch64"
fi

# --- packages: git, curl, Java 17 (headless) ---------------------------------------------------------
if command -v apt-get >/dev/null 2>&1; then
  apt_pkgs=(git curl ca-certificates openjdk-17-jre-headless)
  missing=()
  for p in "${apt_pkgs[@]}"; do
    dpkg-query -W -f='${Status}' "$p" 2>/dev/null | grep -q "install ok installed" || missing+=("$p")
  done
  if ((${#missing[@]} == 0)); then
    log "packages already installed (${apt_pkgs[*]}); skipping apt"
  else
    log "installing packages with apt: ${missing[*]}"
    export DEBIAN_FRONTEND=noninteractive
    # another program's package source on a shared VM can fail (e.g. Caddy's returned 402 on 2026-10-09);
    # that must not block TransitPulse: warn, and let the install below fail only if our packages are unavailable
    apt-get update -q || warn "apt-get update reported errors (often an unrelated package source); continuing"
    apt-get install -y -q "${missing[@]}"
  fi
elif command -v dnf >/dev/null 2>&1; then
  log "installing packages with dnf"
  dnf install -y -q git curl ca-certificates java-17-openjdk-headless
else
  die "neither apt-get nor dnf found; install git, curl and Java 17 by hand, then re-run"
fi

# JAVA_HOME of the Java 17 just installed (path differs per distro and architecture)
java_home=""
for candidate in /usr/lib/jvm/java-17-openjdk-* /usr/lib/jvm/java-17-openjdk /usr/lib/jvm/jre-17-openjdk*; do
  if [[ -x "$candidate/bin/java" ]]; then
    java_home="$candidate"
    break
  fi
done
[[ -n "$java_home" ]] || die "Java 17 not found under /usr/lib/jvm"
"$java_home/bin/java" -version 2>&1 | grep -q 'version "17' || die "$java_home is not Java 17"
log "Java 17 at $java_home"

# --- user and directories ----------------------------------------------------------------------------
if ! id -u "$APP_USER" >/dev/null 2>&1; then
  log "creating system user $APP_USER"
  useradd --system --create-home --home-dir "$STATE_DIR" --shell /usr/sbin/nologin "$APP_USER"
fi
install -d -o "$APP_USER" -g "$APP_USER" -m 750 "$STATE_DIR" "$STATE_DIR/dagster_home"
install -d -o "$APP_USER" -g "$APP_USER" -m 755 "$APP_DIR"
install -d -o root -g root -m 755 "$ETC_DIR"

# --- uv (per-user install, no root Python changes) ---------------------------------------------------
UV="$STATE_DIR/.local/bin/uv"
if [[ ! -x "$UV" ]]; then
  log "installing uv for $APP_USER"
  as_app sh -c 'curl -LsSf https://astral.sh/uv/install.sh | sh'
fi

# --- code ----------------------------------------------------------------------------------------------
if [[ -d "$APP_DIR/.git" ]]; then
  log "updating $APP_DIR ($BRANCH)"
  as_app git -C "$APP_DIR" fetch --quiet origin "$BRANCH"
  as_app git -C "$APP_DIR" checkout --quiet "$BRANCH"
  as_app git -C "$APP_DIR" merge --ff-only --quiet "origin/$BRANCH"
else
  log "cloning $REPO_URL into $APP_DIR"
  as_app git clone --quiet --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
fi

log "syncing Python dependencies (pipeline, dbt, ml, spark)"
as_app bash -c "cd '$APP_DIR' && '$UV' sync --frozen --group pipeline --group dbt --group ml --group spark"

# --- configuration -------------------------------------------------------------------------------------
if [[ ! -f "$ENV_FILE" ]]; then
  log "creating $ENV_FILE from the example (review it before the first backfill)"
  install -o root -g root -m 600 "$APP_DIR/deploy/oracle/transitpulse.env.example" "$ENV_FILE"
  sed -i "s|^JAVA_HOME=.*|JAVA_HOME=$java_home|" "$ENV_FILE"
fi
chown root:root "$ENV_FILE"
chmod 600 "$ENV_FILE"

set -a
# shellcheck source=/dev/null
. "$ENV_FILE"
set +a

dagster_home="${DAGSTER_HOME:-$STATE_DIR/dagster_home}"
install -d -o "$APP_USER" -g "$APP_USER" -m 750 "$dagster_home"
install -o "$APP_USER" -g "$APP_USER" -m 644 "$APP_DIR/pipeline/dagster.yaml" "$dagster_home/dagster.yaml"

# dagster-dbt loads target/manifest.json at import; only `dagster dev` compiles it, so parse here
log "dbt parse (writes the manifest the Dagster code location needs)"
as_app env DBT_TARGET="${DBT_TARGET:-dev}" TP_GCP_PROJECT="${TP_GCP_PROJECT:-unset}" \
  bash -c "cd '$APP_DIR' && .venv/bin/dbt parse --quiet --project-dir dbt/transitpulse --profiles-dir dbt/transitpulse"

# --- service-account key: must exist, owner transitpulse, mode 600 (contents never printed) ---------
key_ok=true
key_path="${GOOGLE_APPLICATION_CREDENTIALS:-$KEY_FILE}"
if [[ ! -f "$key_path" ]]; then
  warn "key file $key_path is missing: copy it with scp (docs/ORACLE_VM.md, step 3)"
  key_ok=false
else
  mode="$(stat -c '%a' "$key_path")"
  owner="$(stat -c '%U' "$key_path")"
  if [[ "$mode" != "600" || "$owner" != "$APP_USER" ]]; then
    warn "$key_path must be owner $APP_USER, mode 600 (found $owner, $mode). Fix with:"
    warn "  sudo chown $APP_USER:$APP_USER $key_path && sudo chmod 600 $key_path"
    key_ok=false
  fi
fi

# --- systemd units -------------------------------------------------------------------------------------
for unit in "${UNITS[@]}"; do
  install -o root -g root -m 644 "$APP_DIR/deploy/oracle/$unit" "/etc/systemd/system/$unit"
done
systemctl daemon-reload

if [[ "$key_ok" != true ]]; then
  die "units installed but not started: fix the key file above, then re-run this script"
fi

systemctl enable --quiet "${UNITS[@]}"
systemctl restart "${UNITS[@]}"
log "services running:"
systemctl --no-pager --lines=0 status "${UNITS[@]}" || true
log "Dagster UI: ssh -L ${TP_DAGSTER_PORT:-3000}:127.0.0.1:${TP_DAGSTER_PORT:-3000} <vm>, then open http://localhost:${TP_DAGSTER_PORT:-3000}"
