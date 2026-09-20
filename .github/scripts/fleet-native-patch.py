"""One-time cloud prefactor: apply narrow, assertion-guarded native seams.

This development helper is removed after its generated changes are committed.
It never changes main, user state, credentials or upstream repositories.
"""
from pathlib import Path

changed = set()


def patch(name, old, new):
    path = Path(name)
    text = path.read_text()
    if new in text:
        return
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{name}: expected one prefactor anchor, got {count}: {old[:90]!r}")
    path.write_text(text.replace(old, new, 1))
    changed.add(name)


patch("bin/fm-project-onboard.py", "FM_CHARTER=f", "FM_SECONDMATE_CHARTER=f")
patch("bin/fm-project-onboard.py", "FM_SCOPE=f", "FM_SECONDMATE_SCOPE=f")

patch("bin/fm-spawn.sh", "  opencode) printf '%s'", "  acp:*) printf '%s' 'FM_HOME=__ACPHOME__ python3 __ACPWORKER__ --task __ACPTASK__ --agent __ACPAGENT__ --gen __ACPGEN__ --cwd __WORKTREE__ --brief __BRIEF__ __MODELFLAG____EFFORTFLAG__' ;;\n  opencode) printf '%s'")
patch("bin/fm-spawn.sh", "# muse, gemini, and agy are verified as CREWMATE/SCOUT adapters only.", "# ACPx is a worker harness; it is deliberately not a primary/Secondmate backend.\ncase \"$HARNESS\" in\nacp:*)\n  # shellcheck source=bin/fm-acpx-lib.sh\n  . \"$SCRIPT_DIR/fm-acpx-lib.sh\"\n  fm_acpx_harness_valid \"$HARNESS\" || { echo 'error: invalid ACP agent name' >&2; exit 1; }\n  [ \"$KIND\" != secondmate ] || { echo 'error: ACPx workers cannot supervise a Secondmate; use OpenCode' >&2; exit 1; }\n  command -v acpx >/dev/null && command -v python3 >/dev/null || { echo 'error: ACPx and Python 3 are required' >&2; exit 1; }\n  ;;\nesac\n\n# muse, gemini, and agy are verified as CREWMATE/SCOUT adapters only.")
patch("bin/fm-spawn.sh", "claude | codex | opencode | pi | pi-signed | grok | kimi | cursor | gemini | muse | rovo | omp | agy)\n    printf -- '--model", "claude | codex | opencode | pi | pi-signed | grok | kimi | cursor | gemini | muse | rovo | omp | agy | acp:*)\n    printf -- '--model")
patch("bin/fm-spawn.sh", "effort_flag_for_harness() {\n  local harness=$1 effort=$2 model=${3:-}\n  [ -n \"$effort\" ] && [ \"$effort\" != default ] || return 0\n  case \"$harness\" in", "effort_flag_for_harness() {\n  local harness=$1 effort=$2 model=${3:-}\n  [ -n \"$effort\" ] && [ \"$effort\" != default ] || return 0\n  case \"$harness\" in\n  acp:*) printf -- '--effort %s ' \"$(shell_quote \"$effort\")\" ;; ")
patch("bin/fm-spawn.sh", "  claude* | opencode* | pi | pi-signed | omp)\n    BUSY_GEN=", "  claude* | opencode* | pi | pi-signed | omp | acp:*)\n    BUSY_GEN=")
patch("bin/fm-spawn.sh", "LAUNCH=${LAUNCH//__WORKTREE__/$sq_worktree}", "case \"$HARNESS\" in\nacp:*)\n  LAUNCH=${LAUNCH//__ACPHOME__/\"$(shell_quote \"$FM_HOME\")\"}\n  LAUNCH=${LAUNCH//__ACPWORKER__/\"$(shell_quote \"$SCRIPT_DIR/fm-acpx-worker.py\")\"}\n  LAUNCH=${LAUNCH//__ACPTASK__/\"$(shell_quote \"$ID\")\"}\n  LAUNCH=${LAUNCH//__ACPAGENT__/\"$(shell_quote \"${HARNESS#acp:}\")\"}\n  LAUNCH=${LAUNCH//__ACPGEN__/\"$(shell_quote \"$BUSY_GEN\")\"}\n  ;;\nesac\nLAUNCH=${LAUNCH//__WORKTREE__/$sq_worktree}")

patch("bin/fm-control-lib.sh", "# The complete control-plane verb allowlist, one per line.", "# shellcheck source=bin/fm-acpx-lib.sh\n. \"$(dirname -- \"${BASH_SOURCE[0]}\")/fm-acpx-lib.sh\"\n\n# The complete control-plane verb allowlist, one per line.")
patch("bin/fm-control-lib.sh", "printf '%s\\n' claude codex opencode pi pi-signed grok kimi cursor gemini muse rovo omp agy", "printf '%s\\n' claude codex opencode pi pi-signed grok kimi cursor gemini muse rovo omp agy acpx")
patch("bin/fm-control-lib.sh", "fm_control_harness_supported() {  # <harness>\n  local harness", "fm_control_harness_supported() {  # <harness>\n  case \"${1:-}\" in acp:*) fm_acpx_harness_valid \"$1\"; return ;; esac\n  local harness")
patch("bin/fm-control-lib.sh", "    pi) printf 'pi' ;;", "    acpx) printf 'acpx' ;;\n    acp:*) fm_acpx_harness_valid \"$1\" || return 1; printf 'acpx' ;;\n    pi) printf 'pi' ;;")
patch("bin/fm-control-lib.sh", "muse|gemini|rovo|agy) [ \"$kind\" != secondmate ]", "muse|gemini|rovo|agy|acpx|acp:*) [ \"$kind\" != secondmate ]")
patch("bin/fm-control-lib.sh", "    grok) printf 'C-c' ;;", "    grok|acpx) printf 'C-c' ;;")
patch("bin/fm-control-lib.sh", "claude|codex|pi|pi-signed|omp|grok|kimi|cursor|gemini|muse|rovo|agy) printf '1'", "claude|codex|pi|pi-signed|omp|grok|kimi|cursor|gemini|muse|rovo|agy|acpx) printf '1'")
patch("bin/fm-control-lib.sh", "claude|codex|opencode|pi|pi-signed|omp|grok|kimi|cursor|gemini|rovo|agy) ;;", "claude|codex|opencode|pi|pi-signed|omp|grok|kimi|cursor|gemini|rovo|agy|acpx) ;;")
patch("bin/fm-control-lib.sh", "claude|codex|opencode|pi|pi-signed|omp|grok|kimi|cursor|gemini|rovo|agy) printf 'none'", "claude|codex|opencode|pi|pi-signed|omp|grok|kimi|cursor|gemini|rovo|agy|acpx) printf 'none'")
patch("bin/fm-control-lib.sh", "claude|opencode|grok|kimi|cursor|muse|rovo) printf '/exit'", "claude|opencode|grok|kimi|cursor|muse|rovo|acpx) printf '/exit'")

patch("bin/fm-busy-lib.sh", "    opencode*) adapter=opencode-plugin ;;", "    acp:*) adapter=acpx-bridge ;;\n    opencode*) adapter=opencode-plugin ;;")
patch("bin/fm-agent-process-lib.sh", "# fm_agent_process_classify_name: the single owner", "# shellcheck source=bin/fm-acpx-lib.sh\n. \"$(dirname -- \"${BASH_SOURCE[0]}\")/fm-acpx-lib.sh\"\n\n# fm_agent_process_classify_name: the single owner")
patch("bin/fm-agent-process-lib.sh", "  if [ -n \"$pid\" ] && fm_gemini_pid_is_gemini \"$pid\"; then", "  if [ -n \"$pid\" ] && fm_acpx_pid_matches \"$pid\"; then\n    printf 'agent'\n    return 0\n  fi\n  if [ -n \"$pid\" ] && fm_gemini_pid_is_gemini \"$pid\"; then")
patch("bin/fm-teardown.sh", "if [ \"$KIND\" != secondmate ] && teardown_owns_worktree; then\n  conclude_task_no_mistakes_run", "if [ \"$KIND\" != secondmate ]; then\n  # Every unlanded-work guard above has passed before an ACP session is closed.\n  # shellcheck source=bin/fm-acpx-lib.sh\n  . \"$SCRIPT_DIR/fm-acpx-lib.sh\"\n  fm_acpx_close_task \"$FM_HOME\" \"$ID\" || { echo 'error: ACP session could not be closed; preserving task work' >&2; exit 1; }\nfi\nif [ \"$KIND\" != secondmate ] && teardown_owns_worktree; then\n  conclude_task_no_mistakes_run")

resolver = Path("bin/fm-dispatch-resolve.sh")
text = resolver.read_text()
old = 'def verified($h): $verified_harnesses | index($h);'
new = 'def verified($h): ($h | test("^acp:[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")) or ($verified_harnesses | index($h));'
patch(str(resolver), old, new)
print("Applied native seams:", ", ".join(sorted(changed)))
