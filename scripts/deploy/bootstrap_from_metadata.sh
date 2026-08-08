#!/bin/sh
set -eu

# One-time bootstrap for an IPv6-only Compute Engine VM.  The deployment
# archives are delivered through instance metadata because Cloud Shell and IAP
# cannot open an SSH connection to a VM without an internal IPv4 address.

STATE_DIR=/var/lib/vocabbuilder-bootstrap
DONE_MARKER="$STATE_DIR/complete"
METADATA_ROOT=http://metadata.google.internal/computeMetadata/v1/instance/attributes

if [ -e "$DONE_MARKER" ]; then
  echo "VocabBuilder bootstrap already completed."
  exit 0
fi

install -d -m 0700 -o root -g root "$STATE_DIR"
WORK_DIR=$(mktemp -d "$STATE_DIR/work.XXXXXX")
trap 'rm -rf -- "$WORK_DIR"' EXIT HUP INT TERM

metadata() {
  curl --fail --silent --show-error \
    --header 'Metadata-Flavor: Google' \
    "$METADATA_ROOT/$1"
}

verify_archive() {
  archive=$1
  checksum_key=$2
  expected=$(metadata "$checksum_key")
  actual=$(sha256sum "$archive" | awk '{print $1}')
  if [ "$actual" != "$expected" ]; then
    echo "Checksum mismatch for $archive" >&2
    exit 1
  fi
}

echo "Reconstructing deployment archives from instance metadata."
metadata vocabbuilder-code-b64 | base64 --decode >"$WORK_DIR/code.tar.gz"
{
  metadata vocabbuilder-data-b64-00
  metadata vocabbuilder-data-b64-01
} | base64 --decode >"$WORK_DIR/data.tar.gz"

verify_archive "$WORK_DIR/code.tar.gz" vocabbuilder-code-sha256
verify_archive "$WORK_DIR/data.tar.gz" vocabbuilder-data-sha256

install -d -m 0700 "$WORK_DIR/code" "$WORK_DIR/data"
tar -xzf "$WORK_DIR/code.tar.gz" -C "$WORK_DIR/code"
tar -xzf "$WORK_DIR/data.tar.gz" -C "$WORK_DIR/data"

echo "Installing the application and system services."
"$WORK_DIR/code/scripts/deploy/install_mobile_server.sh"

DATA_DIR=/var/lib/vocabbuilder
for filename in \
  FrenchVocab.tex FrenchToEnglish.tex EnglishToFrench.tex exported_words_fr.json \
  GermanVocab.tex GermanToEnglish.tex EnglishToGerman.tex exported_words_de.json \
  EnglishVocab.tex exported_words_en.json
do
  [ -f "$WORK_DIR/data/$filename" ] || continue
  install -m 0600 -o vocabbuilder -g vocabbuilder \
    "$WORK_DIR/data/$filename" "$DATA_DIR/$filename"
done

# The current histories are authoritative; append distinct legacy records so
# no local session history disappears during the cutover.
for language in fr de en; do
  primary="$WORK_DIR/data/history-primary/${language}_translations.jsonl"
  legacy="$WORK_DIR/data/history-legacy/${language}_translations.jsonl"
  [ -f "$primary" ] || continue
  if [ -f "$legacy" ]; then
    awk '!seen[$0]++' "$primary" "$legacy" >"$WORK_DIR/${language}_translations.jsonl"
  else
    awk '!seen[$0]++' "$primary" >"$WORK_DIR/${language}_translations.jsonl"
  fi
  install -m 0600 -o vocabbuilder -g vocabbuilder \
    "$WORK_DIR/${language}_translations.jsonl" \
    "$DATA_DIR/history/${language}_translations.jsonl"
done

tailscale_user=$(metadata vocabbuilder-tailscale-user)
case "$tailscale_user" in
  *[!A-Za-z0-9@._+-]*|'')
    echo "Invalid Tailscale user supplied in instance metadata." >&2
    exit 1
    ;;
esac
printf '%s\n' \
  'VOCABBUILDER_PROVIDER=gemini' \
  "VOCABBUILDER_ALLOWED_TAILSCALE_USER=$tailscale_user" \
  >/etc/vocabbuilder/mobile.env
chmod 0600 /etc/vocabbuilder/mobile.env

# This merely prepares private HTTPS routing.  The app intentionally remains
# stopped until its provider key has been entered directly on the VM.
if command -v tailscale >/dev/null 2>&1; then
  tailscale serve --bg 8080 || \
    echo "Tailscale Serve still needs to be enabled after bootstrap." >&2
fi

touch "$DONE_MARKER"
echo "VocabBuilder bootstrap completed successfully."
