"""Cursor readout for a selected SPL trace, with legend selection."""
import numpy as np


def add_frequency_cursor(ax, frequency, *, visible=True):
    """One visible frequency cursor style across response plots and sonograms."""
    return ax.axvline(frequency, color='#ffffff', alpha=1., lw=1.5, zorder=20,
                      gid='frequency-cursor', visible=visible)


class SPLCursor:
    def __init__(self, pane, label, frequency_provider=None):
        self.pane, self.label = pane, label
        self.frequency_provider = frequency_provider
        self.active = None; self.frequency = None; self.lines = {}; self.phase = {}; self.ax = None
        self.selection_changed = None
        self.beam_data = None
        self.marker = None; self.background = None
        canvas = pane.chart.canvas
        canvas.mpl_connect('button_press_event', self.press)
        canvas.mpl_connect('draw_event', self.capture_background)

    def clear(self):
        if self.marker is not None: self.marker.set_animated(False)
        self.marker = None; self.background = None
        if hasattr(self.pane, 'header'): self.pane.header.set_readout_expanded(False)
        self.beam_data = None
        self.lines = {}; self.phase = {}; self.ax = None
        self.label.clear(); self.label.hide()

    def bind_marker(self, marker):
        canvas = self.pane.chart.canvas
        if canvas.supports_blit is not True: return
        self.marker = marker; self.background = None
        marker.set_animated(True)

    def capture_background(self, event):
        if self.marker is None: return
        canvas = self.pane.chart.canvas
        if canvas.is_saving():
            self.background = None
            return
        self.background = canvas.copy_from_bbox(self.marker.axes.bbox)
        self.marker.axes.draw_artist(self.marker)
        canvas.blit(self.marker.axes.bbox)

    def move_marker(self, frequency):
        marker = self.pane.frequency_marker
        marker.set_xdata([frequency, frequency])
        self.follow_marker()
        canvas = self.pane.chart.canvas
        if marker is self.marker and self.background is not None:
            canvas.restore_region(self.background)
            marker.axes.draw_artist(marker)
            canvas.blit(marker.axes.bbox)
        else:
            canvas.draw_idle()

    def bind_beamwidth(self, ax, frequencies, angles, values, threshold=-6.):
        self.beam_threshold = threshold
        self.ax = ax
        self.lines = {}; self.phase = {}
        self.beam_data = (np.asarray(frequencies), np.asarray(angles), np.asarray(values))
        self.label.setToolTip(
            f"{threshold:g} dB relative to the strongest peak within -90° to +90° "
            "in this plot's plane at the cursor frequency, independent of normalization. Crossings "
            "on each side may extend beyond ±90° and are interpolated in dB; full-circle cuts wrap at the seam. "
            "Other lobes do not prevent a width reading. Missing crossings show the "
            "available half-angle limit using the same +/- convention as measured widths."
        )
        self.label.show()
        self.follow_marker()

    def bind(self, ax, phase_ax=None, di_ax=None):
        self.beam_data = None
        self.label.setToolTip('')
        self.ax = ax
        self.lines = {line.get_label(): line for line in ax.lines
                      if not line.get_label().startswith(('_', 'Fit')) and 'phase' not in line.get_label().lower()}
        if di_ax is not None and di_ax is not ax:
            self.lines.update({line.get_label(): line for line in di_ax.lines
                               if not line.get_label().startswith('_')})
        self.phase = {}
        if phase_ax is not None and phase_ax is not ax:
            for line in phase_ax.lines:
                name = line.get_label()
                for key in self.lines:
                    source = 'Reference' if key == 'Reference axis' else key
                    if name in tuple(label+suffix for label in (source, key)
                                     for suffix in (' total phase', ' minimum phase', ' phase')):
                        self.phase[key] = line
        if self.active not in self.lines: self.active = next(iter(self.lines), None)
        self.label.setVisible(bool(self.lines))
        self.highlight()
        self.follow_marker()

    def follow_marker(self):
        if self.frequency_provider is None:
            owner = self.pane.owner
            frequency = float(owner.sphere.freqs[owner.frequency.value()])
        else:
            frequency = self.frequency_provider()
        if frequency is None: self.label.clear()
        else: self.readout(frequency)

    def highlight(self):
        if self.ax is None: return
        legend = self.ax.get_legend()
        if legend is None: return
        for text in legend.get_texts():
            text.set_bbox(dict(boxstyle='round,pad=0.25', facecolor='none', edgecolor=text.get_color(), alpha=.35, linewidth=.8)
                          if text.get_text() == self.active else None)

    def press(self, event):
        if not event.dblclick or event.button != 1 or self.ax is None: return
        legend = self.ax.get_legend()
        if legend is None: return
        handles = getattr(legend, 'legend_handles', [])
        for index, text in enumerate(legend.get_texts()):
            hit = text.contains(event)[0] or (index < len(handles) and handles[index].contains(event)[0])
            if hit and text.get_text() in self.lines:
                self.active = text.get_text(); self.highlight()
                if self.selection_changed is not None:
                    self.selection_changed()
                    return
                self.follow_marker()
                self.pane.chart.canvas.draw_idle(); return

    def readout(self, frequency):
        if self.beam_data is not None:
            from hals_studio.analysis.acoustics import forward_beamwidth

            f, angles, values = self.beam_data
            if not len(f) or frequency < f[0] or frequency > f[-1]:
                self.label.clear()
                return
            index = int(np.argmin(abs(f-frequency)))
            status, left, right = forward_beamwidth(angles, values[index], self.beam_threshold)
            text = (f'+/-{(right-left)/2:.0f}\N{DEGREE SIGN}'
                    if status == 'ok' else f'>+/-{float(status[1:])/2:.0f}\N{DEGREE SIGN}'
                    if status.startswith('>') else status)
            self.label.setText(f'{f[index]:.0f} Hz Beam Width ({self.beam_threshold:g}dB): {text}')
            self.frequency = float(f[index])
            return
        line = self.lines.get(self.active)
        if line is None: return
        f, values = np.asarray(line.get_xdata()), np.asarray(line.get_ydata())
        valid = np.isfinite(f) & np.isfinite(values) & (f > 0)
        f, values = f[valid], values[valid]
        if not len(f) or frequency < f[0] or frequency > f[-1]: self.label.clear(); return
        # Read actual samples rather than inventing interpolated phase near wraps.
        index = int(np.argmin(abs(f-frequency))); hz = f[index]
        self.frequency = float(frequency)
        text = f'{hz:.0f} Hz, {values[index]:.1f} dB'
        phase = self.phase.get(self.active)
        if phase is not None:
            pf, pv = np.asarray(phase.get_xdata()), np.asarray(phase.get_ydata())
            if len(pf) and pf[0] <= hz <= pf[-1]:
                value = pv[int(np.argmin(abs(pf-hz)))]
                if np.isfinite(value): text += f', {value:.1f}\N{DEGREE SIGN}'
        self.label.setText(text)
