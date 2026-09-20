"""Temporary assertion-guarded cloud edit helper; removed before merge."""
from pathlib import Path

changed = []
def patch(name, old, new, count=1):
    path = Path(name)
    text = path.read_text()
    if new in text:
        return
    if text.count(old) != count:
        raise RuntimeError(f"{name}: expected {count} anchors: {old[:80]!r}; found {text.count(old)}")
    path.write_text(text.replace(old, new))
    changed.append(name)

patch("bin/fm_forge.py", "error = result.stderr[-2000:]", "error = (result.stderr or result.stdout)[-2000:]")
patch("bin/fm_forge.py", "if not suffix.startswith(\"/\") or \"..\" in suffix.split(\"/\"):", "if (suffix and not suffix.startswith(\"/\")) or \"..\" in suffix.split(\"/\"):")
patch("bin/fm_forge.py", "result = self.request(\"GET\", \"/\")", "result = self.request(\"GET\", \"\")")
patch("bin/fm-project-onboard.py", 'run("tasks-axi", "add", "--id", task, "--title", title, "--body", body,', 'run("tasks-axi", "add", task, title, "--body-file", str(body_path),')
patch("bin/fm-project-onboard.py", '                run("tasks-axi", "add", task, title, "--body-file", str(body_path),', '                body_path = safe_child(child, f"data/gitea-imports/{task}.md")\n                atomic_text(body_path, body)\n                run("tasks-axi", "add", task, title, "--body-file", str(body_path),')
patch("bin/fm-captain-email.py", "        task = identifier(args.task, \"task ID\")", "        if (home / \".fm-secondmate-parent\").exists():\n            raise ForgeError(\"Secondmate outcomes must use the native parent channel; send captain mail from the parent home\")\n        task = identifier(args.task, \"task ID\")")
patch("tests/fm-captain-email.test.py", "            def handle(self):\n                self.wfile.write", "            def finish(self):\n                try:\n                    super().finish()\n                finally:\n                    self.request.close()\n            def handle(self):\n                self.wfile.write")

patch("bin/fm-gitea-pr.py", 'choices=("identity", "snapshot", "verify", "merge")', 'choices=("identity", "record", "snapshot", "verify", "merge")')
patch("bin/fm-gitea-pr.py", '        elif args.command == "snapshot":', '        elif args.command == "record":\n            value = snapshot(api, identity, checks=False)\n        elif args.command == "snapshot":')
patch("bin/fm-pr-lib.sh", "FM_PR_POLL_RETIREMENT_REJECTED=\n", '''FM_PR_POLL_RETIREMENT_REJECTED=
# A tracked helper path, never loaded from a mutable PR sidecar.
FM_PR_GITEA_HELPER="$(cd "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/fm-gitea-pr.py"
export FM_PR_GITEA_HELPER

fm_pr_gitea_read_record() {  # <canonical-url>
  local record
  record=$(python3 "$FM_PR_GITEA_HELPER" record --url "$1") || return 1
  FM_PR_RECORD_STATE=$(printf '%s' "$record" | jq -er '.state') || return 1
  FM_PR_RECORD_MERGED=$(printf '%s' "$record" | jq -r '.merged') || return 1
}
''')
patch("bin/fm-pr-lib.sh", '  # The path class contains "/" and "-", so this match is greedy to the last', '''  # Gitea is accepted only through explicit private-home repository bindings.
  # An arbitrary self-hosted URL cannot redirect the configured Gitea token.
  case "$raw" in
    */pulls/*)
      local gitea_identity
      gitea_identity=$(python3 "$FM_PR_GITEA_HELPER" identity --url "$raw" 2>/dev/null) || return 1
      gitea_identity=$(printf '%s' "$gitea_identity" | jq -er '[.host,.path,(.number|tostring),.owner,.repo] | @tsv') || return 1
      IFS=$'\t' read -r FM_PR_HOST FM_PR_PATH FM_PR_NUMBER FM_PR_OWNER FM_PR_REPO <<< "$gitea_identity"
      FM_PR_PROVIDER=gitea
      FM_PR_URL=$raw
      return 0
      ;;
  esac
  # The path class contains "/" and "-", so this match is greedy to the last''')
patch("bin/fm-pr-check.sh", 'PR_HEAD=\nif [ "$PROVIDER" = github ]; then', '''PR_HEAD=
if [ "$PROVIDER" = gitea ]; then
  PR_HEAD=$(python3 "$SCRIPT_DIR/fm-gitea-pr.py" record --url "$URL" | jq -er '.head') || exit 1
elif [ "$PROVIDER" = github ]; then''')
patch("bin/fm-pr-poll.sh", '  gitlab)\n', '''  gitea)
    helper=${FM_PR_GITEA_HELPER:-}
    if [ -z "$helper" ]; then
      helper="$(dirname -- "$0")/fm-gitea-pr.py"
    fi
    [ -f "$helper" ] || exit 0
    record=$(python3 "$helper" record --url "$url" 2>/dev/null) || exit 0
    printf '%s' "$record" | jq -e --arg host "$host" --arg path "$path" --arg number "$number" \
      '.host == $host and .path == $path and (.number|tostring) == $number and .merged == true and .state == "closed"' >/dev/null 2>&1 || exit 0
    printf 'merged\\n'
    ;;
  gitlab)
''')
patch("bin/fm-pr-merge.sh", 'RECORDED_HEAD=\nif [ "$PROVIDER" = gitlab ]; then', 'RECORDED_HEAD=\nif [ "$PROVIDER" = gitlab ] || [ "$PROVIDER" = gitea ]; then')
patch("bin/fm-pr-merge.sh", 'case "$PROVIDER" in\n  github)', '''case "$PROVIDER" in
  gitea)
    [ -n "$RECORDED_HEAD" ] || { echo 'error: Gitea merge requires the previously recorded validated head' >&2; exit 1; }
    gitea_method=squash
    for gitea_arg in "$@"; do
      case "$gitea_arg" in
        --squash) gitea_method=squash ;;
        --merge) gitea_method=merge ;;
        --rebase) gitea_method=rebase ;;
        *) echo 'error: unsupported Gitea merge argument; no protection bypass is implemented' >&2; exit 1 ;;
      esac
    done
    gitea_record=$(python3 "$SCRIPT_DIR/fm-gitea-pr.py" verify --url "$URL" --expected-head "$RECORDED_HEAD") || exit 1
    FM_PR_MERGE_HEAD=$(printf '%s' "$gitea_record" | jq -er '.head') || exit 1
    hold_away_record_for_merge || exit 1
    away_status=0
    require_current_away_authority || away_status=$?
    [ "$away_status" -eq 0 ] || exit "$away_status"
    python3 "$SCRIPT_DIR/fm-gitea-pr.py" merge --url "$URL" --expected-head "$FM_PR_MERGE_HEAD" --method "$gitea_method" || exit 1
    persist_accepted_merge_authority || exit 1
    fm_afk_contract_lock_release || true
    fm_lock_release "$MERGE_CONTROL_LOCK" || true
    MERGE_CONTROL_LOCK=
    ;;
  github)''')

# Keep the reference backend. Only its OS-specific foreground lookup changes.
patch("bin/backends/tmux.sh", 'LC_ALL=C ps -t "${tty#/dev/}" -o pid=,pgid=,tpgid=,comm= 2>/dev/null \\', 'fm_backend_tmux_foreground_rows "$tty" \\', count=4)
patch("bin/backends/tmux.sh", 'fm_backend_tmux_foreground_comms() {  # <target>', '''fm_backend_tmux_foreground_rows() {  # <tty>
  case "$(uname -s)" in
    MSYS*|CYGWIN*) python3 "$FM_BACKEND_LIB_DIR/fm-msys-foreground.py" "$1" ;;
    *) LC_ALL=C ps -t "${1#/dev/}" -o pid=,pgid=,tpgid=,comm= 2>/dev/null ;;
  esac
}

fm_backend_tmux_foreground_comms() {  # <target>''')
patch("bin/backends/tmux.sh", '    if fm_gemini_pid_is_gemini "$pid"; then', '    if fm_gemini_pid_is_gemini "$pid" || fm_acpx_pid_matches "$pid"; then')
patch("bin/backends/tmux.sh", '        args=${args#"${args%%[![:space:]]*}"}\n        argv0=${args%%[[:space:]]*}', '''        case "$(uname -s)" in
          MSYS*|CYGWIN*)
            argv0=
            IFS= read -r -d '' argv0 < "/proc/$pid/cmdline" || true
            ;;
          *)
            args=${args#"${args%%[![:space:]]*}"}
            argv0=${args%%[[:space:]]*}
            ;;
        esac''')
patch("bin/backends/tmux.sh", '  case "$comm" in\n    \'\') printf \'unreadable\'; return 0 ;;', '''  case "$(uname -s)" in
    MSYS*|CYGWIN*) printf 'unreadable'; return 0 ;;
  esac
  case "$comm" in
    '') printf 'unreadable'; return 0 ;;''')
print("Changed:", ", ".join(changed))
