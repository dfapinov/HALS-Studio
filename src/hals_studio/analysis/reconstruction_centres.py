"""Observation-sphere centres from project waypoints, in measurement coordinates."""
import numpy as np


def reconstruction_centres(grid):
    centres = [('Scanner Origin (0, 0, 0)', [0., 0., 0.])]
    def add(name, values):
        try:
            r, phi, z = map(float, values)
        except (TypeError, ValueError):
            return
        if not np.isfinite([r, phi, z]).all() or r < 0:
            return
        phi = np.deg2rad(phi)
        centres.append((name, [r*np.cos(phi)/1000, r*np.sin(phi)/1000, z/1000]))
    for name, prefix in [('Tweeter', 'tw'), ('Reference Origin', 'ref_origin')]:
        add(name, [grid.get(f'wp_{prefix}_{axis}') for axis in ('r', 'phi', 'z')])
    for point in grid.get('user_positions', []):
        add(point.get('name') or 'Additional point', [point.get(axis) for axis in ('r', 'phi', 'z')])
    return centres
