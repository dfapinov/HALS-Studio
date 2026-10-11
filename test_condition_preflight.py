import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / 'process_engine'))
import numpy as np
import pytest
from condition_preflight import optimise_transitions
from she_solver_core import matrix_condition, _solve_one_frequency
from stage4_run_she_solve import _get_table_limit


def test_matrix_matches_solver_condition():
    rng = np.random.default_rng(41)
    coords = (rng.uniform(.5, 1., 100), rng.uniform(0, np.pi, 100), rng.uniform(0, 2*np.pi, 100))
    _, metrics = _solve_one_frequency(1000, rng.normal(size=100).astype(complex), coords, 4,
                                      k_val=18., max_lambda=0.)
    assert matrix_condition(coords, 4, 18.) == pytest.approx(metrics['cond_pre'])


@pytest.mark.parametrize('bin_count', [40, 400])
def test_bounded_search_and_upper_cutoff_round_trip(bin_count):
    freqs = np.linspace(100., 4000., bin_count)
    proposed = np.minimum(8, 2 + ((freqs - 100.) / 200.).astype(int))
    entries = {n: np.flatnonzero(proposed >= n)[0] for n in range(3, 9)}
    calls = []
    def condition(n, i):
        calls.append((n, i))
        return 1e4 if n <= 4 else 1e7 * (freqs[i]/freqs[entries[n]])**-8
    result = optimise_transitions(freqs, proposed, condition)
    assert result['status'] == 'ok'
    # Each higher order permits its original entry, a search start, five
    # offset samples and two refinements. The bound is independent of the
    # number of frequency bins; cached/reused samples can cost fewer calls.
    for n in entries:
        assert sum(order == n for order, _ in calls) <= (1 if n <= 4 else 9)
    assert result['evaluations'] == len(calls) == len(set(calls))
    np.testing.assert_array_less(result['adjusted_orders'], proposed+1)
    assert np.all(np.diff(result['adjusted_orders']) >= 0)
    assert any(r['activation_hz'] != r['original_hz'] for r in result['transitions'])
    for row in result['transitions']:
        if row['activation_hz'] is not None and row['order'] > 4 and not row['forced']:
            assert np.isfinite(row['condition']) and row['condition'] <= row['target_upper']
        assert row['activation_hz'] <= 3*row['original_hz']
    assert max(result['adjusted_orders']) == max(proposed)
    np.testing.assert_array_equal([_get_table_limit(f, True, result['manual_table']) for f in freqs],
                                  result['adjusted_orders'])


@pytest.mark.parametrize('orders', [[2, 3, 3], [2, 3, 5], [2, 2, 2]])
def test_missing_n4_retains_original(orders):
    result = optimise_transitions([100, 200, 300], orders, lambda n, i: 1e4)
    assert result['status'] == 'unavailable'
    assert 'manual_table' not in result


def test_non_improving_or_singular_degree_activates_at_deadline():
    result = optimise_transitions(np.arange(1, 21)*100., np.minimum(8, np.arange(20)+2),
                                  lambda n, i: 1e4 if n <= 4 else np.inf)
    assert max(result['adjusted_orders']) == 8
    for row in result['transitions']:
        if row['order'] > 4:
            assert row['forced']
            assert row['activation_hz'] == min(2000, 3*row['original_hz'])


def test_low_condition_keeps_kr_entries():
    freqs = np.arange(1, 21)*100.
    proposed = np.minimum(8, np.arange(20)+2)
    result = optimise_transitions(freqs, proposed, lambda n, i: 1e9 if n <= 4 else 1e4)
    np.testing.assert_array_equal(result['adjusted_orders'], proposed)
    assert all(r['activation_hz'] == r['original_hz'] for r in result['transitions'])


def test_search_refines_crossing_that_overshoots_lower_target():
    freqs = np.arange(100., 2001., 10.)
    proposed = np.where(freqs < 200, 3, np.where(freqs < 400, 4, 5))
    result = optimise_transitions(freqs, proposed,
                                  lambda n, i: 1e4 if n <= 4 else (1e7 if freqs[i] < 430 else 10.))
    row = result['transitions'][-1]
    assert row['activation_hz'] == 430.
    assert row['condition'] < row['target_lower']


def test_failed_order_does_not_block_higher_orders_or_compound_deadlines():
    freqs = np.arange(100., 2100., 100.)
    proposed = np.minimum(9, np.arange(len(freqs))+2)
    result = optimise_transitions(freqs, proposed, lambda n, i: 1e4 if n <= 4 or n == 6 else 1e9)
    rows = {row['order']: row for row in result['transitions']}
    assert rows[5]['forced'] and not rows[6]['forced']
    assert rows[6]['activation_hz'] == rows[5]['activation_hz']
    assert rows[9]['activation_hz'] == min(freqs[-1], 3*rows[9]['original_hz'])
    assert result['adjusted_orders'][-1] == 9


def test_last_bin_and_sparse_frequency_deadlines():
    freqs = np.array([100., 160., 230., 390., 600.])
    result = optimise_transitions(freqs, [3, 4, 5, 6, 8], lambda n, i: 1e4 if n <= 4 else np.inf)
    rows = {row['order']: row for row in result['transitions']}
    assert rows[5]['activation_hz'] == 600.  # final bin, below the 690 Hz deadline
    assert all(rows[n]['activation_hz'] == 600 for n in (6, 7, 8))
    assert result['adjusted_orders'][-1] == 8
    np.testing.assert_array_equal([_get_table_limit(f, True, result['manual_table']) for f in freqs],
                                  result['adjusted_orders'])


def test_stage4_optimises_current_target_before_solving(tmp_path, monkeypatch):
    import stage4_run_she_solve as solver
    import condition_preflight as growth
    import logging
    freqs = np.arange(0., 4100., 100.)
    name = 'input.npz';(tmp_path/name).touch()
    data = dict(freqs=freqs, complex_data={'a': np.ones(len(freqs), complex)},
                filenames=['a'], r_arr=np.array([.2]), th_arr=np.array([1.]),
                ph_arr=np.array([0.]), origins_mm=None, speed_of_sound_mps=315.)
    monkeypatch.setattr(solver, 'load_and_parse_npz', lambda path: data)
    monkeypatch.setattr(solver, 'get_grid_limit', lambda *args: (20, 1))
    monkeypatch.setattr(growth, 'get_grid_limit', lambda *args: (20, 1))
    monkeypatch.setattr(logging, 'basicConfig', lambda **kwargs: None)
    events = []
    def condition(coords, n, k):
        events.append('preflight')
        return 1e4 if n <= 4 else 1e9
    monkeypatch.setattr(growth, 'matrix_condition', condition)
    def solve(**kwargs):
        events.append('solve')
        n = kwargs['order_N']
        return np.zeros(2*(n+1)**2, complex), dict(residual_norm=0., final_N=n,
            stop_reason='test', cond_pre=1e4, cond_post=1e4, residual_vector=np.zeros(1, complex))
    monkeypatch.setattr(solver, '_solve_one_frequency', solve)
    def run(n, optimise=True, manual=False):
        events.clear()
        return solver.run_she_solve(name, 'unused.h5', str(tmp_path), str(tmp_path), n,
            use_manual_table=manual, manual_order_table={4000.: 4},
            save_to_disk=False, show_plot=False, use_process_pool=False, jobs=1,
            condition_preflight=optimise)
    for target in (6, 9):
        result = run(target)
        assert result['N_used'][-1] == target
        preflight = result['condition_preflight']
        assert preflight['settings']['target_n_max'] == target
        assert preflight['settings']['speed_of_sound'] == 315.
        assert all(e == 'preflight' for e in events[:events.index('solve')])
        assert 'preflight' not in events[events.index('solve'):]
        np.testing.assert_array_equal(result['N_used'], preflight['adjusted_orders'])
    manual = run(9, True, manual=True)
    assert manual['N_used'][-1] == 4
    assert manual['condition_preflight'] is None
    assert 'preflight' not in events
    pure_kr = run(9, False)
    assert pure_kr['N_used'][-1] == 9
    assert pure_kr['condition_preflight'] is None
    assert 'preflight' not in events
