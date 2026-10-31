"""Resolve project speed while preserving legacy optimized measurement metadata."""
from pathlib import Path
import numpy as np
import h5py


def project_speed(global_vars, measurement_path=None, coefficients_path=None):
    if global_vars.get('enable_manual_speed_of_sound', False):
        return float(global_vars.get('speed_of_sound', 343.))
    if measurement_path is not None and Path(measurement_path).is_file():
        with np.load(measurement_path, allow_pickle=False) as data:
            if 'speed_of_sound_mps' in data:
                return float(data['speed_of_sound_mps'].item())
    if coefficients_path is not None and Path(coefficients_path).is_file():
        with h5py.File(coefficients_path, 'r') as data:
            if 'speed_of_sound_mps' in data:
                return float(data['speed_of_sound_mps'][()])
    return float(global_vars.get('speed_of_sound', 343.))
