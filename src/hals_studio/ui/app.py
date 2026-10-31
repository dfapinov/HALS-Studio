"""HALS Studio — standalone acoustic field explorer."""
from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

import hals_studio.bootstrap as bootstrap
import numpy as np
from PySide6 import QtCore as C, QtWidgets as W
import hals_studio.analysis.acoustics as ac


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
QPushButton:pressed, QPushButton:checked, QToolButton:pressed, QToolButton:checked { background: #245d75; color: white; border-color: #91e5f1; }
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
QCheckBox::indicator:checked { background: #599bda; border: 1px solid #91e5f1; }
QToolTip { color: #dfedf6; background: #1b3345; border: 1px solid #45677e; }
QMenu { background: #142432; border: 1px solid #355064; }
QMenu::item { padding: 7px 24px; }
QMenu::item:selected { background: #245d75; }
QScrollBar:vertical { background: #101c28; width: 8px; }
QScrollBar::handle:vertical { background: #314b60; min-height: 30px; border-radius: 3px; }
"""
for direction in ('up', 'down'):
    icon = (bootstrap.RESOURCES / 'assets' / f'spin-{direction}.svg').as_posix()
    position = 'top right' if direction == 'up' else 'bottom right'
    STYLE += f'QSpinBox::{direction}-button, QDoubleSpinBox::{direction}-button {{ subcontrol-origin: padding; subcontrol-position: {position}; width: 16px; background: transparent; border: none; margin-right: 2px; }}'
    STYLE += f'QSpinBox::{direction}-arrow, QDoubleSpinBox::{direction}-arrow {{ image: url("{icon}"); width: 10px; height: 9px; }}'
STYLE += 'QComboBox::down-arrow, QToolButton#resetViewsButton::menu-arrow { image: url("'+(bootstrap.RESOURCES/'assets'/'spin-down.svg').as_posix()+'"); width: 10px; height: 9px; }'
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
            # Closing the shared pool may surface a worker failure after the
            # user has already cancelled. Do not open an error dialog on exit.
            if not self.isInterruptionRequested():
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
        from hals_studio.analysis.reconstruction_centres import reconstruction_centres
        from hals_studio.persistence.project_repository import read_project
        grid = {}
        project_path = getattr(parent, 'project_path', None)
        if project_path:
            grid = read_project(project_path).get('grid_vars', {})
        export = getattr(parent, 'export_workspace', None)
        if export is not None and export.config.get('project_path') == project_path:
            grid = export.config.get('project_geometry', grid)
        self.centre = W.QComboBox()
        for title, xyz in reconstruction_centres(grid):
            self.centre.addItem(title, xyz)
        form.addRow('Reconstruction centre', self.centre)
        self.centre.setToolTip('Rebuilds the observation sphere for all Analysis plots around this point.')
        self.radius = number(2, .05, 100, " m", 3)
        self.step = combo(["5° · 2,664 directions", "10° · 684 directions", "3° · 7,320 directions", "2° · 16,380 directions"])
        self.bin_counts = [480, 960, 240, 120, 60, 0]
        self.bins = combo(["480 log targets · fine", "960 log targets · extra fine", "240 log targets",
                           "120 log targets · coarse", "60 log targets · preview", "All native bins · phase / delay"])
        self.mode = combo(["Internal", "External", "Total"])
        self.fmin, self.fmax = number(20, 1, 100000, " Hz", 0), number(20000, 2, 200000, " Hz", 0)
        self.padding = number(50, 0, 100000, " samples", 0)
        self.manual_padding = W.QCheckBox('Edit capture padding')
        self.padding.setEnabled(False)
        self.manual_padding.toggled.connect(self.padding.setEnabled)
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
                           ("", self.manual_padding), ("Capture padding to remove", self.padding)):
            form.addRow(title, obj)
        self.sampling_note = label("", "muted")
        self.sampling_note.setWordWrap(True)
        form.addRow(self.sampling_note)
        self.bins.currentIndexChanged.connect(self.update_sampling)
        self.fmin.valueChanged.connect(self.update_sampling)
        self.fmax.valueChanged.connect(self.update_sampling)
        self.update_sampling()
        note = label("Physical time of flight is retained. No microphone calibration or FRD level offset is applied.\nAll bins at 2° can require substantial RAM and reconstruction time.", "muted")
        note.setWordWrap(True)
        form.addRow(note)
        buttons = W.QDialogButtonBox(W.QDialogButtonBox.Ok | W.QDialogButtonBox.Cancel)
        buttons.button(W.QDialogButtonBox.Ok).setText("Reconstruct sphere")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def options(self):
        offset = self.centre.currentData()
        return dict(radius=self.radius.value(), step=[5, 10, 3, 2][self.step.currentIndex()],
                    bins=self.bin_counts[self.bins.currentIndex()], mode=self.mode.currentText(),
                    fmin=self.fmin.value(), fmax=self.fmax.value(), padding=int(self.padding.value()) if self.manual_padding.isChecked() else 50,
                    manual_padding=self.manual_padding.isChecked(), origins=True,
                    offset=offset,
                    centre_name=self.centre.currentText())

    def restore_centre(self, offset, name=None):
        xyz = np.asarray(offset, dtype=float)
        if xyz.shape != (3,) or not np.isfinite(xyz).all():
            raise ValueError('Reconstruction centre requires three finite coordinates.')
        for index in range(self.centre.count()):
            if ((name is None or self.centre.itemText(index) == name)
                    and np.allclose(self.centre.itemData(index), xyz, rtol=0, atol=1e-9)):
                self.centre.setCurrentIndex(index)
                return
        self.centre.setCurrentIndex(0)

    def update_sampling(self):
        try:
            indices = ac.select_frequencies(self.native_freqs, self.bin_counts[self.bins.currentIndex()], self.fmin.value(), self.fmax.value())
            f = self.native_freqs[indices]
            self.sampling_note.setText(f"{len(f):,} unique native frequencies will be reconstructed.\n"
                "Log targets snap to measured bins; duplicate targets are removed. "
                f"Largest adjacent gap: {np.max(np.diff(f)):,.1f} Hz. No complex interpolation.")
        except ValueError as exc:
            self.sampling_note.setText(str(exc))




def main():
    parser = argparse.ArgumentParser(description="HALS Studio acoustic viewer")
    parser.add_argument("data", nargs="?", help="Stage 4 HDF5 or saved sphere NPZ")
    args = parser.parse_args()
    app = W.QApplication.instance() or W.QApplication(sys.argv)
    app.setApplicationName("HALS Studio")
    app.setStyle("Fusion")
    from hals_studio.ui.workspace import Workspace
    window = Workspace()
    window.show()
    if args.data:
        C.QTimer.singleShot(200, lambda: window.open_path(args.data))
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
