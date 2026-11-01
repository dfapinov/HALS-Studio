"""Shared native-bin probe response for Analysis IRs and timing."""
from pathlib import Path

import numpy as np


def native_response(owner, sphere, *, reference=False):
    """Cache the unshifted export preview, invalidating on source/settings changes."""
    azimuth, elevation = owner.axis if reference else (owner.azimuth.value(), owner.elevation.value())
    source = sphere.metadata.get('source') or getattr(owner, 'source_path', None)
    if source and Path(source).suffix.lower() in ('.h5', '.hdf5') and Path(source).is_file():
        from hals_studio.application.export_preview import PreviewCache
        from hals_studio.application.export_engine import DEFAULT_EXPORT
        from hals_studio.ui.mic_calibration import config as mic_config

        az, el = np.deg2rad([azimuth, elevation])
        point = sphere.metadata.get('radius_m', 2.) * np.array([
            np.cos(el)*np.cos(az), np.cos(el)*np.sin(az), np.sin(el)
        ]) + np.asarray(sphere.metadata.get('offset_m', [0, 0, 0]))
        radius = np.linalg.norm(point)
        coord = [float(np.degrees(np.arccos(point[2]/radius))),
                 float(np.degrees(np.arctan2(point[1], point[0]))), float(radius)]
        config = dict(DEFAULT_EXPORT, coeff_path=str(source), mode='Manual coordinates',
                      manual_coords=[coord], subtract_tof='Off',
                      obs_mode=sphere.metadata.get('mode', 'Internal'),
                      use_optimized_origins=sphere.metadata.get('optimized_origins', True),
                      manual_ir_capture_padding=True,
                      ir_capture_padding_samples=sphere.metadata.get('padding_samples_removed', 50))
        config.update(mic_config(owner))
        stat = Path(source).stat()
        calibration = Path(config['mic_cal_file'])
        calibration_stat = calibration.stat() if config['apply_mic_cal'] and calibration.is_file() else None
        calibration_key = (calibration_stat.st_size, calibration_stat.st_mtime_ns) if calibration_stat else None
        key = (str(Path(source).resolve()), stat.st_size, stat.st_mtime_ns, repr(config), calibration_key)
        if key == getattr(owner, '_analysis_native_key', None):
            return owner._analysis_native_result
        if not hasattr(owner, '_analysis_native_preview'):
            owner._analysis_native_preview = PreviewCache()
        result = owner._analysis_native_preview.run(config, 0, owner.pool, lambda *_: None, lambda: False)
        owner._analysis_native_key = key
        owner._analysis_native_result = result
        return result
    return None

