"""Directivity charts restricted to available export-plane samples."""
import numpy as np
from PySide6 import QtWidgets as W
from hals_studio.application.export_directivity import export_cuts, sweep_direction_indices
from hals_studio.ui.plotting.plots import Chart, draw_polar_cuts
from hals_studio.ui.plotting.plot_interaction import PlotInteraction
from hals_studio.ui.plot_header import PlotHeader

from hals_studio.ui.plotting.plot_settings import GROUPS, default_config
from hals_studio.ui.plotting.directivity_views import draw_globe_cuts, draw_directivity_map

DIRECTIVITY_TITLES = {
    **{key: title for key, title in GROUPS['Directivity'].items() if key != 'cross_sonograms'},
    **{key: GROUPS['SPL & phase'][key] for key in ('sweep_h', 'sweep_v')},
}



class ExportDirectivityPanel(W.QWidget):
    def __init__(self, options=None):
        super().__init__()
        self.chart = Chart(); self.config = default_config('map_h'); self.last_render = None
        self.options = options if options is not None else {}
        self.options.setdefault('polar_sample_points', True)
        for key, value in self.config.items(): self.options.setdefault(key, value)
        self.config = self.options
        self.result = None; self.kind = 'map_h'
        layout = W.QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5); layout.setSpacing(4)
        self.header = PlotHeader(lambda: None, self.reset_axes, self.settings)
        self.header.readout.hide(); layout.addWidget(self.header)
        self.frequency = W.QDoubleSpinBox(); self.frequency.setRange(1, 100000)
        self.frequency.setValue(1000); self.frequency.setSuffix(' Hz'); self.frequency.setKeyboardTracking(False)
        self.frequency.setToolTip('Polar frequency')
        self.header.layout().insertWidget(1, self.frequency)
        self.span = W.QDoubleSpinBox(self); self.span.setRange(6, 120)
        self.span.setValue(self.config['span']); self.span.hide()
        self.settings_button = self.header.gear
        self.stack = W.QStackedWidget(); self.stack.addWidget(self.chart); layout.addWidget(self.stack, 1)
        self.note = W.QLabel(''); self.note.setWordWrap(True); layout.addWidget(self.note)
        self.interaction = PlotInteraction(self)
        from hals_studio.ui.plotting.spl_cursor import SPLCursor
        self.cursor_frequency = 1000.
        self.cursor = SPLCursor(self, self.header.readout, lambda: self.cursor_frequency)
        self.chart.canvas.mpl_connect('button_press_event', self.select_frequency)
        self.frequency.valueChanged.connect(self.redraw); self.span.valueChanged.connect(self.redraw)

    def select_frequency(self, event):
        if not self.kind.startswith('sweep_') or self.result is None: return
        if event.button != 1 or event.inaxes not in self.interaction.axes or event.xdata is None: return
        if self.interaction.on_handle(event): return
        legend = event.inaxes.get_legend()
        if legend is not None and legend.contains(event)[0]: return
        f = self.result['freqs']
        self.cursor_frequency = float(f[np.argmin(abs(f-event.xdata))])
        self.frequency_marker.set_xdata([self.cursor_frequency]*2)
        self.cursor.follow_marker(); self.chart.canvas.draw_idle()

    def fit_names(self, config=None):
        return ['First curve', *getattr(self, 'magnitude_curves', {})]

    def settings(self):
        from hals_studio.ui.pane_setup import Setup
        dialog = Setup(self, allow_pins=False, allow_delay_estimate=False,
            disabled_settings={
                'extent': 'Sweep coverage is set by Export geometry.',
                'step': 'Available angle spacing is set by Export geometry.',
                'overlays': 'Overlays are managed in the Selected Point plot.'})
        if dialog.exec() == W.QDialog.Accepted:
            self.config.update(dialog.values)
            self.span.blockSignals(True); self.span.setValue(self.config['span']); self.span.blockSignals(False)
            self.interaction.saved.clear()
            self.redraw()

    def reset_axes(self):
        if hasattr(self, 'csd_view') and self.stack.currentWidget() is self.csd_view:
            self.csd_view.reset()
        else:
            self.interaction.reset()

    def shutdown(self):
        if hasattr(self, 'csd_view'): self.csd_view.shutdown()

    def update_result(self, result, kind):
        if self.result is result and self.kind == kind: return
        self.result, self.kind = result, kind
        self.redraw()

    def redraw(self, *_):
        if self.result is None: return
        self.frequency.setEnabled(self.kind == 'polar')
        self.frequency.setVisible(self.kind == 'polar')
        if hasattr(self, 'header'): self.header.title.setText(DIRECTIVITY_TITLES[self.kind].upper() + '  \u25be')
        self.settings_button.setVisible(True)
        self.config.update(kind=self.kind, span=self.span.value())
        sweep = self.kind.startswith('sweep_')
        if hasattr(self, 'header'): self.header.readout.setVisible(sweep)
        cuts = export_cuts(self.result, self.config, normalize=False) if sweep else export_cuts(self.result, self.config)
        f = self.result['freqs']
        span = self.span.value(); index = int(np.argmin(abs(f-self.frequency.value())))
        self.interaction.begin((id(self.result), self.kind, span, index))
        self.config.update(kind=self.kind, span=span)
        fig = self.chart.fig
        if hasattr(self, 'stack'): self.stack.setCurrentWidget(self.chart)
        if sweep:
            from hals_studio.ui.plotting.response_plot import draw_response_curves, phase_values
            plane = 'horizontal' if self.kind == 'sweep_h' else 'vertical'
            angles, values = cuts[plane]
            angles, indices = sweep_direction_indices(angles, self.config['sweep_direction'])
            values = values[:, indices]
            prefix = 'H' if plane == 'horizontal' else 'V'
            curves = {f'{prefix} '+('On axis' if angle == 0 else f'{angle:+g}\N{DEGREE SIGN}'): values[:, i]+self.config['offset']
                      for i, angle in enumerate(angles)}
            phase_traces = []
            mode = self.config['phase_mode']
            if mode != 'None' and curves:
                if 'data' in self.result:
                    pressure = np.column_stack([10**(row['mag']/20)*np.exp(1j*np.deg2rad(row['phase']))
                                                for row in self.result['data'].values()])
                else: pressure = self.result['processed']
                _, samples = export_cuts(self.result, normalize=False, samples=pressure)[plane]
                samples = samples[:, indices]
                phase_traces = [(name+' '+mode.lower(), f,
                    phase_values(f, samples[:, i], mode, self.config['wrapped'], self.config['delay']))
                    for i, name in enumerate(curves)]
            self.cursor_frequency = float(f[np.argmin(abs(f-self.cursor_frequency))])
            draw_response_curves(self, f, curves, self.cursor_frequency,
                note='Export points only; '+plane+' SPL sweep. Double-click a legend trace to select its phase and readout.',
                ylabel='Level / dB + FRD offset', phase_mode=mode, phase_traces=phase_traces,
                phase_follow_selection=True)
            if not curves:
                ax = self.chart.fig.axes[0]
                for text in ax.texts: text.set_text('No '+plane+' sweep data')
                self.chart.done()
            return
        elif self.kind == 'polar':
            draw_polar_cuts(self.chart, cuts, index, span, pane=self,
                            close_curves=False, show_points=self.options.get('polar_sample_points', True))
            self.interaction.finish([ax for ax in fig.axes if ax in self._rotation_axes])
        elif self.kind == 'globe_hv':
            mask = (f > 0) & (f >= self.config['fmin']) & (f <= self.config['fmax'])
            if np.count_nonzero(mask) < 2: mask = f > 0
            cuts = {plane: (angles, values[mask]) for plane, (angles, values) in cuts.items()}
            f = f[mask]
            draw_globe_cuts(self, f, cuts, close_curves=False)
        else:
            plane = 'horizontal' if self.kind == 'map_h' else 'vertical'
            angles, values = cuts[plane]
            draw_directivity_map(self, f, angles, values, bounded=True)
        frequency_note = f' - {f[index]:g} Hz' if self.kind == 'polar' else ''
        on_axis = self.config.get('normalization') == 'On axis' if self.kind == 'polar' else self.config.get('directivity_on_axis', False)
        reference = 'the export reference point' if on_axis else 'the strongest export point at each frequency'
        self.note.setText('Export points only; relative to '+reference+'. Missing planes remain empty.'+frequency_note)
        self.chart.done()
