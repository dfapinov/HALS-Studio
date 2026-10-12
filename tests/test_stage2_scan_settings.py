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
               grid_res_mm=15., speed_of_sound=343.)
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
        raise ReachedGrid

    monkeypatch.setattr(stage, 'generate_3d_landscape_volumetric', capture)
    with pytest.raises(ReachedGrid):
        process_stages.search_origins(dict(name='test', action='rescan', cache='cache',
            rescan=[100.], settings=dict(x_bounds='-50, 50', y_bounds='-30, 70',
            z_bounds='0, 100', grid_res_mm='20')), None, tmp_path, 'data.npz', 'input')
