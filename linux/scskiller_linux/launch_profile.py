"""Per-game normal Steam launch configuration and cache routing.

Steam and Proton decide where a game's driver and vkd3d caches live. The helper
must write to those same files, so the configuration is observed from the game
itself when it is started normally through Steam (no launch options) and saved
per game. Only cache locations, graphics flags and runtime identity are kept.
"""
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import os
import re
import struct

from . import backend as b

PROFILES = b.DATA / 'launch-profiles'
# Process environment fields needed to reproduce cache routing and the
# graphics configuration. Prefix, loader and overlay paths are not kept.
CAPTURED_KEYS = frozenset((
    'SteamAppId', 'SteamGameId', 'STEAM_COMPAT_APP_ID', 'STEAM_COMPAT_TOOL_PATHS',
    'VKD3D_CONFIG', 'VKD3D_FEATURE_LEVEL', 'VKD3D_SHADER_MODEL', 'VKD3D_FILTER_DEVICE_NAME',
    'VKD3D_DISABLE_EXTENSIONS', 'VKD3D_SHADER_CACHE_PATH', 'DXVK_CONFIG', 'DXVK_ENABLE_NVAPI',
    'DXVK_FILTER_DEVICE_NAME', 'DXVK_STATE_CACHE_PATH', 'DXVK_NVAPI_DRS_SETTINGS',
    'DXVK_NVAPI_SET_NGX_DEBUG_OPTIONS', 'PROTON_DLSS_UPGRADE', 'PROTON_FSR4_UPGRADE',
    'PROTON_DLSS_INDICATOR', '__GL_SHADER_DISK_CACHE', '__GL_SHADER_DISK_CACHE_PATH',
    '__GL_SHADER_DISK_CACHE_APP_NAME', '__GL_SHADER_DISK_CACHE_READ_ONLY_APP_NAME',
    '__GL_SHADER_DISK_CACHE_SKIP_CLEANUP', '__GLVND_DISALLOW_PATCHING', 'MESA_SHADER_CACHE_DIR',
    'MESA_SHADER_CACHE_DISABLE', 'MESA_DISK_CACHE_SINGLE_FILE', 'MESA_SHADER_CACHE_MAX_SIZE',
    'MESA_GLSL_CACHE_MAX_SIZE', 'MESA_DISK_CACHE_READ_ONLY_FOZ_DBS', 'WINEDLLOVERRIDES'))
GRAPHICS_DLLS = ('d3d12.dll', 'd3d12core.dll', 'dxgi.dll', 'd3d11.dll')
VKD3D_HEADER = 0x30
VKD3D_ENTRY = struct.Struct('<QQII')


class ProfileError(RuntimeError):
    pass


def appid(game):
    return game.id.split(':', 1)[1] if game.id.startswith('steam:') else None


def profile_path(game):
    return PROFILES / (game.id.replace(':', '_') + '.json')


def load(game):
    return b.read_json(profile_path(game), None)


def host_path(path):
    """Steam's container exposes host files under /run/host; the helper runs on the host."""
    path = Path(path)
    if path.is_relative_to('/run/host'):
        path = Path('/') / path.relative_to('/run/host')
    return path


def _environment(pid):
    raw = Path(f'/proc/{pid}/environ').read_bytes().split(b'\0')
    return dict(item.decode(errors='replace').split('=', 1) for item in raw if b'=' in item)


def _maps(pid):
    paths = []
    for line in Path(f'/proc/{pid}/maps').read_text(errors='replace').splitlines():
        parts = line.split(None, 5)
        if len(parts) == 6 and parts[5].startswith('/'):
            paths.append(parts[5].removesuffix(' (deleted)'))
    return list(dict.fromkeys(paths))


def _executables(game):
    names = set()
    try:
        for path in game.install.rglob('*'):
            if path.suffix.lower() == '.exe':
                names.add(path.name.lower())
    except OSError:
        pass
    return names


def game_processes(game, exe_names=None):
    """Running processes of this Steam game that have loaded a graphics stack."""
    app = appid(game)
    if app is None:
        return []
    exe_names = exe_names if exe_names is not None else _executables(game)
    found = []
    for proc in Path('/proc').glob('[0-9]*'):
        try:
            if proc.stat().st_uid != os.getuid():
                continue
            parts = (proc / 'cmdline').read_bytes().decode(errors='replace').split('\0')
            exe = next((a.replace('\\', '/').rsplit('/', 1)[-1] for a in parts if a.lower().endswith('.exe')), None)
            if not exe or exe.lower() not in exe_names:
                continue
            env = _environment(proc.name)
            if env.get('SteamAppId') != app and env.get('STEAM_COMPAT_APP_ID') != app:
                continue
            maps = _maps(proc.name)
            if not any(Path(m).name.lower() in GRAPHICS_DLLS for m in maps):
                continue
            found.append({'pid': int(proc.name), 'exe': exe, 'command': next(a for a in parts if a.lower().endswith('.exe')),
                          'environment': env, 'maps': maps, 'cwd': os.readlink(proc / 'cwd')})
        except (OSError, ValueError, StopIteration):
            continue
    return found


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as file:
        for block in iter(lambda: file.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def runtime_from_environment(env):
    tools = env.get('STEAM_COMPAT_TOOL_PATHS', '')
    for item in tools.split(':'):
        root = host_path(item)
        if (root / 'proton').is_file():
            return root.resolve()
    return None


def build_profile(game, process, runtime, runtime_print, driver_print):
    """Translate an observed game process into a saved per-game profile."""
    env = process['environment']
    cwd = host_path(process['cwd'])
    if not cwd.is_dir() or not cwd.resolve().is_relative_to(game.install.resolve()):
        raise ProfileError(f'The game’s working directory {cwd} is not inside its install directory on this host')
    observed_runtime = runtime_from_environment(env)
    if observed_runtime and observed_runtime != runtime:
        raise ProfileError(f'The game ran with {observed_runtime}, but SCSKiller resolved {runtime}. '
                           'Select the game’s Proton directory in Settings.')
    translation = {}
    for mapped in process['maps']:
        name = Path(mapped).name.lower()
        if name in GRAPHICS_DLLS and name not in translation:
            try:
                translation[name] = _sha256(host_path(mapped))
            except OSError:
                pass
    vkd3d_mapped = [str(host_path(m)) for m in process['maps'] if re.fullmatch(r'vkd3d-proton(\..+)?\.cache', Path(m).name)]
    driver = next((m.rsplit('.so.', 1)[1] for m in process['maps'] if 'libnvidia-glcore.so.' in m), None)
    return {'version': 1, 'game': game.id, 'capturedAt': datetime.now(timezone.utc).isoformat(),
            'build': game.version, 'exe': process['exe'], 'command': process['command'],
            'workingDirectory': str(cwd), 'proton': str(runtime), 'protonFingerprint': runtime_print,
            'driverFingerprint': driver_print, 'nvidiaDriver': driver, 'translationLibraries': translation,
            'vkd3dMapped': vkd3d_mapped,
            'environment': {k: v for k, v in env.items() if k in CAPTURED_KEYS}}


def save(game, profile):
    b.write_json(profile_path(game), profile)


def staleness(game, profile, runtime_print, driver_print):
    """Reasons a saved profile no longer describes the game's normal launch."""
    if not profile:
        return ['No normal Steam launch has been observed for this game yet.']
    reasons = []
    if profile.get('game') != game.id:
        reasons.append('The saved launch settings belong to another game.')
    if profile.get('build') != game.version:
        reasons.append('The game was updated since its launch settings were observed.')
    if profile.get('protonFingerprint') != runtime_print:
        reasons.append('The game’s Proton runtime changed since its launch settings were observed.')
    if profile.get('driverFingerprint') != driver_print:
        reasons.append('The GPU driver changed since the game’s launch settings were observed.')
    if not Path(profile.get('workingDirectory', '')).is_dir():
        reasons.append('The game’s working directory no longer exists.')
    return reasons


def routing(profile):
    """Cache destinations used by the game's normal launch."""
    env = profile['environment']
    nvidia = env.get('__GL_SHADER_DISK_CACHE_PATH')
    explicit = env.get('VKD3D_SHADER_CACHE_PATH')
    if explicit and explicit != '0':
        # vkd3d-proton names an explicit-directory archive after the executable.
        if re.match(r'^[zZ]:[\\/]', explicit):
            explicit = explicit[2:].replace('\\', '/')
        directory = host_path(explicit)
        vkd3d = directory / f'vkd3d-proton.{profile["exe"]}.cache'
    elif explicit == '0':
        vkd3d = None
    else:
        # Without a path, vkd3d-proton uses the process working directory.
        vkd3d = Path(profile['workingDirectory']) / 'vkd3d-proton.cache'
    return {'nvidiaPath': str(host_path(nvidia)) if nvidia else None,
            'nvidiaAppName': env.get('__GL_SHADER_DISK_CACHE_APP_NAME'),
            'mesaPath': str(host_path(env['MESA_SHADER_CACHE_DIR'])) if env.get('MESA_SHADER_CACHE_DIR') else None,
            'vkd3dArchive': str(vkd3d) if vkd3d else None}


def helper_environment(profile, staging):
    """Native environment for the helper so drivers write the game's own caches.

    staging is the vkd3d-proton cache directory as the helper sees it.
    """
    env = {k: v for k, v in profile['environment'].items()
           if k not in ('STEAM_COMPAT_TOOL_PATHS', 'WINEDLLOVERRIDES', 'VKD3D_SHADER_CACHE_PATH',
                        'MESA_DISK_CACHE_READ_ONLY_FOZ_DBS')}
    route = routing(profile)
    if route['nvidiaPath']:
        env['__GL_SHADER_DISK_CACHE'] = '1'
        env['__GL_SHADER_DISK_CACHE_PATH'] = route['nvidiaPath']
    if route['mesaPath']:
        env['MESA_SHADER_CACHE_DIR'] = route['mesaPath']
    # vkd3d output is staged and merged afterwards: the game's archive name
    # depends on its own working directory, which the staged warmer lacks.
    env['VKD3D_SHADER_CACHE_PATH'] = str(staging)
    return env


def read_vkd3d(path):
    """Return (header, {hash: raw entry}) for a vkd3d-proton disk cache archive."""
    data = Path(path).read_bytes()
    if len(data) < VKD3D_HEADER or not data.startswith(b'VKS'):
        raise ProfileError(f'{path} is not a vkd3d-proton cache archive')
    entries, offset = {}, VKD3D_HEADER
    while offset + VKD3D_ENTRY.size <= len(data):
        key, _, size, _ = VKD3D_ENTRY.unpack_from(data, offset)
        end = offset + VKD3D_ENTRY.size + size
        if end > len(data):
            break   # A partially appended final entry is ignored, as vkd3d-proton does.
        entries.setdefault(key, data[offset:end])
        offset = end
    return data[:VKD3D_HEADER], entries


def merge_vkd3d(staging, target, backup_dir):
    """Merge staged helper archives into the game's archive, keeping its entries.

    The game's .cache and pending .cache.write are combined with the new
    entries into one .cache, which vkd3d-proton loads directly next launch.
    """
    target = Path(target)
    sources = sorted(p for p in Path(staging).glob('vkd3d-proton*.cache*') if p.suffix in ('.cache', '.write'))
    if not sources:
        return {'archive': str(target), 'added': 0, 'existing': 0, 'note': 'Helper produced no vkd3d-proton output'}
    header, new = None, {}
    for source in sources:
        h, entries = read_vkd3d(source)
        if header is not None and h != header:
            raise ProfileError('Helper produced vkd3d archives for different devices/builds')
        header = h
        for key, entry in entries.items():
            new.setdefault(key, entry)
    existing, kept, replaced = {}, [], None
    pending = target.with_name(target.name + '.write')
    for path in (target, pending):
        if path.is_file():
            h, entries = read_vkd3d(path)
            backup_dir.mkdir(parents=True, exist_ok=True)
            backup = backup_dir / (path.name + '.' + datetime.now().strftime('%Y%m%d-%H%M%S'))
            backup.write_bytes(path.read_bytes())
            if h != header:
                # vkd3d-proton discards archives from another device or build itself.
                replaced = str(backup)
                continue
            kept.append((path, path.stat().st_mtime_ns))
            for key, entry in entries.items():
                existing.setdefault(key, entry)
    added = [entry for key, entry in new.items() if key not in existing]
    temp = target.with_name(target.name + '.scskiller-tmp')
    with temp.open('wb') as file:
        file.write(header)
        for entry in existing.values():
            file.write(entry)
        for entry in added:
            file.write(entry)
    for path, mtime in kept:
        if path.stat().st_mtime_ns != mtime:
            temp.unlink()
            raise ProfileError(f'{path} changed during merging; close the game and compile again')
    temp.replace(target)
    if pending.exists():
        pending.unlink()
    for source in sources:
        source.unlink()
    return {'archive': str(target), 'added': len(added), 'existing': len(existing),
            'total': len(existing) + len(added), 'replacedIncompatible': replaced, 'backups': str(backup_dir)}


def verify_launch(profile, process):
    """Compare a running game's cache configuration with what the helper populated."""
    route = routing(profile)
    env = process['environment']
    checks = []
    nvidia = env.get('__GL_SHADER_DISK_CACHE_PATH')
    checks.append(('NVIDIA cache directory', route['nvidiaPath'], str(host_path(nvidia)) if nvidia else None))
    checks.append(('NVIDIA cache application name', route['nvidiaAppName'], env.get('__GL_SHADER_DISK_CACHE_APP_NAME')))
    mapped = [str(host_path(m)) for m in process['maps'] if re.fullmatch(r'vkd3d-proton(\..+)?\.cache', Path(m).name)]
    expected = route['vkd3dArchive']
    checks.append(('vkd3d-proton archive mapped', expected, expected if expected in mapped else (mapped[0] if mapped else None)))
    return [{'check': name, 'expected': want, 'observed': got, 'ok': want == got} for name, want, got in checks]
