"""Host transport for the original SCSKiller core running through Proton.

The helper has a private prefix. Game prefixes are never silently substituted or
modified by discovery. The manifest supplies only explicitly selected installs.
"""
from __future__ import annotations
from concurrent.futures import Future
from pathlib import Path
import fcntl
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time

from . import backend as b


def windows_path(path):
    path = Path(path).expanduser().absolute()
    return 'Z:' + str(path).replace('/', '\\')


def unix_path(path):
    if re.match(r'^[zZ]:[\\/]', path):
        return Path(path[2:].replace('\\', '/'))
    return Path(path)


def engine_directory(config):
    explicit = config.get('engine_directory') or os.environ.get('SCSKILLER_ENGINE')
    candidates = [Path(explicit).expanduser()] if explicit else []
    # A zipapp's argv[0] is its archive, so the engine sits next to it.
    candidates += [Path(sys.argv[0]).absolute().parent / 'engine',
                   Path(__file__).resolve().parents[2] / 'dist/linux/engine']
    return next((p for p in candidates if (p / 'scskiller-engine.exe').is_file()), None)


def proton_roots(config):
    roots = []
    if config.get('proton'):
        roots.append(Path(config['proton']).expanduser())
    for steam in b.steam_roots():
        roots.extend((steam / 'compatibilitytools.d').glob('*'))
        roots.extend((steam / 'steamapps/common').glob('Proton*'))
    for folder in (Path('/usr/share/steam/compatibilitytools.d'),
                   Path.home() / '.steam/root/compatibilitytools.d'):
        roots.extend(folder.glob('*'))
    return list(dict.fromkeys(p.resolve() for p in roots if (p / 'proton').is_file()))


def proton_for_game(game, config):
    explicit = config.get('proton')
    if explicit:
        root = Path(explicit).expanduser().resolve()
        if not (root / 'proton').is_file():
            raise ValueError('Selected Proton directory has no proton launcher')
        return root
    if game and game.id.startswith('steam:'):
        prefix = game.cache.parent.parent / 'compatdata' / game.id.split(':')[1]
        try:
            # Steam records the paths of the actual runtime used by this game.
            for line in (prefix / 'config_info').read_text().splitlines():
                if '/files/' in line:
                    root = Path(line.split('/files/', 1)[0])
                    if (root / 'proton').is_file():
                        return root.resolve()
        except OSError:
            pass
    available = proton_roots(config)
    if len(available) == 1:
        return available[0]
    raise ValueError('Select the game’s Proton directory in Settings. Its actual runtime could not be determined unambiguously.')


def runtime_fingerprint(root):
    digest = hashlib.sha256()
    digest.update(str(root).encode())
    for name in ('version', 'toolmanifest.vdf', 'proton'):
        path = root / name
        if path.is_file():
            digest.update(path.read_bytes())
    # Include the translation-layer binaries, not just the friendly Proton name.
    for library in sorted((root / 'files').glob('lib*/wine/*/x86_64*/*.dll')):
        if library.name.lower() in ('d3d12.dll', 'd3d12core.dll', 'dxgi.dll', 'd3d11.dll'):
            digest.update(str(library.relative_to(root)).encode())
            digest.update(library.read_bytes())
    return digest.hexdigest()


def running_executables(exclude_roots=()):
    names = set()
    for proc in Path('/proc').glob('[0-9]*'):
        try:
            if proc.stat().st_uid != os.getuid():
                continue
            parts = (proc / 'cmdline').read_bytes().decode(errors='replace').split('\0')
            # The warmer deliberately takes the game's exe name. Its staged
            # executable is still our helper, not a launched game.
            if any(unix_path(arg).is_relative_to(root) for arg in parts
                   if arg.lower().endswith('.exe') for root in exclude_roots):
                continue
            for arg in parts:
                if arg.lower().endswith('.exe'):
                    names.add(arg.replace('\\', '/').rsplit('/', 1)[-1])
        except (OSError, ProcessLookupError):
            pass
    return sorted(names)


def manifest(games, devices, config, data, runtime):
    index = int(config.get('device', 0))
    if not 0 <= index < len(devices):
        raise ValueError('Select an available Vulkan GPU')
    result = {'DataDirectory': windows_path(data / 'state'),
              'RunningFile': windows_path(data / 'running.json'),
              'Driver': b.fingerprint(devices[index]) + ':' + runtime_fingerprint(runtime),
              'GpuName': devices[index]['name'], 'Threads': config['threads'],
              'GamePrefixInUse': bool(config.get('use_game_prefix', False)),
              'ExperimentalTemplates': bool(config.get('experimental_templates', False)), 'Games': []}
    for game in games:
        result['Games'].append({'Id': game.id, 'Name': game.name, 'InstallDir': windows_path(game.install),
                               'ExePath': getattr(game, 'exe', None), 'Version': getattr(game, 'version', None),
                               'CacheDir': windows_path(game.cache)})
    return result


class EngineError(RuntimeError):
    pass


# Replay graphics options, not a game's prefix, loader paths, overlays or
# pressure-vessel-only ICD paths. Cache locations are supplied by this session.
GRAPHICS_ENV_KEYS = frozenset(('SteamAppId', 'SteamGameId', 'STEAM_COMPAT_APP_ID',
    'VKD3D_CONFIG', 'VKD3D_FEATURE_LEVEL', 'VKD3D_SHADER_MODEL', 'VKD3D_FILTER_DEVICE_NAME',
    'VKD3D_DISABLE_EXTENSIONS', 'DXVK_CONFIG', 'DXVK_ENABLE_NVAPI', 'DXVK_FILTER_DEVICE_NAME',
    'DXVK_NVAPI_DRS_SETTINGS', 'DXVK_NVAPI_SET_NGX_DEBUG_OPTIONS',
    'PROTON_DLSS_UPGRADE', 'PROTON_FSR4_UPGRADE', 'PROTON_DLSS_INDICATOR',
    '__GL_SHADER_DISK_CACHE_APP_NAME', '__GL_SHADER_DISK_CACHE_READ_ONLY_APP_NAME',
    '__GL_SHADER_DISK_CACHE_SKIP_CLEANUP', '__GLVND_DISALLOW_PATCHING',
    'MESA_DISK_CACHE_SINGLE_FILE', 'MESA_SHADER_CACHE_MAX_SIZE', 'MESA_GLSL_CACHE_MAX_SIZE'))


def captured_graphics_environment(path, game):
    record = json.loads(Path(path).expanduser().read_text())
    env = record.get('environment')
    if not isinstance(env, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in env.items()):
        raise EngineError('Environment capture must contain a string environment dictionary')
    app = game.id.removeprefix('steam:')
    if not game.id.startswith('steam:') or env.get('SteamAppId') != app or env.get('SteamGameId') != app:
        raise EngineError('Environment capture belongs to a different Steam game')
    return {k: v for k, v in env.items() if k in GRAPHICS_ENV_KEYS}


class EngineClient:
    def __init__(self, games, devices, config, emit=lambda _: None, process_factory=subprocess.Popen):
        if len(games) != 1:
            raise EngineError('Open one game per engine session so its native driver cache is isolated correctly')
        self.emit = emit
        self.pending = {}
        self.counter = 0
        self.lock = threading.Lock()
        self.closed = threading.Event()
        self.ready = Future()
        self.process = None
        self.process_factory = process_factory
        executable = engine_directory(config)
        if executable is None:
            raise EngineError('Build the original engine first: python3 linux/build-engine.py --bootstrap')
        self.runtime = proton_for_game(games[0] if games else None, config)
        # Every game in one helper must use the same translation stack.
        for game in games:
            if proton_for_game(game, config) != self.runtime:
                raise EngineError('These games use different Proton versions. Open a game separately or select its runtime explicitly.')
        data_root = Path(config.get('engine_data') or b.DATA / 'engine').expanduser().absolute()
        data_root.mkdir(parents=True, exist_ok=True)
        self.data = data_root
        self.guard = (data_root / 'host.lock').open('w')
        try:
            fcntl.flock(self.guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.guard.close()
            raise EngineError('Another original-engine session is already running')
        try:
            self.prefix = data_root / 'prefixes' / hashlib.sha256(str(self.runtime).encode()).hexdigest()[:16]
            if config.get('use_game_prefix'):
                if len(games) != 1 or not games[0].id.startswith('steam:'):
                    raise EngineError('Recording integration currently requires one Steam game with an existing Proton prefix')
                self.prefix = games[0].cache.parent.parent / 'compatdata' / games[0].id.split(':')[1]
                if not (self.prefix / 'pfx/user.reg').is_file():
                    raise EngineError('Start this game once through Steam to create its Proton prefix')
                if running_executables():
                    # The caller may override the conservative check only by closing the active Windows apps.
                    raise EngineError('Close running Windows games/applications before opening a recorder session')
            self.prefix.mkdir(parents=True, exist_ok=True)
            b.write_json(data_root / 'manifest.json', manifest(games, devices, config, data_root, self.runtime))
            b.write_json(data_root / 'running.json', running_executables())
            steam = b.steam_roots()
            if not steam:
                raise EngineError('Steam must be installed and started once before using Proton')
            self.environment = os.environ.copy()
            cache = games[0].cache.expanduser().absolute()
            (cache / 'nvidiav1').mkdir(parents=True, exist_ok=True)
            self.environment.update({'STEAM_COMPAT_CLIENT_INSTALL_PATH': str(steam[0]),
                'STEAM_COMPAT_DATA_PATH': str(self.prefix), 'WINEDEBUG': '-all',
                'PROTONFIXES_DISABLE': '1', 'PROTON_DLSS_UPGRADE': '0', 'PROTON_FSR4_UPGRADE': '0',
                'MANGOHUD': '0', 'WINEDLLOVERRIDES': 'd3d12,d3d12core,dxgi,d3d11=n,b',
                # Windows child-process environment changes do not replace the
                # Unix environment seen by native Vulkan driver libraries.
                # Set the game's cache before starting Proton itself.
                '__GL_SHADER_DISK_CACHE': '1',
                '__GL_SHADER_DISK_CACHE_PATH': str(cache / 'nvidiav1'),
                'MESA_SHADER_CACHE_DIR': str(cache), 'MESA_SHADER_CACHE_DISABLE': 'false',
                'VKD3D_SHADER_CACHE_PATH': windows_path(cache),
                'DXVK_STATE_CACHE_PATH': windows_path(cache)})
            self.graphics_environment = {}
            if config.get('game_environment'):
                self.graphics_environment = captured_graphics_environment(config['game_environment'], games[0])
                # Missing flags in the captured game must not leak in from the
                # terminal launching this helper.
                for key in GRAPHICS_ENV_KEYS:
                    self.environment.pop(key, None)
                self.environment.update(self.graphics_environment)
            if games[0].id.startswith('steam:'):
                app = games[0].id.split(':', 1)[1]
                self.environment.update(SteamAppId=app, SteamGameId=app, STEAM_COMPAT_APP_ID=app)
            b.write_json(data_root / 'graphics-environment.json', {
                'capture': config.get('game_environment'),
                'applied': {k: self.environment[k] for k in sorted(GRAPHICS_ENV_KEYS) if k in self.environment},
                'cache': str(cache), 'protonfixesDisabled': True,
                'note': 'Captured graphics flags are replayed directly; game prefix and container loader settings are not copied.'})
            command = [str(self.runtime / 'proton'), 'runinprefix', str(executable / 'scskiller-engine.exe'),
                       windows_path(data_root / 'manifest.json')]
            self.stderr = (data_root / 'helper.log').open('a')
            self.process_exclusions = (data_root / 'state', executable.absolute())
            if not config.get('use_game_prefix'):
                # runinprefix deliberately skips Proton's prefix setup. A bare
                # Wine prefix lacks DXVK/vkd3d and ICU, even if Wine created it.
                self.emit({'Event': 'log', 'Data': 'Preparing private Proton prefix…'})
                self.process = process_factory(
                    [str(self.runtime / 'proton'), 'run', 'cmd.exe', '/c', 'exit', '0'],
                    env=self.environment, stdin=subprocess.DEVNULL, stdout=self.stderr,
                    stderr=self.stderr, start_new_session=True)
                if self.process.wait(timeout=120) != 0:
                    raise EngineError('Proton prefix setup failed; see ' + str(data_root / 'helper.log'))
            self.process = process_factory(command, env=self.environment, stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=self.stderr, text=True, encoding='utf-8', errors='replace',
                bufsize=1, start_new_session=True)
            self.reader = threading.Thread(target=self._read, daemon=True)
            self.reader.start()
            self.watcher = threading.Thread(target=self._watch, daemon=True)
            self.watcher.start()
        except BaseException:
            self.close()
            raise

    def _watch(self):
        while not self.closed.wait(2):
            try:
                b.write_json(self.data / 'running.json', running_executables(self.process_exclusions))
            except OSError:
                pass

    def _read(self):
        error = None
        try:
            for line in self.process.stdout:
                try:
                    packet = json.loads(line.lstrip('\ufeff'))
                except ValueError:
                    self.emit({'Event': 'log', 'Data': line.rstrip()})
                    continue
                if not isinstance(packet, dict):
                    self.emit({'Event': 'log', 'Data': line.rstrip()})
                    continue
                if 'Event' in packet:
                    if packet['Event'] == 'ready' and not self.ready.done():
                        self.ready.set_result(packet['Data'])
                    self.emit(packet)
                elif 'Id' in packet:
                    with self.lock:
                        future = self.pending.pop(packet['Id'], None)
                    if future and not future.done():
                        if 'Error' in packet:
                            future.set_exception(EngineError(packet['Error']))
                        else:
                            future.set_result(packet.get('Result'))
        except (OSError, ValueError) as exception:
            error = exception
        finally:
            code = self.process.wait()
            error = EngineError(f'Original engine exited ({code}): {error or "see " + str(self.data / "helper.log")}')
            if not self.ready.done():
                self.ready.set_exception(error)
            with self.lock:
                waiting = list(self.pending.values())
                self.pending.clear()
            for future in waiting:
                if not future.done():
                    future.set_exception(error)
            self.emit({'Event': 'exit', 'Data': str(error)})

    def request_async(self, method, **params):
        with self.lock:
            if self.closed.is_set() or self.process.poll() is not None:
                raise EngineError('Original engine is not running')
            self.counter += 1
            ident = self.counter
            future = Future()
            self.pending[ident] = future
            try:
                self.process.stdin.write(json.dumps({'id': ident, 'method': method, **params}) + '\n')
                self.process.stdin.flush()
            except (OSError, ValueError) as error:
                self.pending.pop(ident, None)
                future.set_exception(EngineError(str(error)))
            return future

    def request(self, method, timeout=300, **params):
        return self.request_async(method, **params).result(timeout)

    def close(self):
        if self.closed.is_set():
            return
        self.closed.set()
        if hasattr(self, 'watcher') and threading.current_thread() is not self.watcher:
            self.watcher.join(timeout=3)
        if self.process is not None:
            if self.process.poll() is None:
                try:
                    if self.process.stdin:
                        self.process.stdin.write('{"id":0,"method":"shutdown"}\n')
                        self.process.stdin.flush()
                    else:
                        os.killpg(self.process.pid, signal.SIGTERM)
                    self.process.wait(timeout=5)
                except (OSError, ValueError, subprocess.TimeoutExpired):
                    try:
                        os.killpg(self.process.pid, signal.SIGTERM)
                        self.process.wait(timeout=3)
                    except (ProcessLookupError, subprocess.TimeoutExpired):
                        if self.process.poll() is None:
                            os.killpg(self.process.pid, signal.SIGKILL)
                            self.process.wait()
            if hasattr(self, 'reader') and threading.current_thread() is not self.reader:
                self.reader.join(timeout=3)
            for stream in (self.process.stdin, self.process.stdout):
                if stream:
                    stream.close()
        if hasattr(self, 'stderr'):
            self.stderr.close()
        if hasattr(self, 'guard'):
            self.guard.close()
