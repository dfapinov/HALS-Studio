"""Analysis estimates use native export timing and the displayed direction."""
from types import SimpleNamespace

import numpy as np
import pytest

from hals_studio.analysis.acoustics import demo
from hals_studio.application.analysis_delay import estimated_delay_ms


def owner(sphere):
    return SimpleNamespace(sphere=sphere, axis=(0., 0.), source_path=None, pool=None,
                           azimuth=SimpleNamespace(value=lambda: 90.),
                           elevation=SimpleNamespace(value=lambda: 0.),
                           export_workspace=None, export_setup=None)


def test_imported_sphere_estimates_probe_or_reference():
    sphere = demo()
    sphere.pressure[:] = np.exp(-2j*np.pi*sphere.freqs[:, None, None]*.003)
    sphere.pressure[:, *sphere.index(90., 0.)] = np.exp(-2j*np.pi*sphere.freqs*.004)
    view = owner(sphere)
    assert estimated_delay_ms(view) == pytest.approx(4.)
    assert estimated_delay_ms(view, reference=True) == pytest.approx(3.)


def test_coefficient_estimate_uses_export_native_response(tmp_path, monkeypatch):
    from hals_studio.application.export_preview import PreviewCache
    path = tmp_path/'coefficients.h5'
    path.touch()
    sphere = demo()
    sphere.metadata.update(source=str(path), radius_m=2., offset_m=[.1, .2, .3],
                           mode='External', optimized_origins=False, padding_samples_removed=73)
    view = owner(sphere)
    calls = []

    def run(self, config, index, pool, progress, cancelled):
        calls.append(config)
        freqs = np.arange(20., 20001., 10.)
        return {'freqs': freqs, 'preview_point': {'complex': np.exp(-2j*np.pi*freqs*.00555)},
                'preview_ir': np.zeros(100), 'preview_ir_times': np.arange(100)/48000.}

    monkeypatch.setattr(PreviewCache, 'run', run)
    assert estimated_delay_ms(view) == pytest.approx(5.55)
    config = calls[-1]
    assert config['subtract_tof'] == 'Off'
    assert config['obs_mode'] == 'External'
    assert config['use_optimized_origins'] is False
    assert config['ir_capture_padding_samples'] == 73
    theta, phi, radius = config['manual_coords'][0]
    theta, phi = np.deg2rad([theta, phi])
    np.testing.assert_allclose(radius*np.array([np.sin(theta)*np.cos(phi),
                                               np.sin(theta)*np.sin(phi), np.cos(theta)]),
                               [.1, 2.2, .3])
    cache = view._analysis_native_preview
    estimated_delay_ms(view, reference=True)
    assert view._analysis_native_preview is cache
    assert calls[-1]['manual_coords'] != config['manual_coords']


@pytest.mark.parametrize('ir_first', [True, False])
def test_ir_and_delay_share_response_and_invalidate(tmp_path, monkeypatch, ir_first):
    from hals_studio.application.export_preview import PreviewCache
    from hals_studio.ui.plotting.csd_plot import analysis_ir
    path = tmp_path/'coefficients.h5'
    path.touch()
    sphere = demo()
    sphere.metadata['source'] = str(path)
    view = owner(sphere)
    calls = []
    freqs = np.arange(20., 20001., 10.)
    ir = np.zeros(100)

    def run(self, config, *args):
        calls.append(config)
        return {'freqs': freqs, 'preview_point': {'complex': np.exp(-2j*np.pi*freqs*.00555)},
                'preview_ir': ir, 'preview_ir_times': np.arange(100)/48000.}

    monkeypatch.setattr(PreviewCache, 'run', run)
    if ir_first:
        assert analysis_ir(view, sphere)[0] is ir
    assert estimated_delay_ms(view) == pytest.approx(5.55)
    assert analysis_ir(view, sphere)[0] is ir
    assert estimated_delay_ms(view) == pytest.approx(5.55)
    assert len(calls) == 1
    view.azimuth.value = lambda: 45.
    estimated_delay_ms(view)
    analysis_ir(view, sphere)
    assert len(calls) == 2
    sphere.metadata['padding_samples_removed'] = 80
    analysis_ir(view, sphere)
    estimated_delay_ms(view)
    assert len(calls) == 3
    view.export_setup = {'frd_db_offset': 2.}
    estimated_delay_ms(view)
    assert len(calls) == 4
    sphere.metadata['offset_m'] = [.1, 0, 0]
    analysis_ir(view, sphere)
    assert len(calls) == 5
    path.write_bytes(b'changed')
    estimated_delay_ms(view)
    assert len(calls) == 6
