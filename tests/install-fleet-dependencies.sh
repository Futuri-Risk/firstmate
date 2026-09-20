#!/usr/bin/env bash
# Build public, pinned test dependencies in an explicitly selected directory.
# Usage: bash tests/install-fleet-dependencies.sh /absolute/test-prefix
# Requires Node 22, Go 1.25.5, npm, pnpm 11.26.0 and Git. Never installs a
# production service or runs the ZCode bridge's update-notification build hook.
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
PREFIX=${1:?absolute test prefix required}
case "$PREFIX" in /*) ;; *) echo 'test prefix must be absolute' >&2; exit 2 ;; esac
[ "$PREFIX" != / ] && [ ! -L "$PREFIX" ] || exit 2
mkdir -p "$PREFIX/tools" "$PREFIX/sources"
clone_pin() {
  local name=$1 commit=$2 target="$PREFIX/sources/$1"
  if [ -d "$target/.git" ]; then
    [ "$(git -C "$target" rev-parse HEAD)" = "$commit" ] || { echo "cached $name source differs" >&2; exit 1; }
  else
    git init -q "$target"
    git -C "$target" remote add origin "https://github.com/Futuri-Risk/$name.git"
    git -C "$target" fetch -q --depth=1 origin "$commit"
    git -C "$target" checkout -q --detach FETCH_HEAD
  fi
  printf '%s %s\n' "$name" "$commit" >> "$PREFIX/source-pins.txt"
}
: > "$PREFIX/source-pins.txt"
clone_pin acpx 323191a80ff6dd72e51eb8636a0025d321415d96
pnpm --dir "$PREFIX/sources/acpx" install --frozen-lockfile --ignore-scripts
pnpm --dir "$PREFIX/sources/acpx" run build
chmod +x "$PREFIX/sources/acpx/dist/cli.js"
ln -sfn "$PREFIX/sources/acpx/dist/cli.js" "$PREFIX/tools/acpx"
npm install --prefix "$PREFIX/tasks" --save-exact --ignore-scripts tasks-axi@0.2.4
clone_pin treehouse 99f4db2bbeececc1e6f136a88f79002e5a707174
(cd "$PREFIX/sources/treehouse" && CGO_ENABLED=0 go build -o "$PREFIX/tools/treehouse" .)
clone_pin no-mistakes 2c3a3013d2a221f4549d7fa7c458a11ef88023e5
(cd "$PREFIX/sources/no-mistakes" && CGO_ENABLED=0 go build -o "$PREFIX/tools/no-mistakes" ./cmd/no-mistakes && CGO_ENABLED=0 go build -o "$PREFIX/tools/fakeagent" ./cmd/fakeagent)
clone_pin zcode-acp 6552c7d30554c72e6f69faacbff34d94366d9651
(cd "$PREFIX/sources/zcode-acp" && pnpm install --frozen-lockfile --ignore-scripts && pnpm exec tsc)
"$ROOT/bin/fm-install-shellcheck.sh" "$PREFIX/tools"
"$ROOT/bin/fm-install-actionlint.sh" "$PREFIX/tools"
printf 'tasks-axi 0.2.4\nnode %s\ngo %s\npnpm %s\n' "$(node --version)" "$(go version)" "$(pnpm --version)" >> "$PREFIX/source-pins.txt"
touch "$PREFIX/complete"
