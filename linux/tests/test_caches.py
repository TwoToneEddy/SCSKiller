"""Per-game compiled cache reporting and clearing, on temporary folders."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scskiller_linux import backend as b
from scskiller_linux import caches as c


class CacheTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.install = self.root / 'common/Game'
        (self.install / 'bin/x64').mkdir(parents=True)
        self.cache = self.root / 'shadercache/12'
        for name, size in [('nvidiav1/GLCache/a.bin', 100), ('mesa_shader_cache_db/b', 50),
                           ('fozpipelinesv6/steamapprun_pipeline_cache.foz', 30), ('Game.dxvk-cache', 7)]:
            (self.cache / name).parent.mkdir(parents=True, exist_ok=True)
            (self.cache / name).write_bytes(b'x' * size)
        (self.install / 'bin/x64/vkd3d-proton.cache').write_bytes(b'v' * 20)
        self.game = b.Game('steam:12', 'Game', self.install, self.cache)
        patcher = patch.object(b, 'DATA', self.root / 'data')
        patcher.start()
        self.addCleanup(patcher.stop)
        running = patch('scskiller_linux.launch_profile.game_processes', return_value=[])
        self.running = running.start()
        self.addCleanup(running.stop)

    def profile(self, **env):
        return {'exe': 'game.exe', 'workingDirectory': str(self.install / 'bin/x64'), 'environment': env}

    def test_steam_defaults_report_each_cache(self):
        sizes = {p['name']: p['bytes'] for p in c.parts(self.game)}
        self.assertEqual(sizes, {'NVIDIA driver cache': 100, 'Mesa driver cache': 50,
                                 'vkd3d-proton pipeline cache': 20, 'DXVK state cache': 7})

    def test_clear_keeps_recordings(self):
        b.write_json(b.DATA / 'history.json', {'steam:12': {'result': 'Replayed'}, 'steam:13': {}})
        self.assertEqual(c.clear(self.game), 177)
        self.assertTrue((self.cache / 'fozpipelinesv6/steamapprun_pipeline_cache.foz').is_file())
        self.assertFalse((self.cache / 'nvidiav1').exists())
        self.assertFalse((self.install / 'bin/x64/vkd3d-proton.cache').exists())
        self.assertEqual(b.read_json(b.DATA / 'history.json', {}), {'steam:13': {}})

    def test_shared_driver_cache_is_reported_not_cleared(self):
        shared = self.root / 'home/.cache/nvidia'
        (shared / 'GLCache').mkdir(parents=True)
        (shared / 'GLCache/c.bin').write_bytes(b'x' * 9)
        profile = self.profile(__GL_SHADER_DISK_CACHE_PATH=str(shared), MESA_SHADER_CACHE_DIR=str(self.cache))
        nvidia = next(p for p in c.parts(self.game, profile) if p['name'] == 'NVIDIA driver cache')
        self.assertFalse(nvidia['clearable'])
        c.clear(self.game, profile)
        self.assertTrue((shared / 'GLCache/c.bin').is_file())

    def test_profile_routes_explicit_vkd3d_archive(self):
        explicit = self.cache / 'vkd3d'
        explicit.mkdir()
        (explicit / 'vkd3d-proton.game.exe.cache').write_bytes(b'v' * 5)
        (explicit / 'vkd3d-proton.game.exe.cache.write').write_bytes(b'v' * 3)
        part = next(p for p in c.parts(self.game, self.profile(VKD3D_SHADER_CACHE_PATH='Z:' + str(explicit).replace('/', '\\')))
                    if p['name'] == 'vkd3d-proton pipeline cache')
        self.assertEqual((part['bytes'], part['clearable']), (8, True))

    def test_running_game_is_not_cleared(self):
        self.running.return_value = [{'pid': 1}]
        with self.assertRaises(c.CacheError):
            c.clear(self.game)
        self.assertTrue((self.cache / 'nvidiav1').exists())

    def test_recordings_folder_is_never_cleared(self):
        profile = self.profile(__GL_SHADER_DISK_CACHE_PATH=str(self.cache))
        with self.assertRaises(c.CacheError):
            c.clear(self.game, profile)
        self.assertTrue((self.cache / 'mesa_shader_cache_db').exists())   # nothing deleted before the refusal

    def test_limits(self):
        self.assertEqual(c.limits({}), {'nvidia': 'default', 'mesa': 'default'})
        self.assertEqual(c.limits({'__GL_SHADER_DISK_CACHE_SKIP_CLEANUP': '1', 'MESA_SHADER_CACHE_MAX_SIZE': '2G'}),
                         {'nvidia': None, 'mesa': 2 * 1024 ** 3})
        self.assertEqual(c.limits({'__GL_SHADER_DISK_CACHE_SIZE': '1000', 'MESA_SHADER_CACHE_MAX_SIZE': '512'})['mesa'], 512 * 1024)

    def test_report_warns_near_limit(self):
        report = c.report(self.game, self.profile(__GL_SHADER_DISK_CACHE_SIZE='110'))
        self.assertEqual(len(report['warnings']), 1)


if __name__ == '__main__':
    unittest.main()
