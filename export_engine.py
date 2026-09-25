"""Exact Stage 5 exports, isolated from the analysis sphere and main HALS app.

The copied driver is unchanged. Per-job function globals inject the viewer pool,
logging and cancellation without monkey-patching the shared engine module.
"""
from copy import deepcopy
from datetime import datetime
from pathlib import Path
import json
import re
import tempfile
import types
import numpy as np
import bootstrap
import schema
from acoustics import Cancelled
from utils import load_she_h5, spherical_to_cartesian, cartesian_to_spherical
from stage5_pressure_utils import centered_sweep_angles
import stage5_extract_pressures as stage5

DEFAULT_EXPORT = dict(
    coeff_path='', output_dir=str(bootstrap.ROOT/'outputs'/'response_files'), frd_prefix='HALS',
    mode='Arc sweep', direction='horizontal', range_deg=90, increment_deg=10, dist_mic=1.,
    zero_theta=90., zero_phi=0., offset_x=0., offset_y=0., offset_z=0., offset_step_mm=10.,
    subtract_tof='Ref Origin', frd_db_offset=0., generate_ir_files=False,
    apply_mic_cal=False, mic_cal_file='', mic_cal_mode='subtract', mic_cal_fade_octaves=1.,
    obs_mode='Internal', use_optimized_origins=True, manual_ir_capture_padding=False,
    ir_capture_padding_samples=50, manual_coords=[[90., 0., 1.]],
    dut_depth_x=200., show_stage2_origin=False, stage2_origin_frequency_hz=1000.,
    project_path='', project_name='', project_geometry={}, mic_cal_fallback='', live_preview=True, preview_smoothing='Off',
)


def xyz_from_spherical(coords):
    points = np.asarray(coords, float)
    return np.column_stack(spherical_to_cartesian(points[:, 2], np.deg2rad(points[:, 0]), np.deg2rad(points[:, 1])))


def geometry(config):
    """Same coordinates and order as the bulk exporter, including shared on-axis."""
    c = config; radius = float(c['dist_mic'])
    theta, phi = np.deg2rad([c['zero_theta'], c['zero_phi']])
    forward = np.array([np.sin(theta)*np.cos(phi), np.sin(theta)*np.sin(phi), np.cos(theta)])
    right = np.array([-np.sin(phi), np.cos(phi), 0.]); up = np.cross(forward, right)
    rotation = np.column_stack([forward, right, up]); names = []
    if c['mode'] == 'Manual coordinates':
        coords = [list(row) if len(row) == 3 else [*row, radius] for row in c['manual_coords']]
        names = [f'Point {i+1}' for i in range(len(coords))]
    elif c['mode'] == 'CTA-2034':
        coords, mapping, _ = stage5.generate_cta2034_coords(radius, c['zero_theta'], c['zero_phi'])
        names = ['']*len(coords)
        for name, i in mapping.items(): names[i] = (names[i]+' / '+name).strip(' /')
    else:
        coords = []
        for angle in centered_sweep_angles(int(c['range_deg']), int(c['increment_deg'])):
            a = np.deg2rad(angle)
            for arc in ('horizontal', 'vertical'):
                if c['direction'] not in (arc, 'hor_vert'): continue
                if arc == 'vertical' and c['direction'] == 'hor_vert' and angle == 0: continue
                point = rotation @ (radius*np.array([np.cos(a), np.sin(a) if arc == 'horizontal' else 0,
                                                     np.sin(a) if arc == 'vertical' else 0]))
                r, t, p = cartesian_to_spherical(*point)
                coords.append([np.rad2deg(t), np.rad2deg(p), r]); names.append(f'{arc[0].upper()} {angle:+g}°')
    if not coords: raise ValueError('Add at least one manual coordinate.')
    coords = np.asarray(coords, float)
    if coords.ndim != 2 or coords.shape[1] != 3 or not np.isfinite(coords).all():
        raise ValueError('Coordinates must contain finite theta, phi and radius values.')
    if np.any(coords[:, 2] <= 0) or np.any((coords[:, 0] < 0) | (coords[:, 0] > 180)):
        raise ValueError('Radius must be positive and theta must be between 0° and 180°.')
    base = xyz_from_spherical(coords)
    offset = np.array([c['offset_x'], c['offset_y'], c['offset_z']])/1000
    xyz = base if c['mode'] == 'Manual coordinates' else base+offset
    r, th, ph = cartesian_to_spherical(*xyz.T)
    if np.any(r < 1e-8): raise ValueError('An export point lies at the expansion origin; move it away from zero.')
    final = np.column_stack([np.rad2deg(th), np.rad2deg(ph), r])
    reference = int(np.argmin(coords[:, 2])) if c['mode'] == 'Manual coordinates' else int(np.argmin(np.linalg.norm(base-radius*forward, axis=1)))
    return dict(base=coords, xyz=xyz, spherical=final, names=names, reference=reference,
                origin=np.zeros(3) if c['mode'] == 'Manual coordinates' else offset, forward=forward)


def validate(config, writing=False):
    c = dict(DEFAULT_EXPORT, **config)
    if c['mode'] not in ('Arc sweep', 'Manual coordinates', 'CTA-2034'): raise ValueError('Unknown export mode.')
    for key in ('direction', 'obs_mode', 'subtract_tof', 'mic_cal_mode'):
        allowed = dict(direction=('horizontal', 'vertical', 'hor_vert'), obs_mode=('Internal', 'External', 'Full'),
                       subtract_tof=('Off', 'Ref Origin', 'Min Phase Ref', 'IR Peak'), mic_cal_mode=('subtract', 'add'))
        if c[key] not in allowed[key]: raise ValueError(f'Invalid {key}.')
    for key, default in DEFAULT_EXPORT.items():
        if isinstance(default, (float, int)) and not isinstance(default, bool):
            if not np.isfinite(float(c[key])): raise ValueError(f'{key} must be finite.')
    if c['dist_mic'] <= 0 or not 0 <= c['range_deg'] <= 180 or c['increment_deg'] < 1:
        raise ValueError('Use a positive distance, sweep range 0–180° and increment of at least 1°.')
    if c['ir_capture_padding_samples'] < 0 or c['mic_cal_fade_octaves'] < 0:
        raise ValueError('Padding and calibration fade cannot be negative.')
    if not 0 <= c['zero_theta'] <= 180: raise ValueError('Reference theta must be between 0° and 180°.')
    if not re.fullmatch(r'[^<>:"/\\|?*\x00-\x1f]+', c['frd_prefix']) or c['frd_prefix'].strip('. ') != c['frd_prefix']:
        raise ValueError('Enter a filename prefix without path separators or reserved characters.')
    if not Path(c['coeff_path']).is_file(): raise ValueError('Choose a HALS coefficient HDF5 file first.')
    if c['apply_mic_cal'] and not Path(c['mic_cal_file']).is_file() and not c['mic_cal_fallback'].strip():
        raise ValueError('Choose an existing microphone calibration file, or import a project containing fallback calibration.')
    if writing and not c['output_dir'].strip(): raise ValueError('Choose an output directory.')
    geometry(c)
    return c


class PoolAdapter:
    def __init__(self, pool, cancelled, progress): self.pool, self.cancelled, self.progress = pool, cancelled, progress
    def imap(self, func, iterable):
        from worker_pool import evaluate_task
        tasks = list(iterable)
        results = self.pool.map(tasks, self.cancelled) if self.pool else map(evaluate_task, tasks)
        for i, result in enumerate(results):
            if self.cancelled(): raise Cancelled()
            self.progress(round(80*(i+1)/len(tasks)), f'Evaluating native frequency bins · {i+1}/{len(tasks)} batches')
            yield result


def run_export(config, pool=None, writing=False, progress=lambda *_: None, cancelled=lambda: False, log=lambda *_: None):
    c = validate(config, writing); layout = geometry(c)
    captured = {}; messages = []
    def check():
        if cancelled(): raise Cancelled()
    def output(*parts, **kwargs):
        check(); message = ' '.join(map(str, parts)); messages.append(message); log(message)
    def evaluate(**kwargs):
        check()
        result = stage5.evaluate_she_field(**dict(kwargs, process_pool=PoolAdapter(pool, cancelled, progress), show_progress=False))
        captured.update(result); captured['complex'] = result['complex'].copy()
        np.testing.assert_allclose(kwargs['coords_sph'], layout['spherical'], atol=1e-9)
        return result
    # Globals are private to this job; other viewer reconstruction remains independent.
    env = dict(vars(stage5), print=output, evaluate_she_field=evaluate)
    processed = {}
    def calibrate(*args):
        result = stage5.apply_mic_calibration(*args)
        captured['complex'] = result.copy()
        return result
    def tof(freqs, distance, speed):
        processed.update(distance=float(distance), time=float(distance)/float(speed))
        return stage5.get_tof_phasor(freqs, distance, speed)
    env.update(apply_mic_calibration=calibrate, get_tof_phasor=tof)
    def metrics(freqs, pressure, *args):
        processed['pressure'] = pressure.copy()
        return stage5.calculate_cta2034_metrics(freqs, pressure, *args)
    env['calculate_cta2034_metrics'] = metrics
    for name in ('write_frd', 'write_complex_npz', 'write_wav'):
        original = getattr(stage5, name)
        def write(*args, _fn=original, **kwargs):
            check(); return _fn(*args, **kwargs)
        env[name] = write
    function = stage5.run_cta2034_extraction if c['mode'] == 'CTA-2034' else stage5.run_sweep_extraction
    driver = types.FunctionType(function.__code__, env, function.__name__, function.__defaults__, function.__closure__)
    common = dict(coeff_path=c['coeff_path'], zero_theta=c['zero_theta'], zero_phi=c['zero_phi'],
                  dist_mic=c['dist_mic'], offset_xyz=tuple(np.array([c['offset_x'], c['offset_y'], c['offset_z']])/1000),
                  subtract_tof=c['subtract_tof'], apply_mic_cal=c['apply_mic_cal'], mic_cal_file=c['mic_cal_file'],
                  mic_cal_mode=c['mic_cal_mode'], mic_cal_fade_octaves=c['mic_cal_fade_octaves'],
                  obs_mode=c['obs_mode'], use_optimized_origins=c['use_optimized_origins'], frd_db_offset=c['frd_db_offset'],
                  ir_capture_padding_samples=c['ir_capture_padding_samples'] if c['manual_ir_capture_padding'] else None,
                  save_to_disk=writing, use_process_pool=True)
    if c['mode'] != 'CTA-2034':
        common.update(use_coord_list=c['mode'] == 'Manual coordinates', coord_list=c['manual_coords'],
                      direction=c['direction'], range_deg=c['range_deg'], increment_deg=c['increment_deg'],
                      frd_prefix=c['frd_prefix'], generate_ir_files=c['generate_ir_files'])
    root = Path(c['output_dir']).expanduser().resolve() if writing else None
    if root: root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.atlas-export-', dir=root) as tmp:
        common['output_dir'] = tmp
        if c['apply_mic_cal'] and not Path(c['mic_cal_file']).is_file():
            fallback = Path(tmp)/'microphone-calibration.txt'; fallback.write_text(c['mic_cal_fallback'], encoding='utf-8')
            common['mic_cal_file'] = str(fallback)
        check(); result = driver(**common); check()
        result.update(geometry=layout, raw=captured, config=deepcopy(c), destination=None,
                      processed=processed.get('pressure'), tof_distance=processed.get('distance'), tof_time=processed.get('time'))
        if writing:
            progress(92, 'Finalizing export and settings manifest')
            record = dict(settings=c, native_frequency_bins=len(result['freqs']), observation_points=len(layout['xyz']),
                          engine='HALS Stage 5 snapshot', note='FRD uses delay compensation and dB offset; sweep complex NPZ/WAV retain propagation phase.')
            (Path(tmp)/'atlas-export.json').write_text(json.dumps(record, indent=2), encoding='utf-8')
            (Path(tmp)/'export.log').write_text('\n'.join(messages), encoding='utf-8')
            destination = root/(c['frd_prefix']+'_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
            # Publish only a complete run. Existing exports are never overwritten.
            check(); Path(tmp).rename(destination); result['destination'] = str(destination)
        progress(100, 'Export complete' if writing else 'Preview ready')
        return result


def project_files(folder):
    """Prefer the conventional project file; expose ambiguity instead of guessing."""
    folder = Path(folder).resolve()
    if not folder.is_dir(): raise ValueError('Choose an existing HALS project folder.')
    for name in ('project.json', folder.name+'_project.json', folder.name+'.json'):
        candidate = folder/name
        if candidate.is_file(): return [candidate]
    candidates = sorted(folder.glob('*_project.json'))
    if not candidates: raise ValueError(f'No project.json, *_project.json or matching folder-name JSON found in {folder}.')
    return candidates


def coefficient_files(config):
    root = Path(config['project_path']).parent
    name = config['project_name']
    folders = [root/'outputs'/'coefficients', root]
    for folder in folders:
        for stem in (name+'_coefficients', name):
            for extension in ('.h5', '.hdf5'):
                candidate = folder/(stem+extension)
                if candidate.is_file(): return [candidate]
    return sorted(p for folder in folders for p in folder.glob('*') if p.is_file() and p.suffix.lower() in ('.h5', '.hdf5'))



def waypoint(grid, prefix):
    r, phi, z = [float(grid[f'wp_{prefix}_{key}']) for key in ('r', 'phi', 'z')]
    point = np.array([r*np.cos(np.deg2rad(phi)), r*np.sin(np.deg2rad(phi)), z])/1000
    if not np.isfinite(point).all(): raise ValueError('Waypoint must be finite.')
    return point


def import_project(path):
    path = Path(path).resolve(); project = json.loads(path.read_text(encoding='utf-8-sig'))
    c = deepcopy(DEFAULT_EXPORT); values = project.get('stage5_vars', {})
    c['output_dir'] = 'outputs/response_files'
    mapping = {'zero_theta_deg': 'zero_theta', 'zero_phi_deg': 'zero_phi',
               'offset_mic_x': 'offset_x', 'offset_mic_y': 'offset_y', 'offset_mic_z': 'offset_z'}
    for source, value in values.items():
        key = mapping.get(source, source)
        if key not in c or isinstance(c[key], (dict, list)): continue
        default = c[key]
        if isinstance(default, bool): value = str(value).strip().lower() in ('1', 'true', 'yes', 'on')
        elif isinstance(default, int): value = int(float(value))
        elif isinstance(default, float): value = float(value)
        c[key] = value
    if project.get('stage5_gui_units', 'm') != 'mm':
        for source in ('offset_mic_x', 'offset_mic_y', 'offset_mic_z', 'dut_depth_x'):
            if source in values: c[mapping.get(source, source)] *= 1000
    truth = lambda value: str(value).strip().lower() in ('1', 'true', 'yes', 'on')
    c['mode'] = 'Manual coordinates' if truth(values.get('manual_list_mode')) else 'CTA-2034' if truth(values.get('cta_mode')) else 'Arc sweep'
    legacy_delay = str(c['subtract_tof']).lower()
    if legacy_delay in ('true', 'grid origin'): c['subtract_tof'] = 'Ref Origin'
    elif legacy_delay == 'false': c['subtract_tof'] = 'Off'
    c['manual_coords'] = values.get('manual_coord_list', project.get('stage5_manual_coords', c['manual_coords']))
    name = str(project.get('project_name') or (path.parent.name if path.stem.lower() == 'project' else path.stem.removesuffix('_project')))
    c['project_name'] = name
    c['frd_prefix'] = values.get('frd_prefix') or name
    c['coeff_path'] = str(path.parent/'outputs'/'coefficients'/f'{name}_coefficients.h5')
    for key in ('output_dir', 'mic_cal_file'):
        if c[key] and not Path(c[key]).is_absolute(): c[key] = str(path.parent/c[key])
    c['project_path'] = str(path); c['project_geometry'] = project.get('grid_vars', {})
    grid = c['project_geometry']
    positions = grid.get('user_positions', grid.get('User_positions', []))
    if isinstance(positions, str):
        import ast
        try: positions = ast.literal_eval(positions)
        except (SyntaxError, ValueError): positions = []
    grid['user_positions'] = positions if isinstance(positions, list) else []
    # HALS Post synchronizes Stage 5 offsets from the reference waypoint,
    # falling back to the tweeter. Keep that same project-opening behavior.
    for prefix in ('ref_origin', 'tw'):
        try:
            xyz = waypoint(grid, prefix)*1000
            for axis, value in zip('xyz', xyz): c['offset_'+axis] = round(float(value), 3)
            break
        except (KeyError, ValueError, TypeError): pass
    c['mic_cal_fallback'] = project.get('mic_cal_fallback', '')
    # Resolve project assets against this project copy. An absolute legacy path
    # outside it may belong to another backup copy and must not be followed.
    root = path.parent.resolve()
    for key, fallback in (('output_dir', root/'outputs'/'response_files'),
                           ('mic_cal_file', ''), ('mic_cal_fallback', '')):
        value = c.get(key)
        if not value:
            continue
        candidate = Path(value)
        candidate = (root/candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            c[key] = str(fallback) if fallback else ''
        else:
            c[key] = str(candidate)
    if 'dut_depth_x' not in values or c['dut_depth_x'] <= 0:
        vertices, _, valid = cabinet_geometry(c)
        if valid: c['dut_depth_x'] = float(np.linalg.norm(vertices[2]-vertices[1])*1000)
    matches = coefficient_files(c)
    c['coeff_path'] = str(matches[0]) if len(matches) == 1 else ''
    return c


def acoustic_origin(config):
    """Prefer the full Stage 2 origin data, as HALS Post does; fall back to HDF5."""
    from stage5_pressure_utils import nearest_acoustic_origin
    if config.get('project_path'):
        path = Path(config['project_path']).parent/'outputs'/(config['project_name']+'_complex_data.npz')
        if path.is_file():
            with np.load(path, allow_pickle=False) as data:
                if schema.ORIGINS_MM in data:
                    return nearest_acoustic_origin(data[schema.FREQS], data[schema.ORIGINS_MM], config['stage2_origin_frequency_hz'])
    import h5py
    with h5py.File(config['coeff_path'], 'r') as data:
        return nearest_acoustic_origin(data[schema.FREQS][...], data[schema.ORIGINS_MM][...], config['stage2_origin_frequency_hz'])


def baffle_geometry(config):
    """Read the flat baffle and named waypoints, independently of legacy depth."""
    grid = config.get('project_geometry', {}); named = []
    def point(prefix): return waypoint(grid, prefix)
    for name, prefix in [('Tweeter', 'tw'), ('Project reference', 'ref_origin')]:
        try: named.append((name, point(prefix)))
        except (KeyError, ValueError, TypeError): pass
    for user in grid.get('user_positions', []):
        try:
            r, phi, z = float(user['r'])/1000, np.deg2rad(float(user['phi'])), float(user['z'])/1000
            named.append((user.get('name', 'User position'), np.array([r*np.cos(phi), r*np.sin(phi), z])))
        except (KeyError, ValueError, TypeError): pass
    try:
        bl, tr = point('baffle_bl'), point('baffle_tr')
        try: tl = point('baffle_tl')
        except (KeyError, ValueError, TypeError): tl = np.array([bl[0], bl[1], tr[2]])
        return np.array([bl, tl, tr, bl+tr-tl]), named, True
    except (KeyError, ValueError, TypeError): return None, named, False


def cabinet_geometry(config):
    """Legacy geometry adapter for older project importers."""
    front, named, known = baffle_geometry(config)
    if not known:
        return front, named, known
    back = front.copy()
    back[:, 0] = (front[1, 0]+front[2, 0])/2-float(config.get('dut_depth_x', 200.))/1000
    return np.concatenate([front, back]), named, True
