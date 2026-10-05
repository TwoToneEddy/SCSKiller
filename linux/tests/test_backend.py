import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scskiller_linux import backend as b


def archive(path, entries):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('wb') as f:
        f.write(b.MAGIC + b'\x06')
        for tag, key in entries:
            f.write(f'{tag:024x}{key:016x}'.encode())
            f.write(struct.pack('<IIII', 2, 1, 0, 2))
            f.write(b'{}')


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)

    def test_keyvalues_empty_escaped_and_nested(self):
        result = b.vdf(r'''// comment
        "libraryfolders" { "0" { "label" "" "path" "/games/with \"quotes\"" "apps" { "42" "100" } } }''')
        self.assertEqual(result['libraryfolders']['0']['label'], '')
        self.assertEqual(result['libraryfolders']['0']['path'], '/games/with "quotes"')
        self.assertEqual(result['libraryfolders']['0']['apps']['42'], '100')

    def test_bad_keyvalues(self):
        for text in ('}', '"a" {', '{'):
            with self.assertRaises(ValueError):
                b.vdf(text)

    def test_counts_deduplicate_and_ignore_partial_tail(self):
        path = self.root / 'archive.foz'
        archive(path, [(4, 1), (4, 1), (6, 2), (7, 3), (9, 4)])
        with path.open('ab') as f:
            f.write(b'partial')
        self.assertEqual(b.archive_entries(path), {(4, 1), (6, 2), (7, 3), (9, 4)})

    def test_invalid_archive(self):
        path = self.root / 'archive.foz'
        path.write_bytes(b'not a database')
        with self.assertRaises(ValueError):
            b.archive_entries(path)

    def test_excludes_driver_and_replay_databases(self):
        names = ['fozpipelinesv6/steam_pipeline_cache.foz',
                 'fozpipelinesv6/steamapprun_pipeline_cache.abc/steamapp_pipeline_cache.foz',
                 'fozpipelinesv6/replay_cache.abc.foz',
                 'fozpipelinesv6/steam_pipeline_cache_whitelist.foz',
                 'mesa_shader_cache_sf/foz_cache.foz', 'fozmediav1/video.foz']
        for name in names:
            archive(self.root / name, [])
        self.assertEqual(b.pipeline_archives(self.root), [self.root / names[1]])

    def test_scan_and_driver_invalidation(self):
        install = self.root / 'steamapps/common/Test Game'
        install.mkdir(parents=True)
        manifest = self.root / 'steamapps/appmanifest_42.acf'
        manifest.write_text('"AppState" { "appid" "42" "name" "A game" "installdir" "Test Game" }')
        archive(self.root / 'steamapps/shadercache/42/fozpipelinesv6/steam_pipeline_cache.foz', [(4, 1), (6, 2)])
        with patch.object(b, 'library_roots', return_value=[self.root]), patch.object(b, 'DATA', self.root / 'data'):
            config = {'manual': []}
            games, warnings = b.scan(config, 'driver-one')
            self.assertEqual(warnings, [])
            self.assertEqual((games[0].shaders, games[0].pipelines), (1, 1))
            b.write_json(b.DATA / 'history.json', {'steam:42': {'driver': 'driver-one', 'signature': games[0].signature}})
            self.assertEqual(b.scan(config, 'driver-one')[0][0].status, 'Replayed')
            self.assertEqual(b.scan(config, 'driver-two')[0][0].status, 'Needs rebuilding')
            manifest.write_text('"AppState" { "appid" "42" "name" "escape" "installdir" "../../.." }')
            self.assertEqual(b.scan(config, 'driver-one')[0], [])

    def test_successful_exit_with_failures_is_partial(self):
        for message in ('Parsed graphics 1 / 4, failed 3, cached 0',
                        'Compile compute 1 / 4, skipped 3, cached 0',
                        'Decompress modules 2 / 5, failed validation 3, missing 0',
                        'Clean crashes 1', 'Fossilize ERROR: failure'):
            self.assertTrue(b.replay_has_warnings(message), message)
        self.assertFalse(b.replay_has_warnings('failed 0, skipped 0, missing 0\nClean crashes 0'))

    def fake_replayer(self, body):
        executable = self.root / 'replay with spaces'
        executable.write_text('#!/usr/bin/env python3\n' + body)
        executable.chmod(0o755)
        game = b.Game('test:1', 'Test', self.root, self.root / 'cache',
                      archives=[self.root / 'input with spaces.foz'], pipelines=1)
        config = {'replayer': str(executable), 'threads': 1, 'device': 0}
        return game, config

    def test_real_subprocess_partial_result_persisted(self):
        game, config = self.fake_replayer("print('Compile graphics 1 / 2, skipped 1, cached 0')\n")
        with patch.object(b, 'DATA', self.root / 'data'):
            result = b.Replay().run(game, config, 'driver', lambda _: None)
            self.assertEqual(result, 'Partial replay')
            self.assertEqual(b.read_json(b.DATA / 'history.json', {})[game.id]['result'], 'Partial replay')

    def test_failed_process_never_records_success(self):
        game, config = self.fake_replayer('raise SystemExit(7)\n')
        with patch.object(b, 'DATA', self.root / 'data'):
            with self.assertRaisesRegex(RuntimeError, 'code 7'):
                b.Replay().run(game, config, 'driver', lambda _: None)
            self.assertFalse((b.DATA / 'history.json').exists())

    def test_cancel_terminates_process(self):
        game, config = self.fake_replayer('import time\nprint("started", flush=True)\ntime.sleep(60)\n')
        replay = b.Replay()
        timer = threading.Timer(.3, replay.cancel)
        timer.start()
        try:
            with patch.object(b, 'DATA', self.root / 'data'):
                started = time.monotonic()
                self.assertEqual(replay.run(game, config, 'driver', lambda _: None), 'Cancelled')
                self.assertLess(time.monotonic() - started, 5)
                self.assertIsNotNone(replay.process.poll())
        finally:
            timer.cancel()

    def test_command_preserves_spaces_and_cache_environment(self):
        game, config = self.fake_replayer('')
        command, env = b.replay_command(game, config)
        self.assertEqual(command[1], str(game.archives[0]))
        self.assertEqual(env['__GL_SHADER_DISK_CACHE_PATH'], str(game.cache / 'nvidiav1'))
        self.assertNotIn('--null-device', command)

    def test_atomic_json(self):
        path = self.root / 'sub/settings.json'
        b.write_json(path, {'a': 1})
        b.write_json(path, {'b': 2})
        self.assertEqual(json.loads(path.read_text()), {'b': 2})
        self.assertFalse(path.with_suffix('.tmp').exists())


if __name__ == '__main__':
    unittest.main()
