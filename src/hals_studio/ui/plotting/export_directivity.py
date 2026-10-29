"""Directivity charts restricted to available export-plane samples."""
import numpy as np
from PySide6 import QtWidgets as W
from matplotlib.ticker import FuncFormatter
from hals_studio.application.export_directivity import export_cuts
from hals_studio.ui.plotting.plots import Chart, style, audio_ticks, audio_frequency, draw_polar_cuts
from hals_studio.ui.plotting.plot_interaction import PlotInteraction

from hals_studio.ui.plotting.plot_settings import GROUPS, default_config
from hals_studio.ui.plotting.directivity_views import draw_globe_cuts, draw_spectrogram

DIRECTIVITY_TITLES = GROUPS['Directivity']



class ExportDirectivityPanel(W.QWidget):
    def __init__(self):
        super().__init__()
        self.chart = Chart(); self.config = default_config('map_h'); self.last_render = None
        self.result = None; self.kind = 'map_h'
        layout = W.QVBoxLayout(self)
        toolbar = W.QHBoxLayout(); layout.addLayout(toolbar)
        toolbar.addWidget(W.QLabel('Frequency'))
        self.frequency = W.QDoubleSpinBox(); self.frequency.setRange(1, 100000)
        self.frequency.setValue(1000); self.frequency.setSuffix(' Hz'); self.frequency.setKeyboardTracking(False)
        toolbar.addWidget(self.frequency)
        toolbar.addWidget(W.QLabel('Span'))
        self.span = W.QDoubleSpinBox(); self.span.setRange(6, 120); self.span.setValue(36); self.span.setSuffix(' dB')
        toolbar.addWidget(self.span); toolbar.addStretch()
        reset = W.QPushButton('Reset axes'); toolbar.addWidget(reset)
        layout.addWidget(self.chart, 1)
        self.note = W.QLabel(''); self.note.setWordWrap(True); layout.addWidget(self.note)
        self.interaction = PlotInteraction(self); reset.clicked.connect(self.interaction.reset)
        self.frequency.valueChanged.connect(self.redraw); self.span.valueChanged.connect(self.redraw)

    def update_result(self, result, kind):
        if self.result is result and self.kind == kind: return
        self.result, self.kind = result, kind
        self.redraw()

    def redraw(self, *_):
        if self.result is None: return
        self.frequency.setEnabled(self.kind == 'polar')
        cuts = export_cuts(self.result); f = self.result['freqs']
        span = self.span.value(); index = int(np.argmin(abs(f-self.frequency.value())))
        self.interaction.begin((id(self.result), self.kind, span, index))
        self.config.update(kind=self.kind, span=span)
        fig = self.chart.fig
        if self.kind == 'polar':
            draw_polar_cuts(self.chart, cuts, index, span, pane=self,
                            close_curves=False, show_points=True)
            self.interaction.finish([ax for ax in fig.axes if ax in self._rotation_axes])
        elif self.kind == 'globe_hv':
            draw_globe_cuts(self, f, cuts, close_curves=False)
        else:
            fig.clear(); fig.set_layout_engine('constrained')
            ax = fig.add_subplot()
            plane = 'horizontal' if self.kind == 'map_h' else 'vertical'
            angles, values = cuts[plane]
            if len(angles) < 2:
                ax.set_axis_off()
                ax.text(.5, .5, 'No '+plane+' sweep data', transform=ax.transAxes, ha='center', va='center')
                self.interaction.finish([])
            else:
                image = draw_spectrogram(ax, f, angles, values, self.config, bounded=True)
                style(ax, plane.title(), ylabel='Angle / degrees')
                ax.set_xlim(f[0], f[-1]); ax.set_ylim(angles[0], angles[-1])
                ax.set_xticks(audio_ticks(f[0], f[-1])); ax.xaxis.set_major_formatter(FuncFormatter(lambda value, _: audio_frequency(value)))
                fig.colorbar(image, ax=ax, label='Relative level / dB', pad=.02)
                self.interaction.finish([ax])
        frequency_note = f' - {f[index]:g} Hz' if self.kind == 'polar' else ''
        self.note.setText('Export points only; relative to the export reference point. Missing planes remain empty.'+frequency_note)
        self.chart.done()
