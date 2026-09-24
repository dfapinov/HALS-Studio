"""Shared HALS Studio CTA coordinate generator."""
import numpy as np
from utils import cartesian_to_spherical

def generate_cta2034_coords(dist_m, zero_th, zero_ph):
    """
    Generates the 70 unique spherical coordinates required for CTA-2034-A.
    """
    # Setup rotation matrix from the zero-axis angles
    th_rad_zero = np.radians(float(zero_th))
    ph_rad_zero = np.radians(float(zero_ph))
    F = np.array([np.sin(th_rad_zero) * np.cos(ph_rad_zero), np.sin(th_rad_zero) * np.sin(ph_rad_zero), np.cos(th_rad_zero)])
    R = np.array([-np.sin(ph_rad_zero), np.cos(ph_rad_zero), 0])
    U = np.cross(F, R)
    rot_matrix = np.array([F, R, U]).T

    angles = list(range(0, 360, 10))
    unique_coords = []
    coord_to_idx = {} 
    map_indices = {} 
    coord_deviations = {} 

    def get_phys_coords(orbit, angle_deg):
        if orbit == 'H':
            th_p = 90.0
            ph_p = float(angle_deg)
        elif orbit == 'V':
            if 0 <= angle_deg <= 180:
                th_p = 90.0 - angle_deg
                ph_p = 0.0
                if th_p < 0:
                    th_p = abs(th_p)
                    ph_p = 180.0
            else:
                rem = angle_deg - 180
                th_p = 90.0 + rem
                ph_p = 180.0
                if th_p > 180:
                    th_p = 360 - th_p
                    ph_p = 0.0
        return th_p, ph_p

    def add_point(key_name, th_phys, ph_phys):
        # Convert local spherical coordinates (standard acoustic orientation) to local Cartesian
        th_phys_rad = np.radians(th_phys)
        ph_phys_rad = np.radians(ph_phys)
        x_local = dist_m * np.sin(th_phys_rad) * np.cos(ph_phys_rad)
        y_local = dist_m * np.sin(th_phys_rad) * np.sin(ph_phys_rad)
        z_local = dist_m * np.cos(th_phys_rad)
        p_local = np.array([x_local, y_local, z_local])

        # Rotate the local Cartesian point to the global frame
        p_global = rot_matrix @ p_local
        r_out, th_out_rad, ph_out_rad = cartesian_to_spherical(p_global[0], p_global[1], p_global[2])
        k_t = round(np.degrees(th_out_rad), 2)
        k_p = round(np.degrees(ph_out_rad), 2)
        coord_key = (k_t, k_p)
        
        if coord_key not in coord_to_idx:
            coord_to_idx[coord_key] = len(unique_coords)
            unique_coords.append( (k_t, k_p, dist_m) )
            coord_deviations[len(unique_coords)-1] = th_phys
            
        map_indices[key_name] = coord_to_idx[coord_key]

    for a in angles:
        th, ph = get_phys_coords('H', a)
        add_point(f"H{a}", th, ph)

    for a in angles:
        th, ph = get_phys_coords('V', a)
        add_point(f"V{a}", th, ph)
        
    return unique_coords, map_indices, coord_deviations

