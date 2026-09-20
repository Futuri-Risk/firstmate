#!/usr/bin/env bash
# Public fleet command/transport behavior using real Git, tasks-axi and ACPx.
# Usage: bash tests/fm-fleet-cloud.test.sh
# Required tools are explicit: missing dependencies are not a passing suite.
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
for tool in python3 git jq tasks-axi acpx; do
  command -v "$tool" >/dev/null || { echo "required fleet test tool missing: $tool" >&2; exit 1; }
done
python3 "$ROOT/tests/fm-gitea-onboarding.test.py"
python3 "$ROOT/tests/fm-semantic-labels.test.py"
python3 "$ROOT/tests/fm-acpx-worker.test.py"
