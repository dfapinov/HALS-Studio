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


def test_prediction_budget_and_upper_cutoff_round_trip():
    freqs = np.arange(100., 4100., 100.)
    proposed = np.minimum(8, 2 + np.arange(len(freqs))//2)
    calls = []
    def condition(n, i):
        calls.append((n, i))
        return 1e4 if n <= 4 else 1e7 * (freqs[i]/freqs[2*(n-2)])**-8
    result = optimise_transitions(freqs, proposed, condition)
    assert result['status'] == 'ok'
    assert len(calls) <= 3*6
    np.testing.assert_array_less(result['adjusted_orders'], proposed+1)
    assert np.all(np.diff(result['adjusted_orders']) >= 0)
    assert any(r['activation_hz'] != r['original_hz'] for r in result['transitions'])
    for row in result['transitions']:
        if row['activation_hz'] is not None and row['order'] > 4:
            assert row['condition'] <= 1e5
    np.testing.assert_array_equal([_get_table_limit(f, True, result['manual_table']) for f in freqs],
                                  result['adjusted_orders'])


@pytest.mark.parametrize('orders', [[2, 3, 3], [2, 3, 5], [2, 2, 2]])
def test_missing_n4_retains_original(orders):
    result = optimise_transitions([100, 200, 300], orders, lambda n, i: 1e4)
    assert result['status'] == 'unavailable'
    assert 'manual_table' not in result


def test_non_improving_or_singular_degree_is_not_activated():
    result = optimise_transitions(np.arange(1, 21)*100., np.minimum(8, np.arange(20)+2),
                                  lambda n, i: 1e4 if n <= 4 else np.inf)
    assert max(result['adjusted_orders']) == 4
    assert all(r['activation_hz'] is None for r in result['transitions'] if r['order'] > 4)
