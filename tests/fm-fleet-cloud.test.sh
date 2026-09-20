#!/usr/bin/env bash
# Public fleet behavior using real Git, tasks-axi, ACPx and native FirstMate.
# Usage: bash tests/fm-fleet-cloud.test.sh
# Required tools are explicit: missing dependencies are not a passing suite.
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
for tool in python3 git jq tasks-axi acpx openssl; do
  command -v "$tool" >/dev/null || { echo "required fleet test tool missing: $tool" >&2; exit 1; }
done
failed=0
for suite in fm-gitea-onboarding fm-semantic-labels fm-acpx-worker fm-captain-email fm-gitea-pr; do
  python3 "$ROOT/tests/$suite.test.py" || failed=1
done
exit "$failed"
