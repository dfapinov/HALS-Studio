"""Magnitude/phase composition and trend annotations for an Atlas pane."""
import numpy as np
from matplotlib.ticker import FuncFormatter, MaxNLocator
from matplotlib.transforms import ScaledTranslation
import acoustics as ac
from analysis_metrics import minimum_phase, trend_fit
from plots import style, response_directions, audio_ticks, audio_frequency


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
        if kind == 'cea': names = ['On axis', 'Listening window', 'Early reflections', 'Sound power', 'Sound power DI', 'Early reflections DI']
        elif kind == 'reflections':
            names = {'All': ['Floor', 'Ceiling', 'Front wall', 'Side walls', 'Rear wall'],
                     'Horizontal': ['Front wall', 'Side walls', 'Rear wall', 'Horizontal reflections'],
                     'Vertical': ['Floor', 'Ceiling', 'Vertical reflections']}[c['breakout']]
        else: names = [kind[4:]]
        if kind == 'cea_Sound power' and c['breakout'] != 'All': names += [c['breakout']+' sound power']
        curves = {n: metrics[n] for n in names}
        if all(n.endswith('DI') for n in names): ylabel = 'Directivity index / dB'
        note = f'CEA2034-derived · reference H {o.axis[0]:g}° / V {o.axis[1]:g}° · interpolated energy'
    offset = 0 if ylabel == 'Directivity index / dB' else c['offset']
    return {name: values+offset for name, values in curves.items()}, ylabel, note


def magnitude_curves(pane, s, levels, config=None):
    from panes import selected_magnitudes
    c = pane.config if config is None else config
    curves, labels, notes = {}, [], []
    for kind in selected_magnitudes(c):
        values, label, note = _one_magnitude(pane, s, levels, dict(c, kind=kind))
        curves.update(values)
        if label not in labels: labels.append(label)
        if note and note not in notes: notes.append(note)
    ylabel = labels[0] if len(labels) == 1 else 'Magnitude / DI / dB' if labels else 'Level / dB'
    return curves, ylabel, ' · '.join(notes)


def draw_chart(pane, s, levels, rel, i):
    from mic_calibration import config as shared_config
    from panes import GROUPS, selected_magnitudes
    c, o, kind = pane.config, pane.owner, pane.config['kind']
    fig = pane.chart.fig; fig.clear(); fig.set_layout_engine('constrained'); ax = fig.add_subplot(111)
    pane.phase_axis = None; pane.phase_handle = None; pane.magnitude_curves = {}; pane.fit_result = None
    phase_ax = None; note = ''; phase_note = ''
    selected = selected_magnitudes(c)
    if kind.startswith('map_'):
        angles, h, v = s.cuts(rel); values = h if kind == 'map_h' else v
        img = ax.pcolormesh(s.freqs, angles, values.T, cmap='PColor', vmin=-c['span'], vmax=0, shading='auto')
        fig.colorbar(img, ax=ax, label='Relative level / dB', pad=.02)
        if c['contours']:
            thresholds = sorted(n for n in -np.arange(c.get('directivity_contour_step',6.),c['span'],c.get('directivity_contour_step',6.)) if values.min() < n < values.max())
            if thresholds: ax.contour(s.freqs, angles, values.T, levels=thresholds, colors='white', linewidths=.5)
        style(ax, '', ylabel='Angle / degrees'); ax.set_ylim(-180, 180)
    else:
        curves, ylabel, note = magnitude_curves(pane, s, levels)
        pane.magnitude_curves = curves
        di_curves = {name: values for name, values in curves.items() if name.endswith('DI')}
        curves = {name: values for name, values in curves.items() if name not in di_curves}
        if di_curves: ylabel = 'HALS level / dB + offset'
        trace_colours = {}
        for title, values in curves.items():
            line, = ax.plot(s.freqs, values, lw=1.4, label=title)
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
        if c['overlays']:
            for overlay in o.plot_overlays(pane):
                if not overlay['visible']: continue
                if 'magnitude' in overlay:
                    if overlay.get('di'):
                        di_curves[overlay['name']] = np.interp(s.freqs, overlay['freqs'], overlay['magnitude'])
                        di_colours[overlay['name']] = next(palette)
                    else:
                        ax.plot(overlay['freqs'], np.asarray(overlay['magnitude'])+c['offset']+shared_config(o)['frd_db_offset'], lw=1, alpha=.8, label=overlay['name'])
                    continue
                freq = np.asarray(overlay['freqs']); raw = np.asarray(overlay['real'])+1j*np.asarray(overlay['imag'])
                ax.plot(freq, ac.db(raw)+c['offset']+shared_config(o)['frd_db_offset'], lw=1, alpha=.8, label=overlay['name'])
        if c['fit'] and curves:
            selected = c['fit_curve'] if c['fit_curve'] in curves else next(iter(curves))
            try:
                fit = trend_fit(s.freqs, curves[selected], c['fit_low'], c['fit_high']); pane.fit_result = fit
                ax.plot(fit['freqs'], fit['line'], '--', lw=2., color='#f3e69b', label=f'Fit · {selected}')
                ax.text(.02, .97, f'{selected}: {fit["slope"]:+.2f} dB/oct · ±{fit["deviation"]:.2f} dB max\n'
                        f'{audio_frequency(fit["low"])}–{audio_frequency(fit["high"])} Hz · RMS {fit["rms"]:.2f} dB',
                        transform=ax.transAxes, va='top', fontsize=8, color='#f3e69b',
                        bbox=dict(facecolor='#101c28', alpha=.85, edgecolor='none'))
            except ValueError as exc: note += ' · Fit: '+str(exc)
        style(ax, '', ylabel=ylabel)
        if curves: ax.legend(fontsize=7, ncol=2 if len(curves) > 5 else 1, loc='lower left' if c['fit'] else 'best')
        phase_mode = c['phase_mode'] if kind in GROUPS['SPL & phase'] or c['magnitude_selection'] is not None else 'None'
        if kind in ('phase', 'minimum'): phase_mode = 'Minimum phase' if kind == 'minimum' else 'Total phase'
        if di_curves: phase_mode = 'DI'
        if phase_mode != 'None':
            delay = pane.delay_ms() if phase_mode != 'DI' else 0
            phase_note = pane.delay_note if phase_mode != 'DI' else ''
            if curves:
                phase_ax = fig.add_axes(ax.get_position(), sharex=ax, frameon=False)
                phase_ax.set_in_layout(False); phase_ax.patch.set_visible(False)
                phase_ax.xaxis.set_visible(False); phase_ax.yaxis.tick_right(); phase_ax.yaxis.set_label_position('right')
                for edge in ('top', 'left', 'bottom'): phase_ax.spines[edge].set_visible(False)
            else: phase_ax = ax
            axis_colour = next(iter(di_colours.values())) if di_curves else '#baacf8'
            phase_ax.tick_params(axis='y', colors=axis_colour, labelsize=8)
            phase_ax._response_axis_colour = axis_colour
            phase_ax.set_ylabel('Directivity index / dB' if di_curves else 'Phase / degrees', color=axis_colour, fontsize=8)
            phase_ax.yaxis.set_major_locator(MaxNLocator(5))
            if di_curves:
                for name, values in di_curves.items():
                    phase_ax.plot(s.freqs, values, lw=1.2, label=name, color=di_colours[name])
            else:
                sample = s.index(*o.axis) if selected == ['reference'] else s.index(o.azimuth.value(), o.elevation.value())
                values = phase_values(s.freqs, s.pressure[:, *sample], phase_mode, c['wrapped'], delay)
                source = 'Reference' if selected == ['reference'] else 'Probe'
                px, py = phase_trace(s.freqs, values, c['wrapped'])
                phase_ax.plot(px, py, color='#baacf8', lw=.85, alpha=.8, label=f'{source} {phase_mode.lower()}')
                all_values = [values]
                if c['overlays'] and ('probe' in selected or not selected):
                    for overlay in o.plot_overlays(pane):
                        if not overlay['visible'] or 'magnitude' in overlay: continue
                        freq = np.asarray(overlay['freqs']); raw = np.asarray(overlay['real'])+1j*np.asarray(overlay['imag'])
                        phase = phase_values(freq, raw, phase_mode, c['wrapped'], delay); all_values.append(phase)
                        px, py = phase_trace(freq, phase, c['wrapped'])
                        phase_ax.plot(px, py, lw=.8, alpha=.7, label=overlay['name']+' phase')
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
                # A short handle outside the plotting area, directly above the right axis.
                transform = phase_ax.transAxes + ScaledTranslation(5/72, 7/72, fig.dpi_scale_trans)
                end = phase_ax.transAxes + ScaledTranslation(33/72, 7/72, fig.dpi_scale_trans)
                from matplotlib.patches import ConnectionPatch
                pane.phase_handle = ConnectionPatch((1, 1), (1, 1), coordsA=transform, coordsB=end,
                                                   color=axis_colour, linewidth=2.5, clip_on=False, annotation_clip=False)
                pane.phase_handle.set_annotation_clip(False)
                phase_ax.add_artist(pane.phase_handle)
                phase_ax.text(1, 1, 'dB' if di_curves else 'Phase', transform=phase_ax.transAxes +
                              ScaledTranslation(5/72, 12/72, fig.dpi_scale_trans),
                              ha='left', va='bottom', color=axis_colour, fontsize=8, clip_on=False)
            handles, labels = ax.get_legend_handles_labels()
            if phase_ax is not ax:
                extra_handles, extra_labels = phase_ax.get_legend_handles_labels()
                handles += extra_handles; labels += extra_labels
            ax.legend(handles, labels, fontsize=7, loc='lower left' if c['fit'] else 'best')
            if phase_mode == 'Minimum phase': phase_note = 'Finite-band minimum-phase estimate; no propagation delay.'
        elif not curves:
            ax.text(.5, .5, 'Select magnitude responses or a phase plot from the plot menu.',
                    transform=ax.transAxes, ha='center', va='center', fontsize=9, color='#91aabe', wrap=True)
    pane.frequency_marker = ax.axvline(s.freqs[i], color='#7db0c0', alpha=.35, lw=.8)
    ax.set_xlim(s.freqs[0], 20000. if 19800. <= s.freqs[-1] < 20000. else s.freqs[-1])
    if c['auto_axes'] and not kind.startswith('map_') and curves:
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
    pane.note.setText(' · '.join(part for part in (note, phase_note) if part) or 'Wheel: zoom at cursor · Zoom out: full view')
    if not kind.startswith('map_'):
        pane.cursor.bind(ax, phase_ax if phase_mode not in ('None', 'DI') else None)
    pane.chart.done()
