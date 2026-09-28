#!/bin/sh
# Schedule a daily copy of the VM's newest data archive onto this Mac.
set -eu

CONFIG_ROOT=${XDG_CONFIG_HOME:-"$HOME/.config"}
LAUNCHER_CONFIG=${VOCABBUILDER_LAUNCHER_CONFIG:-"$CONFIG_ROOT/vocabbuilder/remote.env"}
if [ -r "$LAUNCHER_CONFIG" ]; then
  # shellcheck disable=SC1090
  . "$LAUNCHER_CONFIG"
fi

SCRIPT_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(CDPATH='' cd -- "$SCRIPT_DIR/../.." && pwd)
LABEL=com.vocabbuilder.backup-pull
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/Library/Logs/vocabbuilder-backup-pull.log"

# launchd starts jobs with a bare PATH and no Tailscale CLI, so the interpreter
# and the private HTTPS name are resolved once here, where both are available.
PYTHON=$(PYTHONPATH="$PROJECT_ROOT" "${VOCABBUILDER_LOCAL_PYTHON:-python3}" -c \
  'import sys, vocab_builder.cli.backup_pull; print(sys.executable)')
REMOTE_URL=$(PYTHONPATH="$PROJECT_ROOT" "$PYTHON" -c \
  'import sys; from vocab_builder.cli.remote_client import resolve_base_url; print(resolve_base_url(sys.argv[1]))' \
  "${VOCABBUILDER_REMOTE_HOST:-vocabbuilder-mobile}")

mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PYTHON</string>
    <string>-m</string>
    <string>vocab_builder.cli.backup_pull</string>
    <string>--remote-url</string>
    <string>$REMOTE_URL</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict><key>PYTHONPATH</key><string>$PROJECT_ROOT</string></dict>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>12</integer><key>Minute</key><integer>30</integer></dict>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict>
</plist>
PLIST

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "Installed $PLIST; runs daily at 12:30 and now. Log: $LOG"
