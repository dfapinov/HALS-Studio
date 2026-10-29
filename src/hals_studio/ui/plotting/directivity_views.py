"""Frequency/angle heatmaps on circular and intersecting planar coordinates."""
import numpy as np
import pyvista as pv
from hals_studio.ui.plotting.plots import audio_ticks, audio_frequency


def add_rotation_handle(pane, ax, rotation):
    artists = tuple(ax.plot([], [], transform=ax.transAxes, color='#8ca4b8',
                            linewidth=2, solid_capstyle='round', clip_on=False,
                            zorder=30)[0] for _ in range(3))
    for artist in artists: artist.set_in_layout(False)
    pane._rotation_handle_artists[ax] = artists
    position_rotation_handle(pane, ax, rotation)


def position_rotation_handle(pane, ax, rotation):
    """Keep the grab handle attached to the plot's angular orientation."""
    key = pane._rotation_axes[ax]
    from hals_studio.ui.plotting.plot_settings import DEFAULT
    rotation_key = 'polar_rotation' if pane.config['kind'] == 'polar' else 'globe_rotation'
    # Both handles start top-left at the default view and follow subsequent rotation.
    base_angle = 140 - DEFAULT[rotation_key][key]
    angle = np.deg2rad(base_angle + rotation)
    radial = np.array([np.cos(angle), np.sin(angle)])
    tangent = np.array([-radial[1], radial[0]])
    center = np.array([.5, .5])
    grip = center + .68*radial
    pane._rotation_handles[ax] = tuple(grip)
    stem, hook, arrow = pane._rotation_handle_artists[ax]
    stem_points = center + np.outer([.52, .648], radial)
    stem.set_data(stem_points[:, 0], stem_points[:, 1])
    arc_angles = np.linspace(np.pi, np.deg2rad(430), 25)
    arc_points = grip + .032*(np.outer(np.cos(arc_angles), radial) +
                               np.outer(np.sin(arc_angles), tangent))
    hook.set_data(arc_points[:, 0], arc_points[:, 1])
    end_angle = arc_angles[-1]
    direction = -np.sin(end_angle)*radial + np.cos(end_angle)*tangent
    side = np.array([-direction[1], direction[0]])
    end = arc_points[-1]
    tip = end + .015*direction
    wings = np.array([end - .004*direction + .011*side,
                      end - .004*direction - .011*side])
    arrow_points = np.array([end, tip, wings[0], tip, wings[1]])
    arrow.set_data(arrow_points[:, 0], arrow_points[:, 1])


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
    from hals_studio.ui.viewer_theme import NAME
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
    draw_globe_cuts(pane, f, {'horizontal': (angles, h), 'vertical': (angles, v)})


def bounded_edges(values):
    """Bin edges clipped to sampled coverage, without half-bin extrapolation."""
    return np.r_[values[0], (values[:-1]+values[1:])/2, values[-1]]


def draw_spectrogram(ax, frequencies, angles, values, config, *, bounded=False):
    """Shared Analysis/Export frequency-angle heatmap and contour styling."""
    x = np.exp(bounded_edges(np.log(frequencies))) if bounded else frequencies
    y = bounded_edges(angles) if bounded else angles
    image = ax.pcolormesh(x, y, values.T, shading='flat' if bounded else 'auto',
                         cmap='PColor', vmin=-config['span'], vmax=0)
    if config.get('contours', True):
        step = config.get('directivity_contour_step', 6.)
        levels = sorted(v for v in -np.arange(step, config['span'], step)
                        if np.nanmin(values) < v < np.nanmax(values))
        if levels:
            ax.contour(frequencies, angles, values.T, levels=levels, colors='white', linewidths=.5)
    return image


def draw_globe_cuts(pane, f, cuts, *, close_curves=True):
    c = pane.config
    radius = np.log10(f / f[0])
    fig = pane.chart.fig; fig.clear(); fig.set_layout_engine('constrained')
    grid = fig.add_gridspec(1, 3, width_ratios=[1, 1, .045], wspace=.12)
    axes = []
    rotation = c.get('globe_rotation', 0.)
    rotations = rotation if isinstance(rotation, dict) else {'horizontal': float(rotation), 'vertical': float(rotation)}
    pane._rotation_axes = {}
    pane._rotation_handles = {}
    pane._rotation_handle_artists = {}
    img = None
    for column, title in enumerate(('Horizontal', 'Vertical')):
        angles, values = cuts[title.lower()]
        ax = fig.add_subplot(grid[0, column], projection='polar'); axes.append(ax)
        ax.set_anchor('C'); ax.set_title(title, pad=20)
        key = title.lower()
        if len(angles) < 2:
            ax.set_axis_off()
            ax.text(.5, .5, 'No '+key+' sweep data', transform=ax.transAxes, ha='center', va='center')
            continue
        if close_curves and angles[-1]-angles[0] < 359.999:
            angles = np.r_[angles, angles[0]+360]
            values = np.column_stack([values, values[:, 0]])
        pane._rotation_axes[ax] = key
        ax.set_theta_zero_location('S', offset=rotations.get(key, 0.)); ax.set_theta_direction(1)
        ax.grid(False)
        theta = np.deg2rad(angles if close_curves else bounded_edges(angles))
        radial = radius if close_curves else bounded_edges(radius)
        img = ax.pcolormesh(theta, radial, values, shading='nearest' if close_curves else 'flat', cmap='PColor', vmin=-c['span'], vmax=0)
        if c.get('contours', True):
            step = c.get('directivity_contour_step', 6.)
            levels = sorted(value for value in -np.arange(step, c['span'], step) if np.nanmin(values) < value < np.nanmax(values))
            if levels:
                ax.contour(np.deg2rad(angles), radius, values, levels=levels, colors='#d9e2ea', linewidths=.65, alpha=.75)
        ax.set_ylim(0, radius[-1])
        ticks = audio_ticks(f[0], f[-1]); ax.set_yticks(np.log10(ticks/f[0]), [audio_frequency(t)+' Hz' for t in ticks])
        degrees = np.arange(0, 360, 30)
        ax.set_thetagrids(degrees, [f'{d if d <= 180 else d-360}\N{DEGREE SIGN}' for d in degrees])
        ax.grid(True, alpha=.35); ax.set_rlabel_position(-rotations.get(key, 0.))
        # The thin stem and curved grip use axes coordinates, so both scale
        # with the globe and can be positioned as its angle changes.
        add_rotation_handle(pane, ax, rotations.get(key, 0.))
    colour_axis = fig.add_subplot(grid[0, 2])
    if img is not None: fig.colorbar(img, cax=colour_axis, label='Relative level / dB')
    else: colour_axis.set_axis_off()
    pane.interaction.finish(axes)
    pane.chart.done()
    pane.note.setText('Horizontal / vertical globes share frequency and colour scales. Drag the curved handle outside either globe to rotate it independently.')
