import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from concurrent.futures import Future
from pathlib import Path
import sys
import unittest
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from unittest.mock import patch
from scskiller_linux import backend as b
from scskiller_linux import core_gui
from scskiller_linux.core_gui import EngineDialog

STATE = {'Game': {'Id':'steam:1', 'Name':'Example', 'InstallDir':'Z:\\games', 'ExePath':'Z:\\games\\game.exe'},
         'Status':'Ready', 'StatusReason':'Recording available', 'Engine': {'Family':'Unreal'},
         'LastFrames':{'Peaks':[12.5, 25.0, 70.0]}}

class Client:
    def __init__(self, games, devices, config, emit):
        self.ready = Future()
        self.calls = []
        self.closed = False
        data = {'Gpu': {'Name':'Test'}, 'Caps':{'Profile':'proton-recorded-1'}, 'Settings':{'Threads':2}}
        emit({'Event':'ready', 'Data':data})
        self.ready.set_result(data)
    def request(self, method, **params):
        self.calls.append((method, params))
        if method == 'scan': return [STATE]
        if method == 'queue.add': return [{'GameId':'steam:1', 'Stage':'Pending'}]
        if method == 'settings.set': return params['settings']
        if method == 'compile': return [{'GameId':'steam:1', 'Stage':'Done', 'Progress':{'Done':3, 'Total':3, 'Failed':0}}]
        return True
    def publish_caches(self):
        self.published = True
        return {'vkd3d': {'archive':'/game/bin/vkd3d-proton.cache', 'added':3, 'existing':1},
                'nvidia': {'path':'/cache/nvidiav1', 'appName':'steamapp_shader_cache', 'bytes':2e6}}
    def close(self): self.closed = True

class CoreGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app = QApplication.instance() or QApplication([])
    def wait(self, condition):
        for _ in range(100):
            self.app.processEvents()
            if condition(): return
            QTest.qWait(20)
        self.fail('Original-engine GUI timed out')
    def test_scan_queue_settings_and_shutdown(self):
        dialog = EngineDialog([], [], {}, client_factory=Client)
        self.addCleanup(dialog.close)
        dialog.show()
        self.wait(lambda: dialog.table.rowCount() == 1)
        self.assertEqual(dialog.selected_id(), 'steam:1')
        self.assertEqual(dialog.chart.peaks, [12.5, 25.0, 70.0])
        dialog.selected_call('queue.add', dialog.queue_result)
        self.wait(lambda: dialog.queue_table.rowCount() == 1)
        self.assertEqual(dialog.queue_table.item(0, 1).text(), 'Pending')
        dialog.controls['Threads'].setValue(4)
        dialog.save_settings()
        self.wait(lambda: dialog.status.text() == 'Settings saved')
        self.assertEqual(dialog.client.calls[-1][1]['settings']['Threads'], 4)
        self.wait(lambda: not dialog.tasks)
        dialog.close()
        self.assertTrue(dialog.client.closed)

    def steam_dialog(self, profile):
        game = b.Game('steam:1', 'Example', Path('/games'), Path('/cache'), version='1')
        for target, value in (('proton_for_game', Path('/proton')), ('runtime_fingerprint', 'p')):
            mock = patch.object(core_gui, target, return_value=value)
            mock.start(); self.addCleanup(mock.stop)
        for name, value in (('load', profile), ('game_processes', [])):
            mock = patch.object(core_gui.lp, name, return_value=value)
            mock.start(); self.addCleanup(mock.stop)
        boxes = patch.object(core_gui, 'QMessageBox')
        self.box = boxes.start(); self.addCleanup(boxes.stop)
        dialog = EngineDialog([game], [{'name':'GPU'}], {}, client_factory=Client)
        self.addCleanup(dialog.close)
        self.wait(lambda: dialog.table.rowCount() == 1)
        return dialog

    def test_compile_requires_observed_steam_launch(self):
        dialog = self.steam_dialog(None)
        self.assertIn('Detect from Steam launch', dialog.launch_status.text())
        self.box.question.return_value = None
        dialog.compile()
        self.box.question.assert_called_once()
        self.assertFalse(any(c[0] == 'compile' for c in dialog.client.calls))

    def test_compile_publishes_into_game_caches(self):
        profile = {'game':'steam:1', 'build':'1', 'protonFingerprint':'p', 'driverFingerprint':b.fingerprint({'name':'GPU'}),
                   'workingDirectory':'/', 'exe':'game.exe', 'capturedAt':'2026-10-06T18:05:00',
                   'environment':{'__GL_SHADER_DISK_CACHE_PATH':'/cache/nvidiav1'}}
        dialog = self.steam_dialog(profile)
        self.assertIn('/vkd3d-proton.cache', dialog.launch_status.text())
        self.assertIs(dialog.config['launch_profile'], profile)
        dialog.compile()
        self.wait(lambda: self.box.information.called)
        self.assertTrue(dialog.client.published)
        self.assertIn('3 entries added', self.box.information.call_args[0][2])

if __name__ == '__main__': unittest.main()
