import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent / 'process_engine'))
from stage2_centre_origin import export_interpolated_origins
import stage2_centre_origin as origin_export


class FileMapping(dict):
    @property
    def files(self):
        return list(self)


def test_rerun_clears_outside_range_and_preserves_interpolation(monkeypatch):
    saved = {}
    monkeypatch.setattr(origin_export.tempfile, 'mkstemp', lambda **kwargs: (123, 'temporary.npz'))
    monkeypatch.setattr(origin_export.os, 'close', lambda fd: None)
    monkeypatch.setattr(origin_export.np, 'savez', lambda path, **values: saved.update(values))
    replacements = []
    monkeypatch.setattr(origin_export.os, 'replace', lambda source, target: replacements.append((source, target)))
    freqs = np.array([20., 499., 500., 510., 750., 990., 1000., 1001., 20000.])
    data = FileMapping(freqs=freqs, origins_mm=np.full((len(freqs), 3), 99.), pressure=np.arange(len(freqs)))
    origins = export_interpolated_origins(
        [510., 990.], [10., 30.], [20., 40.], [30., 50.], freqs,
        data, '.', 'data.npz', True, test_range_hz=(500., 1000.), hold_origin_lf=False, hold_origin_hf=False)
    np.testing.assert_array_equal(origins[[0, 1, 7, 8]], 0.)
    np.testing.assert_allclose(origins[2:7], [[10, 20, 30], [10, 20, 30],
                                           [20, 30, 40], [30, 40, 50], [30, 40, 50]])
    np.testing.assert_array_equal(saved['origins_mm'], origins)
    np.testing.assert_array_equal(saved['pressure'], data['pressure'])
    assert len(replacements) == 1


def test_export_defaults_to_holding_both_endpoints():
    origins = export_interpolated_origins([500., 1000.], [10., 20.], [0., 0.], [0., 0.],
                                          np.array([499., 500., 750., 1000., 1001.]),
                                          {}, '', '', False)
    np.testing.assert_array_equal(origins[:, 0], [10., 10., 15., 20., 20.])


def test_lf_and_hf_hold_can_be_set_independently():
    for hold_lf in (False, True):
        for hold_hf in (False, True):
            result = export_interpolated_origins(
                [100., 19500.], [10., 20.], [2., 4.], [3., 6.],
                np.array([0., 50., 100., 19500., 24000.]), {}, '', '', False,
                test_range_hz=(100., 20000.), hold_origin_lf=hold_lf, hold_origin_hf=hold_hf)
            np.testing.assert_array_equal(result[0], [10., 2., 3.] if hold_lf else [0., 0., 0.])
            np.testing.assert_array_equal(result[-1], [20., 4., 6.] if hold_hf else [0., 0., 0.])
            np.testing.assert_array_equal(result[2:4], [[10., 2., 3.], [20., 4., 6.]])
