#!/usr/bin/env bash
set -euo pipefail
SOURCE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
APP="$SOURCE_DIR/../dist/linux/scskiller"
if [[ ! -x "$APP" ]]; then
    "$SOURCE_DIR/build.sh"
fi
exec "$APP" "$@"
