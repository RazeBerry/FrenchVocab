#!/bin/sh
set -eu

if [ "$(id -u)" -ne 0 ]; then
  echo "Run through sudo: sudo /usr/local/sbin/vocabbuilder-cli" >&2
  exit 1
fi

set -a
# The deployment creates this root-owned configuration file.
# shellcheck disable=SC1091
. /etc/vocabbuilder/mobile.env
set +a

PROVIDER=${VOCABBUILDER_PROVIDER:-gemini}
cd /var/lib/vocabbuilder
exec runuser -u vocabbuilder -- env \
  HOME=/var/lib/vocabbuilder \
  VOCABBUILDER_CONFIG_DIR=/var/lib/vocabbuilder \
  VOCABBUILDER_HISTORY_DIR=/var/lib/vocabbuilder/history \
  VOCABBUILDER_SKIP_KEYRING=1 \
  /opt/vocabbuilder/.venv/bin/vocabbuilder \
  --provider "$PROVIDER" \
  "$@"
