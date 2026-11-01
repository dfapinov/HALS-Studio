"""Relative coefficient power by spherical harmonic degree and source field."""
import numpy as np


class PowerLegend:
    """Clickable checkbox labels; visibility never changes the calculated total."""
    def __init__(self, fig, hidden):
        from matplotlib.legend_handler import HandlerBase
        from matplotlib.lines import Line2D
        from matplotlib.patches import FancyBboxPatch
        from hals_studio.ui.viewer_theme import colour

        boxes = {}
        class CheckboxHandle(HandlerBase):
            def create_artists(self, legend, original, xd, yd, width, height, fontsize, transform):
                size = fontsize*.8
                box = FancyBboxPatch((-xd, (height-size)/2-yd), size, size,
                                     boxstyle='round,pad=0,rounding_size=1',
                                     linewidth=.8, transform=transform)
                stroke = Line2D([size+4-xd, width-xd], [height/2-yd]*2)
                self.update_prop(stroke, original, legend)
                stroke.set_transform(transform)
                boxes[original] = box
                return [stroke, box]

        self.fig = fig
        self.hidden = hidden
        self.lines = list(fig.axes[0].lines)
        label_colour = fig.axes[0].get_legend().texts[0].get_color()
        self.legend = fig.axes[0].legend(handles=self.lines, loc='lower left',
            bbox_to_anchor=(0, 1.07, 1, .1), mode='expand',
            ncol=min(7, len(self.lines)), fontsize=8, frameon=False,
            handlelength=3.5, handler_map={line: CheckboxHandle() for line in self.lines})
        self.boxes = [boxes[line] for line in self.lines]
        self.selected_colour = '#599bda'
        self.border_colour = colour('#91e5f1')
        self.empty_colour = colour('#466074')
        self.legend.set_draggable(False)
        self.artists = {}
        for i, (text, handle) in enumerate(zip(self.legend.texts, self.legend.legend_handles)):
            text.set_color(label_colour)
            text.set_picker(True); handle.set_picker(6)
            self.artists[text] = self.artists[handle] = i
            self.boxes[i].set_picker(True)
            self.artists[self.boxes[i]] = i
        self.refresh()
        self.connection = fig.canvas.mpl_connect('pick_event', self.pick)

    def refresh(self):
        for i, (line, text, handle) in enumerate(zip(self.lines, self.legend.texts, self.legend.legend_handles)):
            visible = i not in self.hidden
            line.set_visible(visible)
            text.set_text(line.get_label())
            self.boxes[i].set_facecolor(self.selected_colour if visible else 'none')
            self.boxes[i].set_edgecolor(self.border_colour if visible else self.empty_colour)
            text.set_alpha(1. if visible else .45)
            handle.set_alpha(1. if visible else .25)

    def pick(self, event):
        if event.artist not in self.artists or event.mouseevent.button != 1:
            return
        index = self.artists[event.artist]
        if event.mouseevent.key == 'shift':
            self.hidden.clear()
            self.hidden.update(i for i in range(len(self.lines)) if i != index)
        elif index in self.hidden:
            self.hidden.remove(index)
        else:
            self.hidden.add(index)
        self.refresh()
        self.fig.canvas.draw_idle()


def degree_power(freqs, coeffs, orders, speed=343.0, *, field='Internal field'):
    """Return relative power, summed over m, for C or D coefficients.

    Orthonormal Y_nm and h_n^(2)(kr) give integral |p|² r² dΩ =
    sum |C_nm|² / k². The common acoustic impedance and absolute pressure
    calibration are omitted: saved coefficients use the measurement scale.
    Apply the same 1/k² scaling to external D coefficients for comparison,
    consistent with the C/D coefficient-power ratio used in Stage 3.
    External modal power is not net radiated power: the regular j_n field
    contains both incoming and outgoing components.
    Degrees not included in a frequency's solve are zero, not padded modes.
    """
    freqs = np.asarray(freqs, float)
    orders = np.asarray(orders, int)
    if not np.isfinite(speed) or speed <= 0:
        raise ValueError('Speed of sound must be positive and finite.')
    if field not in ('Internal field', 'External field'):
        raise ValueError('Unknown sound power field.')
    power = np.zeros((len(freqs), int(orders.max()) + 1))
    for i, (freq, order) in enumerate(zip(freqs, orders)):
        if not np.isfinite(freq) or freq <= 0:
            power[i] = np.nan
            continue
        count = (order+1)**2
        row = np.asarray(coeffs[i])[:2*count]
        outgoing, external = row[::2], row[1::2]
        selected = outgoing if field == 'Internal field' else external
        if len(row) != 2*count or not np.isfinite(selected).all():
            power[i] = np.nan
            continue
        k = 2*np.pi*freq/speed
        modes = np.abs(selected)**2 / k**2
        for degree in range(order+1):
            power[i, degree] = modes[degree**2:(degree+1)**2].sum()
    return power


def sound_power_figure(path, field='Internal field'):
    from hals_studio.process_engine.utils import load_she_h5
    from matplotlib.figure import Figure
    from matplotlib.ticker import FuncFormatter
    from hals_studio.ui.plotting.plots import audio_frequency, audio_ticks
    from hals_studio.ui.viewer_theme import colour

    data = load_she_h5(path)
    freqs = np.asarray(data['freqs'])
    speed = data.get('speed_of_sound_mps')
    speed = 343.0 if speed is None else float(speed)
    internal_power = degree_power(freqs, data['coeffs'], data['N_used'], speed,
                                  field='Internal field')
    power = (internal_power if field == 'Internal field' else
             degree_power(freqs, data['coeffs'], data['N_used'], speed, field=field))
    valid = np.isfinite(freqs) & (freqs > 0)
    freqs, power = freqs[valid], power[valid]
    if not len(freqs):
        raise ValueError('No positive frequencies available for sound power.')
    def levels(values):
        with np.errstate(divide='ignore', invalid='ignore'):
            return np.where(values > 0, 10*np.log10(values), np.nan)
    fig = Figure(figsize=(12, 7), layout='constrained')
    ax = fig.subplots()
    ax.semilogx(freqs, levels(power.sum(axis=1)), color=colour('#47d7ec'),
                linewidth=2.8, label='Total sound power' if field=='Internal field' else 'Total modal power', zorder=10)
    palette = ['#ffba68', '#baacf8', '#7ae2b1', '#fa7b95', '#f3e69b',
               '#80baff', '#df9dd3', '#aec7d4']
    for degree in range(power.shape[1]):
        ax.plot(freqs, levels(power[:, degree]), color=colour(palette[degree % len(palette)]),
                linestyle=['-', '--', '-.', ':'][(degree // len(palette)) % 4],
                linewidth=1.1, label=f'N={degree}')
    ax.set(title=f'Sound Power vs Harmonic Degree — {field}', xlabel='Frequency (Hz)',
           ylabel='Sound power (relative dB)' if field=='Internal field' else 'Modal power (relative dB)')
    # Keep both field views on the internal field's measurement-level range.
    total_levels = levels(internal_power[valid].sum(axis=1))
    finite = total_levels[np.isfinite(total_levels)]
    if len(finite):
        top = 10*np.ceil((finite.max()+3)/10)
        ax.set_ylim(top-100, top)
    ax.set_xticks(audio_ticks(freqs.min(), freqs.max()))
    ax.xaxis.set_major_formatter(FuncFormatter(lambda value, pos: audio_frequency(value)))
    if freqs.max() > freqs.min(): ax.set_xlim(freqs.min(), freqs.max())
    ax.grid(True, which='major', alpha=.45)
    ax.grid(True, which='minor', alpha=.15)
    ax.legend(loc='lower left', bbox_to_anchor=(0, 1.07, 1, .1), mode='expand',
              ncol=min(7, power.shape[1]+1), fontsize=8, frameon=False)
    note = ('Outgoing coefficient power • Measurement level scale' if field=='Internal field' else
            'External coefficient power • Same scaling as internal • Measurement level scale')
    fig.supxlabel(note, fontsize=8)
    return fig
