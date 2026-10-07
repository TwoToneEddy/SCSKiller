"""Per-game driver and translation-layer shader caches on Linux.

Windows sets one global driver cache size. On Linux each cache is configured
per launch through environment variables, and Steam keeps them per game under
steamapps/shadercache/<appid>. These helpers report where the game's caches
are, how large they are, the size limit their driver applies, and clear the
compiled caches. Steam's Fossilize recordings in the same folder are inputs
for replay and are never cleared.
"""
from __future__ import annotations
from pathlib import Path
import re
import shutil

from . import backend as b
from . import launch_profile as lp

RECORDINGS = 'fozpipelinesv6'


class CacheError(RuntimeError):
    pass


def parse_size(text):
    """Mesa's MESA_SHADER_CACHE_MAX_SIZE syntax: a number with an optional K/M/G suffix; no suffix means KiB."""
    match = re.fullmatch(r'\s*(\d+)\s*([KkMmGg]?)\s*', text or '')
    if not match:
        return None
    return int(match[1]) * {'': 1024, 'k': 1024, 'm': 1024 ** 2, 'g': 1024 ** 3}[match[2].lower()]


def limits(env):
    """Size limit each driver applies to this launch: bytes, None = unlimited, 'default' = driver default."""
    nvidia = 'default'
    if env.get('__GL_SHADER_DISK_CACHE_SKIP_CLEANUP', '') not in ('', '0'):
        nvidia = None   # Steam sets this: the cache is never trimmed
    elif (size := env.get('__GL_SHADER_DISK_CACHE_SIZE', '')).isdigit():
        nvidia = int(size)
    mesa = parse_size(env.get('MESA_SHADER_CACHE_MAX_SIZE')) or 'default'
    return {'nvidia': nvidia, 'mesa': mesa}


def _inside(path, root):
    try:
        return Path(path).resolve().is_relative_to(Path(root).resolve())
    except OSError:
        return False


def parts(game, profile=None):
    """The game's compiled caches: [{name, paths, bytes, clearable, note}].

    Paths come from the saved launch profile when there is one, otherwise from
    Steam's per-game defaults. A path outside the game's own cache folder may be
    shared with other games and is reported but never cleared.
    """
    route = lp.routing(profile) if profile else {'nvidiaPath': None, 'mesaPath': None, 'vkd3dArchive': None}
    own = [game.cache]
    found = []

    def add(name, paths, clearable, note=''):
        paths = [Path(p) for p in paths if Path(p).exists()]
        if paths:
            found.append({'name': name, 'paths': [str(p) for p in paths],
                          'bytes': sum(b.tree_bytes(p) if p.is_dir() else p.stat().st_size for p in paths),
                          'clearable': clearable, 'note': note})

    nvidia = Path(route['nvidiaPath']) if route['nvidiaPath'] else game.cache / 'nvidiav1'
    shared = not any(_inside(nvidia, r) for r in own)
    add('NVIDIA driver cache', [nvidia], not shared,
        'Shared with other applications: not cleared' if shared else '')
    mesa = Path(route['mesaPath']) if route['mesaPath'] else game.cache
    shared = not any(_inside(mesa, r) for r in own)
    # Mesa writes into mesa_shader_cache* subfolders of its directory; the
    # directory itself also holds Steam's recordings and NVIDIA's cache.
    add('Mesa driver cache', sorted(mesa.glob('mesa_shader_cache*')) if mesa.is_dir() else [], not shared,
        'Shared with other applications: not cleared' if shared else '')
    if route['vkd3dArchive']:
        archive = Path(route['vkd3dArchive'])
        # vkd3d-proton's archive sits in the game's own folder or its explicit cache path
        add('vkd3d-proton pipeline cache', [archive, archive.with_name(archive.name + '.write')],
            _inside(archive, game.install) or any(_inside(archive, r) for r in own))
    else:
        # Without a profile: the default archive is in the executable's folder, which is at most two levels down
        add('vkd3d-proton pipeline cache', sorted(p for pattern in ('', '*/', '*/*/')
                                                  for p in game.install.glob(pattern + 'vkd3d-proton*.cache*')), True)
    dxvk = sorted(game.cache.glob('*.dxvk-cache'))
    add('DXVK state cache', dxvk, True)
    return found


def report(game, profile=None):
    env = profile['environment'] if profile else {}
    found = parts(game, profile)
    lim = limits(env)
    warnings = []
    for part, key in (('NVIDIA driver cache', 'nvidia'), ('Mesa driver cache', 'mesa')):
        size = next((p['bytes'] for p in found if p['name'] == part), 0)
        if isinstance(lim[key], int) and size > 0.8 * lim[key]:
            warnings.append(f'{part} is {b.human_bytes(size)} of its {b.human_bytes(lim[key])} limit: '
                            'the driver may evict compiled shaders')
    return {'game': game.id, 'profile': bool(profile), 'parts': found, 'limits': lim, 'warnings': warnings,
            'recordings': str(game.cache / RECORDINGS)}


def clear(game, profile=None):
    """Delete the game's clearable compiled caches. Returns the bytes freed."""
    if lp.game_processes(game):
        raise CacheError(f'{game.name} is running')
    paths = [Path(p) for part in parts(game, profile) if part['clearable'] for p in part['paths']]
    for path in paths:   # checked before anything is deleted
        if path.name == RECORDINGS or (path.is_dir() and (path / RECORDINGS).exists()):
            raise CacheError(f'Refusing to clear {path}: it holds Steam’s pipeline recordings')
    freed = 0
    for path in paths:
        freed += b.tree_bytes(path) if path.is_dir() else path.stat().st_size
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
    # The compile no longer matches what is on disk
    history = b.read_json(b.DATA / 'history.json', {})
    if history.pop(game.id, None) is not None:
        b.write_json(b.DATA / 'history.json', history)
    return freed
