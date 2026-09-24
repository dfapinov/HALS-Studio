"""Frequency/angle heatmaps on circular and intersecting planar coordinates."""
import numpy as np
import pyvista as pv
from plots import audio_ticks, audio_frequency


def cut_data(sphere, relative, config):
    angles, horizontal, vertical = sphere.cuts(relative)
    mask = (sphere.freqs > 0) & (sphere.freqs >= config['fmin']) & (sphere.freqs <= config['fmax'])
    if np.count_nonzero(mask) < 2:
        mask = sphere.freqs > 0
    return sphere.freqs[mask], angles, horizontal[mask], vertical[mask]


def draw_cross_sonograms(pane, sphere, relative):
    p, c = pane.plotter, pane.config
    f, angles, horizontal, vertical = cut_data(sphere, relative, c)
    camera = p.camera_position if getattr(pane, '_scene_kind', None) == 'cross_sonograms' else None
    bounds_key = (float(f[0]), float(f[-1]), 8.)
    refit = getattr(pane, '_cross_bounds', None) != bounds_key
    pane._cross_bounds = bounds_key
    p.clear()
    # A long frequency axis suits the usual landscape pane; log spacing remains.
    position = lambda frequency: 8*np.log10(np.asarray(frequency)/f[0])/np.log10(f[-1]/f[0])
    x, angle = np.meshgrid(position(f), angles / 90, indexing='ij')
    for label, values, y, z in [('Horizontal', horizontal, angle, np.zeros_like(angle)),
                                  ('Vertical', vertical, np.zeros_like(angle), angle)]:
        mesh = pv.StructuredGrid(x, y, z)
        mesh['level'] = values.ravel(order='F')
        p.add_mesh(mesh, scalars='level', cmap='PColor', clim=(-c['span'], 0), lighting=False,
                   scalar_bar_args={'title': 'Relative level / dB', 'vertical': True,
                                    'position_x': .88, 'position_y': .16, 'width': .07, 'height': .68,
                                    'title_font_size': 11, 'label_font_size': 10}, name=label)
        if c.get('contours', True):
            thresholds = -np.arange(c.get('directivity_contour_step',6.), c['span'], c.get('directivity_contour_step',6.))
            thresholds = sorted(v for v in thresholds if np.nanmin(values) < v < np.nanmax(values))
            if thresholds:
                contours = mesh.contour(thresholds, scalars='level')
                if contours.n_points:
                    p.add_mesh(contours, color='#d9e2ea', line_width=1, opacity=.65, lighting=False,
                               show_scalar_bar=False, name=label+' contours')
        if label == 'Horizontal': pane.mesh = mesh
    from viewer_theme import NAME
    foreground = '#c2d1df' if NAME == 'Dark' else '#20324b'
    ticks = audio_ticks(f[0], f[-1])
    # Always retain the actual upper endpoint (often just below 20 kHz).
    if len(ticks) and f[-1]/ticks[-1] < 1.08: ticks = ticks[:-1]
    ticks = np.r_[ticks, f[-1]]
    pane._cross_frequency_ticks = ticks
    # Extend ticks out from the horizontal plane, leaving a clear label gutter.
    edge = float(angles[0] / 90)
    tick_x = position(ticks)
    tick_points = np.empty((2*len(ticks), 3))
    tick_points[0::2] = np.column_stack([tick_x, np.full(len(ticks), edge), np.zeros(len(ticks))])
    tick_points[1::2] = np.column_stack([tick_x, np.full(len(ticks), edge-.35), np.zeros(len(ticks))])
    p.add_lines(tick_points, color=foreground, width=1, connected=False, name='frequency tick marks')
    p.add_point_labels(np.column_stack([tick_x, np.full(len(ticks), edge-.6), np.zeros(len(ticks))]),
                       [f'{t/1000:.3g}k Hz' if t>=1000 else f'{t:.3g} Hz' for t in ticks],
                       font_size=11, text_color=foreground, shape=None, show_points=False, always_visible=True, name='frequency ticks')
    p.add_point_labels(np.array([[8., 2., 0.], [8., 0., 2.]]),
                       ['H +180 deg', 'V +180 deg'], font_size=12, text_color=foreground,
                       shape=None, show_points=False, always_visible=True, name='plane labels')
    if camera: p.camera_position = camera
    if refit and camera: p.reset_camera()
    pane.note.setText(f'H/V sonograms intersect at 0 degrees. Displayed data: {f[0]:,.1f}?{f[-1]:,.1f} Hz. Drag to orbit.')


def draw_globe(pane, sphere, relative):
    c = pane.config
    f, angles, h, v = cut_data(sphere, relative, c)
    if angles[-1] - angles[0] < 359.999:
        angles = np.r_[angles, angles[0]+360]
        h = np.column_stack([h, h[:, 0]])
        v = np.column_stack([v, v[:, 0]])
    radius = np.log10(f / f[0])
    fig = pane.chart.fig; fig.clear(); fig.set_layout_engine('constrained')
    grid = fig.add_gridspec(1, 3, width_ratios=[1, 1, .045], wspace=.12)
    axes = []
    for column, (title, values) in enumerate([('Horizontal', h), ('Vertical', v)]):
        ax = fig.add_subplot(grid[0, column], projection='polar'); axes.append(ax)
        ax.set_anchor('C'); ax.set_title(title, pad=20)
        ax.set_theta_zero_location('S', offset=c.get('globe_rotation', 0.)); ax.set_theta_direction(1)
        ax.grid(False)
        img = ax.pcolormesh(np.deg2rad(angles), radius, values, shading='nearest', cmap='PColor', vmin=-c['span'], vmax=0)
        if c.get('contours', True):
            step = c.get('directivity_contour_step', 6.)
            levels = sorted(value for value in -np.arange(step, c['span'], step) if np.nanmin(values) < value < np.nanmax(values))
            if levels:
                ax.contour(np.deg2rad(angles), radius, values, levels=levels, colors='#d9e2ea', linewidths=.65, alpha=.75)
        ax.set_ylim(0, radius[-1])
        ticks = audio_ticks(f[0], f[-1]); ax.set_yticks(np.log10(ticks/f[0]), [audio_frequency(t)+' Hz' for t in ticks])
        degrees = np.arange(0, 360, 30)
        ax.set_thetagrids(degrees, [f'{d if d <= 180 else d-360}\N{DEGREE SIGN}' for d in degrees])
        ax.grid(True, alpha=.35); ax.set_rlabel_position(0)
    colour_axis = fig.add_subplot(grid[0, 2])
    fig.colorbar(img, cax=colour_axis, label='Relative level / dB')
    pane.interaction.finish(axes)
    pane.chart.done()
    pane.note.setText('Horizontal / vertical globes share frequency and colour scales. Drag either outer edge to rotate both in 10-degree steps.')
