"""Cursor readout for a selected SPL trace, with legend selection."""
import numpy as np


def add_frequency_cursor(ax, frequency, *, visible=True):
    """One cursor style for all response plots."""
    return ax.axvline(frequency, color='#7db0c0', alpha=.35, lw=.8,
                      gid='frequency-cursor', visible=visible)


class SPLCursor:
    def __init__(self, pane, label, frequency_provider=None):
        self.pane, self.label = pane, label
        self.frequency_provider = frequency_provider
        self.active = None; self.frequency = None; self.lines = {}; self.phase = {}; self.ax = None
        self.selection_changed = None
        canvas = pane.chart.canvas
        canvas.mpl_connect('button_press_event', self.press)

    def clear(self):
        self.lines = {}; self.phase = {}; self.ax = None
        self.label.clear(); self.label.hide()

    def bind(self, ax, phase_ax=None, di_ax=None):
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
