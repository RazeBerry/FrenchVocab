#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(CDPATH='' cd -- "$SCRIPT_DIR/../.." && pwd)
cd "$PROJECT_ROOT"

# A deploy command that accepts an explicit remote commit could omit these
# checks. This HEAD-based front door requires independent local and remote Git
# evidence so unpublished or edited source cannot reach the VM.
if [[ -n $(git status --porcelain --untracked-files=all) ]]; then
  echo 'Commit or remove local changes before deploying.' >&2
  exit 1
fi

branch=$(git symbolic-ref --quiet --short HEAD) || {
  echo 'Deploy from a branch with a configured upstream.' >&2
  exit 1
}
remote=$(git config --get "branch.$branch.remote") || true
merge_ref=$(git config --get "branch.$branch.merge") || true
if [[ -z $remote || $remote == . || $merge_ref != refs/heads/* ]]; then
  echo 'The current branch needs a remote upstream branch.' >&2
  exit 1
fi

commit=$(git rev-parse --verify HEAD)
remote_commit=$(git ls-remote --exit-code "$remote" "$merge_ref" | awk -v ref="$merge_ref" '$2 == ref { print $1 }')
if [[ $commit != "$remote_commit" ]]; then
  echo "HEAD is not the pushed tip of $remote/$merge_ref; push it before deploying." >&2
  exit 1
fi

CONFIG_ROOT=${XDG_CONFIG_HOME:-"$HOME/.config"}
LAUNCHER_CONFIG=${VOCABBUILDER_LAUNCHER_CONFIG:-"$CONFIG_ROOT/vocabbuilder/remote.env"}
if [[ -r $LAUNCHER_CONFIG ]]; then
  # The same private identity source used by scripts/macos/vocab.
  # shellcheck disable=SC1090
  . "$LAUNCHER_CONFIG"
fi
REMOTE_HOST=${VOCABBUILDER_REMOTE_HOST:-vocabbuilder-mobile}
REMOTE_USER=${VOCABBUILDER_REMOTE_USER:-}
if [[ ! $REMOTE_USER =~ ^[a-zA-Z_][a-zA-Z0-9_.-]*$ || ! $REMOTE_HOST =~ ^[a-zA-Z0-9][a-zA-Z0-9.-]*$ ]]; then
  echo "Set VOCABBUILDER_REMOTE_USER and a valid VOCABBUILDER_REMOTE_HOST in $LAUNCHER_CONFIG." >&2
  exit 2
fi
target="$REMOTE_USER@$REMOTE_HOST"

# git archive streams from the local object store and needs no local staging copy.
# The remote peak allows for staging, rsync, and pip's temporary build files.
logical_bytes=$(git ls-tree -r -l "$commit" | awk '$4 ~ /^[0-9]+$/ { total += $4 } END { printf "%.0f", total }')
estimated_kib=$(( (logical_bytes * 4 + 1023) / 1024 + 262144 ))
printf 'Deploying pushed commit %s to %s\n' "$commit" "$target"
printf 'Tracked source logical size: %.2f MiB. Estimated peak additional remote disk: %.2f GiB (four source copies plus 256 MiB build allowance).\n' \
  "$(awk -v n="$logical_bytes" 'BEGIN { print n / 1048576 }')" \
  "$(awk -v n="$estimated_kib" 'BEGIN { print n / 1048576 }')"
printf 'Local free space (archive is streamed):\n'
df -Pk .
remote_df=$(tailscale ssh "$target" 'df -Pk /tmp /opt/vocabbuilder')
printf 'Remote free space for staging and installation:\n%s\n' "$remote_df"
if ! printf '%s\n' "$remote_df" | awk -v needed="$estimated_kib" \
  'NR > 1 { seen++; if ($4 < needed) short = 1 } END { exit !(seen == 2 && !short) }'; then
  echo 'Remote free space is below the estimated peak deployment allowance.' >&2
  exit 1
fi

remote_command=$(cat <<'REMOTE'
set -eu
stage=$(mktemp -d /tmp/vb-src.XXXXXX)
trap 'rm -rf -- "$stage"' EXIT
tar -x -C "$stage"
sudo -n rsync -a --delete --chown=root:root --exclude .venv "$stage/" /opt/vocabbuilder/
# mktemp makes the staging root private; rsync copies its mode to the app root.
sudo -n chmod 0755 /opt/vocabbuilder
sudo -n /opt/vocabbuilder/.venv/bin/python -m pip install --no-deps /opt/vocabbuilder
sudo -n install -m 0644 /opt/vocabbuilder/deploy/vocabbuilder-mobile.service /etc/systemd/system/vocabbuilder-mobile.service
sudo -n install -m 0644 /opt/vocabbuilder/deploy/vocabbuilder-backup.service /etc/systemd/system/vocabbuilder-backup.service
sudo -n install -m 0644 /opt/vocabbuilder/deploy/vocabbuilder-backup.timer /etc/systemd/system/vocabbuilder-backup.timer
sudo -n install -m 0755 /opt/vocabbuilder/scripts/deploy/run_remote_cli.sh /usr/local/sbin/vocabbuilder-cli
sudo -n /opt/vocabbuilder/.venv/bin/python - <<'PY'
from pathlib import Path
import vocab_builder

source = Path('/opt/vocabbuilder/vocab_builder')
installed = Path(vocab_builder.__file__).resolve().parent
files = [
    path for path in source.rglob('*')
    if path.is_file() and '__pycache__' not in path.parts
]
different = [
    str(path.relative_to(source)) for path in files
    if not (installed / path.relative_to(source)).is_file()
    or path.read_bytes() != (installed / path.relative_to(source)).read_bytes()
]
if different:
    raise SystemExit('Installed package differs from the archived source: ' + ', '.join(different))
print(f'Installed package matches archived source ({len(files)} files): {installed}')
PY
sudo -n systemctl daemon-reload
sudo -n systemctl restart vocabbuilder-mobile.service
sudo -n systemctl is-active --quiet vocabbuilder-mobile.service
sudo -n /opt/vocabbuilder/.venv/bin/python - <<'PY'
from time import sleep
from urllib.error import URLError
from urllib.request import urlopen

for attempt in range(10):
    try:
        with urlopen('http://127.0.0.1:8080/static/styles.css', timeout=2) as response:
            if response.status == 200:
                print('Local HTTP check passed')
                break
    except URLError:
        pass
    sleep(1)
else:
    raise SystemExit('Service did not answer the local HTTP check')
PY
REMOTE
)

git archive --format=tar "$commit" | tailscale ssh "$target" "$remote_command"
printf 'Deployed and verified %s\n' "$commit"
