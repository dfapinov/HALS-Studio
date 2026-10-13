"""Measurement-derived constraints for Stage 2's normal origin search."""
import numpy as np


def measurement_cylinder(radii_m, polar_angles):
    """Recover the enclosing cylindrical radius and Z limits from parsed filenames."""
    radii = np.asarray(radii_m, dtype=float)
    angles = np.asarray(polar_angles, dtype=float)
    if not radii.size or radii.shape != angles.shape or not np.all(np.isfinite([radii, angles])):
        raise ValueError('Stage 2 needs valid measurement coordinates in the NPZ filenames.')
    radius = float(np.round(np.max(np.abs(radii * np.sin(angles))) * 1000, 9))
    z = np.round(radii * np.cos(angles) * 1000, 9)
    return dict(scan_radius_mm=radius, x_bounds=(-radius, radius),
                y_bounds=(-radius, radius), z_bounds=(float(z.min()), float(z.max())))


def project_to_cylinder(point, cfg):
    """Keep initial simplex vertices feasible, including seeds outside the scan."""
    point = np.array(point, dtype=float, copy=True)
    radius = cfg['scan_radius_mm']
    distance = np.hypot(*point[:2])
    if distance > radius:
        point[:2] *= radius / distance
    point[2] = np.clip(point[2], *cfg['z_bounds'])
    return point


def inside_scan(point, cfg):
    if not all(cfg[f'{axis}_bounds'][0] <= value <= cfg[f'{axis}_bounds'][1]
               for axis, value in zip('xyz', point)):
        return False
    return ('scan_radius_mm' not in cfg or
            np.hypot(*point[:2]) <= cfg['scan_radius_mm'] + 1e-8)
