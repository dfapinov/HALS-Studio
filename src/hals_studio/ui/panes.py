"""Independent plot panes, contextual setup, and pinnable settings."""
from copy import deepcopy
import numpy as np
import pyvista as pv
from pyvistaqt import QtInteractor
from PySide6 import QtCore as C, QtGui as G, QtWidgets as W
from matplotlib.ticker import FuncFormatter
import hals_studio.analysis.acoustics as ac
from hals_studio.analysis.analysis_metrics import minimum_phase, trend_fit, contour_levels
from hals_studio.process_engine.stage5_pressure_utils import get_min_phase_delay
from hals_studio.ui.plotting.plot_interaction import PlotInteraction
from hals_studio.ui.plotting.plots import (Chart, style, draw_zoomable_polars, balloon_mesh, volume_mesh, beam_tunnel_mesh, coverage_surface,
                   response_directions, audio_frequency, audio_ticks, FREQUENCY_STRETCH)

GROUPS = {
    '3D field': {'balloon': 'Balloon / colour sphere', 'cross_sonograms': 'Intersecting H/V sonograms'},
    'Time / decay': {'impulse': 'Impulse response', 'csd': 'Cumulative spectral decay', 'wavelet': 'Morlet wavelet'},
    'Directivity': {'map_h': 'Horizontal spectrogram', 'map_v': 'Vertical spectrogram', 'polar': 'Horizontal + vertical polars', 'globe_hv': 'Horizontal + vertical globes'},
    'SPL & phase': {'di': 'Sound power directivity index', 'probe': 'Probe SPL', 'reference': 'Reference axis SPL',
        'phase': 'Total phase', 'minimum': 'Minimum phase estimate',
        'sweep_h': 'Horizontal SPL sweep', 'sweep_v': 'Vertical SPL sweep'},
    'CEA2034': {'cea': 'Spinorama overview', 'cea_On axis': 'On axis', 'cea_Listening window': 'Listening window',
        'cea_Early reflections': 'Early reflections', 'cea_Sound power': 'Sound power',
        'cea_Predicted in-room': 'Predicted in-room', 'cea_Sound power DI': 'Sound power DI',
        'cea_Early reflections DI': 'Early reflections DI', 'reflections': 'Reflection breakouts',
        'cea_Floor': 'Floor', 'cea_Ceiling': 'Ceiling', 'cea_Front wall': 'Front wall',
        'cea_Side walls': 'Side walls', 'cea_Rear wall': 'Rear wall'},
}
TITLES = {k: v for group in GROUPS.values() for k, v in group.items()}
MAGNITUDE_KINDS = {k: v for category in ('SPL & phase', 'CEA2034') for k, v in GROUPS[category].items() if k not in ('phase', 'minimum')}


def selected_magnitudes(config):
    selected = config.get('magnitude_selection')
    if selected is None: return [config['kind']] if config['kind'] in MAGNITUDE_KINDS else []
    return [key for key in selected if key in MAGNITUDE_KINDS]


DEFAULT = dict(directivity_display='Sonogram', directivity_on_axis=False, directivity_contour_step=6., csd_level_reference=False, wavelet_level_reference=False, wavelet_time_reference=False, csd_method='CSD', wavelet_units='Cycles', wavelet_cycles=12., wavelet_duration=20., wavelet_pre=1., csd_mode='3D waterfall', csd_time=20., csd_pre_time=1., csd_span=30., csd_auto_time=True, csd_fmin=100., csd_fmax=20000., kind='probe', normalization='Peak', smoothing='None', globe_rotation={'horizontal': 0., 'vertical': 90.}, polar_rotation={'horizontal': 0., 'vertical': 270.}, span=36., palette='PColor',
    geometry='dB radius', reference_sphere=True, edges=False, phase_colour=False, orbit='Az / El - no roll',
    contours=True, extent=90., step=10., symmetric=True, sweep_direction='+/-', delay=0., offset=0., wrapped=True,
    di_auto=True, di_min=-5., di_max=20., phase_auto=True, phase_min=-180., phase_max=180., phase=True, phase_mode='Total phase', magnitude_selection=None, phase_height=.45,
    min_phase_delay=False, overlays=True, fmin=20., fmax=20000., ymin=-100., ymax=10., auto_axes=True,
    fit=False, fit_low=100., fit_high=10000., fit_curve='First curve',
    volume_mode='Closed contour surfaces', volume_coordinates='Beam tunnel', beam_extent=90.,
    threshold=-6., contour_low=-18., contour_high=-6., contour_step=3.,
    opacity_low=.12, contour_colours='Red shades', surface_finish='Glossy', breakout='All', pins=[])
def default_config(kind):
    config = dict(deepcopy(DEFAULT), kind=kind)
    config['energy_smoothing_version'] = 1
    if kind in MAGNITUDE_KINDS or kind in ('phase', 'minimum'):
        config['smoothing'] = 'None'
    return config


# key: label, type/options, range. A single schema drives both setup and sidebar.
SPECS = {
    'csd_method': ('Analysis', ['CSD','Morlet wavelet']),
    'directivity_on_axis': ('SPL - normalize on axis', bool),
    'directivity_contour_step': ('Contours Step / dB', (.5, 60.)),
    'directivity_display': ('Display', ['Sonogram', 'Waterfall']),
    'csd_level_reference': ('SPL - normalize', bool),
    'wavelet_level_reference': ('SPL - normalize', bool),
    'wavelet_time_reference': ('Time - normalize to peak arrival', bool),
    'wavelet_units': ('Time axis', ['Milliseconds', 'Cycles']),
    'wavelet_cycles': ('Resolution (higher = narrower bands)', (3., 20.)),
    'wavelet_duration': ('Decay duration / cycles', (.1, 500.)),
    'wavelet_pre': ('Pre allowance / cycles', (0., 100.)),
    'csd_pre_time': ('Pre allowance / milliseconds', (0., 100.)),
    'csd_auto_time': ('Auto time to dB floor', bool),
    'csd_mode': ('Decay display', ['3D waterfall', 'Sonogram']),
    'csd_time': ('Decay duration / milliseconds', (.1, 500.)),
    'csd_span': ('Decay range / dB', (10., 120.)),
    'csd_fmin': ('Frequency minimum / Hz', (1., 100000.)), 'csd_fmax': ('Frequency maximum / Hz', (2., 100000.)),
    'normalization': ('Normalize to', ['Peak', 'On axis']),
    'smoothing': ('Energy smoothing', ['None', '1/24 octave', '1/12 octave', '1/6 octave', '1/3 octave']),
    'span': ('Colour / polar range (dB)', (6., 120.)), 'palette': ('Palette', ['PColor']),
    'geometry': ('Geometry', ['dB radius', 'Pressure radius', 'Colour sphere (no deformation)']),
    'surface_finish': ('Surface finish', ['Matte', 'Satin', 'Glossy']),
    'reference_sphere': ('Reference sphere', bool), 'edges': ('Mesh edges', bool),
    'phase_colour': ('Colour by phase', bool), 'orbit': ('Orbit mode', ['Az / El - no roll', 'Trackball']),
    'contours': ('Show Contours', bool), 'extent': ('Sweep extent (degrees)', (0., 180.)),
    'sweep_direction': ('Direction', ['+/-', '+', '-']),
    'step': ('Sweep increment (degrees)', (1., 90.)), 'symmetric': ('Include negative angles', bool),
    'delay': ('Delay compensation (ms)', (-10000., 10000.)), 'offset': ('Level offset (dB)', (-200., 200.)),
    'min_phase_delay': ('Min phase (Stage 5 reference delay)', bool),
    'phase_mode': ('Phase response', ['None', 'Total phase', 'Minimum phase']),
    'phase_height': ('Phase axis height (fraction)', (.15, 1.)),
    'fit': ('Fit line', bool), 'fit_low': ('Fit range from (Hz)', (.1, 1000000.)),
    'fit_high': ('Fit range to (Hz)', (.1, 1000000.)), 'fit_curve': ('Fit response', ['First curve']),
    'wrapped': ('Wrap phase at +/-180 degrees', bool), 'phase': ('Show probe phase', bool),
    'overlays': ('Show saved probe overlays', bool), 'auto_axes': ('Automatic axes', bool),
    'fmin': ('Frequency minimum (Hz)', (.1, 1000000.)), 'fmax': ('Frequency maximum (Hz)', (.1, 1000000.)),
    'di_auto': ('Automatic DI limits', bool),
    'di_min': ('DI minimum (dB)', (-100000., 100000.)),
    'di_max': ('DI maximum (dB)', (-100000., 100000.)),
    'phase_auto': ('Automatic phase limits', bool),
    'phase_min': ('Phase minimum (degrees)', (-100000., 100000.)),
    'phase_max': ('Phase maximum (degrees)', (-100000., 100000.)),
    'ymin': ('Magnitude minimum (dB)', (-100000., 100000.)), 'ymax': ('Magnitude maximum (dB)', (-100000., 100000.)),
    'volume_mode': ('Volume display', ['Closed contour surfaces', 'Level crossings', 'H/V colour slices']),
    'volume_coordinates': ('Directional layout', ['Beam tunnel', 'Azimuth / elevation']),
    'beam_extent': ('Maximum off-axis angle (degrees)', (15., 180.)),
    'threshold': ('Volume threshold (dB)', (-96., -.1)),
    'contour_low': ('Lowest contour (dB)', (-96., -.1)), 'contour_high': ('Highest contour (dB)', (-96., -.1)),
    'contour_step': ('Contour increment (dB)', (.5, 24.)), 'opacity_low': ('Lowest contour opacity', (0., .95)),
    'contour_colours': ('Contour colours', ['Red shades', 'Single red', 'Palette colours']),
    'breakout': ('Breakout curves', ['All', 'Horizontal', 'Vertical']),
}


def setting_keys(kind, config=None):
    if kind == 'impulse': return []
    if kind in ('csd', 'wavelet'):
        from hals_studio.ui.plotting.csd_plot import decay_setting_keys
        return decay_setting_keys({**DEFAULT, **(config or {}), 'kind': kind})
    if kind == 'cross_sonograms': return ['directivity_on_axis','smoothing','span','contours','directivity_contour_step','fmin','fmax']
    if kind.startswith('globe_'): return ['directivity_on_axis', 'smoothing', 'span', 'contours', 'directivity_contour_step', 'fmin', 'fmax']
    if kind.startswith('map_'): return ['directivity_display','directivity_on_axis','smoothing','span','contours','directivity_contour_step']
    common = ['smoothing']
    if kind in ('balloon', 'volume', 'map_h', 'map_v', 'polar'):
        common += ['normalization', 'span']
    if kind == 'balloon':
        return common + ['geometry', 'surface_finish', 'reference_sphere', 'edges', 'phase_colour', 'delay', 'orbit']
    if kind == 'volume':
        return common + ['volume_coordinates', 'beam_extent', 'volume_mode', 'contour_low', 'contour_high', 'contour_step', 'contour_colours', 'opacity_low', 'surface_finish', 'orbit']
    if kind.startswith('map_'):
        common += ['directivity_display', 'contours']
    if kind.startswith('sweep_'):
        common += ['extent', 'step', 'sweep_direction']
    if kind in GROUPS['SPL & phase']:
        common += ['phase_mode', 'wrapped', 'delay', 'phase_height', 'overlays']
    if kind not in ('phase', 'minimum', 'polar', 'map_h', 'map_v'):
        common += ['fit', 'fit_low', 'fit_high', 'fit_curve']
    if kind in ('reflections', 'cea_Sound power'):
        common += ['breakout']
    if kind != 'polar':
        common += ['offset', 'auto_axes', 'fmin', 'fmax', 'ymin', 'ymax']
    if config is not None and config.get('magnitude_selection') is not None:
        selected = selected_magnitudes(config)
        if any(k.startswith('sweep_') for k in selected): common += ['extent', 'step', 'sweep_direction']
        if any(k in ('reflections', 'cea_Sound power') for k in selected): common += ['breakout']
        common += ['phase_mode', 'wrapped', 'delay', 'phase_height', 'overlays']
        if selected: common += ['fit', 'fit_low', 'fit_high', 'fit_curve']
    if kind in GROUPS['SPL & phase'] or (config and config.get('magnitude_selection') is not None):
        common += ['phase_auto', 'phase_min', 'phase_max']
        if kind in ('phase', 'minimum'): common = [key for key in common if key not in ('ymin', 'ymax')]
    if config and any(k == 'di' or k.endswith(' DI') for k in selected_magnitudes(config)):
        common = [k for k in common if k not in ('phase_auto', 'phase_min', 'phase_max', 'wrapped', 'delay')]
        common += ['di_auto', 'di_min', 'di_max']
    common = list(dict.fromkeys(common))
    return common


def editor(key, value, callback, options=None):
    spec = options if options is not None else SPECS[key][1]
    if key == 'opacity_low':
        w = W.QSlider(C.Qt.Horizontal); w.setRange(0, 95); w.setValue(round(value*100))
        w.setToolTip('Lowest-level surface opacity; highest-level surface stays at 95%.')
        w.valueChanged.connect(lambda v: callback(v/100)); return w
    if spec is bool:
        w = W.QCheckBox(); w.setChecked(value if isinstance(value,bool) else value in ('Each frequency peak','IR peak slice per frequency')); w.toggled.connect(callback)
    elif isinstance(spec, list):
        w = W.QComboBox(); w.setSizeAdjustPolicy(W.QComboBox.AdjustToMinimumContentsLengthWithIcon); w.setMinimumContentsLength(1); w.addItems(spec); w.setCurrentText('Waterfall' if key=='directivity_display' and value=='3D surface' else value); w.currentTextChanged.connect(callback)
    else:
        w = W.QDoubleSpinBox(); w.setRange(*spec); w.setDecimals(3 if key == 'delay' else 1)
        if key == 'phase_height': w.setDecimals(2); w.setSingleStep(.05)
        w.setValue(value); w.setKeyboardTracking(False); w.valueChanged.connect(callback)
    return w


class PlotMenu(W.QMenu):
    """Keep checkboxes open so several responses can be selected in one visit."""
    def addMenu(self, title):
        child = PlotMenu(title, self); super().addMenu(child); return child

    def mouseReleaseEvent(self, event):
        action = self.actionAt(event.pos())
        if event.button() == C.Qt.LeftButton and action and action.isEnabled() and action.isCheckable():
            action.trigger(); event.accept(); return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        action = self.activeAction()
        if event.key() == C.Qt.Key_Space and action and action.isEnabled() and action.isCheckable():
            action.trigger(); event.accept(); return
        super().keyPressEvent(event)


class Setup(W.QDialog):
    def __init__(self, pane):
        super().__init__(pane)
        self.setWindowTitle(f'Pane {pane.index+1} - {TITLES[pane.config["kind"]]} setup')
        if pane.config.get('min_phase_delay'): pane.delay_ms()
        self.values = deepcopy(pane.config)
        if pane.config['kind'] in ('csd','wavelet'): self.values['csd_method']='Morlet wavelet' if pane.config['kind']=='wavelet' else 'CSD'
        layout = W.QVBoxLayout(self)
        note = W.QLabel('Pin selected settings to the left sidebar. Each pane keeps its own settings.')
        note.setWordWrap(True); note.setSizePolicy(W.QSizePolicy.Ignored,W.QSizePolicy.Preferred); layout.addWidget(note); self.size_note=note
        pin_mode = W.QCheckBox('Pin settings - show pin checkboxes'); layout.addWidget(pin_mode)
        scroll = W.QScrollArea(); scroll.setWidgetResizable(True); layout.addWidget(scroll)
        body = W.QWidget(); form = W.QGridLayout(body); form.setAlignment(C.Qt.AlignTop); scroll.setWidget(body)
        self.size_scroll=scroll; self.size_body=body; self.size_pin_mode=pin_mode
        scroll.setHorizontalScrollBarPolicy(C.Qt.ScrollBarAsNeeded)
        self.pin_checks = {}
        self.controls = {}
        self.pane = pane
        self.time_rows = {}
        for row, key in enumerate(setting_keys(pane.config['kind'], {**self.values, '_all_time_controls':True, '_all_decay_controls':True})):
            check = W.QCheckBox('Pin'); check.setChecked(key in self.values['pins']); check.setVisible(False)
            self.pin_checks[key] = check
            pin_mode.toggled.connect(lambda enabled,w=check,k=key: w.setVisible(enabled and (k not in ('csd_time','csd_pre_time','wavelet_duration','wavelet_pre') or k.startswith('wavelet_') == (self.values.get('wavelet_units','Cycles')=='Cycles'))))
            form.addWidget(check, row, 0); caption=W.QLabel(SPECS[key][0]); form.addWidget(caption, row, 1)
            control = editor(key, self.values[key], lambda v, k=key: self.changed(k, v),
                             pane.fit_names() if key == 'fit_curve' else None)
            self.controls[key] = control
            if key == 'delay':
                group = W.QWidget(); row_layout = W.QHBoxLayout(group); row_layout.setContentsMargins(0, 0, 0, 0)
                row_layout.addWidget(control)
                estimate = W.QPushButton('Estimate')
                estimate.setToolTip('Estimate propagation delay from reference-axis excess group delay and fill the delay value.')
                estimate.clicked.connect(lambda checked=False, field=control: pane.fill_estimated_delay(field, self.values))
                row_layout.addWidget(estimate)
                control = group
            form.addWidget(control, row, 2)
            if pane.config['kind'] in ('csd','wavelet'): self.time_rows[key]=(caption,control,check)
        self.sync_time_rows()
        buttons = W.QDialogButtonBox(W.QDialogButtonBox.Ok | W.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject); layout.addWidget(buttons)
        self.size_buttons=buttons
        pin_mode.toggled.connect(lambda _:C.QTimer.singleShot(0,self.fit_contents))

    def showEvent(self,event):
        super().showEvent(event)
        self.fit_contents()

    def fit_contents(self):
        self.size_body.layout().activate()
        content=self.size_body.sizeHint()
        area=self.screen().availableGeometry()
        margins=self.layout().contentsMargins(); spacing=self.layout().spacing()
        width=min(max(340,content.width()+margins.left()+margins.right()+26),int(area.width()*.9))
        note_height=self.size_note.heightForWidth(width-margins.left()-margins.right())
        height=content.height()+max(0,note_height)+self.size_pin_mode.sizeHint().height()+self.size_buttons.sizeHint().height()+margins.top()+margins.bottom()+3*spacing+6
        self.resize(width,min(height,int(area.height()*.85)))

    def sync_time_rows(self):
        from hals_studio.ui.plotting.csd_plot import decay_setting_keys
        for key,(caption,control,check) in self.time_rows.items():
            visible=key in decay_setting_keys(self.values)
            caption.setVisible(visible); control.setVisible(visible)
            if not visible: check.hide()

    def changed(self, key, value):
        self.values[key] = value
        if key == 'phase_mode' and value != 'None':
            selected = [k for k in selected_magnitudes(self.values) if k != 'di' and not k.endswith(' DI')]
            self.values['magnitude_selection'] = selected
            if self.values['kind'] == 'di' or self.values['kind'].endswith(' DI'): self.values['kind'] = selected[0] if selected else 'probe'
        manual = 'auto_axes' if key in ('fmin', 'fmax', 'ymin', 'ymax') else 'phase_auto' if key in ('phase_min', 'phase_max') else 'di_auto' if key in ('di_min', 'di_max') else None
        if manual:
            self.values[manual] = False
            if manual in self.controls: self.controls[manual].setChecked(False)
        if key=='csd_method': self.values['kind']='wavelet' if value=='Morlet wavelet' else 'csd'
        if key in ('wavelet_units','csd_method'):
            self.sync_time_rows()
            C.QTimer.singleShot(0,self.fit_contents)
        if key in ('breakout', 'extent', 'step', 'symmetric', 'sweep_direction') and 'fit_curve' in self.controls:
            options = self.pane.fit_names(self.values); control = self.controls['fit_curve']
            selected = self.values['fit_curve'] if self.values['fit_curve'] in options else 'First curve'
            control.blockSignals(True); control.clear(); control.addItems(options); control.setCurrentText(selected); control.blockSignals(False)
            self.values['fit_curve'] = selected

    def accept(self):
        if self.values['di_min'] >= self.values['di_max']:
            W.QMessageBox.warning(self, 'DI limits', 'DI minimum must be smaller than maximum.'); return
        if self.values['fmin'] >= self.values['fmax'] or self.values['ymin'] >= self.values['ymax']:
            W.QMessageBox.warning(self, 'Axis limits', 'Minimum limits must be smaller than maximum limits.'); return
        if self.values['fit_low'] >= self.values['fit_high']:
            W.QMessageBox.warning(self, 'Fit range', 'Fit minimum must be smaller than fit maximum.'); return
        try: contour_levels(self.values['contour_low'], self.values['contour_high'], self.values['contour_step'])
        except ValueError as exc:
            W.QMessageBox.warning(self, 'Contours', str(exc)); return
        self.values['pins'] = [key for key, w in self.pin_checks.items() if w.isChecked()]
        super().accept()


class PlotPane(W.QFrame):
    def __init__(self, owner, index, kind):
        super().__init__()
        self.owner, self.index = owner, index
        self.config = default_config(kind)
        self.plotter = self.handle = None
        self.last_render = None
        self.setMinimumSize(230, 180)
        layout = W.QVBoxLayout(self); layout.setContentsMargins(5, 5, 5, 5); layout.setSpacing(4)
        self.title = W.QPushButton(); self.title.setStyleSheet('text-align:left; color:#54d9e8; border-radius:4px; padding:8px;')
        self.title.setSizePolicy(W.QSizePolicy.Ignored, W.QSizePolicy.Fixed)
        self.title.setFixedHeight(32)
        self.title.clicked.connect(lambda: self.menu(self.title.mapToGlobal(self.title.rect().bottomLeft())))
        header = W.QHBoxLayout(); header.setContentsMargins(0, 0, 0, 0); header.setSpacing(4)
        header.addWidget(self.title, 1)
        self.cursor_label = W.QLabel(); self.cursor_label.setStyleSheet('font-size:11px; padding:0 5px;')
        self.cursor_label.setFixedWidth(220)
        self.cursor_label.setAlignment(C.Qt.AlignRight | C.Qt.AlignVCenter)
        header.addWidget(self.cursor_label)
        reset = W.QPushButton('Reset axes'); reset.clicked.connect(self.reset_zoom); header.addWidget(reset)
        self.gear = W.QToolButton(); self.gear.setText('⚙'); self.gear.setToolTip('Plot settings')
        reset.setFixedHeight(32); self.gear.setFixedHeight(32); self.gear.setAccessibleName('Plot settings'); self.gear.clicked.connect(self.setup); header.addWidget(self.gear)
        layout.addLayout(header)
        self.stack = W.QStackedWidget(); layout.addWidget(self.stack)
        self.chart = Chart(); self.chart_frame = W.QWidget(); chart_row = W.QHBoxLayout(self.chart_frame)
        chart_row.setContentsMargins(0, 0, 0, 0); chart_row.setSpacing(0); chart_row.addWidget(self.chart, 1)
        self.stack.addWidget(self.chart_frame)
        self.probe_controls = W.QWidget(); self.probe_controls.setObjectName('probeOverlay'); self.probe_controls.setStyleSheet('QWidget#probeOverlay, QWidget#probeOverlay QLabel { background:transparent; }'); probe_row = W.QHBoxLayout(self.probe_controls)
        probe_row.setContentsMargins(6, 3, 6, 3); probe_row.setSpacing(6)
        self.probe_frequency = W.QLabel(); self.probe_frequency.setObjectName('hero'); self.probe_frequency.setStyleSheet('font-size:24px;font-weight:600;background:transparent;')
        self.frequency_controls=W.QWidget(); self.frequency_controls.setObjectName('frequencyOverlay')
        self.frequency_controls.setStyleSheet('QWidget#frequencyOverlay, QWidget#frequencyOverlay QLabel { background:transparent; }')
        frequency_row=W.QHBoxLayout(self.frequency_controls); frequency_row.setContentsMargins(6,3,6,3); frequency_row.setSpacing(6)
        frequency_row.addWidget(self.probe_frequency)
        previous=W.QPushButton('\u2039'); previous.setFixedWidth(54); previous.clicked.connect(lambda:owner.frequency.setValue(max(0,owner.frequency.value()-1))); frequency_row.addWidget(previous)
        self.sweep_button=W.QPushButton('\u25b8 Sweep'); self.sweep_button.setCheckable(True); self.sweep_button.setFixedWidth(70)
        self.sweep_button.clicked.connect(lambda:owner.play.click()); owner.play.toggled.connect(self.sweep_button.setChecked); owner.play.toggled.connect(lambda active:self.sweep_button.setText('\u2161 Pause' if active else '\u25b8 Sweep')); frequency_row.addWidget(self.sweep_button)
        next_button=W.QPushButton('\u203a'); next_button.setFixedWidth(54); next_button.clicked.connect(owner.advance); frequency_row.addWidget(next_button)
        self.frequency_controls.hide()

        self.probe_editors = []
        for name, source in [('Probe azimuth', owner.azimuth), ('Elevation', owner.elevation)]:
            probe_row.addWidget(W.QLabel(name))
            control = W.QDoubleSpinBox(); control.setRange(source.minimum(), source.maximum())
            control.setFixedWidth(90); control.setDecimals(1); control.setSuffix('°'); control.setValue(source.value())
            control.valueChanged.connect(source.setValue)
            def sync(value, target=control):
                target.blockSignals(True); target.setValue(value); target.blockSignals(False)
            source.valueChanged.connect(sync)
            probe_row.addWidget(control); self.probe_editors.append(control)
        self.probe_controls.hide()
        from hals_studio.ui.plotting.spl_cursor import SPLCursor
        self.cursor = SPLCursor(self, self.cursor_label)
        self.interaction = PlotInteraction(self)
        self.chart.canvas.mpl_connect('button_press_event', self.chart_click)
        self.note = W.QLabel(); self.note.setWordWrap(True); self.note.setStyleSheet('font-size:10px;color:#849eb1;padding:3px;')
        layout.addWidget(self.note)
        for widget in (self, self.chart.canvas, self.title):
            widget.setContextMenuPolicy(C.Qt.CustomContextMenu)
            widget.customContextMenuRequested.connect(lambda p, w=widget: self.menu(w.mapToGlobal(p)))

    def chart_click(self, event):
        self.owner.active_plot = self
        if any(ax.get_legend() is not None and ax.get_legend().contains(event)[0] for ax in self.chart.fig.axes): return
        if self.interaction.on_handle(event): return
        if event.button == 1 and event.xdata and event.inaxes and self.config['kind'] not in ('polar', 'globe_hv', 'globe_h', 'globe_v'):
            self.owner.jump_frequency(event.xdata)

    def menu(self, position):
        self.owner.active_plot = self
        menu = PlotMenu(self)
        if hasattr(self, 'extra_menu'):
            self.extra_menu(menu); menu.addSeparator()
        self._magnitude_actions = {}
        exclusive = G.QActionGroup(menu); exclusive.setExclusive(True)
        for category, items in GROUPS.items():
            sub = menu.addMenu(category)
            if category == 'SPL & phase':
                sub.addSection('Magnitude')
                selected = selected_magnitudes(self.config)
                for key, title in items.items():
                    if key in ('phase', 'minimum'): continue
                    action = sub.addAction(title); action.setCheckable(True)
                    self._magnitude_actions.setdefault(key, []).append(action)
                    action.setChecked(key in selected)
                    action.triggered.connect(lambda checked=False, k=key: self.toggle_magnitude(k))
                cea_menu = sub.addMenu('CEA2034 magnitudes')
                for key, title in GROUPS['CEA2034'].items():
                    action = cea_menu.addAction(title); action.setCheckable(True); action.setChecked(key in selected)
                    self._magnitude_actions.setdefault(key, []).append(action)
                    action.triggered.connect(lambda checked=False, k=key: self.toggle_magnitude(k))
                sub.addAction('Clear magnitudes', self.clear_magnitudes)
                sub.addSection('Phase')
                phases = G.QActionGroup(sub); phases.setExclusive(True)
                for mode in ('None', 'Total phase', 'Minimum phase'):
                    action = sub.addAction(mode if mode != 'None' else 'No phase'); action.setCheckable(True); phases.addAction(action)
                    action.setChecked(self.config['phase_mode'] == mode)
                    action.triggered.connect(lambda checked=False, m=mode: self.select_phase(m))
                sub.addSection('Phase display')
                wraps = G.QActionGroup(sub); wraps.setExclusive(True)
                for title, value in [('Wrapped', True), ('Unwrapped', False)]:
                    action = sub.addAction(title); action.setCheckable(True); wraps.addAction(action)
                    action.setChecked(self.config['wrapped'] == value)
                    action.triggered.connect(lambda checked=False, v=value: self.change('wrapped', v))
                continue
            for key, title in items.items():
                action = sub.addAction(title); action.setCheckable(True)
                if category == 'CEA2034': self._magnitude_actions.setdefault(key, []).append(action)
                action.setChecked(key in selected_magnitudes(self.config) if category == 'CEA2034' else key == self.config['kind'])
                if category == 'CEA2034': action.triggered.connect(lambda checked=False, k=key: self.toggle_magnitude(k))
                else:
                    exclusive.addAction(action)
                    action.triggered.connect(lambda checked=False, k=key: self.set_kind(k))
            if category == 'CEA2034': sub.addSeparator(); sub.addAction('Clear magnitudes', self.clear_magnitudes)
        menu.addSeparator(); menu.addAction('Plot setup / pin settings…', self.setup)
        menu.addAction('Add overlay…', lambda: self.owner.capture_overlay(self))
        menu.addAction('Reset zoom', self.reset_zoom)
        if self.config['kind'] in ('balloon', 'cross_sonograms'):
            camera = menu.addMenu('Camera')
            for name in ('Front', 'Side', 'Top', 'Isometric'):
                camera.addAction(name, lambda n=name: self.camera(n))
        menu.addAction('Export plot image…', self.export)
        if self.config['kind'] == 'balloon':
            menu.addAction('Export displayed mesh…', self.export_mesh)
        elif self.config['kind'] not in ('polar', 'globe_hv', 'globe_h', 'globe_v'):
            menu.addAction('Export plotted data CSV…', self.export_csv)
        menu.exec(position)
        self._magnitude_actions = {}; menu.deleteLater()

    def export_mesh(self):
        path, _ = W.QFileDialog.getSaveFileName(self, 'Export VTK structured grid', '', 'VTK grid (*.vts)')
        if path:
            if not path.lower().endswith('.vts'): path += '.vts'
            self.mesh.save(path)

    def export_csv(self):
        import csv
        path, _ = W.QFileDialog.getSaveFileName(self, 'Export plotted data', '', 'CSV (*.csv)')
        if not path: return
        if not path.lower().endswith('.csv'): path += '.csv'
        with open(path, 'w', newline='', encoding='utf-8') as stream:
            writer = csv.writer(stream)
            if self.config['kind'].startswith(('map_', 'globe_')):
                s = self.owner.sphere; levels = self.owner.get_levels(self.config['smoothing'])
                angles, h, v = s.cuts(s.relative(levels, 'On axis' if self.config.get('directivity_on_axis',False) else 'Peak'))
                data = h if self.config['kind'] in ('map_h', 'globe_h') else v
                writer.writerow(['Frequency Hz', 'Angle degrees', 'Relative level dB'])
                for j, freq in enumerate(s.freqs):
                    writer.writerows((freq, angle, value) for angle, value in zip(angles, data[j]))
            else:
                writer.writerow(['Curve', 'Frequency Hz', 'Value', 'Axis units'])
                for ax in self.chart.fig.axes:
                    for line in ax.lines:
                        name = line.get_label()
                        if name.startswith('_'): continue
                        writer.writerows((name, f, value, ax.get_ylabel()) for f, value in zip(line.get_xdata(), line.get_ydata()))

    def export(self):
        path, _ = W.QFileDialog.getSaveFileName(self, 'Export plot', '', 'PNG image (*.png)')
        if path:
            if not path.lower().endswith('.png'): path += '.png'
            if self.config['kind'] in ('csd','wavelet') or (self.config['kind'].startswith('map_') and self.config.get('directivity_display')in ('3D surface','Waterfall')):
                view=self.csd_view
                if view.stack.currentWidget() is view.chart: view.chart.fig.savefig(path,dpi=180)
                else: view.plotter.screenshot(path)
            elif self.config['kind'] == 'impulse' and hasattr(self, 'ir_panel'): self.ir_panel.chart.fig.savefig(path, dpi=180)
            elif self.config['kind'] in ('balloon', 'cross_sonograms'): self.plotter.screenshot(path)
            else: self.chart.fig.savefig(path, dpi=180)

    def setup(self):
        if self.config['kind'] == 'impulse':
            if hasattr(self, 'ir_panel'): self.ir_panel.settings()
            return
        dialog = Setup(self)
        if dialog.exec() == W.QDialog.Accepted:
            self.config = dialog.values; self.invalidate(); self.owner.rebuild_pins(); self.owner.schedule()

    def set_kind(self, kind):
        if kind in MAGNITUDE_KINDS and self.config['kind'] not in MAGNITUDE_KINDS:
            self.config['smoothing'] = 'None'
        self.config['kind'] = kind
        self.config['magnitude_selection'] = None
        if kind in ('phase', 'minimum'): self.config['phase_mode'] = 'Minimum phase' if kind == 'minimum' else 'Total phase'
        self.invalidate(); self.owner.rebuild_pins(); self.owner.schedule()

    def toggle_magnitude(self, kind):
        if self.config['kind'] not in MAGNITUDE_KINDS:
            self.config['smoothing'] = 'None'
        selected = selected_magnitudes(self.config)
        if kind in selected: selected.remove(kind)
        else:
            selected.append(kind)
            if kind == 'di' or kind.endswith(' DI'): self.config['phase_mode'] = 'None'
        self.config['magnitude_selection'] = selected
        self.config['kind'] = selected[0] if selected else 'probe'
        self.sync_magnitude_actions()
        self.invalidate(); self.owner.rebuild_pins(); self.owner.schedule()

    def clear_magnitudes(self):
        self.config['magnitude_selection'] = []; self.config['kind'] = 'probe'
        self.sync_magnitude_actions()
        self.invalidate(); self.owner.rebuild_pins(); self.owner.schedule()

    def sync_magnitude_actions(self):
        selected = selected_magnitudes(self.config)
        for kind, actions in getattr(self, '_magnitude_actions', {}).items():
            for action in actions: action.setChecked(kind in selected)

    def select_phase(self, mode):
        self.config['phase_mode'] = mode
        if self.config['kind'] in MAGNITUDE_KINDS:
            self.config['magnitude_selection'] = selected_magnitudes(self.config)
        elif self.config['kind'] not in ('phase', 'minimum'):
            self.config['kind'] = 'probe'; self.config['magnitude_selection'] = ['probe']
        if self.config['kind'] in ('phase', 'minimum'):
            self.config['kind'] = 'probe' if mode == 'None' else ('minimum' if mode == 'Minimum phase' else 'phase')
        if mode != 'None':
            selected = [k for k in selected_magnitudes(self.config) if k != 'di' and not k.endswith(' DI')]
            self.config['magnitude_selection'] = selected
            if self.config['kind'] == 'di' or self.config['kind'].endswith(' DI'): self.config['kind'] = selected[0] if selected else 'probe'
            self.sync_magnitude_actions()
        self.config['phase'] = mode != 'None'
        self.invalidate(); self.owner.rebuild_pins(); self.owner.schedule()

    def fit_names(self, config=None):
        from hals_studio.ui.plotting.response_plot import magnitude_curves
        if self.owner.sphere is None: return ['First curve']
        config = self.config if config is None else config
        if config['kind'] in ('balloon', 'volume', 'map_h', 'map_v', 'polar'): return ['First curve']
        curves, _, _ = magnitude_curves(self, self.owner.sphere, self.owner.get_levels(config['smoothing']), config)
        return ['First curve', *curves]

    def estimated_delay_ms(self):
        o = self.owner
        if o.sphere is None: return 0.
        pressure = o.sphere.pressure[:, *o.sphere.index(*o.axis)]
        speed = float(o.sphere.metadata.get('speed_of_sound', 343.))
        return get_min_phase_delay(pressure, o.sphere.freqs, speed)/speed*1000

    def fill_estimated_delay(self, field, values):
        try: delay = self.estimated_delay_ms()
        except ValueError as exc:
            W.QMessageBox.warning(self, 'Delay estimate', str(exc)); return
        values['min_phase_delay'] = False
        field.setValue(delay)
        values['delay'] = field.value()
        if values is self.config:
            self.invalidate(); self.owner.schedule()

    def delay_ms(self):
        self.delay_note = ''
        # Convert legacy automatic estimate + trim into one explicit value.
        if self.config.get('min_phase_delay'):
            try: self.config['delay'] += self.estimated_delay_ms()
            except ValueError as exc:
                self.delay_note = f'Delay estimate unavailable: {exc}'
                return self.config['delay']
            self.config['min_phase_delay'] = False
        return self.config['delay']

    def reset_zoom(self):
        if self.config['kind'] == 'impulse':
            if hasattr(self, 'ir_panel'): self.ir_panel.interaction.reset()
            return
        if self.config['kind'] in ('csd', 'wavelet') or (self.config['kind'].startswith('map_') and self.config.get('directivity_display') in ('3D surface','Waterfall')):
            if hasattr(self, 'csd_view'): self.csd_view.reset()
            return
        if self.config['kind'] in ('balloon', 'cross_sonograms'): self.camera()
        else: self.interaction.reset()

    def invalidate(self):
        self.last_render = None

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.invalidate()
        self.owner.schedule()

    def change(self, key, value):
        if key == 'phase_mode':
            self.select_phase(value); return
        previous = self.config[key]; self.config[key] = value
        manual = 'auto_axes' if key in ('fmin', 'fmax', 'ymin', 'ymax') else 'phase_auto' if key in ('phase_min', 'phase_max') else 'di_auto' if key in ('di_min', 'di_max') else None
        if manual:
            self.config[manual] = False
            self.owner.rebuild_pins()
        if key=='csd_method': self.config['kind']='wavelet' if value=='Morlet wavelet' else 'csd'
        if key.startswith('contour_'):
            try: contour_levels(self.config['contour_low'], self.config['contour_high'], self.config['contour_step'])
            except ValueError as exc:
                self.config[key] = previous; self.owner.statusBar().showMessage(str(exc)); self.owner.rebuild_pins(); return
        self.invalidate(); self.owner.schedule()
        if key in ('breakout', 'extent', 'step', 'symmetric', 'sweep_direction', 'wavelet_units', 'csd_method'): self.owner.rebuild_pins()

    def ensure_3d(self):
        if self.plotter is None:
            self.plotter = QtInteractor(self, auto_update=False)
            # Qt's FBO multisampling conflicts with VTK depth peeling and can
            # make every translucent surface disappear on some OpenGL drivers.
            self.plotter.render_window.SetMultiSamples(0)
            self.stack.addWidget(self.plotter.interactor)
            self.probe_controls.setParent(self.plotter.interactor)
            self.frequency_controls.setParent(self.plotter.interactor)
            self.frequency_controls.move(4,4)
            self.plotter.set_background('#09151f', top='#1b3040')
            self.set_lighting()
            self.plotter.add_axes()
            self.plotter.interactor.setContextMenuPolicy(C.Qt.CustomContextMenu)
            self.plotter.interactor.customContextMenuRequested.connect(lambda p: self.menu(self.plotter.interactor.mapToGlobal(p)))
            self.plotter.interactor.installEventFilter(self.interaction)
        self.stack.setCurrentWidget(self.plotter.interactor)
        if self.config['orbit'].startswith('Az'):
            self.plotter.enable_terrain_style(); self.plotter.camera.up = (0, 0, 1)
        else: self.plotter.enable_trackball_style()

    def set_lighting(self):
        # Plotter.clear() removes lights as well as actors. Reinstall after
        # each scene rebuild, otherwise material settings produce a flat fill.
        self.plotter.remove_all_lights()
        for elevation, azimuth, intensity, color in ((30, -40, .95, '#fff2df'), (-20, 45, .3, '#bfdcff'), (55, 145, .6, '#ffffff')):
            light = pv.Light(light_type='camera light', intensity=intensity, color=color)
            light.set_direction_angle(elevation, azimuth)
            self.plotter.add_light(light)

    def camera(self, name='Isometric'):
        if not self.plotter: return
        if name == 'Front': self.plotter.view_yz()
        elif name == 'Top': self.plotter.view_xy()
        elif name == 'Side': self.plotter.view_xz()
        else:
            center = np.asarray(self.plotter.bounds).reshape(3, 2).mean(axis=1)
            self.plotter.camera_position = [center + (3.5, -5, 2.8), center, (0, 0, 1)]
        self.plotter.reset_camera()
        if self.config['kind'] == 'balloon': self.plotter.camera.zoom(1.35)
        self.home_focal = np.asarray(self.plotter.camera.focal_point)
        self.home_distance = np.linalg.norm(np.asarray(self.plotter.camera.position)-self.home_focal)
        self.plotter.render()

    def drag(self, point, widget):
        norm = np.linalg.norm(point)
        if norm < 1e-8: return
        d = np.asarray(point)/norm; widget.SetCenter(d*1.06)
        self.owner.azimuth.setValue(float(np.degrees(np.arctan2(d[1], d[0]))))
        self.owner.elevation.setValue(float(np.degrees(np.arcsin(np.clip(d[2], -1, 1)))))

    def render(self):
        o, c = self.owner, self.config
        if o.sphere is None:
            self.cursor.clear()
            self.interaction.begin(None)
            self.chart.fig.clear(); self.chart.canvas.draw_idle()
            self.stack.setCurrentWidget(self.chart_frame)
            self.probe_controls.hide(); self.frequency_controls.hide()
            self.note.setText('Open coefficients to view analysis plots')
            self.last_render = None
            return
        key = (id(o.sphere), o.frequency.value(), o.azimuth.value(), o.elevation.value(),
               repr(c), o.overlay_revision, o.axis)
        if self.last_render == key: return
        response_plot = c['kind'] in MAGNITUDE_KINDS or c['kind'] in ('phase', 'minimum')
        if (response_plot and self.last_render is not None and
                self.last_render[:1] + self.last_render[2:] == key[:1] + key[2:] and
                hasattr(self, 'frequency_marker')):
            frequency = o.sphere.freqs[o.frequency.value()]
            self.frequency_marker.set_xdata([frequency, frequency])
            self.cursor.follow_marker()
            self.chart.canvas.draw_idle()
            self.last_render = key
            return
        self.cursor.clear()
        title = TITLES[c['kind']]
        selected = selected_magnitudes(c)
        if c['magnitude_selection'] is not None:
            title = ' + '.join(TITLES[k] for k in selected) if len(selected) <= 2 else f'Magnitude responses ({len(selected)} selections)'
            if not selected: title = 'No magnitudes'
        if (c['kind'] in GROUPS['SPL & phase'] or c['magnitude_selection'] is not None) and c['kind'] not in ('phase', 'minimum') and c['phase_mode'] != 'None':
            title += ' / '+c['phase_mode']
        self.title.setText(f'{title.upper()}     ▾')
        self.title.setToolTip(title)
        self.note.setText('Right-click to choose plot or configure settings')
        s, i = o.sphere, o.frequency.value()
        levels = o.get_levels(c['smoothing']); rel = s.relative(levels, ('On axis' if c.get('directivity_on_axis',False) else 'Peak') if c['kind'].startswith(('map_', 'globe_')) or c['kind']=='cross_sonograms' else c['normalization'])
        kind = c['kind']
        self.probe_controls.setVisible(kind == 'balloon')
        self.frequency_controls.setVisible(kind == 'balloon')
        if kind in ('balloon', 'cross_sonograms'):
            previous = getattr(self, '_scene_kind', None)
            self.ensure_3d()
            if previous != kind:
                self.plotter.clear_sphere_widgets(); self.handle = None; self.plotter.clear(); self.set_lighting()
            if kind == 'balloon':
                self.probe_frequency.setText(f'{s.freqs[i]:,.0f} Hz')
                self.probe_controls.adjustSize(); self.probe_controls.move(4,max(4,self.plotter.interactor.height()-self.probe_controls.height()-6)); self.probe_controls.show(); self.probe_controls.raise_()
                self.frequency_controls.adjustSize(); self.frequency_controls.show(); self.frequency_controls.raise_()
                self.balloon(s, rel, i)
            else:
                from hals_studio.ui.plotting.directivity_views import draw_cross_sonograms
                draw_cross_sonograms(self, s, rel)
            if previous != kind: self.camera()
            from hals_studio.ui.viewer_theme import scene_theme
            scene_theme(self.plotter)
            self._scene_kind = kind
        else:
            self.stack.setCurrentWidget(self.chart_frame)
            if c['auto_axes'] and (kind in GROUPS['SPL & phase'] or c['magnitude_selection'] is not None):
                probe_key = (o.azimuth.value(), o.elevation.value(), o.overlay_revision, o.axis)
                if probe_key != getattr(self, '_range_probe', None): self.interaction.saved.clear()
                self._range_probe = probe_key
            self.interaction.begin((id(s), kind, c['auto_axes'], c['fmin'], c['fmax'], c['ymin'], c['ymax'], c['wrapped'], c['phase_mode'], c['phase_auto'], c['phase_min'], c['phase_max'], c['di_auto'], c['di_min'], c['di_max'], tuple(selected_magnitudes(c))))
            if kind.startswith('map_') and c.get('directivity_display') in ('3D surface','Waterfall'):
                from hals_studio.ui.plotting.csd_plot import CSDView
                if not hasattr(self,'csd_view'):
                    self.csd_view=CSDView(); self.stack.addWidget(self.csd_view)
                angles,h,v=s.cuts(rel); data=h if kind=='map_h' else v
                self.stack.setCurrentWidget(self.csd_view)
                self.csd_view.render(None,1.,{**c, 'csd_mode':'3D waterfall','csd_span':c['span'], '_surface_data':(s.freqs,angles,data.T),'_y_label':('Horizontal' if kind=='map_h' else 'Vertical')+' angle / degrees'})
                self.note.setText('Directivity surface - frequency / angle / relative level - drag to orbit, wheel to zoom')
            elif kind == 'impulse':
                from hals_studio.ui.plotting.csd_plot import analysis_ir
                from hals_studio.ui.plotting.export_charts import ImpulsePanel
                if not hasattr(self, 'ir_panel'):
                    self.ir_panel = ImpulsePanel(show_toolbar=False); self.stack.addWidget(self.ir_panel)
                try:
                    ir, fs, _ = analysis_ir(o, s)
                    self.ir_panel.update_ir(np.arange(len(ir))/fs, ir, None, id(s))
                    self.stack.setCurrentWidget(self.ir_panel)
                    self.note.setText('HALS IR generator ? selected probe ? normalized amplitude ? time from generated IR start')
                except (ValueError, OSError) as exc:
                    self.stack.setCurrentWidget(self.chart_frame); self.chart.fig.clear()
                    axis = self.chart.fig.add_subplot(); axis.set_axis_off(); axis.text(.5,.5,str(exc),ha='center',va='center',wrap=True)
                    self.chart.done(); self.note.setText('Impulse response unavailable for this source')
            elif kind in ('csd', 'wavelet'):
                from hals_studio.ui.plotting.csd_plot import analysis_ir, CSDView
                if not hasattr(self, 'csd_view'):
                    self.csd_view = CSDView(); self.stack.addWidget(self.csd_view)
                self.stack.setCurrentWidget(self.csd_view)
                try:
                    ir, fs, note = analysis_ir(o, s); self.csd_view.render(ir, fs, {**c, 'csd_method': 'Morlet wavelet' if kind == 'wavelet' else 'CSD'}); self.note.setText(note)
                except (ValueError, OSError) as exc:
                    self.stack.setCurrentWidget(self.chart_frame); self.chart.fig.clear()
                    axis = self.chart.fig.add_subplot(); axis.set_axis_off(); axis.text(.5,.5,str(exc),ha='center',va='center',wrap=True)
                    self.chart.done(); self.note.setText('CSD unavailable for this source')
            elif kind.startswith('globe_'):
                from hals_studio.ui.plotting.directivity_views import draw_globe
                draw_globe(self, s, rel)
            elif kind == 'polar':
                draw_zoomable_polars(self.chart, s, rel, i, c['span'], pane=self); self.interaction.finish(self.chart.fig.axes)
            else: self.draw_chart(s, levels, rel, i)
        self.last_render = (id(o.sphere), o.frequency.value(), o.azimuth.value(), o.elevation.value(),
                            repr(c), o.overlay_revision, o.axis)

    def balloon(self, s, rel, i):
        from hals_studio.ui.plotting.scene_renderers import balloon
        return balloon(self, s, rel, i)

    def material(self):
        specular, power = {'Matte': (.05, 8), 'Satin': (.4, 18), 'Glossy': (.85, 35)}[self.config['surface_finish']]
        return dict(lighting=True, ambient=.12, diffuse=.8, specular=specular, specular_power=power)

    def volume(self, s, rel, i):
        from hals_studio.ui.plotting.scene_renderers import volume
        return volume(self, s, rel, i)

    def draw_chart(self, s, levels, rel, i):
        from hals_studio.ui.plotting.response_plot import draw_chart
        draw_chart(self, s, levels, rel, i)
