"""Shared Analysis/Export microphone calibration settings and correction."""
from pathlib import Path
import tempfile
import numpy as np
from PySide6 import QtWidgets as W
KEYS = ('apply_mic_cal', 'mic_cal_file', 'mic_cal_mode', 'mic_cal_fade_octaves', 'mic_cal_fallback', 'frd_db_offset')


def config(owner):
    from export_engine import DEFAULT_EXPORT
    source = owner.export_workspace.config if owner.export_workspace else owner.export_setup or {}
    return {key: source.get(key, DEFAULT_EXPORT[key]) for key in KEYS}


def build(owner):
    dialog = W.QDialog(owner)
    dialog.setWindowTitle('Calibration')
    dialog.setMinimumWidth(340)
    layout = W.QVBoxLayout(dialog)
    owner.calibration_dialog = dialog
    group = W.QGroupBox('Microphone calibration'); form = W.QVBoxLayout(group)
    layout.addWidget(group)
    owner.mic_enabled = W.QCheckBox('Apply calibration'); form.addWidget(owner.mic_enabled)
    owner.mic_name = W.QLabel(); owner.mic_name.setWordWrap(True); form.addWidget(owner.mic_name)
    button = W.QPushButton('Load mic calibration…'); form.addWidget(button)
    def update(values):
        if owner.export_workspace:
            owner.export_workspace.config.update(values)
            owner.export_workspace.apply_config(owner.export_workspace.config)
        else:
            if owner.export_setup is None: owner.export_setup = {}
            owner.export_setup.update(values)
        owner.schedule()
    def browse():
        path, _ = W.QFileDialog.getOpenFileName(owner, 'Microphone calibration', config(owner)['mic_cal_file'], 'Calibration (*.txt *.cal *.csv);;All files (*)')
        if path: update(dict(mic_cal_file=path, mic_cal_fallback='', apply_mic_cal=True))
    button.clicked.connect(browse)
    owner.mic_enabled.toggled.connect(lambda enabled: update(dict(apply_mic_cal=enabled)))
    form.addWidget(W.QLabel('FRD offset / dB'))
    owner.frd_offset = W.QDoubleSpinBox(); owner.frd_offset.setRange(-200, 200)
    owner.frd_offset.setDecimals(2); owner.frd_offset.setKeyboardTracking(False)
    owner.frd_offset.setToolTip('Shared with Export. Shifts SPL levels; DI and phase are unchanged.')
    owner.frd_offset.valueChanged.connect(lambda value: update(dict(frd_db_offset=value)))
    form.addWidget(owner.frd_offset)
    note = W.QLabel('Shared with Export. Changes apply immediately.')
    note.setWordWrap(True); layout.addWidget(note)
    buttons = W.QDialogButtonBox(W.QDialogButtonBox.Close)
    buttons.rejected.connect(dialog.close); layout.addWidget(buttons)


def show_dialog(owner):
    sync(owner)
    owner.calibration_dialog.show()
    owner.calibration_dialog.raise_()
    owner.calibration_dialog.activateWindow()


def sync(owner):
    from utils import apply_mic_calibration
    c = config(owner)
    owner.frd_offset.blockSignals(True); owner.frd_offset.setValue(c['frd_db_offset']); owner.frd_offset.blockSignals(False)
    owner.mic_enabled.blockSignals(True); owner.mic_enabled.setChecked(c['apply_mic_cal']); owner.mic_enabled.blockSignals(False)
    owner.mic_name.setText(Path(c['mic_cal_file']).name if c['mic_cal_file'] else 'Embedded project calibration' if c['mic_cal_fallback'] else 'No calibration loaded')
    sphere = owner.sphere
    if sphere is None: return
    if getattr(owner, '_mic_sphere', None) is not sphere:
        owner._mic_sphere = sphere; owner._mic_raw = sphere.pressure; owner._mic_key = None
    path = Path(c['mic_cal_file'])
    key = (repr(c), path.stat().st_mtime_ns if path.is_file() else None)
    if key == owner._mic_key: return
    try:
        pressure = owner._mic_raw
        if c['apply_mic_cal']:
            def apply(filename):
                multiplier = apply_mic_calibration(np.ones(len(sphere.freqs), complex), sphere.freqs, filename, c['mic_cal_mode'], c['mic_cal_fade_octaves'])
                return owner._mic_raw * multiplier[:, None, None]
            if path.is_file(): pressure = apply(path)
            elif c['mic_cal_fallback'].strip():
                with tempfile.TemporaryDirectory() as folder:
                    fallback = Path(folder)/'mic.txt'; fallback.write_text(c['mic_cal_fallback'], encoding='utf-8'); pressure = apply(fallback)
            else: raise ValueError('Calibration file is missing and no embedded calibration is available.')
        sphere.pressure = pressure
        owner.mic_name.setToolTip(c['mic_cal_file'])
    except (ValueError, OSError) as exc:
        sphere.pressure = owner._mic_raw
        owner.mic_name.setText('Calibration unavailable: '+str(exc))
    owner._mic_key = key
    owner.level_cache.clear(); owner.cea_cache.clear()
    for pane in owner.panes: pane.invalidate()
