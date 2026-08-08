#!/bin/sh
set -eu

if [ "$(id -u)" -ne 0 ]; then
  echo "Run this installer with sudo." >&2
  exit 1
fi

SCRIPT_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
SOURCE_DIR=$(CDPATH='' cd -- "$SCRIPT_DIR/../.." && pwd)
APP_DIR=/opt/vocabbuilder
DATA_DIR=/var/lib/vocabbuilder
CONFIG_DIR=/etc/vocabbuilder

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y python3-venv rsync util-linux

if ! id vocabbuilder >/dev/null 2>&1; then
  useradd --system --home-dir "$DATA_DIR" --create-home --shell /usr/sbin/nologin vocabbuilder
fi

install -d -m 0755 -o root -g root "$APP_DIR"
install -d -m 0700 -o vocabbuilder -g vocabbuilder \
  "$DATA_DIR" \
  "$DATA_DIR/history" \
  "$DATA_DIR/exports" \
  "$DATA_DIR/backups"
install -d -m 0755 -o root -g root "$CONFIG_DIR"

rsync -a --delete --chown=root:root \
  --exclude .git \
  --exclude .venv \
  --exclude '*.tex' \
  --exclude '*.apkg' \
  --exclude '*.pdf' \
  --exclude '__pycache__' \
  "$SOURCE_DIR/" "$APP_DIR/"

# Archives created on macOS can carry AppleDouble ``._*`` sidecars. They are
# not application files and can make Python's source scanners report null-byte
# syntax errors after a transfer to Linux.
find "$APP_DIR" -type f -name '._*' -delete

# Archive mode deliberately preserves source attributes, including those on
# the source directory itself. Reassert the executable application boundary so
# a root-only staging directory cannot make the installed service unreachable.
chmod 0755 "$APP_DIR"

python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/python" -m pip install --upgrade pip
"$APP_DIR/.venv/bin/python" -m pip install "${APP_DIR}[mobile]"

install -m 0644 "$APP_DIR/deploy/vocabbuilder-mobile.service" /etc/systemd/system/vocabbuilder-mobile.service
install -m 0644 "$APP_DIR/deploy/vocabbuilder-backup.service" /etc/systemd/system/vocabbuilder-backup.service
install -m 0644 "$APP_DIR/deploy/vocabbuilder-backup.timer" /etc/systemd/system/vocabbuilder-backup.timer
install -m 0755 "$APP_DIR/scripts/deploy/run_remote_cli.sh" /usr/local/sbin/vocabbuilder-cli

if [ ! -e "$CONFIG_DIR/mobile.env" ]; then
  install -m 0600 -o root -g root /dev/null "$CONFIG_DIR/mobile.env"
  printf '%s\n' \
    '# Tailscale identity and non-secret service settings only.' \
    '# VOCABBUILDER_ALLOWED_TAILSCALE_USER=you@example.com' \
    > "$CONFIG_DIR/mobile.env"
fi

# Early installations kept provider keys in the root-owned systemd environment
# file. Move each one into the service user's normal config file once, so a key
# changed through the private web UI remains authoritative after a restart.
# The root-owned file continues to hold only identity and non-secret settings.
CREDENTIAL_FILE="$DATA_DIR/.env"
if grep -Eq '^(GEMINI_API_KEY|ANTHROPIC_API_KEY)=' "$CONFIG_DIR/mobile.env"; then
  if [ ! -e "$CREDENTIAL_FILE" ]; then
    install -m 0600 -o vocabbuilder -g vocabbuilder /dev/null "$CREDENTIAL_FILE"
  fi
  for variable in GEMINI_API_KEY ANTHROPIC_API_KEY; do
    if ! grep -q "^${variable}=" "$CREDENTIAL_FILE"; then
      grep -m 1 "^${variable}=" "$CONFIG_DIR/mobile.env" >> "$CREDENTIAL_FILE" || true
    fi
  done
  chown vocabbuilder:vocabbuilder "$CREDENTIAL_FILE"
  chmod 0600 "$CREDENTIAL_FILE"

  filtered_env=$(mktemp "$CONFIG_DIR/.mobile.env.XXXXXX")
  grep -Ev '^(GEMINI_API_KEY|ANTHROPIC_API_KEY)=' \
    "$CONFIG_DIR/mobile.env" > "$filtered_env" || true
  chown root:root "$filtered_env"
  chmod 0600 "$filtered_env"
  mv -f "$filtered_env" "$CONFIG_DIR/mobile.env"
fi

systemctl daemon-reload
systemctl enable vocabbuilder-mobile.service vocabbuilder-backup.timer
systemctl start vocabbuilder-backup.timer

if [ -f "$CREDENTIAL_FILE" ] && \
   grep -Eq '^(GEMINI_API_KEY|ANTHROPIC_API_KEY)=.+' "$CREDENTIAL_FILE"; then
  systemctl restart vocabbuilder-mobile.service
else
  echo "Installed, but not started: configure a provider in $CREDENTIAL_FILE first." >&2
fi
