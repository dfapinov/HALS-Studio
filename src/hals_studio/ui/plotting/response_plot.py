"""Magnitude/phase composition and trend annotations for a HALS Studio pane."""
import numpy as np
from matplotlib.ticker import FuncFormatter, MaxNLocator
from matplotlib.transforms import ScaledTranslation
import hals_studio.analysis.acoustics as ac
from hals_studio.analysis.analysis_metrics import minimum_phase, trend_fit
from hals_studio.ui.plotting.plots import style, response_directions, audio_ticks, audio_frequency
from hals_studio.ui.plotting.trace_legend import trace_legend
from hals_studio.ui.plotting.spl_cursor import add_frequency_cursor


def phase_values(freqs, pressure, mode, wrapped, delay):
    if mode == 'Minimum phase':
        values = minimum_phase(freqs, np.abs(pressure))
    else:
        values = np.rad2deg(np.unwrap(np.angle(pressure*np.exp(2j*np.pi*freqs*delay/1000))))
    return (values+180)%360-180 if wrapped else values


def phase_trace(freqs, values, wrapped):
    """Insert explicit vertical wrap segments at interpolated crossing frequencies."""
    if not wrapped: return freqs, values
    x, y = [], []
    for j, (freq, value) in enumerate(zip(freqs, values)):
        if j and abs(value-values[j-1]) > 180:
            previous = values[j-1]; delta = (value-previous+180)%360-180
            edge = 180. if delta > 0 else -180.
            fraction = np.clip((edge-previous)/delta, 0, 1) if abs(delta) > 1e-12 else .5
            crossing = np.exp(np.log(freqs[j-1])+fraction*np.log(freq/freqs[j-1]))
            x.extend([crossing, crossing]); y.extend([edge, -edge])
        x.append(freq); y.append(value)
    return np.asarray(x), np.asarray(y)


def _one_magnitude(pane, s, levels, config=None):
    c, o = pane.config if config is None else config, pane.owner
    kind = c['kind']
    ylabel, note = 'HALS level / dB + offset', ''
    if kind == 'probe': curves = {'Probe': levels[:, *s.index(o.azimuth.value(), o.elevation.value())]}
    elif kind == 'reference': curves = {'Reference axis': levels[:, *s.index(*o.axis)]}
    elif kind == 'di':
        curves = {'Sound power DI': levels[:, *s.index(*o.axis)]-s.metrics(levels)['sphere_average']}
        ylabel = 'Directivity index / dB'
    elif kind in ('phase', 'minimum'): return {}, 'Phase / degrees', ''
    elif kind.startswith('sweep_'):
        plane = 'Horizontal' if kind == 'sweep_h' else 'Vertical'
        curves = {f'{plane[0]} {name}': levels[:, *direction] for direction, name in
                  response_directions(s, plane, c['extent'], c['step'], c['symmetric'], c.get('sweep_direction'))}
        note = 'Sweep angles use nearest sphere samples about +X.'
    else:
        metrics = o.get_cea(c['smoothing'])
        from hals_studio.ui.plotting.plot_settings import cta_curve_names
        names = cta_curve_names(kind, c['breakout'])
        curves = {n: metrics[n] for n in names}
        if all(n.endswith('DI') for n in names): ylabel = 'Directivity index / dB'
        note = f'CEA2034-derived · reference H {o.axis[0]:g}° / V {o.axis[1]:g}° · interpolated energy'
    offset = 0 if ylabel == 'Directivity index / dB' else c['offset']
    return {name: values+(0 if name.endswith('DI') else offset) for name, values in curves.items()}, ylabel, note


def magnitude_curves(pane, s, levels, config=None):
    from hals_studio.ui.plotting.plot_settings import selected_magnitudes
    c = pane.config if config is None else config
    curves, labels, notes = {}, [], []
    for kind in selected_magnitudes(c):
        values, label, note = _one_magnitude(pane, s, levels, dict(c, kind=kind))
        curves.update(values)
        if label not in labels: labels.append(label)
        if note and note not in notes: notes.append(note)
    ylabel = labels[0] if len(labels) == 1 else 'Magnitude / DI / dB' if labels else 'Level / dB'
    return curves, ylabel, ' · '.join(notes)


def response_axis(ax, label, colour, *, separate=True):
    """Create/style the shared phase or DI axis."""
    axis = ax
    if separate:
        axis = ax.figure.add_axes(ax.get_position(), sharex=ax, frameon=False)
        axis.set_in_layout(False); axis.patch.set_visible(False)
        axis.xaxis.set_visible(False); axis.yaxis.tick_right(); axis.yaxis.set_label_position('right')
        for edge in ('top', 'left', 'bottom'): axis.spines[edge].set_visible(False)
    axis.tick_params(axis='y', colors=colour, labelsize=8)
    axis._response_axis_colour = colour
    axis.set_ylabel(label, color=colour, fontsize=8)
    axis.yaxis.set_major_locator(MaxNLocator(5))
    return axis


def response_axis_handle(axis, label):
    """The same draggable height handle for phase and DI in both workspaces."""
    from matplotlib.patches import ConnectionPatch
    colour = axis._response_axis_colour
    scale = axis.figure.dpi_scale_trans
    start = axis.transAxes + ScaledTranslation(5/72, 7/72, scale)
    end = axis.transAxes + ScaledTranslation(33/72, 7/72, scale)
    handle = ConnectionPatch((1, 1), (1, 1), coordsA=start, coordsB=end,
                             color=colour, linewidth=2.5, clip_on=False, annotation_clip=False)
    axis.add_artist(handle)
    axis.text(1, 1, label, transform=axis.transAxes + ScaledTranslation(5/72, 12/72, scale),
              ha='left', va='bottom', color=colour, fontsize=8, clip_on=False)
    return handle


def fit_annotation(name, fit):
    return (f'{name}: {fit["slope"]:+.2f} dB/oct \N{MIDDLE DOT} \N{PLUS-MINUS SIGN}{fit["deviation"]:.2f} dB max\n'
            f'{audio_frequency(fit["low"])}\N{EN DASH}{audio_frequency(fit["high"])} Hz \N{MIDDLE DOT} RMS {fit["rms"]:.2f} dB')


def draw_chart(pane, s, levels, rel, i):
    """Prepare Analysis data, then use the shared response renderer."""
    from hals_studio.ui.mic_calibration import config as shared_config
    from hals_studio.ui.plotting.plot_settings import GROUPS, selected_magnitudes
    c, o, kind = pane.config, pane.owner, pane.config['kind']
    if kind.startswith('map_'):
        from hals_studio.ui.plotting.directivity_views import draw_spectrogram
        fig = pane.chart.fig; fig.clear(); fig.set_layout_engine('constrained')
        ax = fig.add_subplot()
        angles, h, v = s.cuts(rel)
        image = draw_spectrogram(ax, s.freqs, angles, h if kind == 'map_h' else v, c)
        fig.colorbar(image, ax=ax, label='Relative level / dB', pad=.02)
        style(ax, '', ylabel='Angle / degrees'); ax.set_ylim(-180, 180)
        ax.set_xlim(s.freqs[0], s.freqs[-1])
        ax.set_xticks(audio_ticks(*ax.get_xlim())); ax.xaxis.set_major_formatter(FuncFormatter(lambda value, _: audio_frequency(value)))
        pane.phase_axis = pane.phase_handle = None
        pane.frequency_marker = add_frequency_cursor(ax, s.freqs[i])
        pane.interaction.finish([ax]); pane.chart.done()
        return
    curves, ylabel, note = magnitude_curves(pane, s, levels)
    selected = selected_magnitudes(c)
    phase_mode = c['phase_mode'] if kind in GROUPS['SPL & phase'] else 'None'
    if kind in ('phase', 'minimum'): phase_mode = 'Minimum phase' if kind == 'minimum' else 'Total phase'
    if any(name.endswith('DI') for name in curves): phase_mode = 'None'
    phase_traces, overlays = [], []
    if phase_mode != 'None':
        delay = pane.delay_ms()
        sample = s.index(*o.axis) if selected == ['reference'] else s.index(o.azimuth.value(), o.elevation.value())
        source = 'Reference' if selected == ['reference'] else 'Probe'
        values = phase_values(s.freqs, s.pressure[:, *sample], phase_mode, c['wrapped'], delay)
        phase_traces.append((source+' '+phase_mode.lower(), s.freqs, values))
        phase_note = 'Finite-band minimum-phase estimate; no propagation delay.' if phase_mode == 'Minimum phase' else pane.delay_note
        note = ' - '.join(part for part in (note, phase_note) if part)
    if c['overlays']:
        for overlay in o.plot_overlays(pane):
            if not overlay['visible']: continue
            frequency = np.asarray(overlay['freqs'])
            is_di = bool(overlay.get('di'))
            if 'magnitude' in overlay: values = np.asarray(overlay['magnitude'])
            else:
                raw = np.asarray(overlay['real'])+1j*np.asarray(overlay['imag'])
                values = ac.db(raw)
                if phase_mode != 'None' and ('probe' in selected or not selected):
                    phase_traces.append((overlay['name']+' phase', frequency,
                        phase_values(frequency, raw, phase_mode, c['wrapped'], delay)))
            if not is_di: values = values+c['offset']+shared_config(o)['frd_db_offset']
            overlays.append((overlay['name'], frequency, values, is_di))
    draw_response_curves(pane, s.freqs, curves, s.freqs[i], ylabel=ylabel, note=note,
                         phase_mode=phase_mode, phase_traces=phase_traces, overlays=overlays)


def draw_response_curves(pane, freqs, curves, cursor_frequency, *, ylabel='HALS level / dB + offset',
                         note='', phase_mode='None', phase_traces=(), overlays=()):
    """Render prepared curves identically in Analysis and Export, without data-owner access."""
    c = pane.config
    fig = pane.chart.fig; fig.clear(); fig.set_layout_engine('constrained'); ax = fig.add_subplot()
    pane.phase_axis = pane.phase_handle = None; pane.fit_result = None
    phase_ax = None
    pane.magnitude_curves = curves
    di_curves = {name: values for name, values in curves.items() if name.endswith('DI')}
    curves = {name: values for name, values in curves.items() if name not in di_curves}
    if di_curves: ylabel = 'HALS level / dB + offset'
    trace_colours = {}
    for title, values in curves.items():
        line, = ax.plot(freqs, values, lw=1.4, label=title)
        trace_colours[title] = line.get_color()
    # DI inherits its SPL partner's actual colour. Unpaired DI uses the
    # next unused colour from the same cycle, including DI-only plots.
    from matplotlib import rcParams
    from itertools import cycle
    palette = cycle(rcParams['axes.prop_cycle'].by_key()['color'])
    for _ in curves: next(palette)
    di_colours = {}
    for name in di_curves:
        partner = name.removesuffix(' DI')
        di_colours[name] = trace_colours[partner] if partner in trace_colours else next(palette)
    for name, frequency, values, is_di in overlays:
        if is_di:
            di_curves[name] = np.interp(freqs, frequency, values)
            di_colours[name] = next(palette)
        else:
            ax.plot(frequency, values, lw=1, alpha=.8, label=name)
    if c['fit'] and curves:
        selected = c['fit_curve'] if c['fit_curve'] in curves else next(iter(curves))
        try:
            fit = trend_fit(freqs, curves[selected], c['fit_low'], c['fit_high']); pane.fit_result = fit
            ax.plot(fit['freqs'], fit['line'], '--', lw=2., color='#f3e69b', label=f'Fit · {selected}')
            ax.text(.02, .97, fit_annotation(selected, fit),
                    transform=ax.transAxes, va='top', fontsize=8, color='#f3e69b',
                    bbox=dict(facecolor='#101c28', alpha=.85, edgecolor='none'))
        except ValueError as exc: note += ' · Fit: '+str(exc)
    style(ax, '', ylabel=ylabel)
    if di_curves: phase_mode = 'DI'
    if phase_mode != 'None':
        axis_colour = next(iter(di_colours.values())) if di_curves else '#baacf8'
        phase_ax = response_axis(ax, 'Directivity index / dB' if di_curves else 'Phase / degrees',
                                 axis_colour, separate=bool(curves))
        if di_curves:
            for name, values in di_curves.items():
                phase_ax.plot(freqs, values, lw=1.2, label=name, color=di_colours[name])
        else:
            all_values = []
            for source, frequency, values in phase_traces:
                px, py = phase_trace(frequency, values, c['wrapped'])
                phase_ax.plot(px, py, color='#baacf8' if not all_values else None,
                              lw=.85, alpha=.8, label=source)
                all_values.append(values)
        pane.phase_axis = phase_ax
        if di_curves:
            values = np.concatenate(list(di_curves.values()))
            low, high = min(0., float(np.nanmin(values))), max(0., float(np.nanmax(values)))
            padding = max(1., (high-low)*.05)
            phase_ax.set_ylim((low-padding, high+padding) if c['di_auto'] else (c['di_min'], c['di_max']))
        elif c['wrapped']:
            phase_ax.set_ylim(-180, 180); phase_ax.set_yticks([-180, -90, 0, 90, 180])
        else:
            values = np.concatenate(all_values); low, high = float(np.nanmin(values)), float(np.nanmax(values))
            padding = max(1., (high-low)*.05)
            phase_ax.set_ylim(low-padding, high+padding)
        if not di_curves and not c['phase_auto'] and c['phase_min'] < c['phase_max']:
            phase_ax.set_ylim(c['phase_min'], c['phase_max']); phase_ax.yaxis.set_major_locator(MaxNLocator(5))
        if curves:
            pane.phase_handle = response_axis_handle(phase_ax, 'dB' if di_curves else 'Phase')
    elif not curves:
        ax.text(.5, .5, 'Select magnitude responses or a phase plot from the plot menu.',
                transform=ax.transAxes, ha='center', va='center', fontsize=9, color='#91aabe', wrap=True)
    trace_legend(ax, [phase_ax] if phase_ax is not None else [])
    pane.frequency_marker = add_frequency_cursor(ax, cursor_frequency)
    ax.set_xlim(freqs[0], 20000. if 19800. <= freqs[-1] < 20000. else freqs[-1])
    if c['auto_axes'] and curves:
        values = np.concatenate([line.get_ydata() for line in ax.lines if not line.get_label().startswith(('_', 'Fit'))])
        top = float(np.nanmax(values)) + 6.
        ax.set_ylim(top - 40., top)
    if not c['auto_axes']:
        ax.set_xlim(c['fmin'], c['fmax'])
        if phase_ax is not ax: ax.set_ylim(c['ymin'], c['ymax'])
    ax.set_xticks(audio_ticks(*ax.get_xlim())); ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: audio_frequency(v)))
    if phase_ax is not None and phase_ax is not ax:
        # Reserve the same right margin as a twinx axis, while its own extent
        # remains independently movable within the magnitude plot.
        ax.set_ylabel(ax.get_ylabel()); fig.get_layout_engine().set(rect=(0, 0, .92, 1))
    else: fig.get_layout_engine().set(rect=(0, 0, 1, 1))
    axes = [ax] + ([phase_ax] if phase_ax is not None and phase_ax is not ax else [])
    pane.interaction.finish(axes, phase_ax if phase_ax is not ax else None)
    pane.note.setText(note or 'Wheel: zoom at cursor - Zoom out: full view')
    pane.cursor.bind(ax, phase_ax if phase_mode not in ('None', 'DI') else None,
                     di_ax=phase_ax if phase_mode == 'DI' else None)
    pane.chart.done()
