"""Parity against the unchanged Stage 5 driver, plus publication/cancellation contracts."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import bootstrap
import h5py
import numpy as np
import pytest
from export_engine import DEFAULT_EXPORT, geometry, run_export, import_project
import stage5_extract_pressures as original
from acoustics import Cancelled


@pytest.fixture
def config(tmp_path):
    f = np.arange(40., 20001., 40.); path = tmp_path/'source.h5'
    with h5py.File(path, 'w') as h:
        h['freqs'] = f; h['N_used'] = np.zeros(len(f), int)
        h['coeffs'] = np.column_stack([np.exp(-2j*np.pi*f*.0003), .08*np.exp(-2j*np.pi*f*.0002)])
        h['origins_mm'] = np.column_stack([20+10*np.sin(f/5000), np.full(len(f), 15.), np.full(len(f), -10.)])
        h['fs'] = 48000.; h['speed_of_sound_mps'] = 345.
    cal = tmp_path/'mic.txt'; cal.write_text('20 1.0\n1000 2.0\n20000 -1.0\n')
    return dict(DEFAULT_EXPORT, coeff_path=str(path), output_dir=str(tmp_path/'out'), frd_prefix='parity',
                direction='hor_vert', range_deg=20, increment_deg=10, zero_theta=75., zero_phi=12.,
                offset_x=40., offset_y=-25., offset_z=15., apply_mic_cal=True, mic_cal_file=str(cal), frd_db_offset=3.)


def direct(c, output, save=False):
    common = dict(coeff_path=c['coeff_path'], output_dir=output, zero_theta=c['zero_theta'], zero_phi=c['zero_phi'],
                  offset_xyz=np.array([c['offset_x'], c['offset_y'], c['offset_z']])/1000, dist_mic=c['dist_mic'],
                  subtract_tof=c['subtract_tof'], apply_mic_cal=c['apply_mic_cal'], mic_cal_file=c['mic_cal_file'],
                  mic_cal_mode=c['mic_cal_mode'], mic_cal_fade_octaves=c['mic_cal_fade_octaves'], obs_mode=c['obs_mode'],
                  use_optimized_origins=c['use_optimized_origins'], frd_db_offset=c['frd_db_offset'],
                  ir_capture_padding_samples=c['ir_capture_padding_samples'] if c['manual_ir_capture_padding'] else None,
                  save_to_disk=save, use_process_pool=False)
    if c['mode'] == 'CTA-2034': return original.run_cta2034_extraction(**common)
    return original.run_sweep_extraction(**common, use_coord_list=c['mode'] == 'Manual coordinates', coord_list=c['manual_coords'],
                                        direction=c['direction'], range_deg=c['range_deg'], increment_deg=c['increment_deg'],
                                        frd_prefix=c['frd_prefix'], generate_ir_files=c['generate_ir_files'])


@pytest.mark.parametrize('mode', ['Arc sweep', 'Manual coordinates', 'CTA-2034'])
@pytest.mark.parametrize('delay', ['Off', 'Ref Origin', 'Min Phase Ref', 'IR Peak'])
def test_native_export_parity(config, tmp_path, mode, delay):
    c = dict(config, mode=mode, subtract_tof=delay, manual_coords=[[90., 0., 1.], [60., 15., 1.5]])
    actual = run_export(c); expected = direct(c, tmp_path/'unused')
    np.testing.assert_array_equal(actual['freqs'], expected['freqs'])
    if mode == 'CTA-2034':
        assert actual['metrics'].keys() == expected['metrics'].keys()
        for name in actual['metrics']: np.testing.assert_allclose(actual['metrics'][name], expected['metrics'][name], atol=1e-10)
        assert len(actual['geometry']['xyz']) == 70
    else:
        assert actual['data'].keys() == expected['data'].keys()
        for name, row in actual['data'].items():
            for key, value in row.items(): np.testing.assert_allclose(value, expected['data'][name][key], atol=1e-10)


def test_files_and_atomic_cancellation(config, tmp_path):
    c = dict(config, range_deg=0, generate_ir_files=True)
    result = run_export(c, writing=True); dest = Path(result['destination'])
    direct(c, tmp_path/'baseline', save=True)
    produced = {p.relative_to(dest/c['frd_prefix']) for p in (dest/c['frd_prefix']).rglob('*') if p.is_file()}
    assert any(p.suffix == '.wav' for p in produced) and any(p.suffix == '.npz' for p in produced)
    for relative in produced:
        a, b = dest/c['frd_prefix']/relative, tmp_path/'baseline'/c['frd_prefix']/relative
        if a.suffix == '.npz':
            with np.load(a) as first, np.load(b) as second:
                for key in first: np.testing.assert_array_equal(first[key], second[key])
        elif a.suffix == '.wav':
            import soundfile as sf
            first, first_rate = sf.read(a, dtype='float32')
            second, second_rate = sf.read(b, dtype='float32')
            assert first_rate == second_rate
            np.testing.assert_array_equal(first, second)
        else: assert a.read_bytes() == b.read_bytes()
    assert (dest/'atlas-export.json').is_file()
    before = set(Path(c['output_dir']).iterdir()); stop = []
    def log(message):
        if 'Writing files' in message: stop.append(True)
    with pytest.raises(Cancelled): run_export(c, writing=True, cancelled=lambda: bool(stop), log=log)
    assert set(Path(c['output_dir']).iterdir()) == before


def test_manual_absolute_and_project_units(config, tmp_path):
    import json
    c = dict(config, mode='Manual coordinates', manual_coords=[[90., 0., 1.]])
    np.testing.assert_allclose(geometry(c)['xyz'], [[1, 0, 0]], atol=1e-12)
    path = tmp_path/'demo_project.json'
    path.write_text(json.dumps(dict(project_name='demo', stage5_vars=dict(offset_mic_x='.025', dut_depth_x='.3',
                  manual_list_mode=True, manual_coord_list=[[45, 30, 2]], zero_theta_deg='80', apply_mic_cal=False))))
    imported = import_project(path)
    assert imported['offset_x'] == 25 and imported['dut_depth_x'] == 300
    assert imported['manual_coords'] == [[45, 30, 2]] and imported['mode'] == 'Manual coordinates'
    assert imported['zero_theta'] == 80


@pytest.mark.parametrize('filename', ['project.json', 'Speaker_project.json'])
def test_project_folder_geometry_and_coefficients(tmp_path, filename):
    import json
    from export_engine import project_files, coefficient_files, cabinet_geometry, acoustic_origin
    folder = tmp_path/'Speaker'; coeff_dir = folder/'outputs'/'coefficients'; coeff_dir.mkdir(parents=True)
    coeff = coeff_dir/'Speaker_coefficients.h5'; coeff.write_bytes(b'coefficient placeholder')
    grid = dict(wp_baffle_bl_r=150, wp_baffle_bl_phi=-90, wp_baffle_bl_z=-250,
                wp_baffle_tr_r=150, wp_baffle_tr_phi=90, wp_baffle_tr_z=250,
                wp_tw_r=25, wp_tw_phi=0, wp_tw_z=100,
                wp_ref_origin_r=50, wp_ref_origin_phi=90, wp_ref_origin_z=75,
                user_positions=[dict(name='Woofer', r=20, phi=0, z=-100)])
    path = folder/filename
    path.write_text(json.dumps(dict(project_name='Speaker', grid_vars=grid, stage5_vars=dict(subtract_tof=True,
                                   offset_mic_x='.8', output_dir='outputs/custom', mic_cal_file='mic.txt'))))
    assert project_files(folder) == [path]
    c = import_project(path)
    assert coefficient_files(c) == [coeff] and c['coeff_path'] == str(coeff)
    np.testing.assert_allclose([c['offset_x'], c['offset_y'], c['offset_z']], [0, 50, 75], atol=1e-10)
    assert c['dut_depth_x'] == pytest.approx(300)  # width-based default, not 200 metres
    assert c['subtract_tof'] == 'Ref Origin' and c['output_dir'] == str(folder/'outputs'/'custom')
    assert c['mic_cal_file'] == str(folder/'mic.txt')
    vertices, named, valid = cabinet_geometry(c)
    assert valid and vertices.shape == (8, 3) and {name for name, _ in named} >= {'Tweeter', 'Project reference', 'Woofer'}
    np.savez(folder/'outputs'/'Speaker_complex_data.npz', freqs=[100, 1000], origins_mm=[[1, 2, 3], [4, 5, 6]])
    frequency, origin = acoustic_origin(c)
    assert frequency == 1000; np.testing.assert_allclose(origin, [.004, .005, .006])


def test_project_folder_fallbacks_and_ambiguity(tmp_path):
    import json
    from export_engine import project_files, coefficient_files
    folder = tmp_path/'Renamed'; folder.mkdir()
    with pytest.raises(ValueError, match='No project.json'): project_files(folder)
    first = folder/'first_project.json'; first.write_text('{}')
    second = folder/'second_project.json'; second.write_text('{}')
    assert len(project_files(folder)) == 2
    path = folder/'project.json'; path.write_text(json.dumps(dict(grid_vars=dict(wp_tw_r='0', wp_tw_phi='0', wp_tw_z='123'))))
    assert project_files(folder) == [path]
    c = import_project(path)
    assert c['project_name'] == 'Renamed' and c['offset_z'] == 123 and c['coeff_path'] == ''
    assert c['dut_depth_x'] == 200 and c['output_dir'] == str(folder/'outputs'/'response_files')
    coeff_dir = folder/'outputs'/'coefficients'; coeff_dir.mkdir(parents=True)
    (coeff_dir/'other.hdf5').write_bytes(b'')
    assert import_project(path)['coeff_path'] == str(coeff_dir/'other.hdf5')
    (coeff_dir/'another.h5').write_bytes(b'')
    c = import_project(path); assert c['coeff_path'] == '' and len(coefficient_files(c)) == 2


@pytest.mark.parametrize('delay', ['Off', 'Ref Origin', 'Min Phase Ref', 'IR Peak'])
def test_selected_preview_matches_hals_post_and_caches(config, delay):
    from export_preview import PreviewCache
    from extract_pressures_core import PressureEvaluationSession
    c = dict(config, subtract_tof=delay); cache = PreviewCache(); shape = geometry(c)
    actual = cache.run(c, 2, None, lambda *_: None, lambda: False)
    with PressureEvaluationSession(c['coeff_path'], use_process_pool=False) as session:
        expected = session.evaluate_preview_response(shape['spherical'][2], reference_coord_sph=shape['spherical'][shape['reference']],
                    reference_distance=float(np.min(shape['base'][:, 2])), subtract_tof=delay,
                    apply_mic_cal=True, mic_cal_file=c['mic_cal_file'], frd_db_offset=c['frd_db_offset'])
    for key, original in [('complex', 'complex_pre_tof'), ('mag', 'magnitude'), ('phase', 'phase')]:
        np.testing.assert_allclose(actual['preview_point'][key], expected[original], atol=1e-10)
    np.testing.assert_allclose(actual['preview_ir'], expected['ir'], atol=1e-10)
    assert len(cache.session.points) == 2 and cache.session.solves == 1
    cache.run(c, 2, None, lambda *_: None, lambda: False)
    shifted = cache.run(dict(c, frd_db_offset=c['frd_db_offset']+6), 2, None, lambda *_: None, lambda: False)
    assert cache.session.solves == 1
    np.testing.assert_allclose(shifted['preview_point']['mag'], actual['preview_point']['mag']+6)
    cache.run(c, 3, None, lambda *_: None, lambda: False)
    assert cache.session.solves == 2 and len(cache.session.points) == 3


def test_cta_frd_offset_does_not_change_di(config, tmp_path):
    c = dict(config, mode='CTA-2034', frd_db_offset=90.)
    expected = direct(c, tmp_path/'cta_offset', save=True)
    for name, (level, phase) in expected['metrics'].items():
        written = np.loadtxt(tmp_path/'cta_offset'/'CTA2034'/f'{name}.frd')
        offset = 0. if name in ('Response_SPDI', 'Response_ERDI') else 90.
        np.testing.assert_allclose(written[:, 1], level+offset, atol=5.1e-6)
