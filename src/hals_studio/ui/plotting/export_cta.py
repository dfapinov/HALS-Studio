"""CTA plots backed by Stage 5 export metrics, independent of Analysis state."""
import numpy as np
from PySide6 import QtWidgets as W
from hals_studio.process_engine.stage5_extract_pressures import CTA2034_METRIC_NAMES
from hals_studio.ui.plotting.plots import Chart
from hals_studio.ui.plotting.plot_settings import cta_curve_names, default_config, TITLES
from hals_studio.ui.plotting.plot_interaction import PlotInteraction
from hals_studio.ui.plotting.spl_cursor import SPLCursor
from hals_studio.ui.plotting.response_plot import draw_response_curves


class CTAPanel(W.QWidget):
    def __init__(self, config=None, choose=lambda: None):
        super().__init__()
        self.chart = Chart()
        self.config = config if config is not None else {}
        for key, value in default_config('cea').items(): self.config.setdefault(key, value)
        self.last_render = None
        self.frequency = None
        self.result = None
        layout = W.QVBoxLayout(self)
        from hals_studio.ui.plot_header import PlotHeader
        self.header = PlotHeader(choose, lambda: self.interaction.reset(), self.settings)
        self.readout = self.header.readout
        layout.setContentsMargins(5, 5, 5, 5); layout.setSpacing(4)
        layout.addWidget(self.header)
        layout.addWidget(self.chart, 1)
        self.note = W.QLabel('CTA-2034 export metrics'); layout.addWidget(self.note)
        self.interaction = PlotInteraction(self)
        self.cursor = SPLCursor(self, self.readout, lambda: self.frequency)
        self.chart.canvas.mpl_connect('button_press_event', self.click)

    def update_metrics(self, result, kind):
        key = (id(result), kind)
        if self.last_render == key: return
        self.last_render = key; self.result = result
        self.interaction.begin(kind)
        self.config['kind'] = kind
        self.header.title.setText(TITLES[kind].upper() + '  \u25be')
        offset = result['config']['frd_db_offset']
        metrics = {name: np.asarray(result['metrics'][filename][0]) + (0 if name.endswith(' DI') else offset)
                   for filename, name in CTA2034_METRIC_NAMES.items()}
        curves = {name: metrics[name] for name in cta_curve_names(kind)}
        f = result['freqs']
        self.frequency = float(f[np.argmin(abs(f-(self.frequency if self.frequency is not None else 1000)))])
        draw_response_curves(self, f, curves, self.frequency,
                             note='CTA-2034 export metrics', ylabel='HALS level / dB + offset')
        self.ax = self.chart.fig.axes[0]

    def settings(self):
        from hals_studio.ui.pane_setup import axis_editors, valid_axis_ranges
        dialog = W.QDialog(self); dialog.setWindowTitle('CTA-2034 plot settings')
        form = W.QFormLayout(dialog)
        values = axis_editors(form, self.config,
            ('auto_axes', 'fmin', 'fmax', 'ymin', 'ymax', 'di_auto', 'di_min', 'di_max', 'phase_height'))
        buttons = W.QDialogButtonBox(W.QDialogButtonBox.Ok | W.QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject); form.addRow(buttons)
        if dialog.exec() != W.QDialog.Accepted: return
        if not valid_axis_ranges(values):
            W.QMessageBox.warning(self, 'Axis limits', 'Each maximum must exceed its minimum.'); return
        self.config.update(values); self.last_render = None; self.interaction.saved.clear()
        if self.result is not None: self.update_metrics(self.result, self.config['kind'])

    def click(self, event):
        if self.result is None or event.button != 1 or event.inaxes not in self.interaction.axes or event.xdata is None: return
        if self.interaction.on_handle(event): return
        legend = self.ax.get_legend()
        if legend is not None and legend.contains(event)[0]: return
        f = self.result['freqs']
        self.frequency = float(f[np.argmin(abs(f-event.xdata))])
        self.frequency_marker.set_xdata([self.frequency]*2)
        self.cursor.follow_marker()
        self.chart.canvas.draw_idle()
