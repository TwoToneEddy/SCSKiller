"""Original-engine controls, separate from the optional Fossilize replay backend."""
import json
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QPainter, QPen, QColor
from PySide6.QtWidgets import (QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTabWidget, QPlainTextEdit, QTableWidget, QTableWidgetItem, QHeaderView,
    QFormLayout, QSpinBox, QCheckBox, QComboBox, QMessageBox, QInputDialog,
    QPushButton, QProgressBar, QFileDialog, QLineEdit)

from .engine import EngineClient, unix_path
from .gui import label, button


class Task(QThread):
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, action):
        super().__init__()
        self.action = action

    def run(self):
        try:
            self.done.emit(self.action())
        except Exception as error:
            self.failed.emit(str(error))


class FrameChart(QWidget):
    def __init__(self):
        super().__init__()
        self.peaks = []
        self.setMinimumHeight(180)
        self.setAccessibleName('Last session frame times')

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor('#202020'))
        painter.setPen(QColor('#cccccc'))
        if not self.peaks:
            painter.drawText(self.rect(), Qt.AlignCenter, 'No recorded frame times')
            return
        maximum = max(50, max(self.peaks))
        width, height = self.width() - 20, self.height() - 35
        painter.drawText(10, 18, f'Frame-time peaks · maximum {maximum:.1f} ms')
        painter.setPen(QPen(QColor('#4cc2f1'), 1))
        for index, value in enumerate(self.peaks):
            x = 10 + index * width / max(1, len(self.peaks) - 1)
            painter.drawLine(int(x), height + 25, int(x), int(height + 25 - height * value / maximum))


class EngineDialog(QDialog):
    packet = Signal(object)

    def __init__(self, games, devices, config, parent=None, client_factory=EngineClient):
        super().__init__(parent)
        self.setWindowTitle('SCSKiller — original engine')
        self.resize(1120, 780)
        self.games, self.devices, self.config = games, devices, dict(config)
        self.client_factory = client_factory
        self.client = None
        self.tasks = []
        self.states, self.queue, self.preferences = {}, {}, {}
        outer = QVBoxLayout(self)
        outer.addWidget(label('Game shaders', 'heading'))
        outer.addWidget(label('Original SCSKiller extraction, planning and compilation through Proton. Experimental: in-game cache reuse remains unverified.', 'muted'))
        self.status = label('Starting the original engine…')
        outer.addWidget(self.status)
        self.tabs = QTabWidget()
        outer.addWidget(self.tabs, 1)
        self.make_library()
        self.make_queue()
        self.make_settings()
        self.make_account()
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(3000)
        self.tabs.addTab(self.log, 'Log')
        self.packet.connect(self.on_packet)
        QTimer.singleShot(0, self.connect_engine)

    def task(self, action, done=None):
        task = Task(action)
        self.tasks.append(task)
        task.done.connect(done or (lambda _: None))
        task.failed.connect(self.error)
        task.finished.connect(lambda: self.cleanup_task(task))
        task.start()
        return task

    def cleanup_task(self, task):
        if task in self.tasks:
            self.tasks.remove(task)
        task.deleteLater()

    def error(self, message):
        self.status.setText(message)
        self.log.appendPlainText('Error: ' + message)

    def connect_engine(self):
        def connect():
            self.client = self.client_factory(self.games, self.devices, self.config, self.packet.emit)
            return self.client.ready.result(timeout=60)
        self.task(connect, lambda _: self.call('scan', done=self.scanned))

    def call(self, method, done=None, **params):
        if self.client is None:
            self.error('The original engine is not connected')
            return
        self.task(lambda: self.client.request(method, timeout=3600, **params), done)

    def make_library(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        actions = QHBoxLayout()
        actions.addWidget(button('Refresh', lambda: self.call('rescan', done=self.scanned)))
        actions.addWidget(button('Extract shaders', lambda: self.selected_call('index', self.show_result)))
        actions.addWidget(button('Build plan', lambda: self.selected_call('plan', self.show_result)))
        actions.addWidget(button('Add to queue', lambda: self.selected_call('queue.add', self.queue_result)))
        actions.addWidget(button('Compile', lambda: self.selected_call('compile', self.queue_result), True))
        actions.addWidget(button('Play', self.play))
        layout.addLayout(actions)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(['Game', 'Engine', 'Shaders', 'Pipelines', 'Status'])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.itemSelectionChanged.connect(self.show_details)
        layout.addWidget(self.table, 1)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(130)
        layout.addWidget(self.details)
        self.chart = FrameChart()
        layout.addWidget(self.chart)
        controls = QHBoxLayout()
        controls.addWidget(button('Encryption key…', self.encryption_key))
        controls.addWidget(button('Install recorder…', self.install_recorder))
        controls.addWidget(button('Remove recorder', lambda: self.selected_call('recorder.uninstall', lambda _: self.refresh_selected())))
        controls.addWidget(button('Record alongside mod…', self.alongside))
        controls.addWidget(button('Clear recording…', self.clear_recording))
        controls.addWidget(button('Export details…', self.export_details))
        layout.addLayout(controls)
        self.tabs.addTab(widget, 'Library')

    def make_queue(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        actions = QHBoxLayout()
        for text, method in [('Start', 'queue.start'), ('Pause', 'queue.pause'), ('Resume', 'queue.resume'), ('Stop', 'queue.stop')]:
            actions.addWidget(button(text, lambda checked=False, m=method: self.call(m)))
        actions.addWidget(button('Remove selected', self.remove_queued))
        layout.addLayout(actions)
        self.queue_table = QTableWidget(0, 3)
        self.queue_table.setHorizontalHeaderLabels(['Game', 'Stage', 'Progress / outcome'])
        self.queue_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.queue_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.queue_table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.queue_table)
        self.progress = QProgressBar()
        layout.addWidget(self.progress)
        self.tabs.addTab(widget, 'Compile queue')

    def make_settings(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        form = QFormLayout()
        self.controls = {}
        for key, title, high in [('Threads', 'Compile threads', 256), ('BackgroundThreads', 'Background threads', 256),
                               ('MaxCompileMemoryGB', 'Memory limit GB (0 = automatic)', 1024),
                               ('RecordingLimitMB', 'Recording limit MB (0 = unlimited)', 65536)]:
            control = QSpinBox()
            control.setRange(0 if 'Limit' in key or 'Memory' in key else 1, high)
            form.addRow(title, control)
            self.controls[key] = control
        for key, title in [('PauseWhileGaming', 'Pause while a game is running'), ('MaximumPlans', 'Generate maximum pipeline combinations'),
                           ('UseCommunityDb', 'Use community shader database'), ('ShareRecordings', 'Share recordings anonymously (opt in)'),
                           ('NotifyNewShaders', 'Notify about new shaders')]:
            control = QCheckBox(title)
            form.addRow(control)
            self.controls[key] = control
        self.priority = QComboBox()
        self.priority.addItems(['BelowNormal', 'Idle'])
        form.addRow('Compile priority', self.priority)
        layout.addLayout(form)
        layout.addWidget(button('Save', self.save_settings, True))
        layout.addWidget(label('Linux startup and scheduling are host features. Windows cache-size controls do not configure Vulkan drivers. Automatic recorder installation remains disabled; use the per-game controls.', 'muted'))
        layout.addStretch()
        self.tabs.addTab(widget, 'Settings')

    def make_account(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        self.account_status = label('Not connected to an account')
        layout.addWidget(self.account_status)
        for text, method in [('Sign in using browser', 'account.signin'), ('Refresh account', 'account.refresh'),
                             ('Sign out', 'account.signout'), ('Sync community database', 'community.sync')]:
            layout.addWidget(button(text, lambda checked=False, m=method: self.call(m, done=self.account_result)))
        layout.addWidget(label('Uses the original account and entitlement checks. Sharing is off until explicitly enabled in Settings.', 'muted'))
        layout.addStretch()
        self.tabs.addTab(widget, 'Account')

    def account_result(self, result):
        self.call('account.status', done=lambda data: self.account_status.setText(json.dumps(data, indent=2)))
        self.show_result(result)

    def on_packet(self, packet):
        event, data = packet.get('Event'), packet.get('Data')
        if event == 'ready':
            self.status.setText('Connected · ' + data['Gpu']['Name'] + ' · ' + data['Caps']['Profile'])
            self.preferences = data['Settings']
            for key, control in self.controls.items():
                if isinstance(control, QCheckBox):
                    control.setChecked(bool(self.preferences.get(key, False)))
                else:
                    control.setValue(self.preferences.get(key, 0))
            self.priority.setCurrentText(self.preferences.get('Priority', 'BelowNormal'))
        elif event == 'log':
            self.log.appendPlainText(str(data))
        elif event == 'game':
            self.states[data['Game']['Id']] = data
            self.render_library()
        elif event == 'queue':
            self.queue[data['GameId']] = data
            self.render_queue()
        elif event == 'open-url':
            url = QUrl(data)
            if url.scheme() in ('https', 'http'):
                QDesktopServices.openUrl(url)
        elif event == 'exit':
            self.status.setText(str(data))

    def scanned(self, states):
        self.states = {s['Game']['Id']: s for s in states}
        self.render_library()
        self.status.setText(f'{len(states)} games detected by the original engine')

    def render_library(self):
        selected = self.selected_id()
        self.ids = list(self.states)
        self.table.setRowCount(len(self.ids))
        for row, key in enumerate(self.ids):
            state = self.states[key]
            plan = state.get('Plan') or {}
            count = sum(plan.get(k, 0) or 0 for k in ('Recorded', 'Generated', 'D3D11Shaders', 'MiddlewareItems'))
            values = [state['Game']['Name'], (state.get('Engine') or {}).get('Family', 'Unknown'),
                      str(state.get('ShaderCount') or '—'), str(count or '—'), state['Status']]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(state.get('StatusReason', ''))
                self.table.setItem(row, col, item)
        if self.ids:
            self.table.selectRow(self.ids.index(selected) if selected in self.ids else 0)

    def selected_id(self):
        row = self.table.currentRow()
        return self.ids[row] if hasattr(self, 'ids') and 0 <= row < len(self.ids) else None

    def selected_call(self, method, done=None, **params):
        key = self.selected_id()
        if key:
            self.call(method, done=done, game=key, **params)

    def show_details(self):
        state = self.states.get(self.selected_id())
        if state:
            game = state['Game']
            self.details.setPlainText(f'{state["StatusReason"]}\nInstall: {game["InstallDir"]}\nExecutable: {game["ExePath"]}\n'
                f'Recorder: {state.get("RecorderNote") or state.get("RecorderSkip") or state.get("RecorderInstalled")}\n'
                f'Last session: {json.dumps(state.get("LastSession"))}')
            self.chart.peaks = (state.get('LastFrames') or {}).get('Peaks', [])
            self.chart.update()

    def queue_result(self, result):
        if isinstance(result, list):
            self.queue = {item['GameId']: item for item in result}
            self.render_queue()
        self.tabs.setCurrentIndex(1)

    def render_queue(self):
        self.queue_ids = list(self.queue)
        self.queue_table.setRowCount(len(self.queue_ids))
        for row, key in enumerate(self.queue_ids):
            item = self.queue[key]
            progress = item.get('Progress') or {}
            note = item.get('Error') or item.get('Note') or f'{progress.get("Done", 0)} / {progress.get("Total", 0)} · failed {progress.get("Failed", 0)}'
            name = self.states.get(key, {}).get('Game', {}).get('Name', key)
            for col, text in enumerate([name, item['Stage'], note]):
                self.queue_table.setItem(row, col, QTableWidgetItem(text))
            if progress.get('Total'):
                self.progress.setRange(0, 1000)
                self.progress.setValue(int(1000 * progress.get('Done', 0) / progress['Total']))

    def remove_queued(self):
        row = self.queue_table.currentRow()
        if 0 <= row < len(getattr(self, 'queue_ids', [])):
            self.call('queue.remove', done=self.queue_result, game=self.queue_ids[row])

    def show_result(self, result):
        self.log.appendPlainText(json.dumps(result, indent=2))
        self.tabs.setCurrentIndex(self.tabs.count() - 1)

    def refresh_selected(self):
        self.selected_call('refresh.game', lambda state: self.on_packet({'Event': 'game', 'Data': state}))

    def save_settings(self):
        prefs = dict(self.preferences)
        for key, control in self.controls.items():
            prefs[key] = control.isChecked() if isinstance(control, QCheckBox) else control.value()
        prefs['Priority'] = self.priority.currentText()
        self.call('settings.set', settings=prefs, done=lambda data: self.status.setText('Settings saved'))

    def encryption_key(self):
        value, accepted = QInputDialog.getText(self, 'Game encryption key', 'AES key (stored locally, not logged):', QLineEdit.Password)
        if accepted and value.strip():
            self.selected_call('key.set', lambda ok: self.status.setText('Key accepted' if ok else 'Key did not decrypt this game'), key=value.strip())

    def install_recorder(self):
        if not self.config.get('use_game_prefix'):
            QMessageBox.information(self, 'Game prefix required', 'Close this window and open a recorder session from the game’s details. It uses that game’s existing Proton prefix so its recorder authorization and DLL override are in the correct place.')
            return
        if QMessageBox.question(self, 'Install recorder?', 'Install the original recorder for this game and set its per-executable Proton DLL override? Anti-cheat and mod compatibility checks still apply.') == QMessageBox.Yes:
            self.selected_call('recorder.install', lambda _: self.refresh_selected())

    def alongside(self):
        if QMessageBox.question(self, 'Record alongside a mod?', 'Allow the original recorder to chain to this game’s existing d3d12.dll mod?') == QMessageBox.Yes:
            self.selected_call('recorder.alongside', lambda _: self.refresh_selected(), enabled=True)

    def clear_recording(self):
        if QMessageBox.question(self, 'Delete recording?', 'Delete this game’s SCSKiller recording and recorded session data?') == QMessageBox.Yes:
            self.selected_call('recording.clear', lambda _: self.refresh_selected(), confirmed=True)

    def play(self):
        key = self.selected_id()
        if key and key.startswith('steam:'):
            QDesktopServices.openUrl(QUrl('steam://rungameid/' + key.split(':')[1]))

    def export_details(self):
        state = self.states.get(self.selected_id())
        if state:
            path, _ = QFileDialog.getSaveFileName(self, 'Export game details', state['Game']['Name'] + '.json', 'JSON (*.json)')
            if path:
                Path(path).write_text(json.dumps(state, indent=2) + '\n')

    def closeEvent(self, event):
        if self.client:
            self.client.close()
        for task in list(self.tasks):
            task.wait(6000)
            if task.isRunning():
                event.ignore()
                self.status.setText('Waiting for the engine to stop…')
                return
        event.accept()
