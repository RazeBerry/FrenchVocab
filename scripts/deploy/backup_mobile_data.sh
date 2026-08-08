#!/bin/sh
set -eu

DATA_DIR=${VOCABBUILDER_DATA_DIR:-/var/lib/vocabbuilder}
BACKUP_DIR="$DATA_DIR/backups"
LOCK_FILE="$DATA_DIR/.vocabbuilder.lock"
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
TARGET="$BACKUP_DIR/vocabbuilder-$STAMP.tar.gz"

install -d -m 0700 "$BACKUP_DIR"
# Use the same catalog lock as every Python mutation. The archive therefore
# represents one coherent point between logical saves rather than a mixture of
# vocabulary, history, and Anki state from different moments.
exec 9>>"$LOCK_FILE"
flock -x 9
tar \
  --exclude='./backups' \
  --exclude='*.lock' \
  -C "$DATA_DIR" \
  -czf "$TARGET.tmp" .
mv "$TARGET.tmp" "$TARGET"
find "$BACKUP_DIR" -type f -name 'vocabbuilder-*.tar.gz' -mtime +30 -delete
