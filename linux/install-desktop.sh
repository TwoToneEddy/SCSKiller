#!/usr/bin/env bash
set -euo pipefail
SOURCE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
"$SOURCE_DIR/build.sh"
python3 - "$SOURCE_DIR" <<'PY'
import os
import sys
from pathlib import Path
source = Path(sys.argv[1])
root = Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share'))
applications = root / 'applications'
applications.mkdir(parents=True, exist_ok=True)
# Desktop Entry quoted arguments need special escaping (including literal percent).
launcher = str(source.parent / 'dist/linux/scskiller')
launcher = launcher.replace('\\', '\\\\').replace('"', '\\"').replace('`', '\\`').replace('$', '\\$').replace('%', '%%')
icon = source / 'scskiller_linux/logo.png'
(applications / 'scskiller.desktop').write_text(f'''[Desktop Entry]
Type=Application
Name=SCSKiller
Comment=Compile recorded Vulkan pipelines before playing
Exec="{launcher}"
Icon={icon}
Terminal=false
Categories=Game;Utility;
StartupWMClass=SCSKiller
''')
print('Installed menu entry:', applications / 'scskiller.desktop')
PY
