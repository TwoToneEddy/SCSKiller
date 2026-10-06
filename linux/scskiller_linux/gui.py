from __future__ import annotations

from pathlib import Path
from importlib.resources import files
import os

from PySide6.QtCore import Qt, QThread, Signal, QTimer, QUrl, QLockFile
from PySide6.QtGui import QDesktopServices, QFont, QIcon, QColor, QPixmap
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QLineEdit, QStackedWidget, QFrame, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView, QPlainTextEdit, QFileDialog,
    QSpinBox, QComboBox, QCheckBox, QFormLayout, QMessageBox, QProgressBar, QDialog, QDialogButtonBox)

from . import backend as b

STYLE = '''
QWidget { background: #272727; color: #f3f3f3; font-size: 13px; }
QMainWindow, #sidebar, #sidebar QWidget, #titlebar { background: #202020; }
QLabel { background: transparent; }
QLabel[muted="true"] { color: #c5c5c5; }
QLabel[heading="true"] { font-size: 28px; font-weight: 650; }
QLabel[big="true"] { font-size: 21px; font-weight: 600; }
QFrame[card="true"] { background: #323232; border: 1px solid #363636; border-radius: 7px; }
QPushButton { background: #363636; border: 1px solid #414141; border-radius: 4px; padding: 8px 12px; }
QPushButton:hover { background: #414141; }
QPushButton:pressed { background: #292929; }
QPushButton:disabled { color: #858585; background: #303030; border-color: #363636; }
QPushButton[accent="true"] { background: #4cc2f1; color: #10252e; border-color: #4cc2f1; }
QPushButton[accent="true"]:disabled { background: #34515c; color: #a0a0a0; border-color: #34515c; }
QPushButton[nav="true"] { text-align: left; background: transparent; border: none; padding: 12px; }
QPushButton[nav="true"]:checked { background: #303030; border-left: 3px solid #4cc2f1; }
QLineEdit, QSpinBox, QComboBox { background: #3a3a3a; border: 1px solid #555; border-radius: 4px; padding: 8px; }
QLineEdit:focus { border-bottom: 2px solid #4cc2f1; }
QTableWidget { background: #323232; border: none; gridline-color: #414141; selection-background-color: #3c4c54; }
QTableWidget::item { padding: 8px; border-bottom: 1px solid #3d3d3d; }
QHeaderView::section { background: #323232; color: #ccc; padding: 10px; border: none; border-bottom: 1px solid #444; }
QTableCornerButton::section { background: #323232; border: none; }
QPlainTextEdit { background: #202020; border: 1px solid #444; font-family: monospace; }
QProgressBar { border: none; background: #444; border-radius: 2px; max-height: 4px; }
QProgressBar::chunk { background: #4cc2f1; }
QScrollBar:vertical { background: #2b2b2b; width: 10px; }
QScrollBar::handle:vertical { background: #606060; border-radius: 5px; min-height: 25px; }
QToolTip { background: #383838; color: white; border: 1px solid #666; }
'''


def label(text, prop=None):
    widget = QLabel(text)
    widget.setWordWrap(True)
    if prop:
        widget.setProperty(prop, True)
    return widget


def button(text, callback, accent=False):
    widget = QPushButton(text)
    widget.clicked.connect(callback)
    if accent:
        widget.setProperty('accent', True)
    return widget


def page(title, note=''):
    widget = QWidget()
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(36, 28, 36, 28)
    layout.setSpacing(20)
    layout.addWidget(label(title, 'heading'))
    if note:
        layout.addWidget(label(note, 'muted'))
    return widget, layout


class ScanThread(QThread):
    result = Signal(object, object, object)
    error = Signal(str)

    def __init__(self, config):
        super().__init__()
        self.config = dict(config)

    def run(self):
        try:
            devices = b.gpu_info()
            index = self.config['device']
            driver = b.fingerprint(devices[index]) if 0 <= index < len(devices) else ''
            games, warnings = b.scan(self.config, driver)
            self.result.emit(games, devices, warnings)
        except Exception as error:
            self.error.emit(str(error))


class CompileThread(QThread):
    line = Signal(str)
    result = Signal(str, str)

    def __init__(self, game, config, driver):
        super().__init__()
        self.game, self.config, self.driver = game, dict(config), driver
        self.replay = b.Replay()

    def run(self):
        try:
            result = self.replay.run(self.game, self.config, self.driver, self.line.emit)
        except Exception as error:
            result = 'Failed: ' + str(error)
        self.result.emit(self.game.id, result)


class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.config = b.settings()
        self.games, self.devices, self.pending = [], [], []
        self.results = {}
        self.scanner = self.worker = None
        self.running = False
        self.setWindowTitle('SCSKiller — Linux')
        icon = QPixmap()
        icon.loadFromData(files(__package__).joinpath('logo.png').read_bytes())
        self.setWindowIcon(QIcon(icon))
        self.resize(1400, 900)
        self.setMinimumSize(1120, 720)
        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        title = label('  ☰    ϟ    SCSKiller   Shader Compilation Stutter Killer')
        title.setObjectName('titlebar')
        title.setFixedHeight(46)
        outer.addWidget(title)
        body = QHBoxLayout()
        body.setSpacing(0)
        outer.addLayout(body)
        sidebar = QWidget()
        sidebar.setObjectName('sidebar')
        sidebar.setFixedWidth(240)
        nav = QVBoxLayout(sidebar)
        nav.setContentsMargins(5, 5, 5, 12)
        self.nav = []
        for index, text in enumerate(('▦    Library', '☷    Compile queue', '⚙    Settings')):
            item = button(text, lambda checked=False, i=index: self.navigate(i))
            item.setProperty('nav', True)
            item.setCheckable(True)
            nav.addWidget(item)
            self.nav.append(item)
        nav.addStretch()
        self.gpu_label = label('GPU\nDetecting Vulkan devices…')
        nav.addWidget(self.gpu_label)
        about = button('ⓘ    About', lambda: self.navigate(3))
        about.setProperty('nav', True)
        about.setCheckable(True)
        nav.addWidget(about)
        self.nav.append(about)
        body.addWidget(sidebar)
        self.pages = QStackedWidget()
        body.addWidget(self.pages, 1)
        self.library_page()
        self.queue_page()
        self.settings_page()
        self.about_page()
        self.navigate(0)
        self.refresh()

    def navigate(self, index):
        self.pages.setCurrentIndex(index)
        for i, item in enumerate(self.nav):
            item.setChecked(i == index)

    def library_page(self):
        widget, layout = page('Library')
        heading = layout.takeAt(0).widget()
        actions = QHBoxLayout()
        self.summary = label('Finding installed games…', 'muted')
        titles = QVBoxLayout()
        titles.setSpacing(4)
        titles.addWidget(heading)
        titles.addWidget(self.summary)
        actions.addLayout(titles, 1)
        self.refresh_button = button('Refresh', self.refresh)
        actions.addWidget(self.refresh_button)
        actions.addWidget(button('Game shaders…', self.open_engine))
        actions.addWidget(button('Add a game…', self.add_game))
        self.all_button = button('Add all ready', self.add_all)
        actions.addWidget(self.all_button)
        self.compile_button = button('ϟ  Compile queue (0)', self.start_queue, True)
        actions.addWidget(self.compile_button)
        layout.addLayout(actions)
        cards = QHBoxLayout()
        self.card_values = []
        for title, value, note in (
            ('Steam shader cache', '—', 'Includes recordings and driver cache files'),
            ('After a driver update', 'Review and compile', 'Changed drivers mark previous replays for rebuilding'),
            ('Compile speed', str(self.config['threads']) + ' threads', 'One game at a time · cancellable')):
            card = QFrame()
            card.setProperty('card', True)
            box = QVBoxLayout(card)
            box.setContentsMargins(16, 16, 16, 16)
            box.addWidget(label(title, 'muted'))
            big = label(value, 'big')
            self.card_values.append(big)
            box.addWidget(big)
            box.addWidget(label(note, 'muted'))
            cards.addWidget(card, 1)
        layout.addLayout(cards)
        self.notice = label('Compile queue replays Vulkan recordings. Use Game shaders… for extraction and compilation from installed game files.', 'muted')
        layout.addWidget(self.notice)
        card = QFrame()
        card.setProperty('card', True)
        box = QVBoxLayout(card)
        self.search = QLineEdit()
        self.search.setPlaceholderText('Search by name or store')
        self.search.setClearButtonEnabled(True)
        self.search.setFixedHeight(36)
        self.search.setMaximumWidth(380)
        self.search.textChanged.connect(self.render)
        box.addWidget(self.search)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(['Game', 'Shaders', 'Pipelines', 'Cache', 'Time', 'Status', ''])
        self.table.verticalHeader().hide()
        self.table.setShowGrid(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        for index, width in enumerate((0, 85, 85, 85, 65, 160, 150)):
            if index:
                self.table.setColumnWidth(index, width)
        self.table.cellDoubleClicked.connect(lambda row, col: self.details(self.visible[row]))
        box.addWidget(self.table)
        layout.addWidget(card, 1)
        self.pages.addWidget(widget)

    def queue_page(self):
        widget, layout = page('Compile queue', 'Replay recorded Vulkan pipelines into the selected GPU driver’s shader cache.')
        actions = QHBoxLayout()
        actions.addWidget(button('Start queue', self.start_queue, True))
        actions.addWidget(button('Stop', self.stop_queue))
        actions.addWidget(button('Remove selected', self.remove_queue))
        actions.addWidget(button('Move up', self.move_queue))
        actions.addWidget(button('Open logs', lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(b.DATA)))))
        actions.addStretch()
        layout.addLayout(actions)
        self.queue_table = QTableWidget(0, 2)
        self.queue_table.setHorizontalHeaderLabels(['Game', 'Status'])
        self.queue_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.queue_table.verticalHeader().hide()
        self.queue_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.queue_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        layout.addWidget(self.queue_table, 1)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        layout.addWidget(self.progress)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(3000)
        layout.addWidget(self.log, 2)
        self.pages.addWidget(widget)

    def settings_page(self):
        widget, layout = page('Settings', 'Preferences are stored per user. No root access is required.')
        form = QFormLayout()
        form.setSpacing(18)
        self.threads = QSpinBox()
        self.threads.setRange(1, os.cpu_count() or 1)
        self.threads.setValue(self.config['threads'])
        form.addRow('Compile threads', self.threads)
        self.device = QComboBox()
        form.addRow('Vulkan GPU', self.device)
        self.replayer = QLineEdit(self.config['replayer'])
        self.replayer.setPlaceholderText('Auto-detect Fossilize from Steam or PATH')
        form.addRow('Fossilize replay executable', self.replayer)
        self.proton_path = QLineEdit(self.config.get('proton', ''))
        self.proton_path.setPlaceholderText('Auto-detect the game’s actual Proton; select its directory if needed')
        form.addRow('Proton directory', self.proton_path)
        self.experimental_templates = QCheckBox('Enable experimental generated DirectX pipelines (cache reuse unverified)')
        self.experimental_templates.setChecked(self.config.get('experimental_templates', False))
        form.addRow(self.experimental_templates)
        self.libraries = QPlainTextEdit('\n'.join(self.config['libraries']))
        self.libraries.setMaximumHeight(130)
        self.libraries.setPlaceholderText('Optional additional Steam library roots, one per line')
        form.addRow('Additional libraries', self.libraries)
        layout.addLayout(form)
        layout.addWidget(button('Save settings', self.save_settings, True), alignment=Qt.AlignLeft)
        layout.addWidget(label('Steam shader pre-caching supplies the recordings used here. Games with no pipeline recordings cannot be precompiled by this Linux backend.\n\nFor Flatpak Steam, discovery includes ~/.var/app/com.valvesoftware.Steam. If its bundled replay executable needs Flatpak runtime libraries, select a host Fossilize build. Vulkan tools must be installed on the host.', 'muted'))
        self.backend_label = label('', 'muted')
        layout.addWidget(self.backend_label)
        layout.addStretch()
        self.pages.addWidget(widget)

    def about_page(self):
        widget, layout = page('About', 'SCSKiller · Native Linux edition 0.1.0')
        layout.addWidget(label('Shader Compilation Stutter Killer', 'big'))
        layout.addWidget(label('A native Qt interface for CachyOS and Bazzite, following the Windows app’s navigation, library, summary cards and compile queue.\n\nThe Linux backend replays Steam or manually supplied Fossilize Vulkan pipeline recordings. Proton games use Vulkan through DXVK / vkd3d-proton. Replay coverage depends on the recordings and the active driver. A successful replay does not guarantee every pipeline was supported or that a later game will have no stutter.\n\nThe original engine is available through Game shaders when built separately. Extraction and compilation are verified for The Witcher 3 on CachyOS/NVIDIA. In-game cache reuse, recorder integration and other configurations still need validation. Windows driver controls and automatic app updates have no Linux implementation yet. The original engine can generate pipelines for supported games without Fossilize recordings; enable experimental generated pipelines in Settings.\n\nGPL-3.0-or-later. Qt for Python (PySide6) is provided under LGPLv3/GPLv3. Fossilize is a separate Valve tool under the MIT license.'))
        layout.addWidget(button('Project website', lambda: QDesktopServices.openUrl(QUrl('https://github.com/BlueHeisenberg/SCSKiller'))), alignment=Qt.AlignLeft)
        layout.addStretch()
        self.pages.addWidget(widget)

    def refresh(self):
        if self.scanner and self.scanner.isRunning():
            return
        if self.running or (self.worker and self.worker.isRunning()):
            self.notice.setText('Stop or finish the queue before refreshing the library.')
            return
        self.refresh_button.setEnabled(False)
        self.summary.setText('Checking libraries and pipeline recordings…')
        if self.scanner is not None:
            self.scanner.deleteLater()
        self.scanner = ScanThread(self.config)
        self.scanner.result.connect(self.scanned)
        self.scanner.error.connect(self.scan_error)
        self.scanner.finished.connect(lambda: self.refresh_button.setEnabled(True))
        self.scanner.start()

    def scan_error(self, text):
        self.notice.setText('Scan failed: ' + text)
        self.summary.setText('Scan failed')

    def scanned(self, games, devices, warnings):
        self.games, self.devices = games, devices
        self.device.clear()
        for index, device in enumerate(devices):
            self.device.addItem(f'{index}: {device["name"]} — {device["driver"]}')
        index = self.config['device']
        self.device.setCurrentIndex(index if index < len(devices) else -1)
        selected = devices[index] if 0 <= index < len(devices) else None
        self.gpu_label.setText(f'GPU\n{selected["name"]}\nDriver {selected["driver"]}' if selected else 'GPU\nVulkan device unavailable\nInstall vulkan-tools / vulkaninfo')
        self.backend_label.setText('Replay executable: ' + (b.find_replayer(self.config) or 'Not found'))
        self.summary.setText(f'{len(games)} games found · {sum(g.pipelines > 0 for g in games)} with pipeline recordings')
        self.card_values[0].setText(b.human_bytes(sum(g.cache_size for g in games)))
        self.notice.setText('\n'.join(warnings) if warnings else 'Linux · Vulkan replay backend. Double-click a game for details and coverage.')
        self.render()

    def render(self):
        query = self.search.text().casefold()
        self.visible = [g for g in self.games if query in (g.name + ' ' + g.store).casefold()]
        self.table.setRowCount(len(self.visible))
        for row, game in enumerate(self.visible):
            active = self.worker and self.worker.isRunning() and self.worker.game.id == game.id
            status = 'Compiling' if active else 'In queue' if game.id in self.pending else game.status
            texts = [game.name + '\n' + game.store + (' · Known to stutter' if game.known else ''),
                     f'{game.shaders:,}' if game.shaders else '—', f'{game.pipelines:,}' if game.pipelines else '—',
                     b.human_bytes(game.cache_size), f'{game.elapsed:.0f}s' if game.elapsed else '—', status]
            for col, text in enumerate(texts):
                item = QTableWidgetItem('' if col == 0 else text)
                item.setToolTip(game.reason if col == 5 else text)
                if col == 5:
                    item.setForeground(QColor('#9cdef5' if status == 'Replayed' else '#efb85b'))
                self.table.setItem(row, col, item)
            name_widget = QWidget()
            name_widget.setStyleSheet('background: transparent;')
            name_layout = QHBoxLayout(name_widget)
            name_layout.setContentsMargins(8, 8, 8, 8)
            initials = ''.join(word[0] for word in game.name.split()[:2]).upper()
            tile = label(initials)
            tile.setAlignment(Qt.AlignCenter)
            tile.setFixedSize(36, 36)
            colors = ['#3e5670', '#655075', '#326574', '#795339']
            tile.setStyleSheet('background: ' + colors[row % len(colors)] + '; border-radius: 8px; font-weight: bold;')
            name_layout.addWidget(tile)
            words = QVBoxLayout()
            words.setSpacing(3)
            name = label(game.name)
            name.setStyleSheet('font-weight: 600;')
            words.addWidget(name)
            words.addWidget(label(game.store + (' · Known to stutter' if game.known else ' · Vulkan'), 'muted'))
            name_layout.addLayout(words, 1)
            name_widget.setToolTip(game.name + '\n' + str(game.install))
            name_widget.setAttribute(Qt.WA_TransparentForMouseEvents)
            self.table.setCellWidget(row, 0, name_widget)
            self.table.setRowHeight(row, 76)
            actions = QWidget()
            actions.setStyleSheet('QWidget { background: transparent; } QPushButton { background: #363636; }')
            box = QHBoxLayout(actions)
            box.setContentsMargins(3, 12, 3, 12)
            play = button('Play', lambda checked=False, g=game: QDesktopServices.openUrl(QUrl('steam://rungameid/' + g.id.split(':')[1])))
            play.setEnabled(game.store == 'Steam')
            box.addWidget(play)
            add = button('＋', lambda checked=False, g=game: self.enqueue(g))
            add.setToolTip('Add to compile queue')
            add.setEnabled(self.can_compile(game) and game.id not in self.pending and not (self.worker and self.worker.isRunning() and self.worker.game.id == game.id))
            box.addWidget(add)
            self.table.setCellWidget(row, 6, actions)
        self.compile_button.setText(f'ϟ  Compile queue ({len(self.pending)})')
        self.compile_button.setEnabled(bool(self.pending) and not self.running)
        self.all_button.setEnabled(any(self.can_compile(g) for g in self.games))
        self.render_queue()

    def can_compile(self, game):
        return game.pipelines > 0 and game.status != 'Scan error' and bool(b.find_replayer(self.config)) and 0 <= self.config['device'] < len(self.devices)

    def enqueue(self, game):
        if game.id not in self.pending and self.can_compile(game):
            self.pending.append(game.id)
            self.results.pop(game.id, None)
        self.render()

    def add_all(self):
        for game in self.games:
            if game.status != 'Replayed' and not (self.worker and self.worker.isRunning() and self.worker.game.id == game.id):
                self.enqueue(game)

    def render_queue(self):
        self.queue_ids = list(dict.fromkeys([*self.results, *self.pending]))
        self.queue_table.setRowCount(len(self.queue_ids))
        names = {g.id: g.name for g in self.games}
        for row, game_id in enumerate(self.queue_ids):
            self.queue_table.setItem(row, 0, QTableWidgetItem(names.get(game_id, game_id)))
            self.queue_table.setItem(row, 1, QTableWidgetItem(self.results.get(game_id, 'Queued')))

    def remove_queue(self):
        row = self.queue_table.currentRow()
        if row >= 0:
            key = self.queue_ids[row]
            if key in self.pending:
                self.pending.remove(key)
            elif self.results.get(key) != 'Compiling':
                self.results.pop(key, None)
            self.render()

    def move_queue(self):
        row = self.queue_table.currentRow()
        if row >= 0 and self.queue_ids[row] in self.pending:
            index = self.pending.index(self.queue_ids[row])
            if index > 0:
                self.pending[index-1], self.pending[index] = self.pending[index], self.pending[index-1]
                self.render_queue()

    def start_queue(self):
        self.navigate(1)
        if self.running or (self.worker and self.worker.isRunning()) or not self.pending or (self.scanner and self.scanner.isRunning()):
            return
        self.running = True
        self.next_job()

    def next_job(self):
        if not self.running or not self.pending:
            self.running = False
            self.progress.setRange(0, 1)
            self.progress.setValue(1)
            self.render()
            self.refresh()
            return
        key = self.pending.pop(0)
        game = next((g for g in self.games if g.id == key), None)
        if game is None or not self.can_compile(game):
            self.results[key] = 'Unavailable — refresh the library'
            QTimer.singleShot(0, self.next_job)
            return
        self.results[key] = 'Compiling'
        self.log.appendPlainText('\n—— ' + game.name + ' ——')
        self.progress.setRange(0, 0)
        driver = b.fingerprint(self.devices[self.config['device']])
        if self.worker is not None:
            self.worker.deleteLater()
        self.worker = CompileThread(game, self.config, driver)
        self.worker.line.connect(self.replay_line)
        self.worker.result.connect(self.compiled)
        self.worker.finished.connect(self.next_job)
        self.worker.start()
        self.render()

    def replay_line(self, text):
        self.log.appendPlainText(text)
        import re
        match = re.search(r'Overall (\d+) / (\d+)', text)
        if match and int(match[2]) > 0:
            self.progress.setRange(0, int(match[2]))
            self.progress.setValue(int(match[1]))

    def compiled(self, key, result):
        self.results[key] = result
        self.log.appendPlainText(result)
        self.render_queue()

    def stop_queue(self):
        self.running = False
        if self.worker and self.worker.isRunning():
            self.worker.replay.cancel()
        self.render()

    def save_settings(self):
        if self.running or (self.worker and self.worker.isRunning()):
            QMessageBox.information(self, 'Compile in progress', 'Stop or finish the queue before changing its settings.')
            return
        self.config.update(threads=self.threads.value(), device=max(0, self.device.currentIndex()),
                           replayer=self.replayer.text().strip(),
                           proton=self.proton_path.text().strip(),
                           experimental_templates=self.experimental_templates.isChecked(),
                           libraries=[p.strip() for p in self.libraries.toPlainText().splitlines() if p.strip()])
        b.write_json(b.CONFIG / 'settings.json', self.config)
        self.card_values[2].setText(str(self.config['threads']) + ' threads')
        self.refresh()

    def open_engine(self, checked=False, game=None, recorder=False):
        if self.running:
            QMessageBox.information(self, 'Replay in progress', 'Stop or finish Vulkan replay before opening the original engine.')
            return
        if game is None:
            row = self.table.currentRow()
            game = self.visible[row] if 0 <= row < len(self.visible) else self.games[0] if self.games else None
        if game is None:
            QMessageBox.information(self, 'No game selected', 'Add or install a game first.')
            return
        from .core_gui import EngineDialog
        config = dict(self.config)
        if recorder:
            if QMessageBox.question(self, 'Use this game’s Proton prefix?',
                    'Open the original engine in this game’s existing prefix? Recorder actions can then set a per-executable DLL override and authorize recording. Close the game first.') != QMessageBox.Yes:
                return
            config['use_game_prefix'] = True
        dialog = EngineDialog([game], self.devices, config, self)
        dialog.exec()
        if dialog.config.get('experimental_templates', False) != self.config.get('experimental_templates', False):
            self.config['experimental_templates'] = dialog.config['experimental_templates']
            self.experimental_templates.setChecked(self.config['experimental_templates'])
            b.write_json(b.CONFIG / 'settings.json', self.config)

    def add_game(self):
        if self.running:
            return
        paths, _ = QFileDialog.getOpenFileNames(self, 'Add Vulkan pipeline recordings', str(Path.home()), 'Fossilize archives (*.foz)')
        if not paths:
            return
        try:
            entries = set().union(*(b.archive_entries(p) for p in paths))
            if not any(tag in (6, 7, 9) for tag, _ in entries):
                raise ValueError('The selected archives contain no Vulkan pipelines.')
            import hashlib
            key = 'manual:' + hashlib.sha256('\n'.join(sorted(paths)).encode()).hexdigest()[:16]
            dialog = QDialog(self)
            dialog.setWindowTitle('Add a game')
            form = QFormLayout(dialog)
            name = QLineEdit(Path(paths[0]).parent.name)
            form.addRow('Game name', name)
            note = label('Select the cache directory used by this game’s Vulkan driver. For non-Steam games, use the same NVIDIA / Mesa cache environment when launching the game.')
            form.addRow(note)
            cache = QLineEdit(str(Path(paths[0]).parent))
            form.addRow('Driver cache root', cache)
            buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            buttons.accepted.connect(dialog.accept)
            buttons.rejected.connect(dialog.reject)
            form.addRow(buttons)
            if dialog.exec() != QDialog.Accepted or not name.text().strip():
                return
            cache_path = Path(cache.text()).expanduser()
            if not cache_path.is_absolute():
                raise ValueError('The cache root must be an absolute path.')
            self.config['manual'] = [x for x in self.config['manual'] if x['id'] != key]
            self.config['manual'].append({'id': key, 'name': name.text().strip(), 'install': str(Path(paths[0]).parent),
                                         'cache': str(cache_path), 'archives': paths})
            b.write_json(b.CONFIG / 'settings.json', self.config)
            self.refresh()
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, 'Cannot add recordings', str(error))

    def details(self, game):
        dialog = QDialog(self)
        dialog.setWindowTitle(game.name)
        dialog.resize(760, 500)
        layout = QVBoxLayout(dialog)
        layout.addWidget(label(game.name, 'heading'))
        text = QPlainTextEdit()
        text.setReadOnly(True)
        text.setPlainText(f'{game.status}\n{game.reason}\n\nInstall: {game.install}\nCache: {game.cache}\n'
                          f'Shaders: {game.shaders:,}\nPipelines: {game.pipelines:,}\n\nRecordings:\n' + '\n'.join(map(str, game.archives)))
        layout.addWidget(text)
        layout.addWidget(button('Game shaders — original engine', lambda: (dialog.accept(), self.open_engine(game=game))))
        layout.addWidget(button('Recorder session…', lambda: (dialog.accept(), self.open_engine(game=game, recorder=True))))
        layout.addWidget(button('Open game folder', lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(game.install)))))
        queue = button('Add to compile queue', lambda: (self.enqueue(game), dialog.accept()), True)
        queue.setEnabled(self.can_compile(game))
        layout.addWidget(queue)
        dialog.exec()

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            if QMessageBox.question(self, 'Stop compilation?', 'Stop the active replay and close SCSKiller?') != QMessageBox.Yes:
                event.ignore()
                return
            self.running = False
            self.worker.replay.cancel()
            self.worker.wait(5000)
            if self.worker.isRunning():
                event.ignore()
                return
        if self.scanner and self.scanner.isRunning():
            self.scanner.wait()
        event.accept()


def main(screenshot=None):
    app = QApplication.instance() or QApplication([])
    app.setApplicationName('SCSKiller')
    app.setDesktopFileName('scskiller')
    app.setFont(QFont('Noto Sans', 10))
    app.setStyleSheet(STYLE)
    b.DATA.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(b.DATA / 'gui.lock'))
    if not lock.tryLock(0):
        message = ('Another SCSKiller window is already open.' if lock.error() == QLockFile.LockFailedError
                   else f'Cannot create the application lock in {b.DATA}. Check directory permissions.')
        if screenshot:
            print(message, file=__import__('sys').stderr)
        else:
            QMessageBox.information(None, 'SCSKiller could not start', message)
        return 1
    window = Window()
    window.show()
    if screenshot:
        def capture():
            if window.scanner and window.scanner.isRunning():
                QTimer.singleShot(300, capture)
                return
            window.grab().save(screenshot)
            app.quit()
        QTimer.singleShot(1500, capture)
    return app.exec()
