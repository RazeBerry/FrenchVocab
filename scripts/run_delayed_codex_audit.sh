#!/bin/zsh
set -euo pipefail

delay_seconds="${1:-900}"

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
timestamp="$(date +%Y%m%d_%H%M%S)"
log_dir="$repo_root/.codex_audits"
prompt_file="$log_dir/audit_prompt_${timestamp}.txt"
result_file="$log_dir/audit_result_${timestamp}.md"
runner_log="$log_dir/audit_runner_${timestamp}.log"
job_script="$log_dir/audit_job_${timestamp}.sh"

mkdir -p "$log_dir"

cat > "$prompt_file" <<'EOF'
Audit the current progress on the VocabBuilder rename + PyPI packaging implementation in this repository.

Focus on:
- broken or partially migrated import paths
- package layout mistakes
- backward-compatibility regressions
- env/config/keyring migration risks
- PyPI packaging metadata gaps
- whether the code would work from an installed wheel rather than only from a git checkout

Review mindset:
- findings first, ordered by severity
- include concrete file references
- mention verification gaps
EOF

cat > "$job_script" <<EOF
#!/bin/zsh
set -euo pipefail
sleep "$delay_seconds"
cd "$repo_root"
codex exec \\
  --full-auto \\
  --sandbox workspace-write \\
  --output-last-message "$result_file" \\
  -C "$repo_root" \\
  "\$(cat "$prompt_file")"
EOF

chmod +x "$job_script"

nohup /bin/zsh "$job_script" >>"$runner_log" 2>&1 </dev/null &

job_pid=$!

printf 'Scheduled delayed Codex audit.\n'
printf 'PID: %s\n' "$job_pid"
printf 'Repo: %s\n' "$repo_root"
printf 'Delay seconds: %s\n' "$delay_seconds"
printf 'Prompt file: %s\n' "$prompt_file"
printf 'Result file: %s\n' "$result_file"
printf 'Runner log: %s\n' "$runner_log"
printf 'Job script: %s\n' "$job_script"
