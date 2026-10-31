"""Export directivity keeps its level scale when the reference axis rotates."""
import numpy as np
import pytest

from hals_studio.application.export_directivity import export_cuts
from hals_studio.application.export_engine import DEFAULT_EXPORT, geometry


@pytest.mark.parametrize('direction, expected, indices', [
    ('+/-', [-90, 0, 90, 180], [0, 1, 2, 3]),
    ('+', [0, 90, 180], [1, 2, 3]),
    ('-', [-180, -90, 0], [3, 0, 1]),
])
def test_sweep_direction_filters_existing_samples(direction, expected, indices):
    from hals_studio.application.export_directivity import sweep_direction_indices
    actual, selected = sweep_direction_indices(np.array([-90., 0., 90., 180.]), direction)
    np.testing.assert_array_equal(actual, expected)
    np.testing.assert_array_equal(selected, indices)


@pytest.mark.parametrize('direction', ['horizontal', 'vertical'])
def test_spl_cuts_keep_absolute_levels_and_only_exported_angles(direction):
    config = dict(DEFAULT_EXPORT, direction=direction, range_deg=180, increment_deg=30, zero_phi=90.)
    layout = geometry(config)
    levels = np.arange(3*len(layout['xyz'])).reshape(3, -1) + 60.
    result = dict(config=config, geometry=layout,
                  data={str(i): {'mag': levels[:, i]} for i in range(levels.shape[1])})
    cuts = export_cuts(result, normalize=False)
    angles, actual = cuts[direction]
    assert len(angles) == 12  # One rear trace, not duplicated at both seam endpoints.
    assert -180 not in angles and 180 in angles
    assert set(actual[0]).issubset(set(levels[0]))
    assert actual.min() >= 60
    missing = 'vertical' if direction == 'horizontal' else 'horizontal'
    assert cuts[missing][1].shape == (3, 0)


@pytest.mark.parametrize('processed', [False, True])
@pytest.mark.parametrize('phi', [0., 90., 180.])
def test_full_sweep_rotation_preserves_directivity_levels(processed, phi):
    config = dict(DEFAULT_EXPORT, direction='horizontal', zero_phi=phi)
    layout = geometry(config)
    # An asymmetric fixed field, with a quieter rear and frequency-dependent
    # directivity. Changing the sweep reference must not change its contrast.
    x, y, _ = (layout['xyz'] / config['dist_mic']).T
    levels = np.array([70., 85.])[:, None] + np.array([8., 16.])[:, None]*x + 3*y
    result = dict(config=config, geometry=layout)
    if processed:
        result['processed'] = 10**(levels/20)
    else:
        result['data'] = {str(i): {'mag': levels[:, i]} for i in range(len(x))}
    angles, values = export_cuts(result)['horizontal']
    absolute = np.deg2rad(angles + phi)
    expected = np.array([8., 16.])[:, None]*np.cos(absolute) + 3*np.sin(absolute)
    expected -= expected.max(axis=1, keepdims=True)
    np.testing.assert_allclose(values, expected, atol=1e-10)
    assert values.max() == 0
    assert np.all(values.min(axis=1) < -15)
    np.testing.assert_allclose(values[:, 0], values[:, -1])
    assert len(export_cuts(result)['vertical'][0]) == 0


def test_planes_share_peak_reference_and_silent_processed_data_is_finite():
    config = dict(DEFAULT_EXPORT)
    layout = geometry(config)
    levels = 60 + 12*layout['xyz'][:, 2]/config['dist_mic']
    result = dict(config=config, geometry=layout, processed=10**(levels[None, :]/20))
    cuts = export_cuts(result)
    assert cuts['vertical'][1].max() == pytest.approx(0)
    assert cuts['horizontal'][1].max() == pytest.approx(-12)
    result['processed'][:] = 0
    for _, values in export_cuts(result).values():
        np.testing.assert_array_equal(values, 0)


def test_display_smoothing_matches_analysis_and_on_axis_is_optional():
    from hals_studio.analysis.acoustics import Sphere
    config = dict(DEFAULT_EXPORT, direction='horizontal', range_deg=90)
    layout = geometry(config)
    freqs = np.array([100., 101., 102., 200.])
    pressure = np.ones((4, len(layout['xyz'])))
    pressure[1, layout['reference']] = 10
    result = dict(config=config, geometry=layout, freqs=freqs, processed=pressure)
    original = pressure.copy()
    options = dict(smoothing='1/3 octave', directivity_on_axis=True)
    angles, values = export_cuts(result, options)['horizontal']
    # Sphere.levels uses the same energy averaging for Analysis plots.
    from types import SimpleNamespace
    levels = Sphere.levels(SimpleNamespace(pressure=pressure, freqs=freqs), 3)
    expected = levels - levels[:, layout['reference'], None]
    raw_angles = np.rad2deg(np.arctan2(layout['xyz'][:, 1], layout['xyz'][:, 0]))
    order = np.argsort(raw_angles)
    np.testing.assert_allclose(values, expected[:, order])
    np.testing.assert_allclose(values[:, angles == 0], 0)
    np.testing.assert_array_equal(pressure, original)


@pytest.mark.parametrize('on_axis', [False, True])
def test_analysis_and_export_normalize_identical_samples_identically(on_axis):
    from types import SimpleNamespace
    from hals_studio.analysis.acoustics import Sphere
    config = dict(DEFAULT_EXPORT, direction='horizontal', range_deg=90)
    layout = geometry(config)
    levels = np.arange(3*len(layout['xyz']), dtype=float).reshape(3, -1)
    result = dict(config=config, geometry=layout,
                  data={str(i): {'mag': levels[:, i]} for i in range(levels.shape[1])})
    sphere = SimpleNamespace(index=lambda: (0, layout['reference']))
    expected = Sphere.relative(sphere, levels[:, None, :], 'On axis' if on_axis else 'Peak')[:, 0]
    angles, actual = export_cuts(result, {'directivity_on_axis': on_axis})['horizontal']
    order = np.argsort(np.arctan2(layout['xyz'][:, 1], layout['xyz'][:, 0]))
    np.testing.assert_allclose(actual, expected[:, order])
