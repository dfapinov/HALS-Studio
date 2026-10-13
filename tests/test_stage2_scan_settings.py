import numpy as np
import pytest

from hals_studio.process_engine import stage2_centre_origin as stage


@pytest.mark.parametrize('spacing', [0.5, 1., 20.])
def test_dense_speed_probes_are_bounded_and_keep_native_indices(spacing, monkeypatch):
    freqs = np.arange(0., 20000. + spacing, spacing)
    original = stage._is_simple_frequency_ratio
    calls = 0

    def checked(*args):
        nonlocal calls
        calls += 1
        assert calls < 10000, 'Probe selection must not enumerate native-bin combinations'
        return original(*args)

    monkeypatch.setattr(stage, '_is_simple_frequency_ratio', checked)
    probes = stage.select_speed_of_sound_probe_bins(freqs, np.arange(len(freqs)))
    assert len(probes) == 6
    assert stage._is_noncoherent_probe_set([f for f, _ in probes])
    assert all(5000 <= f <= 10000 and freqs[i] == f for f, i in probes)


def test_normal_run_speed_probes_do_not_depend_on_origin_resolution(tmp_path, monkeypatch):
    freqs = np.arange(0., 20001.)
    (tmp_path / 'input.npz').touch()
    monkeypatch.setattr(stage, 'load_and_parse_npz', lambda _: dict(
        freqs=freqs, complex_data={'mic': freqs.astype(complex)}, filenames=['mic'],
        r_arr=np.array([1.]), th_arr=np.array([0.]), ph_arr=np.array([0.]), raw_data={}))
    monkeypatch.setattr(stage, 'get_grid_limit', lambda *args: (4, 1))
    captured = []

    class ReachedSpeedScan(Exception):
        pass

    def capture(label, candidates, probes, tweeter, r, th, ph, cfg, **kwargs):
        assert cfg['enable_full_grid_scan'] is False
        assert cfg['scan_radius_mm'] == 0
        assert cfg['z_bounds'] == (1000., 1000.)
        captured.append(probes)
        raise ReachedSpeedScan

    monkeypatch.setattr(stage, 'run_speed_of_sound_candidate_batch', capture)
    for resolution in (1/3, 1/12):
        with pytest.raises(ReachedSpeedScan):
            stage.run_origin_search(str(tmp_path), 'input.npz', 'output.npz',
                                    (0, 0, 0), resolution, plot_results_origins=False)
    assert captured[0] == captured[1]
    assert len(captured[0]) == 6
    assert all(f == pressure[0] for f, pressure in captured[0])


def test_rescan_uses_current_bounds_and_grid_resolution(tmp_path, monkeypatch):
    from hals_studio.application import process_stages
    cfg = dict(x_bounds=(-500, 500), y_bounds=(-500, 500), z_bounds=(-500, 500),
               grid_res_mm=15., speed_of_sound=343., scan_radius_mm=10.)
    result = ({100.: dict(final_c=np.zeros(3), error=1.)}, np.array([100.]),
              ['mic'], {'mic': np.array([1.])}, ([], [], []), cfg, {})
    monkeypatch.setattr(process_stages.process_cache, 'load', lambda *args: result)
    monkeypatch.setattr(process_stages.process_cache, 'hydrate_stage2', lambda *args: result)

    class ReachedGrid(Exception):
        pass

    def capture(context, **kwargs):
        actual = context[-1]
        assert actual['x_bounds'] == (-50., 50.)
        assert actual['y_bounds'] == (-30., 70.)
        assert actual['z_bounds'] == (0., 100.)
        assert actual['grid_res_mm'] == 20.
        assert 'scan_radius_mm' not in actual
        raise ReachedGrid

    monkeypatch.setattr(stage, 'generate_3d_landscape_volumetric', capture)
    with pytest.raises(ReachedGrid):
        process_stages.search_origins(dict(name='test', action='rescan', cache='cache',
            rescan=[100.], settings=dict(x_bounds='-50, 50', y_bounds='-30, 70',
            z_bounds='0, 100', grid_res_mm='20')), None, tmp_path, 'data.npz', 'input')


def test_cylinder_uses_npz_filename_radius_and_asymmetric_height(tmp_path):
    from hals_studio.process_engine.origin_scan_region import measurement_cylinder, inside_scan
    from hals_studio.process_engine.utils import load_and_parse_npz
    from hals_studio.process_engine import schema
    path = tmp_path / 'measurements.npz'
    names = ['mic_r250_ph0_z-125p5.wav', 'mic_r300p5_ph90_z410.wav',
             'mic_r250_ph180_z100.wav']
    np.savez(path, **{schema.FREQS: np.array([100.]),
                     schema.COMPLEX_DATA: {name: np.array([1j]) for name in names}})
    parsed = load_and_parse_npz(path)
    cfg = measurement_cylinder(parsed['r_arr'], parsed['th_arr'])
    parsed['raw_data'].close()
    assert cfg['scan_radius_mm'] == 300.5
    assert cfg['z_bounds'] == (-125.5, 410.)
    assert inside_scan((0, 0, 410), cfg)
    assert inside_scan((300.5, 0, 0), cfg)
    assert not inside_scan((250, 250, 0), cfg)  # Box corner lies outside the cylinder.
    assert not inside_scan((0, 0, -126), cfg)


def test_simplex_moves_an_outside_seed_into_measurement_cylinder(monkeypatch):
    from hals_studio.process_engine.origin_scan_region import inside_scan
    cfg = dict(scan_radius_mm=100., x_bounds=(-100, 100), y_bounds=(-100, 100),
               z_bounds=(20, 150), initial_simplex_step=15., max_iterations=250)
    visited = []
    target = np.array([20., 30., 70.])
    def physics(x, y, z, context):
        point = np.array([x, y, z])
        assert inside_scan(point, cfg)
        visited.append(point)
        return np.sum((point - target)**2)
    monkeypatch.setattr(stage, 'solve_physics_3d', physics)
    result, path = stage.run_simplex_descent_3d((500., 500., 500.), (cfg,))
    np.testing.assert_allclose(result, target, atol=.2)
    assert all(inside_scan(point, cfg) for point in path)
    assert len(visited) > 4


def test_manual_box_simplex_can_search_outside_measurement_cylinder(monkeypatch):
    cfg = dict(x_bounds=(-500, 500), y_bounds=(-500, 500), z_bounds=(-500, 500),
               initial_simplex_step=15., max_iterations=250)
    target = np.array([300., 300., 0.])
    monkeypatch.setattr(stage, 'solve_physics_3d', lambda x,y,z,ctx: np.sum((np.array([x,y,z])-target)**2))
    result, _ = stage.run_simplex_descent_3d((0., 0., 0.), (cfg,))
    np.testing.assert_allclose(result, target, atol=.2)


def test_manual_scan_fields_are_grouped_separately():
    from PySide6.QtWidgets import QApplication, QGroupBox
    from hals_studio.ui.process_workspace import SCHEMA
    from hals_studio.ui.process_forms import StageForms
    app = QApplication.instance() or QApplication([])
    values = {int(stage): {key: spec['default'] for key, spec in fields.items()}
              for stage, fields in SCHEMA.items()}
    forms = StageForms(SCHEMA, values)
    for key in ('x_bounds', 'y_bounds', 'z_bounds', 'grid_res_mm'):
        group = forms.controls[2, key].parentWidget()
        assert isinstance(group, QGroupBox)
        assert group.title() == 'Full grid re-scan only'
    forms.close()
