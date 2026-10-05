"""Linux discovery and Vulkan warming. No Windows DLLs or game injection."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import hashlib
import fcntl
from importlib.resources import files
import json
import os
import re
import shutil
import signal
import struct
import subprocess
import threading
import time

DATA = Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share')) / 'scskiller'
CONFIG = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'scskiller'
MAGIC = b'\x81FOSSILIZEDB\0\0\0'


def read_json(path, default):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return default


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, indent=2) + '\n')
    temp.replace(path)


def settings():
    return {'threads': max(1, (os.cpu_count() or 2) - 2), 'device': 0,
            'replayer': '', 'libraries': [], 'manual': [],
            **read_json(CONFIG / 'settings.json', {})}


def vdf(text):
    """Read Steam's quoted KeyValues, including nested library folders."""
    tokens = re.finditer(r'"((?:\\.|[^"\\])*)"|([{}])|(//[^\n]*)', text)
    stack = [{}]
    key = None
    for token in tokens:
        string, brace, comment = token.groups()
        if comment is not None:
            continue
        if brace == '{':
            if key is None:
                raise ValueError('KeyValues object without a key')
            child = {}
            stack[-1][key] = child
            stack.append(child)
            key = None
        elif brace == '}':
            if len(stack) == 1:
                raise ValueError('Unbalanced KeyValues')
            stack.pop()
            key = None
        else:
            value = re.sub(r'\\([\\"])', r'\1', string)
            if key is None:
                key = value
            else:
                stack[-1][key] = value
                key = None
    if len(stack) != 1:
        raise ValueError('Unclosed KeyValues object')
    return stack[0]


def steam_roots():
    home = Path.home()
    candidates = [home / '.local/share/Steam', home / '.steam/steam',
                  home / '.steam/root', home / '.var/app/com.valvesoftware.Steam/.local/share/Steam']
    return list(dict.fromkeys(p.resolve() for p in candidates if p.is_dir()))


def library_roots(config):
    roots = steam_roots()
    libs = list(roots)
    for root in roots:
        for file in (root / 'steamapps/libraryfolders.vdf', root / 'config/libraryfolders.vdf'):
            try:
                entries = vdf(file.read_text()).get('libraryfolders', {})
                for key, entry in entries.items():
                    path = entry.get('path') if isinstance(entry, dict) else entry if key.isdigit() else None
                    if path:
                        libs.append(Path(path))
            except (OSError, ValueError):
                continue
    libs.extend(Path(p).expanduser() for p in config['libraries'])
    return list(dict.fromkeys(p.resolve() for p in libs if p.is_dir()))


def find_replayer(config):
    if config.get('replayer'):
        path = Path(config['replayer']).expanduser()
        return str(path) if path.is_file() and os.access(path, os.X_OK) else ''
    for name in ('fossilize-replay', 'fossilize_replay'):
        if path := shutil.which(name):
            return path
    for root in steam_roots():
        for folder in ('ubuntu12_64', 'steamrt64'):
            path = root / folder / 'fossilize_replay'
            if path.is_file() and os.access(path, os.X_OK):
                return str(path)
    return ''


def gpu_info():
    try:
        result = subprocess.run(['vulkaninfo', '--summary'], capture_output=True, text=True, timeout=20)
        devices = []
        for block in re.split(r'GPU\d+:', result.stdout)[1:]:
            values = dict(re.findall(r'^\s*(\w+)\s*=\s*(.*?)\s*$', block, re.M))
            devices.append({'name': values.get('deviceName', 'Vulkan GPU'),
                            'driver': values.get('driverInfo', values.get('driverVersion', 'unknown')),
                            'uuid': values.get('deviceUUID', ''), 'type': values.get('deviceType', '')})
        if devices:
            return devices
    except (OSError, subprocess.TimeoutExpired):
        pass
    return []


def fingerprint(device):
    return hashlib.sha256(json.dumps(device, sort_keys=True).encode()).hexdigest()


def archive_entries(path):
    """Read v6 headers only; never decompress game-supplied payloads in the UI.

    Format: ValveSoftware/Fossilize fossilize_db.cpp StreamArchive. A partial
    last entry is permitted (Steam may currently be appending a recording).
    """
    result = set()
    with Path(path).open('rb') as file:
        header = file.read(16)
        if header != MAGIC + b'\x06':
            raise ValueError(f'Not a Fossilize v6 pipeline archive: {path}')
        size = os.fstat(file.fileno()).st_size
        while file.tell() + 56 <= size:
            entry = file.read(56)
            stored, flags, crc, unpacked = struct.unpack('<IIII', entry[40:])
            if file.tell() + stored > size:
                break
            tag = int(entry[8:24], 16)
            key = int(entry[24:40], 16)
            if flags not in (1, 2):
                raise ValueError(f'Invalid archive entry in {path}')
            result.add((tag, key))
            file.seek(stored, 1)
    return result


def pipeline_archives(cache):
    # Steam keeps recordings from several Proton/driver configurations. Replay
    # one current application-info group, not incompatible historical groups.
    def recordings(folder):
        return sorted(p for p in folder.glob('*.foz')
                      if re.fullmatch(r'steam(?:app|apprun)?_pipeline_cache(?:\.[^.]+)*\.foz', p.name))
    versions = sorted(cache.glob('fozpipelinesv*'), reverse=True)
    for version in versions:
        groups = [recordings(p) for p in version.glob('steamapprun_pipeline_cache.*') if p.is_dir()]
        groups = [group for group in groups if group]
        if groups:
            return max(groups, key=lambda group: max(p.stat().st_mtime_ns for p in group))
        if base := recordings(version):
            return base
    return []


def tree_bytes(path):
    total = 0
    try:
        for root, dirs, files in os.walk(path):
            for name in files:
                try:
                    total += (Path(root) / name).stat().st_size
                except OSError:
                    pass
    except OSError:
        pass
    return total


def human_bytes(value):
    for suffix in ('B', 'KB', 'MB', 'GB', 'TB'):
        if value < 1024 or suffix == 'TB':
            return f'{value:.1f} {suffix}'
        value /= 1024


@dataclass
class Game:
    id: str
    name: str
    install: Path
    cache: Path
    store: str = 'Steam'
    archives: list[Path] = field(default_factory=list)
    shaders: int = 0
    pipelines: int = 0
    cache_size: int = 0
    signature: str = ''
    status: str = 'No recordings'
    reason: str = 'No Vulkan pipeline recordings found. Enable Steam shader pre-caching and play once.'
    known: bool = False
    elapsed: float = 0
    version: str | None = None


def scan(config, driver):
    games = {}
    warnings = []
    for library in library_roots(config):
        for manifest in (library / 'steamapps').glob('appmanifest_*.acf'):
            try:
                info = vdf(manifest.read_text())['AppState']
                appid, name = info['appid'], info['name']
                if not str(appid).isdigit():
                    continue
                if re.search(r'^(Proton|Steam Linux|SteamLinux|Steamworks|Steam Controller|Steam\.dll)', name, re.I):
                    continue
                install = (library / 'steamapps/common' / info['installdir']).resolve()
                if not install.is_relative_to((library / 'steamapps/common').resolve()) or not install.is_dir():
                    continue
                games['steam:' + appid] = Game('steam:' + appid, name, install,
                    library / 'steamapps/shadercache' / appid, version=info.get('buildid'))
            except (OSError, ValueError, KeyError, TypeError) as e:
                warnings.append(f'{manifest.name}: {e}')
    for entry in config['manual']:
        games[entry['id']] = Game(entry['id'], entry['name'], Path(entry['install']),
                                  Path(entry['cache']), 'Manual', [Path(p) for p in entry['archives']])
    known = json.loads(files(__package__).joinpath('known-stutter.json').read_text())
    known_ids = {i for g in known.get('games', []) for i in g['ids']}
    records = read_json(DATA / 'history.json', {})
    for game in games.values():
        try:
            if game.store == 'Steam':
                game.archives = pipeline_archives(game.cache)
            entries = set()
            signatures = []
            for archive in game.archives:
                entries.update(archive_entries(archive))
                stat = archive.stat()
                signatures.append((str(archive), stat.st_size, stat.st_mtime_ns))
            game.signature = hashlib.sha256(json.dumps(signatures).encode()).hexdigest()
            game.shaders = sum(t == 4 for t, _ in entries)
            game.pipelines = sum(t in (6, 7, 9) for t, _ in entries)
            game.cache_size = tree_bytes(game.cache)
            game.known = game.id in known_ids
            previous = records.get(game.id, {})
            game.elapsed = previous.get('elapsed', 0)
            if game.pipelines:
                game.status = 'Ready to compile'
                game.reason = 'Vulkan pipeline recordings available'
                if previous.get('driver') == driver and previous.get('signature') == game.signature:
                    game.status = previous.get('result', 'Replayed')
                    game.reason = 'Replay finished for this GPU and driver; see compile log for coverage'
                elif previous:
                    game.status = 'Needs rebuilding'
                    game.reason = 'GPU, driver or pipeline recordings changed'
        except (OSError, ValueError) as e:
            game.status, game.reason = 'Scan error', str(e)
    return sorted(games.values(), key=lambda g: (not g.known, g.store, g.name.casefold())), warnings


def replay_command(game, config):
    exe = find_replayer(config)
    if not exe:
        raise ValueError('Fossilize replay was not found. Start Steam once or choose an executable in Settings.')
    if not game.archives or game.pipelines == 0:
        raise ValueError('This game has no recorded Vulkan pipelines to replay.')
    # Let the real Vulkan driver populate its normal implicit cache. Do not use
    # --null-device or a standalone VkPipelineCache that the game never reads.
    command = [exe, *map(str, game.archives), '--master-process', '--progress',
               '--num-threads', str(max(1, int(config['threads']))),
               '--device-index', str(int(config['device'])), '--timeout-seconds', '60']
    env = os.environ.copy()
    env.update({'__GL_SHADER_DISK_CACHE': '1', '__GL_SHADER_DISK_CACHE_PATH': str(game.cache / 'nvidiav1'),
                'MESA_SHADER_CACHE_DIR': str(game.cache), 'MESA_SHADER_CACHE_DISABLE': 'false'})
    return command, env


class Replay:
    """One cancellable process group, including Fossilize worker processes."""
    def __init__(self):
        self.cancelled = threading.Event()
        self.process = None
        self.lock = threading.Lock()

    def cancel(self):
        self.cancelled.set()
        with self.lock:
            if self.process and self.process.poll() is None:
                try:
                    os.killpg(self.process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass

    def run(self, game, config, driver, emit):
        DATA.mkdir(parents=True, exist_ok=True)
        with (DATA / 'replay.lock').open('w') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError('Another SCSKiller replay is already running.')
            return self._run(game, config, driver, emit)

    def _run(self, game, config, driver, emit):
        command, env = replay_command(game, config)
        game.cache.mkdir(parents=True, exist_ok=True)
        (game.cache / 'nvidiav1').mkdir(exist_ok=True)
        DATA.mkdir(parents=True, exist_ok=True)
        log = DATA / ('compile-' + re.sub(r'[^a-zA-Z0-9_-]', '_', game.id) + '.log')
        start = time.monotonic()
        with log.open('w') as output:
            output.write(json.dumps(command) + '\n')
            with self.lock:
                if self.cancelled.is_set():
                    return 'Cancelled'
                self.process = subprocess.Popen(command, env=env, stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, start_new_session=True, text=True, errors='replace', bufsize=1)
            # The reader is separate so a driver that ignores SIGTERM cannot hang cancellation.
            def reader():
                for line in self.process.stdout:
                    output.write(line)
                    output.flush()
                    emit(line.rstrip())
            reader_thread = threading.Thread(target=reader, daemon=True)
            reader_thread.start()
            while self.process.poll() is None:
                if self.cancelled.wait(.1):
                    try:
                        os.killpg(self.process.pid, signal.SIGTERM)
                        self.process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        os.killpg(self.process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    break
            code = self.process.wait()
            reader_thread.join()
            self.process.stdout.close()
        if self.cancelled.is_set():
            return 'Cancelled'
        if code:
            raise RuntimeError(f'Fossilize exited with code {code}. Log: {log}')
        text = log.read_text()
        # Exit 0 may still mean unsupported or failed pipelines. Never claim full coverage.
        problems = replay_has_warnings(text)
        result = 'Partial replay' if problems else 'Replayed'
        history = read_json(DATA / 'history.json', {})
        history[game.id] = {'driver': driver, 'signature': game.signature,
                            'elapsed': time.monotonic() - start, 'at': time.time(), 'log': str(log), 'result': result}
        write_json(DATA / 'history.json', history)
        return result


def replay_has_warnings(text):
    # Steam's master replayer can return zero with failed validation, missing
    # modules, skipped pipelines or worker crashes. Preserve that distinction.
    return bool(re.search(
        r'Fossilize ERROR|failed to|(?:failed(?: validation)?|missing|skipped|crashes)\s+[1-9]\d*'
        r'|[1-9]\d*\s+(?:pipelines? (?:failed|skipped)|crashes)', text, re.I))
