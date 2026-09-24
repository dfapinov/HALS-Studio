"""HALS Studio — standalone acoustic field explorer."""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path

import bootstrap
import numpy as np
import pyvista as pv
from pyvistaqt import QtInteractor
from PySide6 import QtCore as C, QtGui as G, QtWidgets as W
import acoustics as ac
from plots import (Chart, balloon_mesh, volume_mesh, draw_polars, draw_response,
                   draw_maps, draw_analysis, coverage_surface, audio_ticks, audio_frequency,
                   FREQUENCY_STRETCH, CYAN, AMBER)
from worker_pool import WarmPool


STYLE = """
QWidget { background: #0b141e; color: #c6d6e5; font-family: 'Segoe UI'; font-size: 12px; }
QMainWindow, QScrollArea, QScrollArea > QWidget > QWidget { background: #0b141e; }
QLabel#brand { font-size: 25px; font-weight: 700; color: #f1f7fd; }
QLabel#eyebrow { font-size: 10px; font-weight: 700; color: #52d9ec; letter-spacing: 2px; }
QLabel#muted { color: #829aaf; }
QLabel#hero { font-size: 24px; font-weight: 600; color: #f1f7fd; }
QLabel#badge { color: #ffca83; background: #30291e; border: 1px solid #625134; border-radius: 5px; padding: 5px 9px; }
QFrame#card { background: #101e2b; border: 1px solid #263848; border-radius: 7px; }
QFrame#card QLabel { background: transparent; }
QGroupBox { border: 1px solid #263848; border-radius: 6px; margin-top: 18px; padding: 12px 10px 8px; font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; color: #9eb5c8; }
QPushButton, QToolButton { background: #182b3b; border: 1px solid #2a4357; border-radius: 5px; padding: 7px 11px; }
QPushButton:hover, QToolButton:hover { background: #244359; border-color: #4fa5be; }
QPushButton:pressed, QPushButton:checked { background: #245d75; color: white; }
QPushButton:disabled { color: #556b7b; }
QToolButton#resetViewsButton { padding-right: 29px; }
QToolButton#resetViewsButton::menu-button { subcontrol-origin: padding; subcontrol-position: top right; width: 20px; border: none; border-left: 1px solid #2a4357; border-top-right-radius: 4px; border-bottom-right-radius: 4px; background: transparent; }
QToolButton#resetViewsButton::menu-button:hover { background: #244359; }

QPushButton#primary, QToolButton#primary { background: #599bda; color: #071620; border: none; font-weight: 700; }
QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit { background: #142432; border: 1px solid #2d4456; border-radius: 4px; padding: 5px; selection-background-color: #23728c; }
QComboBox { padding-right: 22px; }
QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: top right; width: 18px; border: none; background: transparent; margin-right: 3px; }
QComboBox QFrame { background: #142432; border: none; }
QComboBox QAbstractItemView { background: #142432; color: #c2d1df; border: 1px solid #2d4456; outline: 0; padding: 3px; selection-background-color: #245d75; }
QSlider::groove:horizontal { height: 4px; background: #293e50; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #4bd4e9; border-radius: 2px; }
QSlider::handle:horizontal { background: #b1f0f8; width: 13px; margin: -5px 0; border-radius: 6px; }
QTabWidget::pane { border: 1px solid #253849; border-radius: 4px; }
QTabBar::tab { padding: 12px 18px; color: #8da8bd; border-bottom: 2px solid transparent; }
QTabBar::tab:selected { color: #61dced; background: #132432; border-bottom: 2px solid #4ed6ea; }
QSplitter::handle { background: #172938; }
QStatusBar { background: #101e2b; color: #91aabe; }
QStatusBar::item { border: none; }
QStatusBar QLabel, QStatusBar QSizeGrip { background: transparent; border: none; }
QProgressBar { border: 1px solid #304454; border-radius: 3px; text-align: center; height: 14px; }
QProgressBar::chunk { background: #278ba2; }
QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: 14px; height: 14px; border: 1px solid #466074; border-radius: 3px; background: #122434; }
QCheckBox::indicator:checked { background: #599bda; border: 2px solid #91e5f1; }
QToolTip { color: #dfedf6; background: #1b3345; border: 1px solid #45677e; }
QMenu { background: #142432; border: 1px solid #355064; }
QMenu::item { padding: 7px 24px; }
QMenu::item:selected { background: #245d75; }
QScrollBar:vertical { background: #101c28; width: 8px; }
QScrollBar::handle:vertical { background: #314b60; min-height: 30px; border-radius: 3px; }
"""
for direction in ('up', 'down'):
    icon = (Path(__file__).resolve().parent / 'assets' / f'spin-{direction}.svg').as_posix()
    position = 'top right' if direction == 'up' else 'bottom right'
    STYLE += f'QSpinBox::{direction}-button, QDoubleSpinBox::{direction}-button {{ subcontrol-origin: padding; subcontrol-position: {position}; width: 16px; background: transparent; border: none; margin-right: 2px; }}'
    STYLE += f'QSpinBox::{direction}-arrow, QDoubleSpinBox::{direction}-arrow {{ image: url("{icon}"); width: 10px; height: 9px; }}'
STYLE += 'QComboBox::down-arrow, QToolButton#resetViewsButton::menu-arrow { image: url("'+(Path(__file__).resolve().parent/'assets'/'spin-down.svg').as_posix()+'"); width: 10px; height: 9px; }'
STYLE += 'QSpinBox, QDoubleSpinBox { padding-right: 22px; }'



def label(text, name=None):
    obj = W.QLabel(text)
    if name:
        obj.setObjectName(name)
    return obj


def combo(items):
    obj = W.QComboBox()
    obj.addItems(items)
    return obj


def number(value, minimum, maximum, suffix="", decimals=1):
    obj = W.QDoubleSpinBox()
    obj.setRange(minimum, maximum)
    obj.setDecimals(decimals)
    obj.setValue(value)
    obj.setSuffix(suffix)
    obj.setKeyboardTracking(False)
    return obj


def button(text, callback, primary=False):
    obj = W.QPushButton(text)
    obj.clicked.connect(callback)
    if primary:
        obj.setObjectName("primary")
    return obj


class Worker(C.QThread):
    progress = C.Signal(int, str)
    loaded = C.Signal(object)
    failed = C.Signal(str)

    def __init__(self, fn, kwargs):
        super().__init__()
        self.fn, self.kwargs = fn, kwargs

    def run(self):
        try:
            result = self.fn(**self.kwargs, progress=self.progress.emit, cancelled=self.isInterruptionRequested)
            if not self.isInterruptionRequested():
                self.loaded.emit(result)
        except ac.Cancelled:
            pass
        except Exception:
            self.failed.emit(traceback.format_exc())


class ReconstructionDialog(W.QDialog):
    def __init__(self, path, parent):
        super().__init__(parent)
        self.setWindowTitle("Reconstruct a complex sphere")
        self.setMinimumWidth(530)
        form = W.QFormLayout(self)
        name = label(Path(path).name, "eyebrow")
        form.addRow(name)
        note = label("Evaluate the HALS sound field around +X (front), +Y (left), +Z (up).\nChoose a radius outside the source / scan boundary for outgoing-field analysis.", "muted")
        note.setWordWrap(True)
        form.addRow(note)
        self.radius = number(2, .05, 100, " m", 3)
        self.step = combo(["5° · 2,664 directions", "10° · 684 directions", "3° · 7,320 directions", "2° · 16,380 directions"])
        self.bin_counts = [480, 960, 240, 120, 60, 0]
        self.bins = combo(["480 log targets · fine", "960 log targets · extra fine", "240 log targets",
                           "120 log targets · coarse", "60 log targets · preview", "All native bins · phase / delay"])
        self.mode = combo(["Internal", "External", "Total"])
        self.fmin, self.fmax = number(20, 1, 100000, " Hz", 0), number(20000, 2, 200000, " Hz", 0)
        self.padding = number(50, 0, 100000, " samples", 0)
        self.origins = W.QCheckBox("Use frequency-dependent Stage 2 origins")
        self.origins.setChecked(True)
        self.offsets = [number(0, -100, 100, " m", 4) for _ in range(3)]
        with ac.h5py.File(path, "r") as h:
            self.native_freqs = h["freqs"][:]
        available = self.native_freqs[np.isfinite(self.native_freqs) & (self.native_freqs > 0)]
        if len(available) < 2:
            raise ValueError("The coefficient file must contain at least two positive frequency bins.")
        # Round the limits outward so fractional endpoint bins are included.
        self.fmin.setRange(0, max(100000., float(np.ceil(available.max()))))
        self.fmax.setMaximum(max(200000., float(np.ceil(available.max()))))
        self.fmin.setValue(float(np.floor(available.min())))
        self.fmax.setValue(float(np.ceil(available.max())))
        for title, obj in (("Observation radius", self.radius), ("Angular sampling", self.step), ("Frequency sampling", self.bins),
                           ("Field component", self.mode), ("Lowest frequency", self.fmin), ("Highest frequency", self.fmax),
                           ("Capture padding to remove", self.padding), ("", self.origins)):
            form.addRow(title, obj)
        self.sampling_note = label("", "muted")
        self.sampling_note.setWordWrap(True)
        form.addRow(self.sampling_note)
        self.bins.currentIndexChanged.connect(self.update_sampling)
        self.fmin.valueChanged.connect(self.update_sampling)
        self.fmax.valueChanged.connect(self.update_sampling)
        self.update_sampling()
        for axis, obj in zip("XYZ", self.offsets):
            form.addRow(f"Sphere centre {axis}", obj)
        note = label("Physical time of flight is retained. No microphone calibration or FRD level offset is applied.\nAll bins at 2° can require substantial RAM and reconstruction time.", "muted")
        note.setWordWrap(True)
        form.addRow(note)
        buttons = W.QDialogButtonBox(W.QDialogButtonBox.Ok | W.QDialogButtonBox.Cancel)
        buttons.button(W.QDialogButtonBox.Ok).setText("Reconstruct sphere")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def options(self):
        return dict(radius=self.radius.value(), step=[5, 10, 3, 2][self.step.currentIndex()],
                    bins=self.bin_counts[self.bins.currentIndex()], mode=self.mode.currentText(),
                    fmin=self.fmin.value(), fmax=self.fmax.value(), padding=int(self.padding.value()),
                    origins=self.origins.isChecked(), offset=[w.value() for w in self.offsets])

    def update_sampling(self):
        try:
            indices = ac.select_frequencies(self.native_freqs, self.bin_counts[self.bins.currentIndex()], self.fmin.value(), self.fmax.value())
            f = self.native_freqs[indices]
            self.sampling_note.setText(f"{len(f):,} unique native frequencies will be reconstructed.\n"
                "Log targets snap to measured bins; duplicate targets are removed. "
                f"Largest adjacent gap: {np.max(np.diff(f)):,.1f} Hz. No complex interpolation.")
        except ValueError as exc:
            self.sampling_note.setText(str(exc))


class Atlas(W.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("HALS Studio | Acoustic field explorer")
        self.resize(1580, 990)
        self.setMinimumSize(1120, 740)
        self.setStyleSheet(STYLE)
        self.setWindowIcon(G.QIcon(str(bootstrap.HERE / "studio.ico")))
        self.sphere = None
        self.comparison = None
        self.worker = None
        self.source_path = None
        self.source_options = None
        self.pending_session = None
        self.mesh = None
        self.volume_dirty = True
        self.chart_dirty = True
        self.pool = WarmPool()
        self.pool.start()
        self.probe_widget = None
        self.play_timer = C.QTimer(self)
        self.play_timer.setInterval(160)
        self.play_timer.timeout.connect(self.advance)
        self.refresh_timer = C.QTimer(self)
        self.refresh_timer.setSingleShot(True)
        self.refresh_timer.setInterval(60)
        self.refresh_timer.timeout.connect(self.refresh)
        self._build()
        self._menus()
        self.pool_timer = C.QTimer(self)
        self.pool_timer.setInterval(300)
        self.pool_timer.timeout.connect(self.pool_status)
        self.pool_timer.start()
        self.setAcceptDrops(True)
        self.set_sphere(self.sphere)

    def _build(self):
        root = W.QWidget()
        self.setCentralWidget(root)
        layout = W.QVBoxLayout(root)
        layout.setContentsMargins(18, 14, 18, 9)
        layout.setSpacing(12)
        header = W.QHBoxLayout()
        logo = W.QVBoxLayout()
        logo.addWidget(label("HALS Studio", "brand"))
        logo.addWidget(label("ACOUSTIC FIELD EXPLORER", "eyebrow"))
        header.addLayout(logo)
        header.addSpacing(32)
        header.addWidget(label("FROM MEASUREMENT TO INSIGHT", "muted"))
        header.addStretch()
        self.badge = label("SYNTHETIC DEMO", "badge")
        self.badge.setFixedHeight(29)
        header.addWidget(self.badge)
        self.open_button = button("＋  Open data", self.open_data, True)
        header.addWidget(self.open_button)
        export = button("Export  ▾", lambda: None)
        menu = W.QMenu(export)
        for title, fn in (("Workspace screenshot…", self.screenshot), ("3D viewport PNG…", self.scene_screenshot),
                          ("Complex sphere NPZ…", self.save_cache), ("Analysis CSV…", self.save_csv),
                          ("3D mesh VTK…", self.save_mesh), ("Active charts PNG…", self.save_chart),
                          ("Session…", self.save_session)):
            menu.addAction(title, fn)
        export.setMenu(menu)
        header.addWidget(export)
        layout.addLayout(header)
        body = W.QHBoxLayout()
        body.setSpacing(15)
        scroll = W.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(W.QFrame.NoFrame)
        scroll.setFixedWidth(265)
        scroll.setHorizontalScrollBarPolicy(C.Qt.ScrollBarAlwaysOff)
        side = W.QWidget()
        controls = W.QVBoxLayout(side)
        controls.setContentsMargins(0, 0, 6, 0)
        controls.setSpacing(12)
        self.dataset_label = label("", "eyebrow")
        self.dataset_label.setWordWrap(True)
        controls.addWidget(self.dataset_label)
        self.dataset_info = label("", "muted")
        self.dataset_info.setWordWrap(True)
        self.dataset_info.setMaximumWidth(242)
        controls.addWidget(self.dataset_info)

        group = W.QGroupBox("FREQUENCY")
        g = W.QVBoxLayout(group)
        self.frequency_label = label("1,000 Hz", "hero")
        g.addWidget(self.frequency_label)
        self.frequency = W.QSlider(C.Qt.Horizontal)
        self.frequency.setTracking(True)
        self.frequency.valueChanged.connect(self.schedule)
        g.addWidget(self.frequency)
        row = W.QHBoxLayout()
        previous = button("‹", lambda: self.frequency.setValue(max(0, self.frequency.value() - 1)))
        previous.setFixedWidth(36)
        row.addWidget(previous)
        self.play = button("▶  Sweep", self.toggle_play)
        self.play.setCheckable(True)
        row.addWidget(self.play)
        following = button("›", self.advance)
        following.setFixedWidth(36)
        row.addWidget(following)
        g.addLayout(row)
        self.frequency_entry = number(1000, 1, 200000, " Hz", 1)
        self.frequency_entry.valueChanged.connect(self.jump_frequency)
        g.addWidget(self.frequency_entry)
        self.bin_label = label("", "muted")
        self.bin_label.setWordWrap(True)
        g.addWidget(self.bin_label)
        controls.addWidget(group)

        group = W.QGroupBox("FIELD DISPLAY")
        g = W.QFormLayout(group)
        g.setRowWrapPolicy(W.QFormLayout.WrapAllRows)
        self.normalization = combo(["Peak", "On axis"])
        self.smoothing = combo(["None", "1/24 octave", "1/12 octave", "1/6 octave", "1/3 octave"])
        self.dynamic = number(36, 12, 96, " dB", 0)
        self.mapping = combo(["dB radius", "Pressure radius", "Colour sphere (no deformation)"])
        self.color = combo(["turbo", "viridis", "inferno", "coolwarm", "PColor"])
        self.color.setToolTip("PColor: classic blue–cyan–green–yellow–red pseudocolour palette (jet).")
        for title, obj in (("Normalize each frequency to", self.normalization), ("Energy smoothing", self.smoothing),
                           ("Display range", self.dynamic), ("Balloon geometry", self.mapping), ("Colour palette", self.color)):
            g.addRow(title, obj)
        self.wire = W.QCheckBox("Mesh edges")
        self.reference = W.QCheckBox("Reference sphere")
        self.reference.setChecked(True)
        self.phase_color = W.QCheckBox("Colour balloon by phase")
        for w in (self.reference, self.wire, self.phase_color):
            g.addRow(w)
            w.toggled.connect(self.schedule)
        for w in (self.normalization, self.smoothing, self.mapping, self.color):
            w.currentIndexChanged.connect(self.settings_changed)
        self.dynamic.valueChanged.connect(self.settings_changed)
        controls.addWidget(group)

        group = W.QGroupBox("DIRECTION PROBE")
        g = W.QFormLayout(group)
        self.azimuth = number(0, -180, 180, "°", 1)
        self.elevation = number(0, -90, 90, "°", 1)
        self.delay = number(0, -1000, 1000, " ms", 4)
        self.level_offset = number(0, -200, 200, " dB", 2)
        g.addRow("Azimuth", self.azimuth)
        g.addRow("Elevation", self.elevation)
        g.addRow("Remove delay", self.delay)
        g.addRow("Level offset", self.level_offset)
        for w in (self.azimuth, self.elevation, self.delay, self.level_offset):
            w.valueChanged.connect(self.settings_changed)
        self.probe_label = label("", "muted")
        self.probe_label.setWordWrap(True)
        g.addRow(self.probe_label)
        controls.addWidget(group)
        controls.addWidget(button("Pin as comparison", self.pin_comparison))
        self.compare_label = label("No reference pinned", "muted")
        self.compare_label.setWordWrap(True)
        self.compare_label.setMaximumWidth(242)
        controls.addWidget(self.compare_label)
        controls.addWidget(button("Clear comparison", self.clear_comparison))
        controls.addWidget(button("Dataset details", self.details))
        controls.addStretch()
        scroll.setWidget(side)
        body.addWidget(scroll)

        content = W.QVBoxLayout()
        cards = W.QHBoxLayout()
        self.cards = []
        for title in ("ON AXIS", "DIRECTIVITY INDEX", "HORIZONTAL / −6 dB", "VERTICAL / −6 dB"):
            card = W.QFrame()
            card.setObjectName("card")
            cl = W.QVBoxLayout(card)
            cl.setContentsMargins(14, 10, 14, 10)
            cl.addWidget(label(title, "eyebrow"))
            value = label("—", "hero")
            cl.addWidget(value)
            self.cards.append(value)
            cards.addWidget(card)
        content.addLayout(cards)
        self.tabs = W.QTabWidget()
        self.tabs.currentChanged.connect(self.tab_changed)
        content.addWidget(self.tabs, 1)
        field = W.QWidget()
        fl = W.QVBoxLayout(field)
        fl.setContentsMargins(6, 6, 6, 6)
        toolbar = W.QHBoxLayout()
        self.field_title = label("3D RADIATION FIELD", "eyebrow")
        toolbar.addWidget(self.field_title)
        toolbar.addStretch()
        self.orbit_mode = combo(["Az / El · no roll", "Free orbit"])
        self.orbit_mode.currentIndexChanged.connect(self.set_orbit_mode)
        toolbar.addWidget(self.orbit_mode)
        for title in ("Front", "Top", "Side", "Iso"):
            toolbar.addWidget(button(title, lambda checked=False, view=title: self.camera(view)))
        fl.addLayout(toolbar)
        vertical = W.QSplitter(C.Qt.Vertical)
        horizontal = W.QSplitter(C.Qt.Horizontal)
        self.plotter = QtInteractor(field, auto_update=False, multi_samples=4)
        self.plotter.set_background("#0c1823", top="#132638")
        self.plotter.enable_terrain_style()
        self.plotter.add_axes(xlabel="X / front", ylabel="Y / left", zlabel="Z / up", color="#98acbd")
        self.plotter.enable_point_picking(callback=self.pick_point, show_message=False, show_point=False, left_clicking=False)
        horizontal.addWidget(self.plotter.interactor)
        self.polars = Chart()
        self.polars.setMinimumWidth(230)
        horizontal.addWidget(self.polars)
        horizontal.setSizes([850, 270])
        vertical.addWidget(horizontal)
        self.response = Chart()
        self.response.setMinimumHeight(190)
        self.response.canvas.mpl_connect("button_press_event", self.chart_click)
        response_panel = W.QWidget()
        response_layout = W.QVBoxLayout(response_panel)
        response_layout.setContentsMargins(0, 0, 0, 0)
        response_controls = W.QHBoxLayout()
        self.response_mode = combo(["Overview", "Horizontal SPL", "Vertical SPL", "Horizontal polar", "Vertical polar"])
        self.response_extent = number(90, 10, 180, "°", 0)
        self.response_step = number(10, 1, 90, "°", 0)
        self.response_symmetric = W.QCheckBox("± angles")
        response_controls.addWidget(self.response_mode)
        response_controls.addWidget(label("Range"))
        response_controls.addWidget(self.response_extent)
        response_controls.addWidget(label("Step"))
        response_controls.addWidget(self.response_step)
        response_controls.addWidget(self.response_symmetric)
        response_controls.addStretch()
        self.response_mode.currentIndexChanged.connect(self.response_controls_changed)
        self.response_extent.valueChanged.connect(self.schedule)
        self.response_step.valueChanged.connect(self.schedule)
        self.response_symmetric.toggled.connect(self.schedule)
        self.response_controls_changed()
        response_layout.addLayout(response_controls)
        response_layout.addWidget(self.response)
        vertical.addWidget(response_panel)
        vertical.setSizes([550, 230])
        fl.addWidget(vertical)
        fl.addWidget(label("DRAG to orbit · SCROLL to zoom · Drag the green handle to probe · P picks a surface direction", "muted"))
        self.tabs.addTab(field, "01  Sound field")

        volume = W.QWidget()
        vl = W.QVBoxLayout(volume)
        row = W.QHBoxLayout()
        row.addWidget(label("FREQUENCY × AZIMUTH × ELEVATION", "eyebrow"))
        row.addStretch()
        self.volume_mode = combo(["Coverage envelopes", "Isosurfaces only", "H/V colour slices"])
        self.volume_mode.currentIndexChanged.connect(self.volume_changed)
        row.addWidget(self.volume_mode)
        self.iso_checks = []
        self.frequency_color = W.QCheckBox("Frequency colour")
        self.frequency_color.setChecked(True)
        self.frequency_color.toggled.connect(self.volume_changed)
        row.addWidget(self.frequency_color)
        for value, color in ((-6, "#ffb35b"), (-12, "#43d8e4"), (-24, "#697df4")):
            check = W.QCheckBox(f"{value} dB")
            check.setChecked(True)
            check.setStyleSheet(f"color: {color};")
            check.toggled.connect(self.volume_changed)
            row.addWidget(check)
            self.iso_checks.append(check)
        row.addWidget(button("Reset view", self.reset_volume_camera))
        vl.addLayout(row)
        self.volume_plotter = QtInteractor(volume, auto_update=False, multi_samples=4)
        self.volume_plotter.set_background("#0c1823", top="#142738")
        vl.addWidget(self.volume_plotter.interactor, 1)
        self.volume_note = label("Level isosurfaces over the front hemisphere. Frequency runs logarithmically; horizontal and vertical angles span ±90°. Colour = log frequency on the inner surface.", "muted")
        self.volume_note.setWordWrap(True)
        vl.addWidget(self.volume_note)
        self.tabs.addTab(volume, "02  Spectral volume")
        self.maps = Chart(toolbar=True)
        self.maps.canvas.mpl_connect("button_press_event", self.map_click)
        self.tabs.addTab(self.maps, "03  Directivity maps")
        self.analysis = Chart(toolbar=True)
        self.tabs.addTab(self.analysis, "04  Response & phase")
        body.addLayout(content, 1)
        layout.addLayout(body, 1)
        self.progress = W.QProgressBar()
        self.progress.setMaximumWidth(200)
        self.progress.hide()
        self.cancel_button = button("Cancel reconstruction", self.cancel_load)
        self.cancel_button.hide()
        self.statusBar().addPermanentWidget(self.progress)
        self.statusBar().addPermanentWidget(self.cancel_button)
        self.worker_label = label("Workers warming…", "muted")
        self.statusBar().addPermanentWidget(self.worker_label)
        self.statusBar().showMessage("Ready")

    def _menus(self):
        file = self.menuBar().addMenu("File")
        for title, fn, shortcut in (("Open coefficients / sphere…", self.open_data, "Ctrl+O"),
                                     ("Import Stage 5 export folder…", self.open_folder, ""),
                                     ("Load session…", self.load_session, "Ctrl+L"),
                                     ("Save session…", self.save_session, "Ctrl+S"),
                                     ("Workspace screenshot…", self.screenshot, "Ctrl+Shift+S")):
            action = file.addAction(title, fn)
            if shortcut:
                action.setShortcut(shortcut)
        file.addSeparator()
        file.addAction("Restart workers", self.restart_pool)
        file.addAction("Exit", self.close)
        self.menuBar().addMenu("Help").addAction("Controls & acoustic conventions", self.help)
        G.QShortcut(G.QKeySequence("Space"), self, activated=self.toggle_play)
        G.QShortcut(G.QKeySequence("Right"), self, activated=self.advance)
        G.QShortcut(G.QKeySequence("Left"), self, activated=lambda: self.frequency.setValue(max(0, self.frequency.value() - 1)))

    def octave(self):
        return [0, 24, 12, 6, 3][self.smoothing.currentIndex()]

    def schedule(self, *_):
        self.refresh_timer.start()

    def settings_changed(self, *_):
        if self.sphere is None: return
        level_key = (id(self.sphere), self.octave())
        if getattr(self, "_level_key", None) != level_key:
            self.levels = self.sphere.levels(self.octave())
            self._level_key = level_key
        self.relative = self.sphere.relative(self.levels, self.normalization.currentText())
        self.volume_dirty = self.chart_dirty = True
        self.schedule()

    def set_sphere(self, sphere):
        self.play_timer.stop()
        self.play.setChecked(False)
        self.play.setText("▶  Sweep")
        self.sphere = sphere
        if sphere is None: return
        self.frequency.blockSignals(True)
        self.frequency.setRange(0, len(sphere.freqs) - 1)
        self.frequency.setValue(int(np.argmin(abs(sphere.freqs - 1000))))
        self.frequency.blockSignals(False)
        self.dataset_label.setText(sphere.name.upper())
        self.dataset_info.setText(f"{len(sphere.freqs):,} frequencies · {len(sphere.elevation)*len(sphere.azimuth):,} directions\n"
                                  f"{sphere.metadata.get('radius_m', 0):g} m · {sphere.metadata.get('mode', 'Complex export')}\n"
                                  f"{sphere.freqs[0]:g}–{sphere.freqs[-1]:g} Hz")
        targets = sphere.metadata.get("requested_frequency_targets")
        if targets:
            self.dataset_info.setText(self.dataset_info.text() + f"\n{targets} log targets → {len(sphere.freqs)} unique bins")
        self.badge.setText("SYNTHETIC DEMO" if sphere.metadata.get("demo") else "HALS / COMPLEX FIELD")
        self.settings_changed()
        self.refresh()
        self.camera("Iso")
        self.statusBar().showMessage(f"Loaded {sphere.name} · original complex pressure preserved")

    def refresh(self):
        if self.sphere is None: return
        s, i = self.sphere, self.frequency.value()
        f = s.freqs[i]
        self.frequency_label.setText(f"{f:,.0f} Hz")
        self.frequency_entry.blockSignals(True)
        self.frequency_entry.setValue(f)
        self.frequency_entry.blockSignals(False)
        gap = f"Next +{s.freqs[i+1]-f:,.1f} Hz" if i+1 < len(s.freqs) else "Highest stored frequency"
        self.bin_label.setText(f"Bin {i+1:,} / {len(s.freqs):,} · {gap}")
        idx = s.index(self.azimuth.value(), self.elevation.value())
        p = s.pressure[i, *idx]
        self.probe_label.setText(f"Sample: H {s.azimuth[idx[1]]:+g}° / V {s.elevation[idx[0]]:+g}°\n"
                                 f"{self.levels[i, *idx]+self.level_offset.value():.2f} dB · {np.angle(p, deg=True):+.1f}° raw phase")
        metrics = s.metrics(self.levels)
        angles, h, v = s.cuts(self.levels)
        values = [f"{metrics['on_axis'][i]+self.level_offset.value():.1f} dB", f"{metrics['directivity_index'][i]:.1f} dB"]
        for cut in (h, v):
            bw = ac.beamwidth(angles, cut[i:i+1])[0]
            values.append(f"{bw:.0f}°" if np.isfinite(bw) else "No crossing")
        for card, value in zip(self.cards, values):
            card.setText(value)
        active = self.tabs.currentIndex()
        if active == 0:
            self.render_balloon()
            draw_polars(self.polars, s, self.relative, i, self.dynamic.value())
            draw_response(self.response, s, self.levels, i, (self.azimuth.value(), self.elevation.value()),
                          self.level_offset.value(), self.comparison, self.response_mode.currentText(),
                          self.response_extent.value(), self.response_step.value(), self.response_symmetric.isChecked(), self.dynamic.value())
        elif active == 1:
            if self.volume_dirty:
                self.render_volume()
            self.render_frequency_plane()
        elif active == 2:
            draw_maps(self.maps, s, self.levels, self.relative, i, self.dynamic.value(), self.color.currentText())
        elif active == 3:
            draw_analysis(self.analysis, s, self.levels, (self.azimuth.value(), self.elevation.value()),
                          self.delay.value(), self.level_offset.value(), self.comparison)

    def render_balloon(self):
        s, i = self.sphere, self.frequency.value()
        self.mesh = balloon_mesh(s, self.relative[i], self.dynamic.value(), self.mapping.currentText())
        scalar = "Relative level / dB"
        cmap, clim = self.color.currentText(), (-self.dynamic.value(), 0)
        if self.phase_color.isChecked():
            phase = np.angle(s.pressure[i] * np.exp(2j * np.pi * s.freqs[i] * self.delay.value() / 1000), deg=True)
            self.mesh["Phase / degrees"] = np.column_stack((phase, phase[:, 0])).ravel(order="F")
            scalar, cmap, clim = "Phase / degrees", "twilight", (-180, 180)
        self.plotter.remove_scalar_bar(render=False) if self.plotter.scalar_bars else None
        self.plotter.add_mesh(self.mesh, name="field", scalars=scalar, cmap=cmap, clim=clim,
                              smooth_shading=True, show_edges=self.wire.isChecked(), edge_color="#314d62",
                              specular=.3, specular_power=25, ambient=.25, diffuse=.8,
                              scalar_bar_args=dict(title=scalar, color="#bed0e0", vertical=True, position_x=.87,
                                                   position_y=.22, height=.57, width=.055, title_font_size=11,
                                                   label_font_size=10, fmt="%.0f"), reset_camera=False)
        if self.reference.isChecked():
            xyz = ac.directions(np.arange(-90, 91, 10), np.arange(-180, 181, 15)) * 1.005
            reference_mesh = pv.StructuredGrid(xyz[..., 0], xyz[..., 1], xyz[..., 2])
            self.plotter.add_mesh(reference_mesh, name="reference",
                                  style="wireframe", color="#678296", opacity=.17, line_width=.6, reset_camera=False)
        else:
            self.plotter.remove_actor("reference", reset_camera=False)
        idx = s.index(self.azimuth.value(), self.elevation.value())
        shape = (len(s.elevation), len(s.azimuth) + 1)
        vertex = np.ravel_multi_index(idx, shape, order="F")
        point = self.mesh.points[vertex]
        self.plotter.add_mesh(pv.Line((0, 0, 0), point * 1.08), name="probe", color="#b8ffdf", line_width=2,
                              reset_camera=False)
        direction = ac.directions([self.elevation.value()], [self.azimuth.value()])[0, 0]
        handle = direction * 1.06
        if self.probe_widget is None:
            self.probe_widget = self.plotter.add_sphere_widget(self.drag_probe, center=handle, radius=.055,
                color="#90ffbf", selected_color="#ffffff", pass_widget=True, test_callback=False,
                interaction_event="always", theta_resolution=16, phi_resolution=16)
            self.probe_widget.SetScale(False)
        else:
            self.probe_widget.SetCenter(handle)
        self.plotter.add_mesh(pv.Line(point, handle), name="probe_handle_line", color="#90ffbf", line_width=2, reset_camera=False)
        self.plotter.add_text(f"{s.freqs[i]:,.0f} Hz\n{self.normalization.currentText()} reference · {self.dynamic.value():g} dB span",
                              position="upper_left", font_size=11, color="#9fb9ce", name="readout")
        self.field_title.setText(f"3D RADIATION FIELD   /   {self.mapping.currentText().upper()}")
        self.plotter.render()

    def render_volume(self):
        camera = self.volume_plotter.camera_position if self.volume_plotter.actors else None
        self.volume_plotter.clear()
        self.volume_grid = volume_mesh(self.sphere, self.relative)
        count = 0
        slices = self.volume_mode.currentIndex() == 2
        for control in [self.frequency_color, *self.iso_checks]:
            control.setEnabled(not slices)
        for check, level, color, opacity in zip(self.iso_checks, (-6, -12, -24), ("#ffba68", "#43d8e4", "#7487f7"), (.92, .32, .15)):
            if not check.isChecked() or slices:
                continue
            surface = coverage_surface(self.volume_grid, level, closed=self.volume_mode.currentIndex() == 0)
            if surface.n_points:
                kwargs = {"color": color}
                if self.frequency_color.isChecked() and level == -6:
                    surface["log10 frequency"] = surface.points[:, 0]
                    kwargs = dict(scalars="log10 frequency", cmap="turbo_r", show_scalar_bar=False,
                                  clim=FREQUENCY_STRETCH * np.log10(self.sphere.freqs[[0, -1]]))
                self.volume_plotter.add_mesh(surface, name=f"iso{level}", opacity=opacity,
                                             smooth_shading=True, specular=.3, label=f"{level} dB", reset_camera=False, **kwargs)
                count += 1
        if slices:
            for name, normal in (("Horizontal", (0, 0, 1)), ("Vertical", (0, 1, 0))):
                cut = self.volume_grid.slice(normal=normal, origin=(0, 0, 0))
                self.volume_plotter.add_mesh(cut, name=name, scalars="Relative level / dB", cmap=self.color.currentText(),
                    clim=(-self.dynamic.value(), 0), show_scalar_bar=name == "Horizontal", lighting=False,
                    scalar_bar_args={"title": "Relative level / dB", "color": "#c0d4e3"}, reset_camera=False)
        self.volume_plotter.add_mesh(self.volume_grid.outline(), color="#597387", line_width=1, reset_camera=False)
        self.volume_plotter.show_bounds(xtitle="Frequency / Hz", ytitle="Azimuth / degrees", ztitle="Elevation / degrees",
                                       color="#9cb6c9", font_size=10, grid="back", location="outer", n_xlabels=5,
                                       n_ylabels=3, n_zlabels=3, show_xlabels=False,
                                       axes_ranges=(*np.log10(self.sphere.freqs[[0, -1]]), -90, 90, -90, 90))
        ticks = audio_ticks(*self.sphere.freqs[[0, -1]])
        if not len(ticks):
            ticks = self.sphere.freqs[[0, -1]]
        positions = np.column_stack((FREQUENCY_STRETCH*np.log10(ticks), np.full(len(ticks), -1.13), np.full(len(ticks), -1.13)))
        self.volume_plotter.add_point_labels(positions, [audio_frequency(v) for v in ticks], name="audio_ticks",
            font_size=12, point_size=0, shape_opacity=0, text_color="#c0d4e3", always_visible=True,
            show_points=False, reset_camera=False)
        for n, value in enumerate(ticks):
            x = FREQUENCY_STRETCH*np.log10(value)
            self.volume_plotter.add_mesh(pv.Line((x, -1, -1), (x, 1, -1)), name=f"tick_grid{n}",
                                         color="#354e61", line_width=.5, reset_camera=False)
        if count:
            self.volume_plotter.add_legend(bcolor="#142331", size=(.15, .14))
        elif not slices:
            self.volume_plotter.add_text("No selected level crossings in this field", font_size=12, color="#afc5d8")
        if camera:
            self.volume_plotter.camera_position = camera
        else:
            self.reset_volume_camera()
        self.volume_note.setText([
            "Coverage above −6/−12/−24 dB. Flat caps mean coverage reaches the sampled boundary, not a measured level crossing. Colour range does not alter these thresholds.",
            "Only −6/−12/−24 dB crossings are drawn. Broad LF coverage can have no crossings; use Coverage envelopes or H/V colour slices.",
            "Horizontal (elevation 0°) and vertical (azimuth 0°) slices. Colour uses the selected palette, normalization and display range."
        ][self.volume_mode.currentIndex()])
        self.volume_dirty = False

    def render_frequency_plane(self):
        x = FREQUENCY_STRETCH * np.log10(self.sphere.freqs[self.frequency.value()])
        plane = pv.Plane(center=(x, 0, 0), direction=(1, 0, 0), i_size=2, j_size=2)
        self.volume_plotter.add_mesh(plane, name="frequency", color="#c9f3ff", opacity=.08, show_edges=True, reset_camera=False)
        self.volume_plotter.add_text(f"SELECTED  {self.sphere.freqs[self.frequency.value()]:,.0f} Hz", position="upper_left",
                                     font_size=11, color="#bee7f4", name="frequency_label")
        self.volume_plotter.render()

    def reset_volume_camera(self):
        center = FREQUENCY_STRETCH * np.mean(np.log10(self.sphere.freqs[[0, -1]]))
        self.volume_plotter.camera_position = [(center-3, -7, 3), (center, 0, 0), (0, 0, 1)]
        self.volume_plotter.reset_camera()
        self.volume_plotter.render()

    def camera(self, name):
        if name == "Front":
            self.plotter.view_yz()
        elif name == "Top":
            self.plotter.view_xy()
        elif name == "Side":
            self.plotter.view_xz()
        else:
            self.plotter.camera_position = [(3.5, -5, 2.8), (0, 0, 0), (0, 0, 1)]
        self.plotter.reset_camera()
        self.plotter.camera.zoom(1.48)
        self.plotter.render()

    def set_orbit_mode(self):
        if self.orbit_mode.currentIndex() == 0:
            self.plotter.camera.up = (0, 0, 1)
            self.plotter.enable_terrain_style()
        else:
            self.plotter.enable_trackball_style()
        self.plotter.render()

    def response_controls_changed(self):
        mode = self.response_mode.currentText()
        self.response_extent.setEnabled(mode != "Overview")
        self.response_step.setEnabled("SPL" in mode)
        self.response_symmetric.setEnabled("SPL" in mode)
        self.schedule()

    def drag_probe(self, point, widget):
        radius = np.linalg.norm(point)
        if radius < 1e-8:
            return
        direction = np.asarray(point) / radius
        widget.SetCenter(direction * 1.06)
        for control, value in ((self.azimuth, np.degrees(np.arctan2(direction[1], direction[0]))),
                               (self.elevation, np.degrees(np.arcsin(np.clip(direction[2], -1, 1))))):
            control.blockSignals(True)
            control.setValue(value)
            control.blockSignals(False)
        self.schedule()

    def pool_status(self):
        state = self.pool.state
        if state == "ready":
            self.worker_label.setText(f"{self.pool.workers} workers ready")
        elif state == "warming":
            self.worker_label.setText(f"Workers warming · {self.pool.initialized}/{self.pool.workers}")
        else:
            self.worker_label.setText(f"Workers {state}")
        self.worker_label.setToolTip(self.pool.error or "Viewer-owned Stage 5 process pool; reused between imports.")

    def restart_pool(self):
        if self.worker and self.worker.isRunning():
            self.statusBar().showMessage("Cancel the current reconstruction before restarting workers.")
            return
        self.pool.close()
        self.pool = WarmPool()
        self.pool.start()

    def volume_changed(self):
        self.volume_dirty = True
        self.schedule()

    def tab_changed(self, *_):
        if hasattr(self, "levels"):
            self.schedule()

    def advance(self):
        if self.sphere is None: return
        self.frequency.setValue((self.frequency.value() + 1) % len(self.sphere.freqs))

    def toggle_play(self):
        if self.sphere is None: return
        if self.play_timer.isActive():
            self.play_timer.stop()
            self.play.setChecked(False)
            self.play.setText("▶  Sweep")
        else:
            self.play_timer.start()
            self.play.setChecked(True)
            self.play.setText("Ⅱ  Pause")

    def jump_frequency(self, f):
        if self.sphere is None: return
        self.frequency.setValue(int(np.argmin(abs(self.sphere.freqs - f))))

    def chart_click(self, event):
        if event.inaxes and event.inaxes.name != "polar" and event.xdata and event.button == 1:
            self.jump_frequency(event.xdata)

    def map_click(self, event):
        if not event.inaxes or event.button != 1 or event.xdata is None:
            return
        # Ignore toolbar pan/zoom and colorbar axes.
        if event.canvas.toolbar and event.canvas.toolbar.mode:
            return
        title = event.inaxes.get_title(loc="left")
        if "SPHERICAL MAP" in title:
            self.azimuth.setValue(event.xdata)
            self.elevation.setValue(event.ydata)
        elif "DIRECTIVITY" in title or "BEAMWIDTH" in title:
            self.jump_frequency(event.xdata)

    def pick_point(self, point):
        radius = np.linalg.norm(point)
        if radius > 1e-6:
            self.azimuth.setValue(np.degrees(np.arctan2(point[1], point[0])))
            self.elevation.setValue(np.degrees(np.arcsin(np.clip(point[2] / radius, -1, 1))))

    def pin_comparison(self):
        self.comparison = self.sphere
        self.compare_label.setText(f"Reference: {self.sphere.name}\nNative level; no automatic alignment")
        self.schedule()

    def clear_comparison(self):
        self.comparison = None
        self.compare_label.setText("No reference pinned")
        self.schedule()

    def open_data(self):
        path, _ = W.QFileDialog.getOpenFileName(self, "Open HALS data", str(bootstrap.ROOT),
                                               "HALS coefficients / sphere (*.h5 *.hdf5 *.npz);;All files (*)")
        if path:
            self.open_path(path)

    def open_path(self, path, options=None):
        if self.worker and self.worker.isRunning():
            self.statusBar().showMessage("A reconstruction is already running. Cancel it before opening another dataset.")
            return
        path = Path(path)
        if path.suffix.lower() in (".h5", ".hdf5"):
            if options is None:
                try:
                    dialog = ReconstructionDialog(path, self)
                except Exception as exc:
                    self.error(str(exc))
                    return
                if dialog.exec() != W.QDialog.Accepted:
                    return
                options = dialog.options()
            self.start_job(ac.reconstruct, dict(path=str(path), pool=self.pool, **options), str(path), options)
        elif path.is_dir():
            self.start_job(ac.import_exports, {"folder": str(path)}, str(path), None)
        else:
            try:
                sphere = ac.load_sphere(path)
                self.set_sphere(sphere)
                self.source_path, self.source_options = str(path.resolve()), None
                self.apply_pending_session()
            except Exception as exc:
                self.error(str(exc))

    def open_folder(self):
        path = W.QFileDialog.getExistingDirectory(self, "Select a full-sphere Stage 5 complex export")
        if path:
            self.open_path(path)

    def start_job(self, fn, kwargs, source, options):
        self.play_timer.stop()
        self.play.setChecked(False)
        self.job_source, self.job_options = str(Path(source).resolve()), options
        self.job_cancelled = False
        self.worker = Worker(fn, kwargs)
        self.worker.progress.connect(self.job_progress)
        self.worker.loaded.connect(self.job_loaded)
        self.worker.failed.connect(self.error)
        self.worker.finished.connect(self.job_finished)
        self.progress.setValue(0)
        self.progress.show()
        self.cancel_button.show()
        self.open_button.setEnabled(False)
        self.statusBar().showMessage("Preparing complex sphere…")
        self.worker.start()

    def job_progress(self, value, message):
        self.progress.setValue(value)
        self.statusBar().showMessage(message)

    def job_loaded(self, sphere):
        if self.job_cancelled:
            return
        self.source_path, self.source_options = self.job_source, self.job_options
        self.set_sphere(sphere)
        self.apply_pending_session()

    def job_finished(self):
        self.progress.hide()
        self.cancel_button.hide()
        self.open_button.setEnabled(True)
        if self.job_cancelled:
            self.statusBar().showMessage("Reconstruction cancelled. Previous dataset retained.")
        self.pending_session = None

    def cancel_load(self):
        if self.worker:
            self.job_cancelled = True
            self.worker.requestInterruption()
            self.statusBar().showMessage("Cancelling after the current frequency…")

    def clear_data(self):
        if self.worker and self.worker.isRunning():
            return
        self.source_path = self.source_options = None
        self.set_sphere(None)

    def error(self, message):
        self.pending_session = None
        self.statusBar().showMessage("Operation failed; previous data retained")
        dialog = W.QMessageBox(self)
        dialog.setWindowTitle("HALS Studio")
        dialog.setIcon(W.QMessageBox.Warning)
        dialog.setText(message.splitlines()[-1])
        dialog.setDetailedText(message)
        dialog.exec()

    def choose_save(self, title, extension):
        path, _ = W.QFileDialog.getSaveFileName(self, title, str(bootstrap.HERE / (self.sphere.name.replace("/", "-") + extension)),
                                               f"{extension.upper()[1:]} files (*{extension})")
        if path and not path.lower().endswith(extension):
            path += extension
        return path

    def save_action(self, title, extension, writer):
        path = self.choose_save(title, extension)
        if path:
            try:
                writer(path)
                self.statusBar().showMessage(f"Saved {path}")
            except Exception as exc:
                self.error(str(exc))

    def screenshot(self):
        self.save_action("Save workspace image", ".png", lambda p: self.grab().save(p))

    def scene_screenshot(self):
        plotter = self.volume_plotter if self.tabs.currentIndex() == 1 else self.plotter
        self.save_action("Save 3D viewport", ".png", lambda p: plotter.screenshot(p, scale=2))

    def save_cache(self):
        self.save_action("Save complete complex sphere", ".npz", lambda p: ac.save_sphere(self.sphere, p))

    def save_csv(self):
        self.save_action("Save analysis metrics", ".csv", lambda p: ac.export_metrics(self.sphere, p, self.levels,
            self.azimuth.value(), self.elevation.value(), self.delay.value(), self.level_offset.value()))

    def save_mesh(self):
        if self.tabs.currentIndex() == 1:
            mesh = self.volume_grid
        else:
            mesh = balloon_mesh(self.sphere, self.relative[self.frequency.value()], self.dynamic.value(), self.mapping.currentText())
        self.save_action("Save field mesh", ".vtk", mesh.save)

    def save_chart(self):
        chart = {0: self.response, 2: self.maps, 3: self.analysis}.get(self.tabs.currentIndex(), self.response)
        self.save_action("Save analysis chart", ".png", lambda p: chart.fig.savefig(p, dpi=200))

    def session_dict(self):
        return dict(version=1, source=self.source_path, reconstruction=self.source_options, frequency=float(self.sphere.freqs[self.frequency.value()]),
                    normalization=self.normalization.currentIndex(), smoothing=self.smoothing.currentIndex(), dynamic=self.dynamic.value(),
                    mapping=self.mapping.currentIndex(), color=self.color.currentIndex(), azimuth=self.azimuth.value(), elevation=self.elevation.value(),
                    delay=self.delay.value(), level_offset=self.level_offset.value(), tab=self.tabs.currentIndex(),
                    wire=self.wire.isChecked(), reference=self.reference.isChecked(), phase_color=self.phase_color.isChecked(),
                    frequency_color=self.frequency_color.isChecked(),
                    orbit_mode=self.orbit_mode.currentIndex(), volume_mode=self.volume_mode.currentIndex(),
                    response_mode=self.response_mode.currentIndex(), response_extent=self.response_extent.value(),
                    response_step=self.response_step.value(), response_symmetric=self.response_symmetric.isChecked(),
                    isosurfaces=[c.isChecked() for c in self.iso_checks], camera=[list(v) for v in self.plotter.camera_position])

    def save_session(self):
        if not self.source_path and self.sphere is not None:
            self.error("Save a complex sphere cache and open it before saving a session.")
            return
        self.save_action("Save viewer session", ".json", lambda p: Path(p).write_text(json.dumps(self.session_dict(), indent=2), encoding="utf-8"))

    def load_session(self):
        path, _ = W.QFileDialog.getOpenFileName(self, "Load viewer session", str(bootstrap.HERE), "Session (*.json)")
        if not path:
            return
        try:
            session = json.loads(Path(path).read_text(encoding="utf-8"))
            if session.get("version") != 1:
                raise ValueError("Unsupported viewer session version.")
            self.pending_session = session
            if session.get("source"):
                self.open_path(session["source"], session.get("reconstruction"))
            else:
                self.clear_data()
                self.apply_pending_session()
        except Exception as exc:
            self.error(str(exc))

    def apply_pending_session(self):
        session = self.pending_session
        if not session:
            return
        self.pending_session = None
        for name in ("normalization", "smoothing", "mapping", "color", "orbit_mode", "volume_mode", "response_mode"):
            getattr(self, name).setCurrentIndex(int(session.get(name, 0)))
        for name in ("dynamic", "azimuth", "elevation", "delay", "level_offset", "response_extent", "response_step"):
            if name in session:
                getattr(self, name).setValue(float(session[name]))
        for name in ("wire", "reference", "phase_color", "frequency_color", "response_symmetric"):
            if name in session:
                getattr(self, name).setChecked(bool(session[name]))
        for check, value in zip(self.iso_checks, session.get("isosurfaces", [True]*3)):
            check.setChecked(value)
        self.jump_frequency(session.get("frequency", 1000))
        self.tabs.setCurrentIndex(int(session.get("tab", 0)))
        if "camera" in session:
            self.plotter.camera_position = session["camera"]
        self.schedule()

    def details(self):
        dialog = W.QDialog(self)
        dialog.setWindowTitle("Dataset provenance")
        dialog.resize(700, 450)
        layout = W.QVBoxLayout(dialog)
        text = W.QPlainTextEdit(json.dumps(self.sphere.metadata, indent=2))
        text.setReadOnly(True)
        layout.addWidget(text)
        layout.addWidget(button("Close", dialog.accept))
        dialog.exec()

    def help(self):
        W.QMessageBox.information(self, "HALS Studio · conventions",
            "Open Stage 4 HDF5 coefficients to reconstruct a full complex sphere. The main HALS application is never modified.\n\n"
            "+X = front, +Y = left, +Z = up. Elevation = 90° − HALS theta. Probe and cuts use the nearest angular sample. "
            "Positive horizontal angles point toward +Y; positive vertical angles point toward +Z.\n\n"
            "Levels are 20 log10 |HALS pressure| plus the explicit display offset, not automatically calibrated SPL. "
            "DI uses an area-weighted full-sphere energy average. Beamwidth measures the front-connected −6 dB lobe; "
            "No crossing means coverage cannot be bounded. These metrics are not a CTA-2034 Spinorama.\n\n"
            "Smoothing averages energy in fractional-octave bands. Phase stays untouched. Delay removal only affects phase/delay plots "
            "and phase colour. Raw complex exports are preserved. Use all source frequency bins for phase/group-delay work: "
            "sparse logarithmic samples can unwrap incorrectly. No impulse response is synthesized from sparse data.\n\n"
            "Drag to orbit; wheel to zoom; P over the balloon to probe. Space starts a frequency sweep; arrow keys step bins. "
            "Click response/maps to select frequency; click the spherical map to select direction.\n\n"
            "Save NPZ for a portable complex sphere. Session files retain source/settings/camera; comparison pins last only for this run.")

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "levels"):
            self.schedule()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if urls:
            self.open_path(urls[0].toLocalFile())

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.cancel_load()
            self.statusBar().showMessage("Cancelling reconstruction… close again when it has stopped.")
            event.ignore()
            return
        self.play_timer.stop()
        self.refresh_timer.stop()
        self.pool_timer.stop()
        self.pool.close()
        self.plotter.close()
        self.volume_plotter.close()
        event.accept()


def main():
    parser = argparse.ArgumentParser(description="HALS Studio acoustic viewer")
    parser.add_argument("data", nargs="?", help="Stage 4 HDF5 or saved sphere NPZ")
    args = parser.parse_args()
    app = W.QApplication.instance() or W.QApplication(sys.argv)
    app.setApplicationName("HALS Studio")
    app.setStyle("Fusion")
    from workspace import Workspace
    window = Workspace()
    window.show()
    if args.data:
        C.QTimer.singleShot(200, lambda: window.open_path(args.data))
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
