"""Plot-only processing caches; measurement data stays in the output NPZ."""
import os
import pickle
from pathlib import Path
import numpy as np


def load_stage1(path, settings):
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError('Stage 1 output NPZ is missing. Run Stage 1 again.')
    with np.load(path, allow_pickle=True) as data:
        freqs = data['freqs']
        spectra = data['data'].item()
        meta = data['meta'].item() if 'meta' in data else {}
        fs = float(data['fs'].item()) if 'fs' in data else (2.0 * float(freqs[-1]) if len(freqs) else 0.0)
    smooth = None
    if settings.get('enable_smoothing') and settings.get('keep_raw_and_smoothed'):
        smooth_path = path.with_name(path.stem + '_smoothed.npz')
        if not smooth_path.is_file():
            raise FileNotFoundError('Stage 1 smoothed NPZ is missing. Run Stage 1 again.')
        with np.load(smooth_path, allow_pickle=True) as data:
            smooth = data['data'].item()
    return freqs, spectra, smooth, meta, fs


def compact(stage, result):
    if stage == 1:
        raise ValueError('Stage 1 plots must be loaded from their NPZ output.')
    if stage == 2:
        # Preserve the viewer tuple positions, without embedding input spectra.
        fields = ('final_c', 'original_c', 'error', 'original_error', 'grid',
                  'X_vals', 'Y_vals', 'Z_vals')
        rows = {f: {k: v for k, v in row.items() if k in fields}
                for f, row in result[0].items()}
        return rows, None, None, None, None, result[5], None
    if stage == 4:
        plot = {k: result[k] for k in ('freqs', 'N_used', 'cond', 'pct_error')}
        if 'P_measured' in result and 'residual_vector' in result:
            measured = result['P_measured']
            mask = abs(measured) >= abs(measured).max(axis=1, keepdims=True)*10**(-90/20)
            plot['pct_error'] = np.linalg.norm(np.where(mask, result['residual_vector'], 0), axis=1)/np.maximum(np.linalg.norm(np.where(mask, measured, 0), axis=1), 1e-20)*100
        return plot
    # Stage 3 already contains only summary curves, reference powers and tables.
    return result


def save(path, stage, result):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix('.tmp').open('wb') as stream:
        pickle.dump(compact(stage, result), stream, pickle.HIGHEST_PROTOCOL)
    os.replace(path.with_suffix('.tmp'), path)


def load(path, stage):
    with Path(path).open('rb') as stream:
        result = pickle.load(stream)
    legacy = (stage == 2 and result[3] is not None) or (stage == 4 and 'coeffs' in result)
    result = compact(stage, result)
    if legacy:
        save(path, stage, result)
    return result


def hydrate_stage2(result, npz_path):
    """Reload spectra only for an explicit origin edit or grid rescan."""
    from process_engine.utils import load_and_parse_npz
    parsed = load_and_parse_npz(npz_path)
    source = parsed['raw_data']
    try:
        data = dict(source)
    finally:
        source.close()
    return (result[0], parsed['freqs'], parsed['filenames'], parsed['complex_data'],
            (parsed['r_arr'], parsed['th_arr'], parsed['ph_arr']), result[5], data)


def load_stage4_summary(coeff_path):
    import h5py
    with h5py.File(coeff_path) as source:
        return {key: source[key][()] for key in ('freqs', 'N_used', 'cond', 'pct_error')}


def hydrate_stage4(npz_path, coeff_path, *, process_pool=None):
    """Load saved NPZ/H5 into the original 1/96-octave spatial computation."""
    from process_engine.utils import load_and_parse_npz, load_she_h5
    from process_engine.spatial_error_viewer import compute_spatial_error_data
    she = load_she_h5(coeff_path)
    parsed = load_and_parse_npz(npz_path)
    try:
        freqs = parsed['freqs']
        indices = np.searchsorted(freqs, she['freqs'])
        if (np.any(indices >= len(freqs)) or
                not np.allclose(freqs[indices], she['freqs'], rtol=1e-8, atol=1e-8)):
            raise ValueError('The measurement NPZ and coefficients have different frequency bins.')
        if not parsed['filenames']:
            raise ValueError('The measurement NPZ contains no usable microphone coordinates.')
        measured = np.column_stack([parsed['complex_data'][name][indices]
                                    for name in parsed['filenames']])
        coords = np.column_stack((np.degrees(parsed['th_arr']),
                                  np.degrees(parsed['ph_arr']), parsed['r_arr']))
        speed = she.get('speed_of_sound_mps')
        if speed is None:
            speed = parsed.get('speed_of_sound_mps')
        speed = 343. if speed is None else float(speed)
        if she['origins_mm'] is None:
            she['origins_mm'] = np.zeros((len(she['freqs']), 3))
        _, _, _, sub_freqs, sub_orders, measured, reconstructed = compute_spatial_error_data(
            she, measured, coords, speed, process_pool=process_pool, show_progress=False)
        return dict(freqs=sub_freqs, N_used=sub_orders, P_measured=measured,
                    coords_sph=coords, speed_of_sound_mps=speed,
                    P_reconstructed=reconstructed)
    finally:
        parsed['raw_data'].close()


def spatial_reconstruction(result, index):
    return result['P_reconstructed'][index]
