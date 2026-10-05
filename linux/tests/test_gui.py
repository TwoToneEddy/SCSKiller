import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from scskiller_linux import backend as b
from scskiller_linux.gui import Window


class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        executable = self.root / 'replayer'
        executable.write_text('#!/usr/bin/env python3\nprint("Compile graphics 1 / 1, skipped 0, cached 0")\n')
        executable.chmod(0o755)
        self.config = {'threads': 1, 'device': 0, 'replayer': str(executable), 'manual': [], 'libraries': []}
        self.games = [b.Game('steam:1', 'First Game', self.root, self.root / 'cache1',
                             archives=[self.root / 'one.foz'], shaders=2, pipelines=1, status='Ready to compile'),
                      b.Game('steam:2', 'Second Game', self.root, self.root / 'cache2',
                             archives=[self.root / 'two.foz'], shaders=3, pipelines=2, status='Ready to compile')]
        for item in (patch.object(b, 'settings', return_value=self.config),
                     patch.object(b, 'gpu_info', return_value=[{'name': 'Test GPU', 'driver': '1'}]),
                     patch.object(b, 'scan', return_value=(self.games, [])),
                     patch.object(b, 'DATA', self.root / 'data'),
                     patch.object(b, 'CONFIG', self.root / 'config')):
            item.start()
            self.addCleanup(item.stop)
        self.window = Window()
        self.window.show()
        self.wait_until(lambda: self.window.table.rowCount() == 2)
        self.addCleanup(self.window.close)

    def wait_until(self, condition):
        for _ in range(100):
            self.app.processEvents()
            if condition():
                return
            QTest.qWait(30)
        self.fail('GUI operation timed out')

    def test_navigation_search_and_queue_order(self):
        self.window.search.setText('second')
        self.assertEqual(self.window.table.rowCount(), 1)
        self.assertEqual(self.window.visible[0].id, 'steam:2')
        self.window.search.clear()
        self.window.add_all()
        self.window.add_all()
        self.assertEqual(self.window.pending, ['steam:1', 'steam:2'])
        self.window.navigate(1)
        self.assertEqual(self.window.pages.currentIndex(), 1)
        self.window.queue_table.selectRow(1)
        self.window.move_queue()
        self.assertEqual(self.window.pending, ['steam:2', 'steam:1'])
        self.window.queue_table.selectRow(0)
        self.window.remove_queue()
        self.assertEqual(self.window.pending, ['steam:1'])

    def test_queue_completes_two_real_subprocesses(self):
        self.window.add_all()
        self.window.start_queue()
        self.wait_until(lambda: not self.window.running)
        self.assertEqual(self.window.results, {'steam:1': 'Replayed', 'steam:2': 'Replayed'})
        self.assertFalse(self.window.pending)
        self.assertIn('Compile graphics', self.window.log.toPlainText())

    def test_settings_persist(self):
        self.window.libraries.setPlainText('/games/a\n/games/b')
        self.window.save_settings()
        stored = b.read_json(b.CONFIG / 'settings.json', {})
        self.assertEqual(stored['libraries'], ['/games/a', '/games/b'])


if __name__ == '__main__':
    unittest.main()
