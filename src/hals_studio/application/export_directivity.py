"""Plane cuts from evaluated export coordinates, without sphere reconstruction."""
import numpy as np
from hals_studio.analysis.acoustics import relative_levels


def sweep_direction_indices(angles, direction):
    """Filter evaluated directions; the shared rear point belongs to either side."""
    displayed = np.asarray(angles).copy()
    if direction == '-':
        displayed[np.isclose(displayed, 180)] = -180
        indices = np.flatnonzero(displayed <= 0)
    elif direction == '+':
        indices = np.flatnonzero(displayed >= 0)
    else:
        indices = np.arange(len(displayed))
    indices = indices[np.argsort(displayed[indices])]
    return displayed[indices], indices


def export_cuts(result, options=None, *, normalize=True, samples=None):
    options = options or {}
    config, geometry = result['config'], result['geometry']
    if samples is not None:
        levels = samples
    elif 'data' in result:
        levels = np.column_stack([row['mag'] for row in result['data'].values()])
    else:
        levels = 20*np.log10(np.maximum(abs(result['processed']), np.finfo(float).tiny))
    # The reference direction rotates with the sweep and can face a deep null.
    # Use one peak per frequency across the export set so rotating a full sweep
    # only reorders its levels, rather than clipping louder directions to red.
    smoothing = options.get('smoothing', 'None')
    if smoothing != 'None' and samples is None:
        from hals_studio.analysis.acoustics import smooth_energy
        octave = {'1/24 octave': 24, '1/12 octave': 12, '1/6 octave': 6, '1/3 octave': 3}[smoothing]
        energy = smooth_energy(result['freqs'], 10**(levels/10), octave)
        levels = 10*np.log10(np.maximum(energy, 1e-60))
    on_axis = (options.get('normalization') == 'On axis' if options.get('kind') == 'polar'
               else options.get('directivity_on_axis', False))
    relative = relative_levels(levels, levels[:, geometry['reference']] if on_axis else None) if normalize else levels
    forward = geometry['forward']
    phi = np.deg2rad(config['zero_phi'])
    right = np.array([-np.sin(phi), np.cos(phi), 0.])
    up = np.cross(forward, right)
    local = (geometry['xyz']-geometry['origin']) @ np.column_stack([forward, right, up])
    radius = np.linalg.norm(local, axis=1)
    cuts = {}
    for plane, tangent, normal in [('horizontal', 1, 2), ('vertical', 2, 1)]:
        if config['mode'] == 'Arc sweep' and config['direction'] not in (plane, 'hor_vert'):
            cuts[plane] = (np.array([]), relative[:, :0]); continue
        # CTA coordinates are rounded to 0.01 degrees by the export engine.
        mask = abs(local[:, normal]) <= np.maximum(radius, 1.)*np.deg2rad(.02)
        indices = np.flatnonzero(mask)
        angles = np.round(np.rad2deg(np.arctan2(local[indices, tangent], local[indices, 0])), 5)
        # Shared on-axis/back-axis points and duplicate sweep endpoints are one direction.
        angles[np.isclose(abs(angles), 180, atol=.02)] = 180
        angles[np.isclose(angles, 0, atol=.02)] = 0
        angles, unique = np.unique(angles, return_index=True)
        values = relative[:, indices[unique]]
        full = config['mode'] == 'CTA-2034' or (config['mode'] == 'Arc sweep' and config['range_deg'] == 180)
        if normalize and full and len(angles) > 1 and angles[-1] == 180:
            angles = np.r_[-180., angles]; values = np.column_stack([values[:, -1], values])
        cuts[plane] = (angles, values)
    return cuts
