"""Selected-microphone SPL/total-phase and IR panes for the export workspace."""
from copy import deepcopy
import numpy as np
from PySide6 import QtCore as C, QtWidgets as W
from matplotlib.transforms import ScaledTranslation
from matplotlib.patches import ConnectionPatch
from plots import Chart, style, audio_ticks, audio_frequency
from matplotlib.ticker import FuncFormatter, MaxNLocator
from response_plot import phase_trace
from plot_interaction import PlotInteraction
from analysis_metrics import trend_fit

RESPONSE_DEFAULT = dict(phase_height=.45, wrapped=True, fit=False, fit_low=100., fit_high=10000.,
                        fit_curve='Selected mic', overlays=[], auto_axes=True, fmin=20., fmax=20000., ymin=-100., ymax=10., phase_auto=True, phase_min=-180., phase_max=180.)


class ResponsePanel(W.QWidget):
    def __init__(self, workspace):
        super().__init__(); self.workspace = workspace; self.chart = Chart(); self.last_render = None
        self.config = deepcopy(RESPONSE_DEFAULT); self.background = None; self.key = None; self.artists = []
        self.latest = None; self.fit_result = None
        layout = W.QVBoxLayout(self); layout.setContentsMargins(5, 5, 5, 5)
        self.point_label = W.QLabel()
        toolbar_widget = W.QWidget(); toolbar_widget.setStyleSheet('QPushButton, QToolButton { padding:7px 5px; } QLabel, QCheckBox { font-size:11px; }')
        self.toolbar = W.QHBoxLayout(toolbar_widget); self.toolbar.setContentsMargins(0,0,0,0); self.toolbar.setSpacing(4); layout.addWidget(toolbar_widget)
        self.add_overlay_button = W.QPushButton('Add overlay'); self.add_overlay_button.clicked.connect(self.add_overlay); self.toolbar.addWidget(self.add_overlay_button)
        button = W.QToolButton(); button.setText('Overlays'); button.clicked.connect(self.overlays); self.toolbar.addWidget(button)
        self.fit_toggle = W.QCheckBox('Fit line'); self.fit_toggle.toggled.connect(self.toggle_fit); self.toolbar.addWidget(self.fit_toggle); self.toolbar.addSpacing(10)
        self.fit_limits = {}
        for key, title in [('fit_low', 'Fit Lower'), ('fit_high', 'Fit Upper')]:
            self.toolbar.addWidget(W.QLabel(title))
            spin = W.QDoubleSpinBox(); spin.setRange(.1, 100000); spin.setDecimals(0)
            spin.setFixedWidth(78); spin.setKeyboardTracking(False); spin.setToolTip(title+' / Hz')
            spin.setValue(self.config[key]); spin.valueChanged.connect(lambda value, key=key: self.set_fit_limit(key, value))
            self.fit_limits[key] = spin; self.toolbar.addWidget(spin)
        self.toolbar.addStretch()
        layout.addWidget(self.chart, 1)
        self.note = W.QLabel('Select coefficients to preview the microphone response.'); self.note.setStyleSheet('color:#849eb1;font-size:10px;padding:3px;'); layout.addWidget(self.note)
        self.interaction = PlotInteraction(self)
        self.chart.canvas.mpl_connect('draw_event', self.capture)
        self.chart.canvas.mpl_connect('resize_event', self.resize_chart)
        self.chart.canvas.setContextMenuPolicy(C.Qt.CustomContextMenu)
        self.chart.canvas.customContextMenuRequested.connect(self.context)
        self.chart.fig.add_subplot().set_axis_off(); self.chart.done()

    def set_fit_limit(self, key, value):
        self.sync(); self.config[key] = value; self.reset()

    def toggle_fit(self, value):
        self.sync(); self.config['fit'] = value; self.reset()

    def context(self, point):
        menu = W.QMenu(self)
        menu.addAction('Add overlay', self.add_overlay); menu.addAction('Overlays…', self.overlays)
        menu.addSeparator(); menu.addAction('Plot settings…', self.settings); menu.addAction('Reset axes', self.reset)
        menu.exec(self.chart.canvas.mapToGlobal(point))

    def sync(self):
        options = self.workspace.config.setdefault('response_options', deepcopy(RESPONSE_DEFAULT))
        for key, value in RESPONSE_DEFAULT.items(): options.setdefault(key, deepcopy(value))
        self.config = options
        for key, spin in self.fit_limits.items():
            spin.blockSignals(True); spin.setValue(options[key]); spin.blockSignals(False)
        self.fit_toggle.blockSignals(True); self.fit_toggle.setChecked(options['fit']); self.fit_toggle.blockSignals(False)

    def reset(self):
        self.key = None; self.interaction.saved.clear()
        if self.latest: self.update_response(*self.latest)

    def resize_chart(self, *_):
        self.background = None
        fig = self.chart.fig; fig.set_layout_engine(None)
        width, height = fig.bbox.width, fig.bbox.height
        fig.subplots_adjust(left=min(.22, 70/max(width, 1)), right=1-min(.25, 76/max(width, 1)),
                            bottom=min(.25, 52/max(height, 1)), top=.97)
        self.interaction.layout_phase()

    def capture(self, *_):
        if not self.artists: return
        self.chart.fig.set_layout_engine(None)
        self.background = self.chart.canvas.copy_from_bbox(self.chart.fig.bbox); self.blit()

    def blit(self):
        self.chart.canvas.restore_region(self.background)
        for artist in self.artists:
            if artist.get_visible(): artist.axes.draw_artist(artist)
        self.chart.canvas.blit(self.chart.fig.bbox)

    def update_response(self, frequencies, magnitude, phase, label, source):
        auto_range = bool(self.latest and label != self.latest[3])
        if auto_range: self.interaction.saved.clear()
        self.sync(); self.latest = (frequencies, magnitude, phase, label, source)
        c = self.config
        traces = [('Selected mic', frequencies, magnitude, phase)]
        for overlay in c['overlays']:
            if overlay.get('visible', True):
                traces.append((overlay['name'], np.asarray(overlay['freqs']), np.asarray(overlay['mag']), np.asarray(overlay['phase'])))
        values = []
        for name, f, mag, ph in traces:
            phase_values = ph if c['wrapped'] else np.rad2deg(np.unwrap(np.deg2rad(ph)))
            px, py = phase_trace(f, phase_values, c['wrapped'])
            values.append((name, f, mag, px, py))
        key = (source, frequencies[0], frequencies[-1], len(frequencies), c['wrapped'],
               tuple(v[0] for v in values), c['fit'], c['fit_curve'], c['fit_low'], c['fit_high'])
        rebuild = key != self.key
        fig = self.chart.fig
        if rebuild:
            self.artists = []; self.background = None; self.interaction.begin(key)
            fig.clear(); fig.set_layout_engine(None)
            self.ax = fig.add_subplot(); self.phase_ax = fig.add_axes(self.ax.get_position(), sharex=self.ax, frameon=False)
            self.phase_ax.set_in_layout(False); self.phase_ax.patch.set_visible(False); self.phase_ax.xaxis.set_visible(False)
            self.phase_ax.yaxis.tick_right(); self.phase_ax.yaxis.set_label_position('right')
            for spine in self.phase_ax.spines.values(): spine.set_visible(False)
            self.phase_ax.tick_params(axis='y', colors='#baacf8', labelsize=8)
            self.phase_ax.set_ylabel('Total phase / °', color='#baacf8', fontsize=8); self.phase_ax.yaxis.set_major_locator(MaxNLocator(5))
            style(self.ax, '', ylabel='Level / dB + FRD offset')
            self.lines = []
            colors = ['#47d7ec', '#ffba68', '#7ae2b1', '#fa7b95', '#80baff']
            for i, (name, f, mag, px, py) in enumerate(values):
                color = colors[i % len(colors)]
                line, = self.ax.plot(f, mag, color=color, lw=1.3, label=name)
                phase_line, = self.phase_ax.plot(px, py, color='#baacf8' if i == 0 else color, alpha=.8, lw=.85)
                self.lines.append((line, phase_line)); self.artists.extend([line, phase_line])
            self.ax.legend(fontsize=7, loc='lower left' if c['fit'] else 'upper right')
            self.fit_line, = self.ax.plot([], [], '--', color='#f3e69b', lw=1.6)
            self.fit_text = self.ax.text(.02, .97, '', transform=self.ax.transAxes, va='top', fontsize=8, color='#f3e69b',
                                         bbox=dict(facecolor='#101c28', alpha=.85, edgecolor='none'))
            self.artists.extend([self.fit_line, self.fit_text])
            a = self.phase_ax.transAxes + ScaledTranslation(5/72, 7/72, fig.dpi_scale_trans)
            b = self.phase_ax.transAxes + ScaledTranslation(33/72, 7/72, fig.dpi_scale_trans)
            self.phase_ax.add_artist(ConnectionPatch((1, 1), (1, 1), coordsA=a, coordsB=b, color='#baacf8', linewidth=2.5, clip_on=False))
            self.phase_ax.text(1, 1, '↕ phase', transform=self.phase_ax.transAxes+ScaledTranslation(5/72, 12/72, fig.dpi_scale_trans),
                               color='#baacf8', ha='left', va='bottom', fontsize=8, clip_on=False)
            self.ax.set_xlim(frequencies[0], frequencies[-1]); self.ax.set_xticks(audio_ticks(frequencies[0], frequencies[-1]))
            self.ax.xaxis.set_major_formatter(FuncFormatter(lambda value, _: audio_frequency(value)))
            self.phase_ax.set_ylim(-180, 180) if c['wrapped'] else self.phase_ax.autoscale_view()
            if c['wrapped']: self.phase_ax.set_yticks([-180, -90, 0, 90, 180])
            self.interaction.finish([self.ax, self.phase_ax], self.phase_ax)
            self.resize_chart()
            for artist in self.artists: artist.set_animated(True)
            self.key = key
        needs_draw = rebuild
        for (line, phase_line), (_, f, mag, px, py) in zip(self.lines, values):
            line.set_data(f, mag); phase_line.set_data(px, py)
        for index, ax in enumerate([self.ax, self.phase_ax]):
            if index in self.interaction.saved or (index == 1 and c['wrapped']): continue
            data = np.concatenate([v[2 if index == 0 else 4] for v in values]); low, high = float(np.min(data)), float(np.max(data))
            padding = max(1., (high-low)*.05); low -= padding; high += padding
            if index == 0: high = float(np.max(data)) + 6.; low = high - 40.
            old_low, old_high = ax.get_ylim()
            if index == 0 or rebuild or auto_range or low < old_low or high > old_high:
                ax.set_ylim(low if index == 0 or rebuild or auto_range else min(low, old_low), high if index == 0 or rebuild or auto_range else max(high, old_high)); needs_draw = True
                self.interaction.full[index] = (ax.get_xlim(), ax.get_ylim())
        if not c['auto_axes'] and 0 not in self.interaction.saved:
            self.ax.set_xlim(c['fmin'], c['fmax']); self.ax.set_ylim(c['ymin'], c['ymax']); needs_draw = True
        if not c['phase_auto'] and 1 not in self.interaction.saved:
            self.phase_ax.set_ylim(c['phase_min'], c['phase_max']); self.phase_ax.yaxis.set_major_locator(MaxNLocator(5)); needs_draw = True
        if not c['auto_axes'] or not c['phase_auto']:
            for index, axis in enumerate([self.ax, self.phase_ax]):
                if index not in self.interaction.saved: self.interaction.full[index] = (axis.get_xlim(), axis.get_ylim())
        self.fit_result = None; self.fit_line.set_visible(c['fit']); self.fit_text.set_visible(c['fit'])
        if c['fit']:
            selected = next((v for v in values if v[0] == c['fit_curve']), values[0])
            try:
                fit = trend_fit(selected[1], selected[2], c['fit_low'], c['fit_high']); self.fit_result = fit
                self.fit_line.set_data(fit['freqs'], fit['line'])
                self.fit_text.set_text(f'{selected[0]}: {fit["slope"]:+.2f} dB/oct · ±{fit["deviation"]:.2f} dB max\n'
                                       f'{audio_frequency(fit["low"])}–{audio_frequency(fit["high"])} Hz · RMS {fit["rms"]:.2f} dB')
            except ValueError as exc: self.fit_line.set_visible(False); self.fit_text.set_text(str(exc))
        self.note.setText(label+' · Total phase · drag the purple handle to resize its axis')
        if not needs_draw and self.background is not None: self.blit()
        else: self.background = None; self.chart.done()

    def add_overlay(self):
        if not self.latest: return
        self.sync(); f, mag, phase, label, _ = self.latest
        name, ok = W.QInputDialog.getText(self, 'Add overlay', 'Name', text=label)
        if not ok or not name.strip(): return
        base = name.strip(); existing = {o['name'] for o in self.config['overlays']} | {'Selected mic'}; name = base; n = 2
        while name in existing: name = f'{base} ({n})'; n += 1
        self.config['overlays'].append(dict(name=name, freqs=np.asarray(f).tolist(), mag=np.asarray(mag).tolist(), phase=np.asarray(phase).tolist(), visible=True))
        self.reset()

    def overlays(self):
        self.sync(); dialog = W.QDialog(self); dialog.setWindowTitle('Response overlays'); box = W.QVBoxLayout(dialog)
        for overlay in self.config['overlays']:
            check = W.QCheckBox(overlay['name']); check.setChecked(overlay.get('visible', True))
            check.toggled.connect(lambda value, item=overlay: item.update(visible=value)); box.addWidget(check)
        clear = W.QPushButton('Clear overlays'); clear.clicked.connect(lambda: (self.config['overlays'].clear(), dialog.accept())); box.addWidget(clear)
        close = W.QPushButton('Close'); close.clicked.connect(dialog.accept); box.addWidget(close)
        dialog.exec(); self.reset()

    def settings(self):
        self.sync(); dialog = W.QDialog(self); dialog.setWindowTitle('SPL + total phase settings'); form = W.QFormLayout(dialog)
        wrapped = W.QCheckBox(); wrapped.setChecked(self.config['wrapped']); form.addRow('Wrapped phase', wrapped)
        fit = W.QCheckBox(); fit.setChecked(self.config['fit']); form.addRow('Fit line', fit)
        curve = W.QComboBox(); curve.addItems(['Selected mic']+[o['name'] for o in self.config['overlays']]); curve.setCurrentText(self.config['fit_curve']); form.addRow('Fit response', curve)
        low, high = W.QDoubleSpinBox(), W.QDoubleSpinBox()
        for widget, key, label in [(low, 'fit_low', 'Fit from / Hz'), (high, 'fit_high', 'Fit to / Hz')]:
            widget.setRange(.1, 100000); widget.setValue(self.config[key]); form.addRow(label, widget)
        # Use the Analysis schema and editors so labels, units and limits stay identical.
        from panes import SPECS, editor
        axis_values = {key: self.config[key] for key in ('auto_axes', 'fmin', 'fmax', 'ymin', 'ymax', 'phase_auto', 'phase_min', 'phase_max')}
        axis_controls = {}
        def axis_changed(key, value):
            axis_values[key] = value
            manual = 'auto_axes' if key in ('fmin', 'fmax', 'ymin', 'ymax') else 'phase_auto' if key in ('phase_min', 'phase_max') else None
            if manual:
                axis_values[manual] = False
                axis_controls[manual].setChecked(False)
        for key, value in axis_values.items():
            axis_controls[key] = editor(key, value, lambda value, key=key: axis_changed(key, value))
            form.addRow(SPECS[key][0], axis_controls[key])
        actions = W.QDialogButtonBox(W.QDialogButtonBox.Ok | W.QDialogButtonBox.Cancel); form.addRow(actions)
        actions.accepted.connect(dialog.accept); actions.rejected.connect(dialog.reject)
        if dialog.exec() == W.QDialog.Accepted:
            if axis_values['fmin'] >= axis_values['fmax'] or axis_values['ymin'] >= axis_values['ymax'] or axis_values['phase_min'] >= axis_values['phase_max']:
                W.QMessageBox.warning(self, 'Axis limits', 'Each maximum must exceed its minimum.'); return
            self.config.update(axis_values)
            self.config.update(wrapped=wrapped.isChecked(), fit=fit.isChecked(), fit_low=low.value(), fit_high=high.value(), fit_curve=curve.currentText()); self.reset()


class ImpulsePanel(W.QWidget):
    def __init__(self, show_toolbar=True):
        super().__init__(); self.config = {}; self.last_render = None; self.chart = Chart(); self.key = None
        layout = W.QVBoxLayout(self); layout.setContentsMargins(5, 5, 5, 5)
        row = W.QHBoxLayout(); layout.addLayout(row); row.addWidget(W.QLabel('IMPULSE RESPONSE / PROPAGATION TIMING')); row.addStretch()
        button = W.QPushButton('Reset axes'); button.clicked.connect(lambda: self.interaction.reset()); row.addWidget(button)
        gear = W.QToolButton(); button.setFixedHeight(32); gear.setFixedHeight(32); gear.setText('\u2699'); gear.clicked.connect(self.settings); row.addWidget(gear)
        if not show_toolbar:
            for index in range(row.count()):
                widget = row.itemAt(index).widget()
                if widget is not None: widget.hide()
        layout.addWidget(self.chart, 1); self.interaction = PlotInteraction(self)
        self.chart.fig.add_subplot().set_axis_off(); self.chart.done()

    def settings(self):
        if not hasattr(self, 'ax'): return
        dialog = W.QDialog(self); dialog.setWindowTitle('IR axis ranges'); form = W.QFormLayout(dialog)
        fields = []
        for title, value in zip(['Time minimum / ms', 'Time maximum / ms', 'Amplitude minimum', 'Amplitude maximum'], [*self.ax.get_xlim(), *self.ax.get_ylim()]):
            field = W.QDoubleSpinBox(); field.setRange(-1e9, 1e9); field.setDecimals(4); field.setValue(value)
            fields.append(field); form.addRow(title, field)
        buttons = W.QDialogButtonBox(W.QDialogButtonBox.Ok | W.QDialogButtonBox.Cancel); form.addRow(buttons)
        buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject)
        if dialog.exec() == W.QDialog.Accepted:
            x0, x1, y0, y1 = [f.value() for f in fields]
            if x0 >= x1 or y0 >= y1:
                W.QMessageBox.warning(self, 'Axis ranges', 'Each maximum must exceed its minimum.'); return
            self.ax.set_xlim(x0, x1); self.ax.set_ylim(y0, y1)
            self.interaction.saved[0] = ((x0, x1), (y0, y1)); self.chart.done()

    def update_ir(self, times, ir, delay, source):
        key = (source, len(ir), times[-1], delay is not None)
        rebuild = key != self.key
        if rebuild:
            self.chart.fig.clear(); self.chart.fig.set_layout_engine('constrained'); self.ax = self.chart.fig.add_subplot()
            self.line, = self.ax.plot([], [], color='#7ae2b1', lw=.9)
            self.marker = self.ax.axvline(0, color='#ffba68', ls='--', lw=1)
            style(self.ax, '', xlabel='Time / ms', ylabel='Normalized amplitude'); self.ax.set_ylim(-1.05, 1.05)
            self.interaction.begin(key); self.key = key
        peak = np.max(abs(ir)); self.line.set_data(times*1000, ir/peak if peak else ir)
        self.marker.set_visible(delay is not None)
        if delay is not None:
            self.marker.set_xdata([delay*1000]*2); self.marker.set_label(f'FRD t=0 · {delay*1000:.3f} ms'); self.ax.legend(fontsize=7)
        end = min(times[-1]*1000, max(20., times[int(np.argmax(abs(ir)))]*1000+10, (delay or 0)*1000+10))
        if rebuild or not self.interaction.saved: self.ax.set_xlim(0, end)
        if rebuild: self.interaction.finish([self.ax])
        elif not self.interaction.saved: self.interaction.full[0] = (self.ax.get_xlim(), self.ax.get_ylim())
        self.chart.done()
