"""Exercise the real pipe transport without requiring Wine or a GPU."""
from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scskiller_linux import backend as b
from scskiller_linux import engine as e
RUNNING_EXECUTABLES = e.running_executables

HELPER = '''import json, sys
print('Proton startup diagnostic', flush=True)
print('[]', flush=True)
print(json.dumps({'Event':'ready','Data':{'Protocol':1}}), flush=True)
for line in sys.stdin:
    req = json.loads(line)
    method = req['method']
    if method == 'shutdown': break
    if method == 'die': sys.exit(7)
    if method == 'fail':
        reply = {'Id':req['id'], 'Error':'Reader failed'}
    else:
        reply = {'Id':req['id'], 'Result':req}
    print(json.dumps(reply), flush=True)
'''

class EngineTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.runtime = self.root / 'Proton with spaces'
        self.runtime.mkdir()
        (self.runtime / 'proton').write_text('placeholder')
        self.binary = self.root / 'engine'
        self.binary.mkdir()
        (self.binary / 'scskiller-engine.exe').touch()
        self.game = b.Game('steam:12', 'Test Game', self.root / 'game', self.root / 'steamapps/shadercache/12')
        self.config = {'engine_directory': str(self.binary), 'proton': str(self.runtime),
                       'engine_data': str(self.root / 'data'), 'device':0, 'threads':2}
        self.devices = [{'name':'Test GPU', 'driver':'1'}]
        self.events = []
        for mock in (patch.object(b, 'steam_roots', return_value=[self.root]),
                     patch.object(e, 'running_executables', return_value=[])):
            mock.start()
            self.addCleanup(mock.stop)

    def client(self):
        commands = []
        def spawn(command, **kwargs):
            commands.append(command)
            self.command, self.environment = command, kwargs['env']
            return subprocess.Popen([sys.executable, '-u', '-c', HELPER], **kwargs)
        client = e.EngineClient([self.game], self.devices, self.config, self.events.append, spawn)
        self.addCleanup(client.close)
        self.assertEqual(client.ready.result(5), {'Protocol':1})
        self.assertEqual(commands[0][1:], ['run', 'cmd.exe', '/c', 'exit', '0'])
        return client

    def test_roundtrip_and_isolation(self):
        client = self.client()
        result = client.request('index', game=self.game.id, timeout=5)
        self.assertEqual(result['game'], self.game.id)
        self.assertEqual(self.command[0], str(self.runtime / 'proton'))
        self.assertEqual(self.command[1], 'runinprefix')
        self.assertIn('/prefixes/', self.environment['STEAM_COMPAT_DATA_PATH'])
        self.assertEqual(self.environment['__GL_SHADER_DISK_CACHE_PATH'], str(self.game.cache / 'nvidiav1'))
        self.assertIn('d3d12core', self.environment['WINEDLLOVERRIDES'])
        manifest = json.loads((client.data / 'manifest.json').read_text())
        self.assertFalse(manifest['GamePrefixInUse'])
        self.assertEqual(manifest['GpuName'], 'Test GPU')
        self.assertTrue(any(p.get('Data') == '[]' for p in self.events))
        futures = [client.request_async('echo', value=n) for n in range(20)]
        self.assertEqual([f.result(5)['value'] for f in futures], list(range(20)))

    def test_request_error_does_not_kill_connection(self):
        client = self.client()
        with self.assertRaisesRegex(e.EngineError, 'Reader failed'):
            client.request('fail', timeout=5)
        self.assertEqual(client.request('echo', timeout=5)['method'], 'echo')

    def test_process_exit_fails_pending_request(self):
        client = self.client()
        with self.assertRaisesRegex(e.EngineError, r'exited \(7\)'):
            client.request('die', timeout=5)

    def test_close_releases_session_lock(self):
        client = self.client()
        with self.assertRaisesRegex(e.EngineError, 'already running'):
            self.client()
        client.close()
        self.assertIsNotNone(client.process.poll())
        self.assertFalse(client.reader.is_alive())
        self.assertFalse(client.watcher.is_alive())
        with self.assertRaisesRegex(e.EngineError, 'not running'):
            client.request('echo')
        self.client()

    def test_recorder_requires_existing_game_prefix(self):
        self.config['use_game_prefix'] = True
        with self.assertRaisesRegex(e.EngineError, 'Start this game once'):
            self.client()
        self.config['use_game_prefix'] = False
        self.client()  # failed construction must release its lock

    def test_steam_recorded_runtime_and_explicit_override(self):
        prefix = self.root / 'steamapps/compatdata/12'
        prefix.mkdir(parents=True)
        (prefix / 'config_info').write_text(str(self.runtime / 'files/lib/wine') + '\n')
        self.assertEqual(e.proton_for_game(self.game, {}), self.runtime)
        with self.assertRaisesRegex(ValueError, 'no proton launcher'):
            e.proton_for_game(self.game, {'proton':str(self.root / 'missing')})

    def test_path_roundtrip(self):
        path = self.root / 'game directory' / 'shader.cache'
        self.assertEqual(e.unix_path(e.windows_path(path)), path)

    def test_warmer_is_not_reported_as_running_game(self):
        staging = self.root / 'state'
        proc = self.root / 'fake-proc'
        proc.mkdir()
        (proc / 'cmdline').write_bytes((e.windows_path(staging / 'stage-1/game.exe') + '\0--child\0').encode())
        with patch.object(Path, 'glob', return_value=[proc]):
            self.assertEqual(RUNNING_EXECUTABLES(), ['game.exe'])
            self.assertEqual(RUNNING_EXECUTABLES([staging]), [])
            (proc / 'cmdline').write_bytes(b'Z:\\games\\game.exe\0')
            self.assertEqual(RUNNING_EXECUTABLES([staging]), ['game.exe'])

    def test_multiple_games_cannot_share_native_cache_environment(self):
        with self.assertRaisesRegex(e.EngineError, 'one game'):
            e.EngineClient([self.game, self.game], self.devices, self.config)

    def test_translation_layer_change_invalidates_runtime(self):
        for layout in ('x86_64', 'x86_64-windows'):
            dll = self.runtime / 'files/lib/wine/vkd3d-proton' / layout / 'd3d12core.dll'
            dll.parent.mkdir(parents=True)
            dll.write_bytes(b'first translation layer')
            before = e.runtime_fingerprint(self.runtime)
            dll.write_bytes(b'updated translation layer')
            self.assertNotEqual(before, e.runtime_fingerprint(self.runtime))

if __name__ == '__main__':
    unittest.main()
