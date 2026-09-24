"""Four-pane Atlas workspace with named views, pinned settings and probe overlays."""
import json
from copy import deepcopy
from pathlib import Path
import numpy as np
from PySide6 import QtCore as C, QtGui as G, QtWidgets as W
import bootstrap
import acoustics as ac
from app import Atlas, STYLE, label, button, number
from panes import PlotPane, DEFAULT, TITLES, SPECS, editor, setting_keys, default_config
from analysis_metrics import cea2034, reference_axis
from worker_pool import WarmPool
from preferences import studio_settings


class ViewButton(W.QPushButton):
    """A normal click selects; holding for 450 ms enables live reordering."""
    def __init__(self, name, owner):
        super().__init__(name)
        self.owner = owner; self.view_name = name; self.reordering = False
        self.setCheckable(True)
        self.setToolTip('Click to select. Hold and drag to reorder. Right-click to rename or delete.')
        self.hold = C.QTimer(self); self.hold.setSingleShot(True); self.hold.setInterval(450)
        self.hold.timeout.connect(self.start_reorder)
        self.clicked.connect(lambda: owner.load_view(self.view_name))

    def start_reorder(self):
        if not self.isDown(): return
        self.reordering = True; self.setDown(False); self.setCursor(C.Qt.ClosedHandCursor)

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        if event.button() == C.Qt.LeftButton: self.hold.start()

    def mouseMoveEvent(self, event):
        if self.reordering:
            parent = self.parentWidget()
            x = parent.mapFromGlobal(event.globalPosition().toPoint()).x()
            others = [name for name in self.owner.views if name != self.view_name]
            index = sum(x > self.owner.view_buttons[name].geometry().center().x() for name in others)
            others.insert(index, self.view_name)
            if others != list(self.owner.views):
                self.owner.views = {name: self.owner.views[name] for name in others}
                self.owner.view_bar.removeWidget(self); self.owner.view_bar.insertWidget(index, self)
            event.accept(); return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self.hold.stop()
        if self.reordering:
            self.reordering = False; self.setDown(False); self.unsetCursor()
            self.owner.select_view_name(self.owner.current_view)
            event.accept(); return
        super().mouseReleaseEvent(event)


class PanePositionIcon(W.QWidget):
    """Four-pane position marker with a 4:3 outline."""
    def __init__(self, index):
        super().__init__()
        self.index = index
        self.setFixedSize(28, 22)
        self.setToolTip(('Top left', 'Top right', 'Bottom left', 'Bottom right')[index])

    def paintEvent(self, event):
        painter = G.QPainter(self)
        colour = self.palette().color(G.QPalette.WindowText)
        painter.setPen(G.QPen(colour, 1))
        left, top, width, height = 2, 2, 24, 18
        painter.fillRect(C.QRectF(left+(self.index % 2)*width/2, top+(self.index // 2)*height/2, width/2, height/2), colour)
        painter.drawRect(C.QRectF(left, top, width, height))
        painter.drawLine(C.QPointF(left+width/2, top), C.QPointF(left+width/2, top+height))
        painter.drawLine(C.QPointF(left, top+height/2), C.QPointF(left+width, top+height/2))


class Workspace(Atlas):
    def __init__(self, start_pool=True, settings=None):
        W.QMainWindow.__init__(self)
        self.setWindowTitle('HALS Studio')
        self.project_path = None; self.theme_name = 'Dark'
        self.overlay_shortcut = G.QShortcut(G.QKeySequence('Ctrl+A'), self)
        self.overlay_shortcut.activated.connect(lambda: self.export_workspace.response_panel.add_overlay() if self.workspace_mode.currentData() == 1 else self.capture_overlay() if self.workspace_mode.currentData()==0 else None)
        self.resize(1640, 1000); self.setMinimumSize(1000, 680); self.setStyleSheet(STYLE)
        self.setWindowIcon(G.QIcon(str(bootstrap.HERE / 'studio.ico')))
        self.sphere = None; self.source_path = self.source_options = None
        self.worker = self.pending_session = None
        self.axis = (0., 0.); self.axis_source = None
        self.overlays = []; self.overlay_revision = 0
        self.level_cache = {}; self.cea_cache = {}
        self.settings = settings if settings is not None else studio_settings()
        self.pool = WarmPool(workers=int(self.settings.value('worker_count',0)) or None)
        if start_pool: self.pool.start()
        self.play_timer = C.QTimer(self); self.play_timer.setInterval(180); self.play_timer.timeout.connect(self.advance)
        self.refresh_timer = C.QTimer(self); self.refresh_timer.setSingleShot(True); self.refresh_timer.setInterval(70)
        self.refresh_timer.timeout.connect(self.refresh)
        self.pool_timer = C.QTimer(self); self.pool_timer.setInterval(400); self.pool_timer.timeout.connect(self.pool_status)
        self.pool_timer.start()
        self.settings = settings if settings is not None else studio_settings()
        self.views = self.template_views()
        self._build_workspace(); self._menus()
        self.menuBar().setStyleSheet('QMenuBar { border-bottom: 1px solid rgba(150, 170, 190, 65); }')
        file_menu = self.menuBar().actions()[0].menu(); file_menu.clear()
        file_menu.addAction('Open data...', self.open_data, G.QKeySequence('Ctrl+O'))
        file_menu.addAction('Analysis Import Settings', self.analysis_import_settings)
        file_menu.addAction('Save Project', self.save_project, G.QKeySequence('Ctrl+S'))
        file_menu.addAction('Preferences...', self.preferences)
        workspace_menu = file_menu.addMenu('Workspace')
        for index, name in ((2, 'Process'), (0, 'Analysis'), (1, 'Export')):
            workspace_menu.addAction(name, lambda checked=False, i=index: self.set_workspace(i))
        file_menu.addSeparator(); file_menu.addAction('Exit', self.close, G.QKeySequence('Alt+F4'))
        self.setAcceptDrops(True); self.set_sphere(self.sphere)
        last = self.settings.value('last_view', 'Sound field')
        if last not in self.views: last = next(iter(self.views))
        self.apply_view(self.views[last]); self.select_view_name(last)
        self.set_theme(self.settings.value('theme', 'Dark'))
        # Export embeds a native VTK window. Creating it after this QMainWindow
        # has been shown makes Qt briefly hide and recreate the top-level HWND
        # while native child windows are attached. Build it during startup so
        # opening a project or switching to Export cannot flash the whole app.
        from project_ui import ensure_export
        ensure_export(self)
        self.set_workspace(int(self.settings.value('default_workspace', 0)))

    @staticmethod
    def default_views():
        result = {}
        for name, kinds in {'Sound field': ['balloon', 'probe', 'polar', 'map_h'],
                            'Directivity': ['cross_sonograms', 'map_h', 'map_v', 'di'],
                            'Globes': ['globe_hv', 'cross_sonograms', 'polar', 'probe'],
                            'CEA2034': ['cea', 'reflections', 'cea_Sound power DI', 'cea_Early reflections DI']}.items():
            configs = [default_config(k) for k in kinds]
            for config in configs:
                if config['kind'] != 'probe': config['phase_mode'] = 'None'
            if name == 'Sound field': configs[0]['pins'] = ['normalization', 'span', 'geometry']
            result[name] = dict(version=2, panes=configs, outer=[600, 380], rows=[[700, 800], [700, 800]])
        return result

    @staticmethod
    def valid_view(view):
        return isinstance(view, dict) and len(view.get('panes', [])) == 4 and all(p.get('kind') in (*TITLES, 'volume', 'globe_h', 'globe_v') for p in view['panes'])

    def _build_workspace(self):
        root = W.QWidget(); self.setCentralWidget(root); layout = W.QVBoxLayout(root)
        head = W.QHBoxLayout(); self.header_layout = head; layout.addLayout(head)
        brand = label('HALS Studio', 'brand'); self.brand_label = brand; brand.setFixedWidth(245); head.addWidget(brand)
        self.open_button = button('+  Open data', self.open_data, True); head.addWidget(self.open_button)
        self.project_path_field = W.QLineEdit(); self.project_path_field.setReadOnly(True); self.project_path_field.setPlaceholderText('Project folder or coefficient file')
        head.addWidget(self.project_path_field, 1); head.addWidget(button('Save Project', self.save_project))
        self.workspace_mode = W.QComboBox()
        for name, key in [('Process', 2), ('Analysis', 0), ('Export', 1)]: self.workspace_mode.addItem(name, key)
        self.workspace_mode.setCurrentIndex(1)
        self.workspace_mode.currentIndexChanged.connect(lambda _: self.switch_workspace(self.workspace_mode.currentData()))
        self.export_workspace = None; self.export_setup = None; self.process_workspace = None; self.process_toolbar = None
        self.badge = label(''); self.badge.setParent(root); self.badge.hide()
        modebar = W.QHBoxLayout(); self.modebar=modebar; mode_label = W.QWidget(); mode_row = W.QHBoxLayout(mode_label); mode_row.setContentsMargins(0, 0, 0, 0); mode_row.addWidget(label('Workspace')); mode_row.addWidget(self.workspace_mode); mode_row.addStretch(); self.mode_label = mode_label; mode_label.setFixedWidth(245); modebar.addWidget(mode_label); layout.addLayout(modebar)
        self.workspace_stack = W.QStackedWidget(); layout.addWidget(self.workspace_stack, 1)
        analysis = W.QWidget(); body = W.QHBoxLayout(analysis); body.setContentsMargins(0, 0, 0, 0)
        self.workspace_stack.addWidget(analysis)
        self.analysis_split = W.QSplitter(C.Qt.Horizontal)
        self.analysis_split.setHandleWidth(7); self.analysis_split.setChildrenCollapsible(False)
        body.addWidget(self.analysis_split)
        scroll = W.QScrollArea(); scroll.setWidgetResizable(True); scroll.setMinimumWidth(150); scroll.setFrameShape(W.QFrame.NoFrame); self.analysis_scroll = scroll
        scroll.setHorizontalScrollBarPolicy(C.Qt.ScrollBarAlwaysOff)
        sidebar = W.QWidget(); self.sidebar = W.QVBoxLayout(sidebar); self.sidebar.setContentsMargins(4, 4, 12, 4); self.sidebar.setSizeConstraint(W.QLayout.SetNoConstraint); sidebar.setMinimumWidth(0); scroll.setWidget(sidebar); self.analysis_split.addWidget(scroll)
        self.dataset_label = label('', 'eyebrow'); self.dataset_label.setWordWrap(True); self.dataset_label.setStyleSheet('font-size:14px;font-weight:600;letter-spacing:0px;color:#52d9ec;'); self.dataset_info = label('', 'muted'); self.dataset_info.setWordWrap(True)
        self.sidebar.addWidget(self.dataset_label); self.sidebar.addWidget(self.dataset_info)
        group = W.QGroupBox(); form = W.QVBoxLayout(group); self.sidebar.addWidget(group); form.addWidget(label('FREQUENCY', 'muted'))
        self.frequency_label = label('', 'hero'); form.addWidget(self.frequency_label)
        self.frequency = W.QSlider(C.Qt.Horizontal); self.frequency.valueChanged.connect(self.schedule); form.addWidget(self.frequency)
        row = W.QHBoxLayout(); form.addLayout(row)
        row.addWidget(button('‹', lambda: self.frequency.setValue(max(0, self.frequency.value()-1))))
        self.play = button('▶ Sweep', self.toggle_play); self.play.setCheckable(True); row.addWidget(self.play)
        row.addWidget(button('›', self.advance))
        self.frequency_entry = number(1000, .1, 1000000, ' Hz'); self.frequency_entry.valueChanged.connect(self.jump_frequency)
        group.hide(); self.frequency_group=group
        form.addWidget(self.frequency_entry); self.bin_label = label('', 'muted'); self.bin_label.setWordWrap(True); form.addWidget(self.bin_label)
        self.axis_label = label('', 'muted'); self.axis_label.setWordWrap(True); self.axis_label.hide()
        self.pinned = W.QWidget(); self.pinned_layout = W.QVBoxLayout(self.pinned); self.pinned_layout.setContentsMargins(0, 0, 0, 0)
        from mic_calibration import build as build_mic_calibration
        build_mic_calibration(self)
        self.sidebar.addWidget(self.pinned)
        from mic_calibration import show_dialog as show_calibration
        self.sidebar.addWidget(button('Calibration', lambda: show_calibration(self)))
        self.sidebar.addWidget(button('Overlays…', self.overlay_dialog))
        self.sidebar.addStretch()
        plot_area = W.QWidget(); plot_area.setMinimumWidth(400)
        content = W.QVBoxLayout(plot_area); content.setContentsMargins(0, 0, 0, 0)
        self.analysis_plot_area = plot_area
        plot_area.installEventFilter(self)
        self.analysis_split.addWidget(plot_area)
        self.analysis_split.setStretchFactor(0, 0); self.analysis_split.setStretchFactor(1, 1)
        analysis_width = int(self.settings.value('analysis_sidebar_width', 245))
        self.analysis_split.setSizes([analysis_width, 1350])
        self.analysis_split.splitterMoved.connect(lambda *_: self.settings.setValue('analysis_sidebar_width', self.analysis_split.sizes()[0]))
        self.azimuth = number(0, -180, 180, '°'); self.elevation = number(0, -90, 90, '°')
        # Shared probe state; each balloon supplies its own visible editors.
        for widget in (self.azimuth, self.elevation):
            widget.setParent(root); widget.hide()
        self.azimuth.valueChanged.connect(self.schedule); self.elevation.valueChanged.connect(self.schedule)
        self.views_toolbar = W.QWidget(); bar = W.QHBoxLayout(self.views_toolbar); bar.setContentsMargins(0, 0, 0, 0); modebar.addWidget(self.views_toolbar, 1); modebar.addStretch()
        self.view_bar = W.QHBoxLayout(); bar.addLayout(self.view_bar); bar.addSpacing(80)
        self.reset_views_button = W.QToolButton(); self.reset_views_button.setText('Save Viewport'); self.reset_views_button.setObjectName('resetViewsButton')
        self.reset_views_button.setPopupMode(W.QToolButton.MenuButtonPopup)
        self.reset_views_button.clicked.connect(self.save_viewport)
        menu = W.QMenu(self.reset_views_button); menu.addAction('Reset views', self.reset_views); menu.addAction('Save as default template...', self.save_default_template)
        self.reset_views_button.setMenu(menu); bar.addWidget(self.reset_views_button); bar.addStretch()
        self.outer = W.QSplitter(C.Qt.Vertical); self.outer.setHandleWidth(7); content.addWidget(self.outer, 1)
        self.rows, self.panes = [], []
        for row in range(2):
            split = W.QSplitter(C.Qt.Horizontal); split.setHandleWidth(7); split.setChildrenCollapsible(False)
            self.rows.append(split); self.outer.addWidget(split)
            for col in range(2):
                pane = PlotPane(self, row*2+col, ['balloon', 'probe', 'polar', 'map_h'][row*2+col])
                split.addWidget(pane); self.panes.append(pane)
        self.outer.setChildrenCollapsible(False)
        self.progress = W.QProgressBar(); self.progress.setFixedWidth(200); self.progress.hide()
        self.cancel_button = button('Cancel', self.cancel_load); self.cancel_button.hide()
        self.worker_label = label('', 'muted')
        self.statusBar().addPermanentWidget(self.progress); self.statusBar().addPermanentWidget(self.cancel_button)
        self.statusBar().addPermanentWidget(self.worker_label); self.rebuild_view_buttons()

    def get_levels(self, smoothing):
        if smoothing not in self.level_cache:
            octave = {'None': 0, '1/24 octave': 24, '1/12 octave': 12, '1/6 octave': 6, '1/3 octave': 3}[smoothing]
            from mic_calibration import config as shared_config
            self.level_cache[smoothing] = self.sphere.levels(octave) + shared_config(self)['frd_db_offset']
        return self.level_cache[smoothing]

    def preferences(self):
        import os
        dialog=W.QDialog(self);dialog.setWindowTitle('Preferences');form=W.QFormLayout(dialog)
        theme = W.QComboBox(); theme.addItems(['Dark', 'Light']); theme.setCurrentText(self.theme_name); form.addRow('Theme', theme)
        folder = W.QLineEdit(str(self.settings.value('browse_folder', '')))
        folder.setPlaceholderText('Current project folder, otherwise home')
        folder_row = W.QWidget(); row = W.QHBoxLayout(folder_row); row.setContentsMargins(0,0,0,0); row.addWidget(folder)
        def browse():
            path = W.QFileDialog.getExistingDirectory(dialog, 'Default browse folder', folder.text() or str(Path.home()))
            if path: folder.setText(path)
        row.addWidget(button('Browse...', browse)); form.addRow('Default browse folder', folder_row)
        workspace = W.QComboBox()
        for name, key in [('Process', 2), ('Analysis', 0), ('Export', 1)]: workspace.addItem(name, key)
        workspace.setCurrentIndex(workspace.findData(int(self.settings.value('default_workspace', 0))))
        form.addRow('Startup workspace', workspace)
        form.addRow(W.QLabel('Saved projects reopen in their last saved workspace.'))
        count=W.QSpinBox();count.setRange(1,61);count.setValue(self.pool.workers);form.addRow('Worker processes',count)
        note=W.QLabel(f'{os.cpu_count()} logical CPUs detected. Default: {max(1,(os.cpu_count() or 2)//2)} workers.\nMore workers are not always faster; performance depends on the CPU and workload.');note.setWordWrap(True);form.addRow(note)
        status=W.QLabel();status.setWordWrap(True);form.addRow(status)
        buttons=W.QDialogButtonBox(W.QDialogButtonBox.Save|W.QDialogButtonBox.Cancel);form.addRow(buttons);buttons.rejected.connect(dialog.reject)
        def apply():
            busy=(self.worker and self.worker.isRunning()) or (self.export_workspace and self.export_workspace.job) or (self.process_workspace and self.process_workspace.job)
            if busy and self.pool.workers!=count.value():status.setText('Wait for the current calculation to finish before changing workers.');return
            if folder.text().strip() and not Path(folder.text().strip()).is_dir():
                status.setText('Choose an existing browse folder.'); return
            self.settings.setValue('browse_folder', folder.text().strip())
            self.settings.setValue('default_workspace', workspace.currentData())
            self.settings.setValue('theme', theme.currentText()); self.set_theme(theme.currentText())
            self.settings.setValue('worker_count',count.value())
            if self.pool.workers!=count.value():self.pool.close();self.pool=WarmPool(count.value());self.pool.start()
            dialog.accept()
        buttons.accepted.connect(apply);dialog.resize(420,200);dialog.exec()

    def set_workspace(self, key):
        self.workspace_mode.setCurrentIndex(self.workspace_mode.findData(key))

    def switch_workspace(self, index):
        self.views_toolbar.setVisible(index == 0)
        if index == 0: C.QTimer.singleShot(0, self.align_view_toolbar)
        if index==2:
            self.play_timer.stop();self.play.setChecked(False)
            if self.process_workspace is None:
                from process_workspace import ProcessWorkspace
                self.process_workspace=ProcessWorkspace(self);self.workspace_stack.addWidget(self.process_workspace)
                self.process_toolbar=self.process_workspace.toolbar
                self.modebar.insertWidget(2,self.process_toolbar,1)
            self.process_toolbar.show();self.workspace_stack.setCurrentWidget(self.process_workspace);self.process_workspace.adopt_project();return
        if self.process_toolbar:self.process_toolbar.hide()
        if index == 1:
            self.play_timer.stop(); self.play.setChecked(False)
            if self.export_workspace is None:
                from export_workspace import ExportWorkspace
                self.export_workspace = ExportWorkspace(self); self.workspace_stack.addWidget(self.export_workspace)
                if self.export_setup: self.export_workspace.apply_config(self.export_setup)
            self.workspace_stack.setCurrentWidget(self.export_workspace)
            self.badge.setText('HALS / STAGE 5'); self.open_button.setText('+  Open data')
            self.export_workspace.adopt_source(); self.export_workspace.preview_if_live()
        else:
            self.workspace_stack.setCurrentIndex(0); self.open_button.setText('+  Open data')
            self.badge.setText('HALS / COMPLEX FIELD')

    def analysis_import_settings(self):
        from app import ReconstructionDialog
        if self.worker and self.worker.isRunning():
            self.statusBar().showMessage('Wait for reconstruction to finish or cancel it before changing import settings.'); return
        source = self.source_path or (self.sphere.metadata.get('source') if self.sphere is not None else None)
        if not source or Path(source).suffix.lower() not in ('.h5', '.hdf5'):
            W.QMessageBox.information(self, 'Analysis Import Settings', 'Open a coefficient file or a project with coefficients first.'); return
        try:
            dialog = ReconstructionDialog(source, self)
            dialog.setWindowTitle('Analysis Import Settings')
            options = self.source_options or {}
            for key in ('radius', 'fmin', 'fmax', 'padding'):
                if key in options: getattr(dialog, key).setValue(options[key])
            if options.get('step') in (5, 10, 3, 2): dialog.step.setCurrentIndex([5, 10, 3, 2].index(options['step']))
            if options.get('bins') in dialog.bin_counts: dialog.bins.setCurrentIndex(dialog.bin_counts.index(options['bins']))
            if 'mode' in options: dialog.mode.setCurrentText(options['mode'])
            if 'origins' in options: dialog.origins.setChecked(options['origins'])
            for field, value in zip(dialog.offsets, options.get('offset', [])): field.setValue(value)
            dialog.update_sampling()
            if dialog.exec() != W.QDialog.Accepted: return
            options = dialog.options()
            ac.select_frequencies(dialog.native_freqs, options['bins'], options['fmin'], options['fmax'])
            # Bypass project opening: retain the current project, views and calibration.
            Atlas.open_path(self, source, options)
        except (OSError, ValueError, KeyError) as exc:
            self.error(str(exc))

    def open_data(self):
        self.open_data_file()

    def open_data_file(self):
        from project_ui import choose_data
        path = choose_data(self)
        if path: self.open_path(path)

    def open_project_folder(self):
        start = str(Path(self.project_path).parent) if self.project_path else str(Path.home())
        folder = W.QFileDialog.getExistingDirectory(self, 'Open HALS project folder', start)
        if folder: self.open_path(folder)

    def open_path(self, path, options=None):
        from project_ui import open_data_path
        open_data_path(self, path, options)

    def open_export_project(self): self.open_data()

    def open_folder(self):
        path = W.QFileDialog.getExistingDirectory(self, 'Select a full-sphere Stage 5 complex export')
        if path: Atlas.open_path(self, path)


    def save_project(self):
        from project_ui import save_project
        save_project(self)

    def set_theme(self, name):
        from viewer_theme import apply_theme
        apply_theme(self, name)

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if urls: self.open_path(urls[0].toLocalFile()); event.acceptProposedAction()

    def get_cea(self, smoothing):
        key = (smoothing, self.axis)
        if key not in self.cea_cache: self.cea_cache[key] = cea2034(self.sphere, self.get_levels(smoothing), self.axis)
        return self.cea_cache[key]

    def set_sphere(self, sphere):
        self.play_timer.stop(); self.play.setChecked(False); self.play.setText('▶ Sweep')
        self.sphere = sphere; self.level_cache.clear(); self.cea_cache.clear()
        for control in (self.frequency, self.frequency_entry, self.play): control.setEnabled(sphere is not None)
        if sphere is None:
            self.source_path = self.source_options = None
            self._mic_sphere = self._mic_raw = self._mic_key = None
            self.axis = (0., 0.); self.axis_source = None
            self.dataset_label.setText(Path(self.project_path).stem.replace('_project', '') if self.project_path else 'No data loaded')
            self.dataset_info.setText('No coefficients loaded'); self.dataset_info.setToolTip('')
            self.frequency_label.setText(''); self.bin_label.setText('')
            self.update_axis_label()
            for pane in self.panes: pane.invalidate()
            self.refresh()
            return
        self.frequency.blockSignals(True); self.frequency.setRange(0, len(sphere.freqs)-1)
        self.frequency.setValue(int(np.argmin(abs(sphere.freqs-1000)))); self.frequency.blockSignals(False)
        self.dataset_label.setText(Path(self.project_path).stem.replace('_project','') if self.project_path else sphere.name.upper())
        self.dataset_info.setText(f'{len(sphere.freqs):,} frequencies · {len(sphere.elevation)*len(sphere.azimuth):,} directions\n'
                                 f'{sphere.freqs[0]:,.1f}–{sphere.freqs[-1]:,.1f} Hz')
        self.badge.setText('SYNTHETIC DEMO' if sphere.metadata.get('demo') else 'HALS / COMPLEX FIELD')
        self.axis = (0., 0.); self.axis_source = None
        source = sphere.metadata.get('source') or self.source_path
        if source and not sphere.metadata.get('demo'):
            self.dataset_info.setText(Path(source).name + '\n' + self.dataset_info.text())
            self.dataset_info.setToolTip(str(source))
        else:
            self.dataset_info.setToolTip('')
        if source and not sphere.metadata.get('demo'):
            base = Path(source).parent
            for parent in [base, *list(base.parents)[:2]]:
                candidates = list(parent.glob('*project.json'))
                valid = []
                for candidate in candidates:
                    try: valid.append((candidate, reference_axis(candidate)))
                    except (ValueError, OSError): pass
                if len(valid) == 1:
                    self.axis_source, self.axis = str(valid[0][0]), valid[0][1]; break
                if len(valid) > 1: break  # Ambiguous: user can explicitly select the project.
        self.update_axis_label()
        for pane in self.panes: pane.invalidate()
        self.refresh(); self.statusBar().showMessage(f'Loaded {sphere.name} · original complex pressure preserved')

    def update_axis_label(self):
        self.axis_label.setText(f'Reference axis H {self.axis[0]:g}° / V {self.axis[1]:g}°\n'+
                               (Path(self.axis_source).name if self.axis_source else '+X default · no project axis loaded'))
        self.axis_label.setToolTip(self.axis_source or 'File → Load HALS project reference axis')

    def load_axis(self):
        path, _ = W.QFileDialog.getOpenFileName(self, 'HALS project reference axis', '', 'Project JSON (*.json)')
        if path:
            try:
                self.axis = reference_axis(path); self.axis_source = path; self.cea_cache.clear(); self.update_axis_label(); self.schedule()
            except Exception as exc: self.error(str(exc))

    def refresh(self):
        # Plot refreshes can synchronously render VTK/Matplotlib widgets. While
        # a splitter is being dragged, defer them until the pointer is released
        # to avoid recursive Qt paints during repeated resize events.
        if W.QApplication.mouseButtons() & C.Qt.MouseButton.LeftButton:
            self.refresh_timer.start(100)
            return
        from mic_calibration import sync
        sync(self)
        if self.export_workspace: self.export_workspace.refresh_custom_panes()
        if self.sphere is None:
            for pane in self.panes: pane.render()
            return
        s, i = self.sphere, self.frequency.value(); f = s.freqs[i]
        self.frequency_label.setText(f'{f:,.0f} Hz'); self.frequency_entry.blockSignals(True)
        self.frequency_entry.setValue(f); self.frequency_entry.blockSignals(False)
        gap = f'Next +{s.freqs[i+1]-f:,.1f} Hz' if i+1 < len(s.freqs) else 'Highest stored frequency'
        self.bin_label.setText(f'Bin {i+1:,} / {len(s.freqs):,} · {gap}')
        for pane in self.panes: pane.render()

    def rebuild_pins(self):
        while self.pinned_layout.count():
            item = self.pinned_layout.takeAt(0)
            if item.widget(): item.widget().hide(); item.widget().deleteLater()
        count = 0
        for pane in self.panes:
            keys = [k for k in pane.config['pins'] if k in setting_keys(pane.config['kind'], pane.config)]
            if not keys: continue
            from html import escape
            group = W.QGroupBox(); form = W.QVBoxLayout(group)
            heading = W.QHBoxLayout(); heading.setSpacing(6)
            heading.addWidget(PanePositionIcon(pane.index), 0, C.Qt.AlignTop)
            caption = W.QLabel(escape(TITLES[pane.config['kind']]))
            caption.setWordWrap(True); caption.setTextFormat(C.Qt.RichText)
            heading.addWidget(caption, 1); form.addLayout(heading)
            for key in keys:
                control = editor(key, pane.config[key], lambda v, p=pane, k=key: p.change(k, v),
                                 pane.fit_names() if key == 'fit_curve' else None)
                if isinstance(control, W.QCheckBox):
                    control.setText(SPECS[key][0])
                else:
                    caption = label(SPECS[key][0]); caption.setWordWrap(True); form.addWidget(caption)
                if key == 'delay':
                    control_group = W.QWidget(); row = W.QHBoxLayout(control_group); row.setContentsMargins(0, 0, 0, 0); row.addWidget(control)
                    estimate = W.QPushButton('Estimate')
                    estimate.setToolTip('Fill the delay value from the reference-axis excess group-delay estimate.')
                    estimate.clicked.connect(lambda checked=False, p=pane, field=control: p.fill_estimated_delay(field, p.config))
                    row.addWidget(estimate); control = control_group
                form.addWidget(control)
            self.pinned_layout.addWidget(group); count += len(keys)
        if not count:
            text = label('Right-click a pane → Plot setup → Pin settings to add controls here.', 'muted')
            text.setWordWrap(True); self.pinned_layout.addWidget(text)
        self._pinned_control_count = count

    def view_dict(self):
        configs = []
        for pane in self.panes:
            config = deepcopy(pane.config)
            if pane.plotter: config['camera'] = [list(x) for x in pane.plotter.camera_position]
            configs.append(config)
        return dict(version=2, panes=configs, outer=self.outer.sizes(), rows=[r.sizes() for r in self.rows])

    def apply_view(self, view):
        if not self.valid_view(view): raise ValueError('A view must contain four recognized plot panes.')
        for pane, config in zip(self.panes, view['panes']):
            pane.config = dict(default_config(config['kind']), **deepcopy(config))
            if 'sweep_direction' not in config:
                pane.config['sweep_direction'] = '+/-' if config.get('symmetric', True) else '+'
            pane.config['pins'] = ['sweep_direction' if key == 'symmetric' else key for key in pane.config['pins']]
            # Older templates/projects captured the former 1/12 default.
            # Migrate once; newly saved explicit smoothing choices still persist.
            if config.get('energy_smoothing_version', 0) < 1:
                pane.config['smoothing'] = 'None'
                pane.config['energy_smoothing_version'] = 1
            if pane.config['kind'] in ('globe_h', 'globe_v'): pane.config['kind'] = 'globe_hv'
            if pane.config['kind'] == 'volume': pane.config['kind'] = 'cross_sonograms'
            if 'phase_mode' not in config:
                pane.config['phase_mode'] = ('Minimum phase' if config['kind'] == 'minimum' else
                    'Total phase' if config['kind'] in ('probe', 'phase') and config.get('phase', True) else 'None')
            if pane.config['volume_mode'] == 'Coverage envelopes': pane.config['volume_mode'] = 'Closed contour surfaces'
            pane.invalidate()
        self.outer.setSizes(view.get('outer', [600, 400]))
        for row, sizes in zip(self.rows, view.get('rows', [[1, 1], [1, 1]])): row.setSizes(sizes)
        self.rebuild_pins(); self.refresh()
        for pane in self.panes:
            if pane.plotter and 'camera' in pane.config:
                pane.plotter.camera_position = pane.config['camera']; pane.plotter.render()

    def rebuild_view_buttons(self):
        while self.view_bar.count():
            item = self.view_bar.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        self.view_buttons = {}
        for name in self.views:
            b = ViewButton(name, self)
            b.setContextMenuPolicy(C.Qt.CustomContextMenu)
            b.customContextMenuRequested.connect(lambda point, n=name, widget=b: self.view_menu(n, widget.mapToGlobal(point)))
            self.view_buttons[name] = b; self.view_bar.addWidget(b)

    def view_menu(self, name, position):
        menu = W.QMenu(self)
        def rename():
            updated, ok = W.QInputDialog.getText(self, 'Rename view', 'New name:', text=name)
            if ok and updated.strip() and updated.strip() != name:
                updated = updated.strip()
                if updated in self.views:
                    W.QMessageBox.warning(self, 'Name in use', 'Choose a different view name.'); return
                self.views[updated] = self.views.pop(name)
                if self.current_view == name: self.current_view = updated
                self.persist_views()
        def remove():
            if self.current_view == name: self.delete_view()
            else: self.views.pop(name); self.persist_views()
        menu.addAction('Rename...', rename); menu.addAction('Delete', remove).setEnabled(len(self.views) > 1)
        menu.exec(position)

    def select_view_name(self, name):
        self.current_view = name
        for title, b in self.view_buttons.items(): b.setChecked(name == title)

    def load_view(self, name):
        if getattr(self, 'current_view', None) in self.views: self.views[self.current_view] = self.view_dict()
        self.apply_view(self.views[name]); self.select_view_name(name)
        self.settings.setValue('last_view', name)

    def persist_views(self):
        # View edits are project-local until explicitly saved as a default template.
        self.rebuild_view_buttons(); self.select_view_name(self.current_view)

    def template_views(self):
        try:
            saved = json.loads(self.settings.value('views_v2', '{}'))
            if isinstance(saved, dict):
                views = {name: view for name, view in saved.items()
                         if name not in ('Beam tunnel', 'Beam tube') and self.valid_view(view)}
                if views: return views
        except (ValueError, TypeError): pass
        return self.default_views()

    def reset_views(self):
        self.views = self.template_views()
        name = self.current_view if self.current_view in self.views else next(iter(self.views))
        self.rebuild_view_buttons(); self.apply_view(self.views[name]); self.select_view_name(name)

    def save_viewport(self):
        name, ok = W.QInputDialog.getText(self, 'Save Viewport', 'Name for the new view setup:')
        if not ok or not name.strip(): return
        name = name.strip()
        if name in self.views:
            W.QMessageBox.warning(self, 'Name in use', 'Choose a different view name.'); return
        snapshot = self.view_dict()
        if self.current_view in self.views: self.views[self.current_view] = deepcopy(snapshot)
        self.views[name] = snapshot
        self.current_view = name; self.persist_views()
        self.statusBar().showMessage('Viewport added. Save Project to store it in the project.')

    def save_default_template(self):
        if W.QMessageBox.question(self, 'Save default template',
                'Replace the default views for new projects with the current views?',
                W.QMessageBox.Yes | W.QMessageBox.No, W.QMessageBox.No) != W.QMessageBox.Yes: return
        self.views[self.current_view] = self.view_dict()
        self.settings.setValue('views_v2', json.dumps(self.views)); self.settings.sync()
        self.statusBar().showMessage('Default view template saved.')

    def rename_view(self):
        name, ok = W.QInputDialog.getText(self, 'Rename view', 'New name:', text=self.current_view)
        if ok and name.strip() and name.strip() != self.current_view:
            if name.strip() in self.views:
                W.QMessageBox.warning(self, 'Name in use', 'Choose a different view name.'); return
            self.views[name.strip()] = self.views.pop(self.current_view); self.current_view = name.strip(); self.persist_views()

    def delete_view(self):
        if len(self.views) <= 1: return
        self.views.pop(self.current_view)
        # Keep the deleted name current until load_view has switched panes:
        # otherwise it saves the outgoing layout over the destination view.
        target = next(iter(self.views))
        self.rebuild_view_buttons()
        self.load_view(target)

    def plot_overlays(self, pane):
        # Preserve old shared overlays when first visiting a legacy pane.
        return pane.config.setdefault('overlay_traces', deepcopy(self.overlays))

    def capture_overlay(self, pane=None):
        if self.sphere is None: return
        from panes import selected_magnitudes
        pane = pane or getattr(self, 'active_plot', None) or self.panes[1]
        selected = selected_magnitudes(pane.config)
        if not selected:
            self.statusBar().showMessage('Select an SPL plot before adding an overlay.'); return
        idx = self.sphere.index(*self.axis) if selected == ['reference'] else self.sphere.index(self.azimuth.value(), self.elevation.value())
        name, ok = W.QInputDialog.getText(self, 'Add overlay', 'Trace name:', text=self.sphere.name)
        if ok and name.strip():
            traces = self.plot_overlays(pane)
            if selected in (['probe'], ['reference']):
                pressure = self.sphere.pressure[:, *idx]
                traces.append(dict(name=name.strip(), visible=True, freqs=self.sphere.freqs.tolist(), real=pressure.real.tolist(), imag=pressure.imag.tolist()))
            else:
                from response_plot import magnitude_curves
                from mic_calibration import config as shared_config
                curves, _, _ = magnitude_curves(pane, self.sphere, self.get_levels(pane.config['smoothing']))
                for title, values in curves.items():
                    is_di = title.endswith('DI')
                    offset = 0 if is_di else pane.config['offset'] + shared_config(self)['frd_db_offset']
                    traces.append(dict(name=name.strip()+' - '+title, visible=True, freqs=self.sphere.freqs.tolist(), magnitude=(values-offset).tolist(), di=is_di))
            pane.config['overlays'] = True
            self.overlay_revision += 1; self.schedule()

    def overlay_dialog(self):
        from panes import selected_magnitudes
        dialog = W.QDialog(self); dialog.setWindowTitle('Plot overlays'); dialog.resize(600, 400)
        layout = W.QVBoxLayout(dialog)
        tree = W.QTreeWidget(); tree.setHeaderHidden(True); layout.addWidget(tree)
        entries = {}
        for pane in self.panes:
            traces = self.plot_overlays(pane)
            if not selected_magnitudes(pane.config) and not traces: continue
            group = W.QTreeWidgetItem(tree, [f'{pane.index+1} - {TITLES[pane.config["kind"]]}'])
            for overlay in traces:
                item = W.QTreeWidgetItem(group, [overlay['name']])
                item.setFlags(item.flags() | C.Qt.ItemIsUserCheckable | C.Qt.ItemIsEditable)
                item.setCheckState(0, C.Qt.Checked if overlay['visible'] else C.Qt.Unchecked)
                entries[id(item)] = (traces, overlay)
            group.setExpanded(True)
        def apply(item, column):
            entry = entries.get(id(item))
            if entry:
                entry[1].update(name=item.text(0), visible=item.checkState(0) == C.Qt.Checked)
                self.overlay_revision += 1; self.schedule()
        def remove():
            item = tree.currentItem(); entry = entries.pop(id(item), None)
            if entry:
                entry[0].remove(entry[1]); item.parent().removeChild(item)
                self.overlay_revision += 1; self.schedule()
        tree.itemChanged.connect(apply)
        row = W.QHBoxLayout(); layout.addLayout(row)
        row.addWidget(button('Remove selected', remove)); row.addWidget(button('Close', dialog.accept))
        dialog.exec()

    def session_dict(self):
        if self.export_workspace: self.export_workspace.sync_plot_setup()
        return dict(version=2, theme=self.theme_name, source=self.source_path, reconstruction=self.source_options, view=self.view_dict(),
                    overlays=self.overlays, axis=list(self.axis), axis_source=self.axis_source,
                    export_setup=self.export_workspace.config if self.export_workspace else self.export_setup,
                    export_layout=dict(outer=self.export_workspace.frames.sizes(), rows=[r.sizes() for r in self.export_workspace.rows]) if self.export_workspace else None,
                    view_order=list(self.views),
                    workspace_mode=self.workspace_mode.currentData(),
                    process_layout=self.process_workspace.layout_state() if self.process_workspace else None,
                    frequency=float(self.sphere.freqs[self.frequency.value()]) if self.sphere is not None else 1000., probe=[self.azimuth.value(), self.elevation.value()])

    def save_session(self):
        self.save_action('Save session', '.studio.json', lambda p: Path(p).write_text(json.dumps(self.session_dict(), indent=2), encoding='utf-8'))

    def load_session(self):
        path, _ = W.QFileDialog.getOpenFileName(self, 'Load session', '', 'HALS Studio session (*.json)')
        if not path: return
        try:
            state = json.loads(Path(path).read_text(encoding='utf-8'))
            if state.get('version') != 2 or not self.valid_view(state.get('view')):
                raise ValueError('This workspace requires a version 2 four-pane session. Older sphere caches can still be opened.')
            self.pending_session = state
            if state.get('source'): self.open_path(state['source'], state.get('reconstruction'))
            else: self.apply_pending_session()
        except Exception as exc: self.error(str(exc))

    def apply_pending_session(self):
        state = self.pending_session
        if not state: return
        if state.get('view_order'):
            self.views = {name: self.views[name] for name in dict.fromkeys([*state['view_order'], *self.views]) if name in self.views}
            self.rebuild_view_buttons(); self.select_view_name(self.current_view)
        self.axis = tuple(state.get('axis', (0., 0.))); self.axis_source = state.get('axis_source'); self.cea_cache.clear()
        self.overlays = state.get('overlays', []); self.overlay_revision += 1
        self.azimuth.setValue(state['probe'][0]); self.elevation.setValue(state['probe'][1]); self.jump_frequency(state['frequency'])
        self.update_axis_label(); self.apply_view(state['view']); self.pending_session = None
        self.export_setup = state.get('export_setup')
        if self.export_workspace and self.export_setup: self.export_workspace.apply_config(self.export_setup)
        self.set_workspace(state.get('workspace_mode', 0))
        if self.export_workspace and state.get('export_layout'):
            saved = state['export_layout']; self.export_workspace.frames.setSizes(saved['outer'])
            for row, sizes in zip(self.export_workspace.rows, saved['rows']): row.setSizes(sizes)
        self.set_theme(state.get('theme', self.theme_name))

    def export_cea(self):
        if self.sphere is None: return
        def write(path):
            metrics = self.get_cea('None')
            np.savetxt(path, np.column_stack([self.sphere.freqs, *metrics.values()]), delimiter=',',
                       header='Frequency Hz,'+','.join(metrics), comments='')
        self.save_action('Export CEA2034-derived curves', '.csv', write)

    def choose_save(self, title, extension):
        import re
        directory = C.QStandardPaths.writableLocation(C.QStandardPaths.DocumentsLocation)
        name = re.sub(r'[<>:"/\\|?*]', '-', self.sphere.name)
        path, _ = W.QFileDialog.getSaveFileName(self, title, str(Path(directory)/(name+extension)),
                                               f'{extension.upper()[1:]} files (*{extension})')
        if path and not path.lower().endswith(extension): path += extension
        return path

    def help(self):
        W.QMessageBox.information(self, 'HALS Studio',
            'Right-click any pane to choose a plot, open its setup, or export its image. Drag dividers to resize.\n\n'
            'The gear opens plot settings; Pin settings exposes checkboxes for sidebar controls. Save Project stores your views, settings, pins, dividers and cameras. Reset views restores the default template. '
            'Save session also stores source, reference axis and complex probe overlays.\n\n'
            'Drag the green balloon handle to probe; edit azimuth/elevation within the balloon pane. Probe curves use the nearest angular sample. '
            'Space sweeps frequencies. Wheel zooms around the cursor; zoom out returns to the full view. '
            'Select multiple magnitude checkboxes in SPL & phase or CEA2034; Clear magnitudes keeps phase. '
            'Choose phase separately. Drag the purple phase-axis top handle to resize it. '
            'Unwrapped phase automatically fits its full range; sparse frequency bins can unwrap incorrectly.\n\n'
            'Delay compensation → Min phase calls the same Stage 5 reference-axis excess group-delay helper; the number is additional manual trim. '
            'Fit line uses a least-squares trend versus log frequency, equally weighted per octave; ± is maximum deviation, not a confidence interval.\n\n'
            'CEA2034-derived curves use the project reference axis, energy interpolation and power averages. These are sphere-derived estimates. '
            'Levels are relative to the HALS pressure units, not automatically calibrated SPL. Minimum phase is a finite-band estimate. '
            'Coverage caps mark sampled boundaries, not measured level crossings.')

    def closeEvent(self, event):
        if self.process_workspace:
            self.process_workspace.shutdown()
            if self.process_workspace.plotter:self.process_workspace.plotter.close()
        if self.export_workspace and self.export_workspace.job and self.export_workspace.job.isRunning():
            self.export_workspace.cancel(); self.statusBar().showMessage('Cancelling Stage 5… close again when it has stopped.'); event.ignore(); return
        if self.worker and self.worker.isRunning():
            self.cancel_load(); self.statusBar().showMessage('Cancelling reconstruction… close again when it has stopped.'); event.ignore(); return
        self.settings.setValue('last_view', self.current_view)
        self.play_timer.stop(); self.refresh_timer.stop(); self.pool_timer.stop(); self.pool.close()
        for pane in self.panes:
            if pane.plotter: pane.plotter.close()
            if hasattr(pane, 'csd_view'): pane.csd_view.shutdown()
        if self.export_workspace: self.export_workspace.shutdown()
        event.accept()

    def align_view_toolbar(self):
        if self.workspace_mode.currentData() != 0 or not self.panes: return
        origin = self.mode_label.mapTo(self.centralWidget(), C.QPoint(0, 0)).x()
        target = self.panes[0].title.mapTo(self.centralWidget(), C.QPoint(0, 0)).x()
        spacing = self.modebar.spacing()
        self.mode_label.setFixedWidth(max(150, target-origin-spacing))
        brand_origin = self.brand_label.mapTo(self.centralWidget(), C.QPoint(0, 0)).x()
        self.brand_label.setFixedWidth(max(150, target-brand_origin-self.header_layout.spacing()))

    def eventFilter(self, watched, event):
        if watched is getattr(self, 'analysis_plot_area', None) and event.type() in (C.QEvent.Resize, C.QEvent.Move, C.QEvent.Show):
            C.QTimer.singleShot(0, self.align_view_toolbar)
        return super().eventFilter(watched, event)

    def resizeEvent(self, event):
        W.QMainWindow.resizeEvent(self, event)
        if hasattr(self, 'panes'):
            for pane in self.panes: pane.invalidate()
            self.schedule()
