#!/bin/sh
# Restore VocabBuilder data from one daily archive: sudo restore_mobile_data.sh ARCHIVE
set -eu

ARCHIVE=${1:?usage: restore_mobile_data.sh ARCHIVE}
DATA_DIR=${VOCABBUILDER_DATA_DIR:-/var/lib/vocabbuilder}
SERVICE=vocabbuilder-mobile.service
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
ASIDE="$DATA_DIR/backups/pre-restore-$STAMP"

# A truncated or corrupt archive fails here, before anything is stopped or moved.
gzip -t "$ARCHIVE"
tar -tzf "$ARCHIVE" >/dev/null

# The service keeps a request journal in memory; replaying it onto restored
# files could reapply saves the archive predates.
systemctl stop "$SERVICE"
exec 9>>"$DATA_DIR/.vocabbuilder.lock"
flock -x 9
install -d -m 0700 "$ASIDE"
echo "Moving the current data aside to $ASIDE"
# Nothing is deleted. The provider key stays where it is: archives never
# carry it, and an older archive's key may since have been rotated.
find "$DATA_DIR" -mindepth 1 -maxdepth 1 \
  ! -name backups ! -name '*.lock' ! -name '.env' \
  -exec mv {} "$ASIDE"/ \;
tar -xzf "$ARCHIVE" -C "$DATA_DIR" --exclude='./.env' --exclude='./.env.*'
exec 9>&-
systemctl start "$SERVICE"
echo "Restored $ARCHIVE"
