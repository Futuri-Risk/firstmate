#!/usr/bin/env bash
# Native process-event adapter for upstream synchronization.
# Usage: fm-procevent-upstream.sh poll <project> <period-seconds>
#        fm-procevent-upstream.sh classify|terminal|silent <captured-result>
# FirstMate's existing source runner owns the background process and restarts.
# It does not bypass task, worktree, validation or captain authority boundaries.
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
case "${1:-}" in
  poll)
    project=${2:?project required}
    period=${3:?period required}
    [[ $project =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$ ]] || exit 2
    [[ $period =~ ^[0-9]+$ ]] && [ "$period" -ge 60 ] && [ "$period" -le 86400 ] || exit 2
    sleep "$period"
    result=$(mktemp)
    trap 'rm -f -- "$result"' EXIT
    if python3 "$ROOT/fm-upstream-sync.py" once --project "$project" > "$result"; then
      if jq -e '.state == "queued" and .new_work == true' "$result" >/dev/null; then
        printf 'status: queued\n'
      else
        printf 'status: current\n'
      fi
      printf 'output:\n'
      cat "$result"
    else
      printf 'status: stale\noutput:\nUpstream synchronization failed; cached source remains available but is not fresh.\n'
    fi
    ;;
  classify)
    awk '/^output:/{exit} /^status:/{sub(/^status: */, ""); print; exit}' "${2:?captured result required}"
    ;;
  terminal)
    # Recurring until explicitly unregistered through the native source runner.
    exit 1
    ;;
  silent)
    # Queued work already wakes the owning Secondmate with its stable task ID.
    grep -Eq '^status: (current|queued)$' "${2:?captured result required}"
    ;;
  *) printf 'usage: %s poll <project> <seconds> | classify|terminal|silent <result>\n' "$0" >&2; exit 2 ;;
esac
