import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from concurrent.futures import Future
from pathlib import Path
import sys
import unittest
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
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
        return True
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

if __name__ == '__main__': unittest.main()
