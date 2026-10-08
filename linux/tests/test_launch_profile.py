"""Cache routing for normal Steam launches, without a game or GPU."""
from pathlib import Path
import json
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scskiller_linux import backend as b
from scskiller_linux import engine as e
from scskiller_linux import launch_profile as lp

HEADER = b'VKS\x04' + bytes(range(44))


def entry(key, payload=b'x'):
    return struct.pack('<QQII', key, 0, len(payload), 2) + payload


def archive(path, keys, header=HEADER):
    path.write_bytes(header + b''.join(entry(k, bytes([k % 256]) * 3) for k in keys))


class LaunchProfileTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.install = self.root / 'common/Game'
        (self.install / 'bin/x64').mkdir(parents=True)
        (self.install / 'bin/x64/game.exe').touch()
        self.runtime = self.root / 'proton'
        self.runtime.mkdir()
        (self.runtime / 'proton').touch()
        self.game = b.Game('steam:12', 'Game', self.install, self.root / 'shadercache/12', version='7')
        self.process = {'pid': 5, 'exe': 'game.exe', 'command': 'S:\\common\\Game\\bin\\x64\\game.exe',
            'cwd': str(self.install / 'bin'),
            'maps': ['/run/host/usr/lib/libnvidia-glcore.so.615.71.09', str(self.install / 'bin/vkd3d-proton.cache')],
            'environment': {'SteamAppId': '12', 'STEAM_COMPAT_TOOL_PATHS': f'{self.runtime}:/elsewhere',
                '__GL_SHADER_DISK_CACHE_PATH': str(self.root / 'shadercache/12/nvidiav1'),
                '__GL_SHADER_DISK_CACHE_APP_NAME': 'steamapp_shader_cache', 'WINEPREFIX': '/game/pfx',
                'VK_DRIVER_FILES': '/container/icd.json', 'DXVK_ENABLE_NVAPI': '1'}}

    def profile(self):
        return lp.build_profile(self.game, self.process, self.runtime.resolve(), 'proton-1', 'driver-1')

    def test_profile_keeps_routing_and_flags_but_not_container_or_prefix(self):
        profile = self.profile()
        self.assertEqual(profile['nvidiaDriver'], '615.71.09')
        self.assertNotIn('WINEPREFIX', profile['environment'])
        self.assertNotIn('VK_DRIVER_FILES', profile['environment'])
        route = lp.routing(profile)
        self.assertEqual(route['vkd3dArchive'], str(self.install / 'bin/vkd3d-proton.cache'))
        self.assertEqual(route['nvidiaAppName'], 'steamapp_shader_cache')
        env = lp.helper_environment(profile, 'Z:\\stage')
        self.assertEqual(env['VKD3D_SHADER_CACHE_PATH'], 'Z:\\stage')
        self.assertEqual(env['__GL_SHADER_DISK_CACHE_PATH'], str(self.root / 'shadercache/12/nvidiav1'))
        self.assertTrue(all(c['ok'] for c in lp.verify_launch(profile, self.process)))

    def test_mapped_archive_wins_over_working_directory(self):
        # Witcher 3: sampled in bin/x64_dx12, but the mapped archive is bin/.
        (self.install / 'bin/x64_dx12').mkdir(parents=True, exist_ok=True)
        self.process['cwd'] = str(self.install / 'bin/x64_dx12')
        self.process['maps'][1] = str(self.install / 'bin/vkd3d-proton.cache')
        self.assertEqual(lp.routing(self.profile())['vkd3dArchive'], str(self.install / 'bin/vkd3d-proton.cache'))

    def test_explicit_vkd3d_directory_uses_executable_name(self):
        self.process['environment']['VKD3D_SHADER_CACHE_PATH'] = 'Z:\\cache\\dir'
        self.assertEqual(lp.routing(self.profile())['vkd3dArchive'], '/cache/dir/vkd3d-proton.game.exe.cache')

    def test_different_runtime_or_outside_working_directory_is_rejected(self):
        other = self.root / 'other'
        other.mkdir()
        (other / 'proton').touch()
        self.process['environment']['STEAM_COMPAT_TOOL_PATHS'] = str(other)
        with self.assertRaisesRegex(lp.ProfileError, 'Proton'):
            self.profile()
        self.process['environment']['STEAM_COMPAT_TOOL_PATHS'] = str(self.runtime)
        self.process['cwd'] = str(self.root)
        with self.assertRaisesRegex(lp.ProfileError, 'working directory'):
            self.profile()

    def test_staleness_after_runtime_driver_or_game_update(self):
        profile = self.profile()
        self.assertEqual(lp.staleness(self.game, profile, 'proton-1', 'driver-1'), [])
        self.assertEqual(len(lp.staleness(self.game, profile, 'proton-2', 'driver-2')), 2)
        self.game.version = '8'
        self.assertIn('updated', lp.staleness(self.game, profile, 'proton-1', 'driver-1')[0])
        self.assertTrue(lp.staleness(self.game, None, 'proton-1', 'driver-1'))

    def test_merge_preserves_game_entries_and_pending_writes(self):
        stage = self.root / 'stage'
        stage.mkdir()
        archive(stage / 'vkd3d-proton.game.exe.cache.write', [1, 2, 3])
        target = self.install / 'bin/vkd3d-proton.cache'
        archive(target, [3, 4])
        archive(target.with_name('vkd3d-proton.cache.write'), [5])
        result = lp.merge_vkd3d(stage, target, self.root / 'backup')
        self.assertEqual((result['added'], result['existing'], result['total']), (2, 3, 5))
        header, entries = lp.read_vkd3d(target)
        self.assertEqual(header, HEADER)
        self.assertEqual(sorted(entries), [1, 2, 3, 4, 5])
        self.assertFalse(target.with_name('vkd3d-proton.cache.write').exists())
        self.assertFalse(any(stage.iterdir()))
        self.assertEqual(len(list((self.root / 'backup').iterdir())), 2)

    def test_merge_replaces_archive_from_other_build_after_backup(self):
        stage = self.root / 'stage'
        stage.mkdir()
        archive(stage / 'vkd3d-proton.game.exe.cache', [1])
        target = self.install / 'bin/vkd3d-proton.cache'
        archive(target, [9], header=b'VKS\x04' + bytes(44))
        result = lp.merge_vkd3d(stage, target, self.root / 'backup')
        self.assertTrue(result['replacedIncompatible'])
        self.assertEqual(sorted(lp.read_vkd3d(target)[1]), [1])

    def test_truncated_final_entry_is_ignored(self):
        path = self.root / 'a.cache'
        archive(path, [1, 2])
        path.write_bytes(path.read_bytes() + entry(3)[:10])
        self.assertEqual(sorted(lp.read_vkd3d(path)[1]), [1, 2])

    def test_engine_session_writes_game_caches_and_publishes(self):
        binary = self.root / 'engine'
        binary.mkdir()
        (binary / 'scskiller-engine.exe').touch()
        config = {'engine_directory': str(binary), 'proton': str(self.runtime), 'engine_data': str(self.root / 'data'),
                  'device': 0, 'threads': 2, 'launch_profile': self.profile()}
        seen = {}
        def spawn(command, **kwargs):
            seen['env'] = kwargs['env']
            return subprocess.Popen([sys.executable, '-c', 'import sys; sys.stdin.read()'], **kwargs)
        with patch.object(b, 'steam_roots', return_value=[self.root]), \
             patch.object(e, 'running_executables', return_value=[]), \
             patch.object(lp, 'game_processes', return_value=[]), \
             patch.dict(e.os.environ, {'VKD3D_CONFIG': 'from_terminal'}):
            client = e.EngineClient([self.game], [{'name': 'GPU'}], config, process_factory=spawn)
            self.addCleanup(client.close)
            env = seen['env']
            self.assertEqual(env['__GL_SHADER_DISK_CACHE_PATH'], str(self.root / 'shadercache/12/nvidiav1'))
            self.assertEqual(env['__GL_SHADER_DISK_CACHE_APP_NAME'], 'steamapp_shader_cache')
            self.assertEqual(env['VKD3D_SHADER_CACHE_PATH'], e.windows_path(client.staging))
            self.assertNotIn('VKD3D_CONFIG', env)
            self.assertNotIn('WINEPREFIX', env)
            child = json.loads((client.data / 'manifest.json').read_text())['Games'][0]['CacheEnvironment']
            self.assertEqual(child['VKD3D_SHADER_CACHE_PATH'], e.windows_path(client.staging))
            self.assertEqual(child['__GL_SHADER_DISK_CACHE_APP_NAME'], 'steamapp_shader_cache')
            archive(client.staging / 'vkd3d-proton.game.exe.cache.write', [7])
            result = client.publish_caches()
            self.assertEqual(result['vkd3d']['added'], 1)
            self.assertEqual(json.loads((client.data / 'routing.json').read_text())['vkd3d']['total'], 1)
            with patch.object(lp, 'game_processes', return_value=[{'pid': 1}]):
                with self.assertRaisesRegex(e.EngineError, 'Close the game'):
                    client.publish_caches()


if __name__ == '__main__':
    unittest.main()
