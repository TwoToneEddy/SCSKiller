"""Build an executable Python archive; Qt stays in the system/venv installation."""
from pathlib import Path
import sys
import tempfile
import shutil
import zipapp

source = Path(__file__).resolve().parent
with tempfile.TemporaryDirectory(prefix='scskiller-build-') as temp:
    root = Path(temp)
    shutil.copytree(source / 'scskiller_linux', root / 'scskiller_linux',
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    shutil.copy(source.parent / 'LICENSE', root / 'LICENSE')
    (root / '__main__.py').write_text('from scskiller_linux.__main__ import main\nraise SystemExit(main())\n')
    zipapp.create_archive(root, sys.argv[1], interpreter='/usr/bin/env python3', compressed=True)
