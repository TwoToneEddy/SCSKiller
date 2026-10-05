#!/usr/bin/env bash
set -euo pipefail
SOURCE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname -- "$SOURCE_DIR")"
PYTHON_BIN="${PYTHON:-python3}"
if ! "$PYTHON_BIN" -c 'from PySide6 import QtWidgets' 2>/dev/null; then
    if [[ ! -x "$SOURCE_DIR/.venv/bin/python" ]]; then
        "$PYTHON_BIN" -m venv "$SOURCE_DIR/.venv" || {
            echo 'Install Python venv/pip support (see linux/README.md), then retry.' >&2
            exit 1
        }
    fi
    PYTHON_BIN="$SOURCE_DIR/.venv/bin/python"
    "$PYTHON_BIN" -m pip install -r "$SOURCE_DIR/requirements.txt"
fi
"$PYTHON_BIN" -m compileall -q "$SOURCE_DIR/scskiller_linux"
"$PYTHON_BIN" -m unittest discover -s "$SOURCE_DIR/tests" -v
mkdir -p "$PROJECT_DIR/dist/linux"
"$PYTHON_BIN" "$SOURCE_DIR/package.py" "$PROJECT_DIR/dist/linux/scskiller.pyz"
cat > "$PROJECT_DIR/dist/linux/scskiller" <<'LAUNCHER'
#!/usr/bin/env bash
set -euo pipefail
APP_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON:-python3}"
if ! "$PYTHON_BIN" -c 'from PySide6 import QtWidgets' 2>/dev/null; then
    if [[ -x "$APP_DIR/../../linux/.venv/bin/python" ]]; then
        PYTHON_BIN="$APP_DIR/../../linux/.venv/bin/python"
    else
        echo 'PySide6 is missing. Run ./linux/build.sh first, or install requirements.txt.' >&2
        exit 1
    fi
fi
exec "$PYTHON_BIN" "$APP_DIR/scskiller.pyz" "$@"
LAUNCHER
chmod +x "$PROJECT_DIR/dist/linux/scskiller"
printf '\nBuilt: %s\nRun:   %s\n' "$PROJECT_DIR/dist/linux/scskiller.pyz" "$PROJECT_DIR/dist/linux/scskiller"
