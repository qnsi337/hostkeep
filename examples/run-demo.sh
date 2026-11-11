#!/usr/bin/env bash
# Starts Hostkeep on a throw-away copy of examples/demo-ssh — your real
# ~/.ssh/config and ~/.config/hostkeep are not touched.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEMO="$(mktemp -d "${TMPDIR:-/tmp}/hostkeep-demo.XXXXXX")"
cp -r "$ROOT/examples/demo-ssh/." "$DEMO/"
chmod 700 "$DEMO"; find "$DEMO" -type f -exec chmod 600 {} +
# ssh resolves relative Include paths against ~/.ssh — make them absolute for the demo copy
find "$DEMO" -type f -exec sed -i -E "s#^(\s*Include\s+)([^/~])#\1$DEMO/\2#" {} +
echo "Demo config: $DEMO/config"
HOSTKEEP_CONFIG="$DEMO/config" HOSTKEEP_DATA="$DEMO/.hostkeep-data" \
    exec "$ROOT/bin/hostkeep" "$@"
