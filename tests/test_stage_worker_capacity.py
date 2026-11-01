"""Stage concurrency follows the configured pool, including diagnostics phases."""
import numpy as np
import pytest
from hals_studio.process_engine.runtime import EngineRuntime


class InlinePool:
    workers = 18
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def imap_unordered(self, function, items, chunksize=1):
        return map(function, items)


def measurement_data():
    rng = np.random.default_rng(17)
    count = 128
    freqs = np.array([0., 5000., 6000., 7000.])
    names = [str(i) for i in range(count)]
    return dict(freqs=freqs, filenames=names,
                complex_data={name: rng.normal(size=4)+1j*rng.normal(size=4) for name in names},
                r_arr=rng.uniform(.7, .9, count),
                th_arr=np.arccos(rng.uniform(-1, 1, count)),
                ph_arr=rng.uniform(-np.pi, np.pi, count),
                origins_mm=None, speed_of_sound_mps=343.)


def test_stage3_uses_same_available_pool_for_solves_and_directivity(monkeypatch, tmp_path):
    from hals_studio.process_engine import stage3_optimize_she_settings as stage
    monkeypatch.setattr(stage, 'load_and_parse_npz', lambda path: measurement_data())
    (tmp_path/'input.npz').touch()
    pool = InlinePool()
    requests = []
    used = []
    class Runtime(EngineRuntime):
        def collect(self, executor, function, tasks, label, chunksize=1):
            used.append((label, executor))
            return super().collect(executor, function, tasks, label, chunksize)
    runtime = Runtime(output=lambda text: None,
                      pool_factory=lambda workers=None: (requests.append(workers) or pool))
    result = stage.run_open_branch_optimizer(str(tmp_path), 'input.npz', (2, 4),
        freq_start_hz=5000., freq_end_hz=7000., octave_resolution=0,
        spl_sphere_points=32, save_plot=False, runtime=runtime)
    assert requests == [None]
    assert used
    assert all(executor is pool for _, executor in used)
    assert result['step1']['sample_frequency_count'] == 3


@pytest.mark.parametrize('requested', [None, 3, 40])
def test_stage4_uses_requested_pool_capacity(monkeypatch, tmp_path, requested):
    from hals_studio.process_engine import stage4_run_she_solve as stage
    monkeypatch.setattr(stage, 'load_and_parse_npz', lambda path: measurement_data())
    (tmp_path/'input.npz').touch()
    requests = []
    pool = InlinePool()
    pool.workers = min(requested or 18, 18)
    runtime = EngineRuntime(output=lambda _: None,
        pool_factory=lambda workers=None: (requests.append(workers) or pool))
    result = stage.run_she_solve('input.npz', 'unused.h5', str(tmp_path), str(tmp_path),
        target_n_max=2, jobs=requested, save_to_disk=False, show_plot=False, runtime=runtime)
    assert requests == [requested]
    assert result['coeffs'].shape == (3, 18)


def test_stage2_grid_borrows_full_pool(monkeypatch):
    from hals_studio.process_engine import stage2_centre_origin as stage
    monkeypatch.setattr(stage, 'solve_physics_3d', lambda x, y, z, context: x+2*y+3*z)
    requested = []
    runtime = EngineRuntime(output=lambda text: None,
        pool_factory=lambda workers=None: (requested.append(workers) or InlinePool()))
    cfg = dict(grid_res_mm=1., x_bounds=(-1, 1), y_bounds=(-1, 1), z_bounds=(-1, 1))
    x, y, z, grid = stage.generate_3d_landscape_volumetric((cfg,), runtime=runtime)
    assert requested == [None]
    np.testing.assert_array_equal(grid, x[:, None, None]+2*y[None, :, None]+3*z[None, None, :])


def test_speed_probe_tasks_use_full_pool_even_with_few_candidates(monkeypatch):
    from hals_studio.process_engine import stage2_centre_origin as stage
    requested = []
    def worker(args):
        speed, probes, *_ = args
        return speed, 1., [dict(freq=f, error=1.) for f, _ in probes]
    monkeypatch.setattr(stage, '_worker_speed_of_sound_candidate', worker)
    runtime = EngineRuntime(output=lambda text: None,
        pool_factory=lambda workers=None: (requested.append(workers) or InlinePool()))
    result = stage.run_speed_of_sound_candidate_batch('test', [342., 343.],
        [(5000., [1]), (6000., [1]), (7000., [1])], (0, 0, 0), [], [], [], {}, runtime=runtime)
    assert requested == [None]
    assert len(result) == 2
    assert all(len(row[2]) == 3 for row in result)
