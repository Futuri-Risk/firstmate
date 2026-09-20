#!/usr/bin/env bash
# ACPx harness integration, not a runtime backend.
# Usage: source fm-acpx-lib.sh; fm_acpx_harness_valid acp:<agent>
#        fm_acpx_pid_matches <pid>
#        fm_acpx_close_task <home> <task-id>
# No process is claimed from a substring in a prompt or an unrelated Python
# command. An unreadable argv is unknown, never proof that a process died.

fm_acpx_harness_valid() {
  local target=${1#acp:}
  [[ ${1:-} == acp:* && $target =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$ ]]
}

fm_acpx_pid_matches() {
  local pid=${1:-} arg count=0 executable= script=
  case "$pid" in ''|*[!0-9]*) return 1 ;; esac
  [ -r "/proc/$pid/cmdline" ] || return 1
  while IFS= read -r -d '' arg; do
    case "$count" in
      0) executable=${arg##*/} ;;
      1) script=$arg; break ;;
    esac
    count=$((count + 1))
  done < "/proc/$pid/cmdline"
  case "$executable" in python|python3|python3.[0-9]|python3.[0-9][0-9]) ;; *) return 1 ;; esac
  [ -f "$script" ] || return 1
  [ "$script" -ef "$(dirname -- "${BASH_SOURCE[0]}")/fm-acpx-worker.py" ]
}

fm_acpx_close_task() {
  local home=$1 task=$2 meta harness gen worktree
  meta="$home/state/$task.meta"
  [ -f "$meta" ] || return 0
  harness=$(sed -n 's/^harness=//p' "$meta")
  case "$harness" in acp:*) ;; *) return 0 ;; esac
  fm_acpx_harness_valid "$harness" || return 1
  gen=$(sed -n 's/^busy_gen=//p' "$meta")
  worktree=$(sed -n 's/^worktree=//p' "$meta")
  [ -n "$gen" ] && [ -n "$worktree" ] || return 1
  FM_HOME="$home" python3 "$(dirname -- "${BASH_SOURCE[0]}")/fm-acpx-worker.py" \
    --task "$task" --gen "$gen" --agent "${harness#acp:}" --cwd "$worktree" --control close >/dev/null
}
