"""Dedicated Stage 5 export workspace: physical geometry, native-bin previews and jobs."""
from copy import deepcopy
from pathlib import Path
import json
import threading
import numpy as np
from PySide6 import QtCore as C, QtGui as G, QtWidgets as W
import pyvista as pv
from pyvistaqt import QtInteractor
import bootstrap
from acoustics import Cancelled
from export_engine import (DEFAULT_EXPORT, geometry, cabinet_geometry, import_project, run_export,
                           project_files, coefficient_files, acoustic_origin)
from plot_interaction import PlotInteraction
from complex_to_ir_core import complex_to_ir
from export_preview import PreviewCache


class SceneZoom(C.QObject):
    eventFilter = PlotInteraction.eventFilter
    def __init__(self, pane): super().__init__(pane); self.pane = pane


class ExportWorker(C.QThread):
    progress = C.Signal(int, str)
    message = C.Signal(str)
    result = C.Signal(object)
    failed = C.Signal(str)
    def __init__(self, config, pool, writing, preview_cache=None, point_index=0, aggregate=False):
        super().__init__(); self.config, self.pool, self.writing = deepcopy(config), pool, writing
        self.stop = threading.Event()
        self.preview_cache, self.point_index, self.aggregate = preview_cache, point_index, aggregate
    def run(self):
        try:
            if not self.writing and not self.aggregate:
                result = self.preview_cache.run(self.config, self.point_index, self.pool, self.progress.emit, self.stop.is_set)
            else:
                result = run_export(self.config, self.pool, self.writing, self.progress.emit, self.stop.is_set, self.message.emit)
            if not self.stop.is_set(): self.result.emit(result)
        except Cancelled: self.message.emit('Cancelled; no incomplete export was published.')
        except Exception as exc: self.failed.emit(str(exc))


class ExportWorkspace(W.QWidget):
    def __init__(self, owner):
        super().__init__(); self.owner = owner; self.config = deepcopy(DEFAULT_EXPORT)
        self.job = None; self.result = None; self.selected = 0; self.destination = None
        self.controls = {}; self.loading = False; self.dirty = True; self.pending_preview = False
        self.generation = 0; self.scene_initialized = False; self.full_limits = {}
        self.preview_cache = PreviewCache(); self.free_zoom_out = True
        self.busy_timer = C.QTimer(self); self.busy_timer.setSingleShot(True); self.busy_timer.setInterval(500)
        self.busy_timer.timeout.connect(self.show_busy)
        self.timer = C.QTimer(self); self.timer.setSingleShot(True); self.timer.setInterval(180)
        self.timer.timeout.connect(self.preview_if_live)
        self.build()
        self.apply_config(self.config)

    def build(self):
        root = W.QVBoxLayout(self); root.setContentsMargins(0, 4, 0, 0)
        source_host = W.QWidget(); source = W.QHBoxLayout(source_host); source_host.hide()
        self.source_host = source_host
        title = W.QLabel('STAGE 5 / EXPORT'); title.setStyleSheet('color:#47d7ec;font-weight:bold;letter-spacing:2px;')
        source.addWidget(title); self.source = W.QLineEdit(); self.source.setPlaceholderText('HALS coefficient file (.h5)')
        self.source.editingFinished.connect(lambda: self.change('coeff_path', self.source.text()))
        self.source_widgets = [self.source]
        source.addWidget(self.source, 1)
        self.project_button = W.QToolButton(); self.project_button.setText('Open project folder…')
        self.project_button.setPopupMode(W.QToolButton.MenuButtonPopup)
        self.project_button.clicked.connect(self.open_project_folder)
        menu = W.QMenu(self.project_button); menu.addAction('Open project JSON…', self.load_project)
        self.project_button.setMenu(menu); source.addWidget(self.project_button); self.source_widgets.append(self.project_button)
        for text, fn in [('Coefficients…', self.browse_source), ('Load setup…', self.load_setup), ('Save setup…', self.save_setup)]:
            button = W.QPushButton(text); button.clicked.connect(fn); source.addWidget(button); self.source_widgets.append(button)
        self.project_summary = W.QLabel(); self.project_summary.setWordWrap(True)
        self.project_summary.setStyleSheet('color:#91aabe;padding:2px 0;'); self.project_summary.hide()
        self.split = W.QSplitter(); root.addWidget(self.split, 1)
        sidebar = W.QWidget(); sidebar.setMinimumWidth(200)
        sidebar_layout = W.QVBoxLayout(sidebar); sidebar_layout.setContentsMargins(5, 5, 5, 5)
        self.sidebar_selector = W.QComboBox(); sidebar_layout.addWidget(self.sidebar_selector)
        self.sidebar = W.QStackedWidget(); sidebar_layout.addWidget(self.sidebar, 1)
        self.sidebar_selector.currentIndexChanged.connect(self.sidebar.setCurrentIndex)
        self.split.addWidget(sidebar)
        left = W.QWidget(); side = W.QVBoxLayout(left); side.setContentsMargins(0, 0, 5, 0)
        self.tabs = W.QTabWidget(); side.addWidget(self.tabs, 1)
        self.tabs.tabBar().setExpanding(False)
        self.forms = {}
        for name in ('Geometry', 'Output', 'Advanced'):
            scroll = W.QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(W.QFrame.NoFrame)
            body = W.QWidget(); form = W.QFormLayout(body); form.setFieldGrowthPolicy(W.QFormLayout.AllNonFixedFieldsGrow)
            scroll.setWidget(body); self.tabs.addTab(scroll, 'Export geometry' if name == 'Geometry' else 'Advanced settings' if name == 'Advanced' else name); self.forms[name] = form
        self.section('Geometry', 'REFERENCE GEOMETRY')
        self.add('Advanced', 'zero_theta', 'Theta / degrees', (0, 180, 2))
        self.add('Advanced', 'zero_phi', 'Phi / degrees', (-360, 360, 2))
        note = W.QLabel('Theta: 0° up, 90° forward. Phi: azimuth.\nOffsets translate the reference and sweep together.\nManual points are absolute; offsets do not apply.')
        note.setWordWrap(True); note.setStyleSheet('color:#849eb1;font-size:11px'); self.forms['Advanced'].addRow(note)
        for axis in 'xyz': self.add('Geometry', f'offset_{axis}', f'Offset {axis.upper()} / mm', (-100000, 100000, 2))
        self.add('Geometry', 'offset_step_mm', 'Jog step / mm', (1, 1000, 0))
        self.section('Geometry', 'EVALUATION')
        self.add('Geometry', 'mode', 'Evaluation', ['Arc sweep', 'CTA-2034', 'Manual coordinates'])
        self.add('Geometry', 'dist_mic', 'Distance / m', (.001, 1000., 3))
        self.add('Geometry', 'direction', 'Direction', ['horizontal', 'vertical', 'hor_vert'])
        self.add('Geometry', 'range_deg', 'Range / ±degrees', (0, 180, 0))
        self.add('Geometry', 'increment_deg', 'Increment / degrees', (1, 180, 0))
        self.manual_frame = W.QWidget(); manual_layout = W.QVBoxLayout(self.manual_frame); manual_layout.setContentsMargins(0, 0, 0, 0)
        self.manual_table = W.QTableWidget(0, 3); self.manual_table.setHorizontalHeaderLabels(['Theta / deg', 'Phi / deg', 'r / m'])
        self.manual_table.horizontalHeader().setSectionResizeMode(W.QHeaderView.Stretch)
        self.manual_table.setMinimumHeight(220); manual_layout.addWidget(self.manual_table)
        self.manual_table.itemChanged.connect(self.manual_changed)
        buttons = W.QHBoxLayout(); manual_layout.addLayout(buttons)
        for text, fn in [('Add', self.manual_add), ('Remove', self.manual_remove), ('Import CSV', self.manual_import)]:
            button = W.QPushButton(text); button.clicked.connect(fn); buttons.addWidget(button)
        self.forms['Geometry'].addRow(self.manual_frame)
        self.add('Geometry', 'subtract_tof', 'Delay compensation', ['Off', 'Ref Origin', 'Min Phase Ref', 'IR Peak'])
        self.add('Output', 'output_dir', 'Output directory', 'directory')
        self.add('Output', 'frd_prefix', 'Filename prefix', str)
        self.add('Output', 'generate_ir_files', 'Generate WAV impulse files', bool)
        note = W.QLabel('Sweep: FRD + full complex NPZ + coordinate list; optional WAV.\nCTA-2034: Stage 5 metric FRDs and reflection breakout.\n\nFRD uses the selected delay compensation and level offset. Complex NPZ and WAV retain propagation phase and their original level, as in Stage 5.\n\nEach export creates a new run folder, with settings and a log.')
        note.setWordWrap(True); note.setStyleSheet('color:#91aabe'); self.forms['Output'].addRow(note)
        self.section('Output', 'CALIBRATION')
        self.add('Output', 'frd_db_offset', 'FRD offset / dB', (-200, 200, 2))
        self.add('Output', 'apply_mic_cal', 'Apply calibration', bool)
        self.add('Output', 'mic_cal_file', 'Calibration file', 'file')
        self.add('Output', 'mic_cal_mode', 'Calibration mode', ['subtract', 'add'])
        self.add('Output', 'mic_cal_fade_octaves', 'Fade / octaves', (0, 10, 2))
        self.add('Advanced', 'obs_mode', 'Observation field', ['Internal', 'External', 'Full'])
        self.add('Advanced', 'use_optimized_origins', 'Use optimized origins', bool)
        self.add('Advanced', 'manual_ir_capture_padding', 'Edit capture padding', bool)
        self.add('Advanced', 'ir_capture_padding_samples', 'Padding / samples', (0, 100000, 0))
        note = W.QLabel('Exports evaluate the coefficient file at every native frequency bin and exact physical position. Analysis sphere resolution, smoothing, normalization and probe settings do not change these exports.\n\nOptimized origins and capture-padding correction use the same engine as HALS Stage 5.')
        note.setWordWrap(True); note.setStyleSheet('color:#91aabe'); self.forms['Advanced'].addRow(note)
        row = W.QHBoxLayout(); side.addLayout(row)
        self.export_button = W.QPushButton('Run Export'); self.export_button.setStyleSheet('background:#599bda;color:#071721;font-weight:bold;')
        self.export_button.clicked.connect(lambda: self.start(True)); row.addWidget(self.export_button)
        self.cancel_button = W.QPushButton('Cancel'); self.cancel_button.clicked.connect(self.cancel); row.addWidget(self.cancel_button); self.cancel_button.hide()
        self.open_folder = W.QPushButton('Open Export Folder'); self.open_folder.clicked.connect(self.reveal); self.open_folder.setEnabled(False); row.addWidget(self.open_folder)
        self.frames = W.QSplitter(C.Qt.Vertical); self.split.addWidget(self.frames)
        self.frames.setMinimumWidth(0); self.frames.setSizePolicy(W.QSizePolicy.Ignored, W.QSizePolicy.Expanding)
        self.rows = [W.QSplitter(C.Qt.Horizontal), W.QSplitter(C.Qt.Horizontal)]
        for splitter in [self.frames, *self.rows]:
            splitter.setHandleWidth(7); splitter.setChildrenCollapsible(False)
            if splitter is not self.frames:
                splitter.setMinimumWidth(0); splitter.setSizePolicy(W.QSizePolicy.Ignored, W.QSizePolicy.Preferred)
        for row in self.rows: self.frames.addWidget(row)
        scene = W.QWidget(); scene_layout = W.QVBoxLayout(scene); scene_layout.setContentsMargins(5, 5, 5, 5)
        scene.setMinimumWidth(0); scene.setSizePolicy(W.QSizePolicy.Ignored, W.QSizePolicy.Preferred)
        bar = W.QHBoxLayout(); scene_layout.addLayout(bar)
        origin = W.QCheckBox('Acoustic origin'); self.controls['show_stage2_origin'] = origin
        origin.setMinimumWidth(140)
        origin.toggled.connect(lambda value: self.change('show_stage2_origin', value)); bar.addWidget(origin)
        frequency = W.QDoubleSpinBox(); frequency.setRange(1, 100000); frequency.setDecimals(1); frequency.setSuffix(' Hz'); frequency.setKeyboardTracking(False)
        frequency.setFixedWidth(116)
        self.controls['stage2_origin_frequency_hz'] = frequency
        frequency.valueChanged.connect(lambda value: self.change('stage2_origin_frequency_hz', value)); bar.addWidget(frequency); bar.addStretch()
        for name, fn in [('Top', lambda: self.camera('top')), ('Front', lambda: self.camera('front')), ('Iso', lambda: self.camera('iso')), ('Save image…', self.save_image)]:
            button = W.QPushButton(name); button.clicked.connect(fn); bar.addWidget(button)
        # Export's 3D scene is resized continuously while the user drags the
        # workspace splitters.  The periodic auto-update render can re-enter
        # QVTK's paint path during those resizes, so render only on explicit
        # scene updates and user interaction.
        self.plotter = QtInteractor(scene, auto_update=False); self.plotter.set_background('#101c28', top='#193344')
        self.plotter.enable_terrain_style(); self.plotter.render_window.SetMultiSamples(0)
        self.zoom = SceneZoom(self); self.plotter.interactor.installEventFilter(self.zoom)
        scene_layout.addWidget(self.plotter.interactor, 1); self.scene_note = W.QLabel(); self.scene_note.setWordWrap(True); scene_layout.addWidget(self.scene_note)
        self.plotter.enable_point_picking(callback=self.pick, show_message=False, show_point=False, left_clicking=True, tolerance=.03)
        self.rows[0].addWidget(scene)
        from export_charts import ResponsePanel, ImpulsePanel
        self.response_panel = ResponsePanel(self); self.chart = self.response_panel.chart
        self.response_panel.setMinimumWidth(0); self.response_panel.setSizePolicy(W.QSizePolicy.Ignored, W.QSizePolicy.Preferred)
        self.rows[0].addWidget(self.response_panel)
        row = self.response_panel.toolbar
        row.addWidget(self.response_panel.point_label)
        self.previous = W.QPushButton('‹'); self.previous.setFixedWidth(30)
        self.previous.clicked.connect(lambda: self.select((self.selected-1)%len(self.layout_data['xyz']))); row.addWidget(self.previous)
        row.addWidget(W.QLabel('Prev/Next'))
        self.point_label = self.response_panel.point_label
        self.next = W.QPushButton('›'); self.next.setFixedWidth(30)
        self.next.clicked.connect(lambda: self.select((self.selected+1)%len(self.layout_data['xyz']))); row.addWidget(self.next)
        reset = W.QPushButton('Reset axes'); reset.clicked.connect(self.response_panel.reset); row.addWidget(reset)
        gear = W.QToolButton(); gear.setText('\u2699'); reset.setFixedHeight(32); gear.setFixedHeight(32); gear.setToolTip('Response plot settings'); gear.clicked.connect(self.response_panel.settings); row.addWidget(gear)
        from csd_plot import CSDPanel
        self.csd_panel = CSDPanel(); self.rows[1].addWidget(self.csd_panel)
        self.ir_panel = ImpulsePanel(); self.rows[1].addWidget(self.ir_panel)
        for panel in (self.csd_panel, self.ir_panel):
            panel.setMinimumWidth(0); panel.setSizePolicy(W.QSizePolicy.Ignored, W.QSizePolicy.Preferred)
        for splitter in self.rows: splitter.setSizes([600, 650])
        self.frames.setSizes([650, 350])
        self.points = W.QTableWidget(0, 4); self.points.setHorizontalHeaderLabels(['Point', 'r / m', 'θ / °', 'φ / °'])
        self.points.setSelectionBehavior(W.QAbstractItemView.SelectRows); self.points.setSelectionMode(W.QAbstractItemView.SingleSelection)
        self.points.setEditTriggers(W.QAbstractItemView.NoEditTriggers); self.points.verticalHeader().hide()
        self.points.horizontalHeader().setSectionResizeMode(W.QHeaderView.ResizeToContents)
        self.points.itemSelectionChanged.connect(self.table_select); 
        from project_metadata import MetadataEditor
        self.metadata_editor = MetadataEditor(self)
        self.log = W.QPlainTextEdit(); self.log.setReadOnly(True); self.log.setMaximumBlockCount(2000)
        cli = W.QWidget(); cli_layout = W.QVBoxLayout(cli); cli_layout.addWidget(self.log)
        cli_buttons = W.QHBoxLayout(); cli_layout.addLayout(cli_buttons)
        self.cli_run = W.QPushButton('Run Export'); self.cli_run.clicked.connect(lambda: self.start(True)); cli_buttons.addWidget(self.cli_run)
        self.cli_open = W.QPushButton('Open Export Folder'); self.cli_open.clicked.connect(self.reveal); self.cli_open.setEnabled(False); cli_buttons.addWidget(self.cli_open)
        self.cli_cancel = W.QPushButton('Cancel export'); self.cli_cancel.clicked.connect(self.cancel); cli_layout.addWidget(self.cli_cancel); self.cli_cancel.hide()
        for title, widget in [('Settings', left), ('Metadata', self.metadata_editor), ('CLI Output', cli), ('Export Points', self.points)]:
            self.sidebar.addWidget(widget); self.sidebar_selector.addItem(title)
        from export_panes import ExportPane
        self.custom_panes = []
        for index, (splitter, position, native, title) in enumerate([
                (self.rows[0], 1, self.response_panel, 'Export SPL / phase'),
                (self.rows[1], 0, self.csd_panel, 'Export CSD / wavelet'),
                (self.rows[1], 1, self.ir_panel, 'Export impulse response')]):
            native.setParent(None)
            host = ExportPane(self, index, native, title)
            host.setMinimumWidth(0); host.setSizePolicy(W.QSizePolicy.Ignored, W.QSizePolicy.Preferred)
            splitter.insertWidget(position, host)
            self.custom_panes.append(host)
        export_width = int(self.owner.settings.value('export_sidebar_width', 350))
        self.split.setSizes([export_width, 1270]); self.split.splitterMoved.connect(lambda *_: self.owner.settings.setValue('export_sidebar_width', self.split.sizes()[0]))
        self.split.setStretchFactor(0, 0); self.split.setStretchFactor(1, 1)
        self.split.setHandleWidth(7); self.split.setChildrenCollapsible(False)
        self.status = W.QLabel('Choose coefficients or import a HALS project.'); root.addWidget(self.status)
        self.progress = W.QProgressBar(); self.progress.setMaximumHeight(7); self.progress.setTextVisible(False); root.addWidget(self.progress)
        for widget in (self.progress, self.cancel_button):
            policy = widget.sizePolicy(); policy.setRetainSizeWhenHidden(True); widget.setSizePolicy(policy)
        self.progress.hide()

    def section(self, tab, title):
        label = W.QLabel(title); label.setStyleSheet('color:#47d7ec;letter-spacing:1px;padding-top:12px;'); self.forms[tab].addRow(label)

    def add(self, tab, key, label, spec):
        if isinstance(spec, list):
            widget = W.QComboBox(); widget.addItems(spec); widget.currentTextChanged.connect(lambda v: self.change(key, v))
        elif isinstance(spec, tuple):
            widget = W.QDoubleSpinBox(); widget.setRange(*spec[:2]); widget.setDecimals(spec[2]); widget.setKeyboardTracking(False)
            widget.valueChanged.connect(lambda v: self.change(key, int(v) if spec[2] == 0 else v))
        elif spec is bool:
            widget = W.QCheckBox(); widget.toggled.connect(lambda v: self.change(key, v))
        else:
            widget = W.QLineEdit(); widget.editingFinished.connect(lambda: self.change(key, widget.text()))
        self.controls[key] = widget
        if spec in ('file', 'directory'):
            frame = W.QWidget(); row = W.QHBoxLayout(frame); row.setContentsMargins(0, 0, 0, 0); row.addWidget(widget)
            browse = W.QToolButton(); browse.setText('…'); browse.clicked.connect(lambda: self.browse_control(key, spec)); row.addWidget(browse)
            self.forms[tab].addRow(label, frame)
        else: self.forms[tab].addRow(label, widget)

    def apply_config(self, config, refresh_metadata=True):
        self.loading = True; self.config = dict(deepcopy(DEFAULT_EXPORT), **deepcopy(config))
        self.source.setText(self.config['coeff_path'])
        for key, widget in self.controls.items():
            value = self.config[key]
            if isinstance(widget, W.QComboBox): widget.setCurrentText(str(value))
            elif isinstance(widget, W.QDoubleSpinBox): widget.setValue(float(value))
            elif isinstance(widget, W.QCheckBox): widget.setChecked(bool(value))
            else: widget.setText(str(value))
        self.config['live_preview'] = True
        from csd_plot import DEFAULTS as CSD_DEFAULTS
        self.csd_panel.config = self.config.setdefault('csd_options', dict(CSD_DEFAULTS))
        for key, value in CSD_DEFAULTS.items(): self.csd_panel.config.setdefault(key, value)
        self.csd_panel.method.blockSignals(True); self.csd_panel.method.setCurrentText(self.csd_panel.config.get('csd_method', 'CSD')); self.csd_panel.method.blockSignals(False)
        self.csd_panel.mode.blockSignals(True); self.csd_panel.mode.setCurrentText(self.csd_panel.config['csd_mode']); self.csd_panel.mode.blockSignals(False)
        self.config['preview_smoothing'] = 'Off'
        self.fill_manual()
        for pane, state in zip(self.custom_panes, deepcopy(self.config.get('plot_panes', [{}, {}, {}]))):
            pane.restore(state)
        self.loading = False; self.changed()
        if refresh_metadata: self.metadata_editor.reload()

    def update_project_summary(self):
        path = self.config['project_path']
        if path:
            self.project_summary.setText(f'{self.config["project_name"] or Path(path).stem} · {Path(path).parent}\n'
                                         f'Reference XYZ: {self.config["offset_x"]:g}, {self.config["offset_y"]:g}, {self.config["offset_z"]:g} mm')
        else: self.project_summary.setText('Standalone coefficients · open a project folder to load cabinet, driver and reference geometry.')

    def change(self, key, value):
        if self.loading: return
        self.config[key] = value
        if key in ('output_dir', 'frd_prefix', 'generate_ir_files'): return
        if key == 'preview_smoothing': self.draw_response(); return
        if key in ('show_stage2_origin', 'stage2_origin_frequency_hz', 'dut_depth_x', 'offset_step_mm'):
            for axis in 'xyz': self.controls['offset_'+axis].setSingleStep(self.config['offset_step_mm'])
            self.update_scene(); return
        if key == 'live_preview':
            if value: self.preview_if_live()
            return
        if key == 'mode' and value == 'CTA-2034':
            self.config['dist_mic'] = 2.; self.controls['dist_mic'].setValue(2.)
        self.changed(update_geometry=key in ('mode', 'dist_mic', 'direction', 'range_deg', 'increment_deg',
                                            'zero_theta', 'zero_phi', 'offset_x', 'offset_y', 'offset_z', 'coeff_path'))

    def changed(self, update_geometry=True):
        self.owner.schedule()
        self.generation += 1; self.dirty = True
        self.update_project_summary()
        if self.job and self.job.isRunning() and not self.job.writing: self.job.stop.set(); self.pending_preview = True
        c = self.config; manual = c['mode'] == 'Manual coordinates'; sweep = c['mode'] == 'Arc sweep'
        for key in ('range_deg', 'increment_deg', 'direction'): self.forms['Geometry'].setRowVisible(self.controls[key], sweep)
        self.forms['Geometry'].setRowVisible(self.controls['dist_mic'], not manual)
        self.forms['Geometry'].setRowVisible(self.manual_frame, manual)
        for key in ('dist_mic', 'zero_theta', 'zero_phi', 'offset_x', 'offset_y', 'offset_z'): self.controls[key].setEnabled(not manual)
        self.controls['generate_ir_files'].setEnabled(c['mode'] != 'CTA-2034')
        self.controls['ir_capture_padding_samples'].setEnabled(c['manual_ir_capture_padding'])
        for axis in 'xyz': self.controls['offset_'+axis].setSingleStep(c['offset_step_mm'])
        self.status.setText('Settings changed · response preview pending' if c['coeff_path'] else 'Choose coefficients or import a HALS project.')
        if update_geometry: self.update_scene()
        self.draw_response(); self.timer.start(180)

    def adopt_source(self):
        source = self.owner.source_path or (self.owner.sphere.metadata.get('source') if self.owner.sphere is not None else None)
        if source and Path(source).suffix.lower() in ('.h5', '.hdf5') and not self.config['coeff_path']:
            project = self.owner.axis_source
            if project and Path(project).is_file():
                try: self.config = import_project(project)
                except (ValueError, TypeError, OSError) as exc: self.log.appendPlainText('Project settings could not be imported: '+str(exc))
            else:
                self.config.update(frd_prefix=Path(source).stem.removesuffix('_coefficients'),
                                   zero_theta=90-self.owner.axis[1], zero_phi=self.owner.axis[0])
            self.config['coeff_path'] = str(source)
            self.apply_config(self.config)

    def browse_source(self):
        path, _ = W.QFileDialog.getOpenFileName(self, 'HALS coefficients', self.config['coeff_path'], 'HALS coefficients (*.h5 *.hdf5)')
        if path:
            self.config['coeff_path'] = path; self.config['frd_prefix'] = Path(path).stem.removesuffix('_coefficients'); self.apply_config(self.config)

    def browse_control(self, key, kind):
        if kind == 'directory': path = W.QFileDialog.getExistingDirectory(self, 'Export directory', self.config[key])
        else: path, _ = W.QFileDialog.getOpenFileName(self, 'Microphone calibration', self.config[key], 'Calibration (*.txt *.cal *.csv);;All files (*)')
        if path: self.controls[key].setText(path); self.change(key, path)

    def load_project(self):
        path, _ = W.QFileDialog.getOpenFileName(self, 'Import HALS project', '', 'HALS project (*.json)')
        if path: self.open_project(path)

    def open_project_folder(self):
        current = self.config.get('project_path')
        folder = W.QFileDialog.getExistingDirectory(self, 'Open HALS project folder', str(Path(current).parent) if current else '')
        if folder: self.open_project(folder)

    def open_project(self, path):
        if self.job and self.job.writing:
            self.status.setText('Wait for the export to finish, or cancel it before opening a project.'); return
        try:
            path = Path(path)
            candidates = project_files(path) if path.is_dir() else [path]
            if len(candidates) > 1:
                name, ok = W.QInputDialog.getItem(self, 'Choose project', 'This folder contains several projects:', [p.name for p in candidates], 0, False)
                if not ok: return
                path = next(p for p in candidates if p.name == name)
            else: path = candidates[0]
            config = import_project(path)
            candidates = coefficient_files(config)
            if len(candidates) > 1:
                name, ok = W.QInputDialog.getItem(self, 'Choose coefficients', 'Several coefficient files were found:', [p.name for p in candidates], 0, False)
                if ok: config['coeff_path'] = str(next(p for p in candidates if p.name == name))
            self.apply_config(config)
            self.log.appendPlainText('Opened project: '+str(path))
            if config['coeff_path']:
                self.log.appendPlainText('Coefficients: '+config['coeff_path'])
                self.status.setText('Project loaded · geometry and export settings ready')
            else:
                self.status.setText('Project geometry loaded · select coefficients with Coefficients…')
                self.log.appendPlainText('No coefficient file selected. Expected in '+str(path.parent/'outputs'/'coefficients'))
        except Exception as exc: self.error(str(exc))

    def save_setup(self):
        self.sync_plot_setup()
        path, _ = W.QFileDialog.getSaveFileName(self, 'Save export setup', 'stage5-export.json', 'Export setup (*.json)')
        if path:
            try: Path(path).write_text(json.dumps(self.config, indent=2), encoding='utf-8')
            except Exception as exc: self.error(str(exc))

    def load_setup(self):
        path, _ = W.QFileDialog.getOpenFileName(self, 'Load export setup', '', 'Export setup (*.json)')
        if path:
            try:
                data = json.loads(Path(path).read_text(encoding='utf-8')); self.apply_config(data.get('settings', data))
            except Exception as exc: self.error(str(exc))

    def fill_manual(self):
        table = self.manual_table; table.blockSignals(True); table.setRowCount(0)
        for row in self.config['manual_coords']:
            values = list(row) if len(row) == 3 else [*row, self.config['dist_mic']]
            i = table.rowCount(); table.insertRow(i)
            for j, value in enumerate(values): table.setItem(i, j, W.QTableWidgetItem(str(value)))
        table.blockSignals(False)

    def manual_changed(self, *_):
        if self.loading: return
        try:
            table = self.manual_table
            rows = [[float(table.item(i, j).text()) for j in range(3)] for i in range(table.rowCount())]
            geometry(dict(self.config, manual_coords=rows, mode='Manual coordinates'))
            self.config['manual_coords'] = rows; self.changed()
        except (ValueError, AttributeError) as exc: self.status.setText('Coordinates: '+str(exc))

    def manual_add(self):
        self.config['manual_coords'].append([90., 0., self.config['dist_mic']]); self.fill_manual(); self.changed()

    def manual_remove(self):
        selected = {item.row() for item in self.manual_table.selectedItems()}
        rows = [row for i, row in enumerate(self.config['manual_coords']) if i not in selected]
        if not rows: self.status.setText('Keep at least one export point.'); return
        self.config['manual_coords'] = rows; self.fill_manual(); self.changed()

    def manual_import(self):
        path, _ = W.QFileDialog.getOpenFileName(self, 'Import theta, phi, radius CSV', '', 'CSV (*.csv *.txt)')
        if not path: return
        try:
            rows = np.loadtxt(path, delimiter=',', ndmin=2).tolist()
            geometry(dict(self.config, manual_coords=rows, mode='Manual coordinates'))
            self.config['manual_coords'] = rows; self.fill_manual(); self.changed()
        except (ValueError, OSError) as exc: W.QMessageBox.warning(self, 'Coordinates', str(exc))

    def update_scene(self):
        previous = self.plotter.suppress_rendering
        self.plotter.suppress_rendering = True
        try: self.rebuild_scene()
        finally:
            self.plotter.suppress_rendering = previous
            from viewer_theme import scene_theme
            scene_theme(self.plotter)
            if not previous: self.plotter.render()

    def rebuild_scene(self):
        try: data = geometry(self.config)
        except Exception as exc: self.scene_note.setText(str(exc)); return
        self.layout_data = data; self.selected = min(self.selected, len(data['xyz'])-1)
        p = self.plotter; camera = p.camera_position if self.scene_initialized else None; p.clear()
        for elevation, azimuth, strength in [(30, -40, .95), (-20, 45, .3), (55, 145, .6)]:
            light = pv.Light(light_type='camera light', intensity=strength); light.set_direction_angle(elevation, azimuth); p.add_light(light)
        xyz = data['xyz']; scale = max(.2, float(np.max(np.linalg.norm(xyz-data['origin'], axis=1))))
        vertices, named, known = cabinet_geometry(self.config)
        if known:
            faces = [4, 0, 1, 2, 3, 4, 4, 7, 6, 5, 4, 0, 4, 5, 1, 4, 1, 5, 6, 2, 4, 2, 6, 7, 3, 4, 3, 7, 4, 0]
            p.add_mesh(pv.PolyData(vertices, faces), color='#345268', smooth_shading=False, specular=.65, specular_power=30, show_edges=True)
            p.add_mesh(pv.PolyData(vertices[:4], [4, 0, 1, 2, 3]), color='#52798e', specular=.6)
        # Mark the actual reference origin at the arrow stem, not the unused
        # world-coordinate zero when the project origin has been offset.
        p.add_mesh(pv.Sphere(radius=scale*.012, center=data['origin']), color='#7ae2b1', specular=.8)
        p.add_mesh(pv.Arrow(start=data['origin'], direction=data['forward'], scale=scale*.7, shaft_radius=.009, tip_radius=.035), color='#7ae2b1', specular=.6)
        from vtkmodules.vtkRenderingCore import vtkBillboardTextActor3D
        camera_pos = np.asarray(p.camera_position[0], float)
        def add_ball_label(point, text, actor_name):
            point = np.asarray(point, float)
            toward_camera = camera_pos - point
            norm = np.linalg.norm(toward_camera)
            if norm: point = point + toward_camera / norm * scale * .014
            actor = vtkBillboardTextActor3D(); actor.SetInput(text); actor.SetPosition(*point)
            actor.SetDisplayOffset(0, 20)
            prop = actor.GetTextProperty(); prop.SetFontSize(10); prop.SetColor(184/255, 214/255, 232/255)
            prop.SetJustificationToCentered(); prop.SetVerticalJustificationToBottom(); prop.SetBold(True)
            p.add_actor(actor, name=actor_name, reset_camera=False, render=False, pickable=False)
        add_ball_label(data['origin'], 'Reference origin', 'reference-origin-label')
        colors = np.array([[71, 215, 236] if name.startswith('H') else [255, 186, 104] if name.startswith('V') else [166, 146, 255] for name in data['names']], dtype=np.uint8)
        self.point_mesh = pv.PolyData(xyz); self.point_mesh['rgb'] = colors
        p.add_mesh(self.point_mesh, scalars='rgb', rgb=True, point_size=11, render_points_as_spheres=True, name='points', pickable=True)
        if self.config['mode'] != 'Manual coordinates':
            forward = data['forward']; phi = np.deg2rad(self.config['zero_phi']); right = np.array([-np.sin(phi), np.cos(phi), 0]); up = np.cross(forward, right)
            for prefix, tangent, color in [('H', right, '#47d7ec'), ('V', up, '#ffba68')]:
                indices = [i for i, name in enumerate(data['names']) if prefix in name]
                if self.config['mode'] == 'Arc sweep' and prefix == 'V' and self.config['direction'] == 'hor_vert': indices.append(data['reference'])
                if len(indices) < 2: continue
                points = xyz[indices]; angles = np.arctan2((points-data['origin'])@tangent, (points-data['origin'])@forward)
                points = points[np.argsort(angles)]
                if self.config['mode'] == 'CTA-2034': points = np.vstack([points, points[0]])
                p.add_mesh(pv.lines_from_points(points), color=color, line_width=2, opacity=.55, pickable=False)
        if self.config['show_stage2_origin'] and (self.config['project_path'] or self.config['coeff_path']):
            try:
                frequency, origin = acoustic_origin(self.config)
                named.append((f'Acoustic origin · {frequency:g} Hz', origin))
            except (OSError, KeyError, ValueError): self.log.appendPlainText('Acoustic origin is unavailable in this coefficient file.')
        from plots import COLORS
        for index, (name, point) in enumerate(named):
            if name == 'Project reference' and np.allclose(point, data['origin']):
                continue  # Already shown by the green reference-origin marker.
            color = COLORS[index % len(COLORS)]
            p.add_mesh(pv.Sphere(radius=scale*.012, center=point), color=color, specular=.6)
            add_ball_label(point, name, f'waypoint-label-{index}')
        p.add_axes(xlabel='X / forward', ylabel='Y', zlabel='Z / up')
        p.show_grid(color='#7895a8', xtitle='X / m', ytitle='Y / m', ztitle='Z / m',
                    font_size=9, n_xlabels=3, n_ylabels=3, n_zlabels=3, grid='back', location='outer')
        self.points.blockSignals(True); self.points.setRowCount(len(xyz))
        for i, (name, coords) in enumerate(zip(data['names'], data['spherical'])):
            for j, value in enumerate([name, *[f'{v:.3f}' for v in coords[[2, 0, 1]]]]):
                item = W.QTableWidgetItem(value); item.setToolTip('XYZ / m: '+', '.join(f'{v:.5f}' for v in xyz[i])); self.points.setItem(i, j, item)
        self.points.selectRow(self.selected); self.points.blockSignals(False)
        scene_key = repr([self.config[k] for k in ('mode', 'dist_mic', 'range_deg', 'direction', 'manual_coords', 'project_geometry')])
        if camera:
            p.camera_position = camera
            if scene_key != getattr(self, 'scene_key', None): p.reset_camera(); self.remember_camera()
        else: self.camera('iso')
        self.scene_key = scene_key
        self.scene_initialized = True; self.highlight()
        self.scene_note.setText(f'{len(xyz)} exact export positions · click a point to inspect · drag to orbit · '+('Project cabinet' if known else 'No project cabinet geometry loaded'))

    def camera(self, mode='iso'):
        self.plotter.disable_parallel_projection()
        if mode == 'front': self.plotter.view_yz()
        elif mode == 'top': self.plotter.view_xy()
        else: self.plotter.view_isometric()
        self.plotter.reset_camera(); self.plotter.render()
        self.remember_camera()

    def remember_camera(self):
        position, focal, _ = self.plotter.camera_position
        self.home_focal = np.asarray(focal, float); self.home_distance = float(np.linalg.norm(np.asarray(position)-focal))

    def pick(self, point):
        if not hasattr(self, 'layout_data'): return
        distance = np.linalg.norm(self.layout_data['xyz']-np.asarray(point), axis=1)
        if distance.min() < max(.04, self.config['dist_mic']*.05): self.select(int(distance.argmin()))

    def table_select(self):
        if self.points.currentRow() >= 0: self.select(self.points.currentRow())

    def select(self, index):
        self.selected = int(index); self.points.blockSignals(True); self.points.selectRow(index); self.points.blockSignals(False)
        self.highlight()
        if self.dirty or (self.result and 'preview_point' in self.result and self.result['point_index'] != self.selected):
            self.changed(update_geometry=False)
            # Navigation should not incur the debounce used for typing settings.
            self.timer.stop(); self.preview_if_live()
        else: self.draw_response()

    def highlight(self):
        point = self.layout_data['xyz'][self.selected]; radius = max(.2, self.config['dist_mic'])*.023
        actor = self.plotter.renderer.actors.get('selected')
        if actor is None:
            actor = self.plotter.add_mesh(pv.Sphere(radius=1), name='selected', color='#7ae2b1', specular=.9, specular_power=25, reset_camera=False, pickable=False, render=False)
        actor.SetScale(radius, radius, radius); actor.SetPosition(*point)
        self.plotter.render(); name = self.layout_data['names'][self.selected]
        self.point_label.setText(f'{self.selected+1}/{len(self.layout_data["xyz"])} · {name}')

    def preview_if_live(self):
        if self.dirty and self.isVisible() and self.config['coeff_path']: self.start(False)

    def start(self, writing):
        if getattr(self.owner,'process_workspace',None) and self.owner.process_workspace.job:
            self.status.setText('Wait for processing to finish before running Export.');return
        if self.job is not None:
            if not writing: self.pending_preview = True
            return
        if self.owner.worker and self.owner.worker.isRunning():
            self.status.setText('Wait for sphere reconstruction to finish before running Export.'); return
        from export_engine import validate
        try: validate(self.config, writing)
        except Exception as exc: self.status.setText(str(exc)); return
        self.timer.stop(); self.pending_preview = False; self.job_generation = self.generation
        aggregate = False
        self.job = ExportWorker(self.config, self.owner.pool, writing, self.preview_cache, self.selected, aggregate)
        self.job.result.connect(self.completed); self.job.failed.connect(self.error); self.job.message.connect(self.log.appendPlainText)
        self.job.progress.connect(self.job_progress); self.job.finished.connect(self.finished)
        self.cli_run.setEnabled(False); self.export_button.setEnabled(False)
        if writing:
            self.sidebar_selector.setCurrentIndex(2); self.show_busy()
        else: self.busy_timer.start()
        self.tabs.setEnabled(not writing)
        self.metadata_editor.setEnabled(not writing)
        for widget in self.source_widgets: widget.setEnabled(not writing)
        self.owner.open_button.setEnabled(not writing)
        self.progress.setValue(0); self.status.setText('Exporting…' if writing else 'Evaluating full-resolution responses…')
        self.job.start()

    def show_busy(self):
        if self.job is not None:
            self.cancel_button.show(); self.cli_cancel.setVisible(self.job.writing); self.progress.show()

    def job_progress(self, value, message):
        if self.progress.isVisible(): self.progress.setValue(value); self.status.setText(message)
    def error(self, message): self.status.setText('Export: '+message); self.log.appendPlainText('ERROR: '+message)
    def cancel(self):
        self.timer.stop(); self.pending_preview = False
        if self.job: self.job.stop.set(); self.status.setText('Cancelling…')
    def completed(self, result):
        if self.job_generation != self.generation and not self.job.writing: return
        self.result = result; self.dirty = self.job_generation != self.generation
        if result['destination']:
            self.destination = result['destination']; self.open_folder.setEnabled(True); self.cli_open.setEnabled(True)
            self.status.setText('Export complete: '+self.destination); self.log.appendPlainText('Completed: '+self.destination)
        else:
            delay = '' if result['tof_time'] is None else f' · TOF {result["tof_time"]*1000:.4f} ms / {result["tof_distance"]:.4f} m'
            scope = 'selected point + reference' if 'preview_point' in result else f'{len(result["geometry"]["xyz"])} points'
            self.status.setText(f'Preview ready · {len(result["freqs"]):,} native frequency bins · {scope}'+delay)
        self.draw_response()
    def finished(self):
        self.busy_timer.stop(); self.progress.hide()
        self.cli_run.setEnabled(True); self.export_button.setEnabled(True); self.cancel_button.hide(); self.cli_cancel.hide(); self.tabs.setEnabled(True)
        self.metadata_editor.setEnabled(True)
        for widget in self.source_widgets: widget.setEnabled(True)
        self.owner.open_button.setEnabled(True)
        if self.job.stop.is_set(): self.status.setText('Cancelled; ready for another calculation.')
        self.job.deleteLater(); self.job = None
        if self.pending_preview: self.pending_preview = False; self.timer.start(0)

    def sync_plot_setup(self):
        self.config['plot_panes'] = [pane.state() for pane in self.custom_panes]

    def refresh_custom_panes(self):
        for pane in self.custom_panes: pane.refresh()
        self.sync_plot_setup()

    def draw_response(self, *_):
        self.refresh_custom_panes()
        if self.result is None or self.dirty: return
        result = self.result; f = result['freqs']
        if 'preview_point' in result: data = result['preview_point']
        elif 'data' in result: data = list(result['data'].values())[self.selected]
        else:
            raw = result['raw']['complex'][:, self.selected]; processed = result['processed'][:, self.selected]
            data = dict(complex=raw, mag=20*np.log10(abs(processed)+np.finfo(float).eps)+result['config']['frd_db_offset'], phase=np.angle(processed, deg=True))
        source = result['config']['coeff_path']
        label = f'{self.selected+1}/{len(result["geometry"]["xyz"])} · {result["geometry"]["names"][self.selected]}'
        self.response_panel.update_response(f, data['mag'], data['phase'], label, source)
        if 'preview_ir' in result:
            ir, times = result['preview_ir'], result['preview_ir_times']
        else:
            fs = result.get('raw', {}).get('fs') or (44100 if f[-1] < 23000 else 48000)
            ir = complex_to_ir(data['complex'], f, target_fs=fs)
            times = np.arange(len(ir))/fs
        self.ir_panel.update_ir(times, ir, result['tof_time'], source)
        self.csd_panel.update_ir(ir, 1/(times[1]-times[0]))
        for pane in self.custom_panes:
            for kind, widget in pane.native_widgets.items():
                if widget in (self.response_panel, self.ir_panel, self.csd_panel): continue
                if kind == 'response': widget.update_response(f, data['mag'], data['phase'], label, source)
                elif kind == 'impulse': widget.update_ir(times, ir, result['tof_time'], source)
                else: widget.update_ir(ir, 1/(times[1]-times[0]))

    def reveal(self):
        if self.destination: G.QDesktopServices.openUrl(C.QUrl.fromLocalFile(self.destination))
    def save_image(self):
        path, _ = W.QFileDialog.getSaveFileName(self, 'Save export geometry image', 'export-geometry.png', 'PNG (*.png)')
        if path: self.plotter.screenshot(path)
    def shutdown(self):
        for pane in self.custom_panes: pane.shutdown()
        self.timer.stop(); self.busy_timer.stop(); self.plotter.close(); self.csd_panel.view.shutdown()
