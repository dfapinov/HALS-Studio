"""Shared HALS Studio CTA coordinate generator."""
import numpy as np
from utils import cartesian_to_spherical


def generate_cta2034_coords(dist_m, zero_th, zero_ph):
    """Generate the 70 unique spherical coordinates required by CTA-2034-A."""
    th_rad_zero = np.radians(float(zero_th))
    ph_rad_zero = np.radians(float(zero_ph))
    forward = np.array([np.sin(th_rad_zero) * np.cos(ph_rad_zero),
                        np.sin(th_rad_zero) * np.sin(ph_rad_zero), np.cos(th_rad_zero)])
    right = np.array([-np.sin(ph_rad_zero), np.cos(ph_rad_zero), 0])
    up = np.cross(forward, right)
    rotation = np.array([forward, right, up]).T

    unique_coords, coord_to_idx, map_indices, coord_deviations = [], {}, {}, {}

    def physical_coords(orbit, angle):
        if orbit == 'H':
            return 90.0, float(angle)
        if angle <= 180:
            theta, phi = 90.0 - angle, 0.0
            return (abs(theta), 180.0) if theta < 0 else (theta, phi)
        theta, phi = 90.0 + angle - 180, 180.0
        return (360.0 - theta, 0.0) if theta > 180 else (theta, phi)

    def add_point(key, theta, phi):
        theta, phi = np.radians(theta), np.radians(phi)
        local = np.array([dist_m * np.sin(theta) * np.cos(phi),
                          dist_m * np.sin(theta) * np.sin(phi), dist_m * np.cos(theta)])
        global_point = rotation @ local
        _, theta_out, phi_out = cartesian_to_spherical(*global_point)
        coord_key = (round(np.degrees(theta_out), 2), round(np.degrees(phi_out), 2))
        if coord_key not in coord_to_idx:
            coord_to_idx[coord_key] = len(unique_coords)
            unique_coords.append((*coord_key, dist_m))
            coord_deviations[len(unique_coords) - 1] = np.degrees(theta)
        map_indices[key] = coord_to_idx[coord_key]

    for orbit in 'HV':
        for angle in range(0, 360, 10):
            add_point(f'{orbit}{angle}', *physical_coords(orbit, angle))
    return unique_coords, map_indices, coord_deviations
