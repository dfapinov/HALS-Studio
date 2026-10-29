"""Plane cuts from evaluated export coordinates, without sphere reconstruction."""
import numpy as np


def export_cuts(result):
    config, geometry = result['config'], result['geometry']
    if 'data' in result:
        levels = np.column_stack([row['mag'] for row in result['data'].values()])
    else:
        levels = 20*np.log10(np.maximum(abs(result['processed']), np.finfo(float).tiny))
    relative = levels - levels[:, geometry['reference'], None]
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
        if full and len(angles) > 1 and angles[-1] == 180:
            angles = np.r_[-180., angles]; values = np.column_stack([values[:, -1], values])
        cuts[plane] = (angles, values)
    return cuts
