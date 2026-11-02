"""Directivity references, saved settings, and absolute-level display ranges."""
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest
from matplotlib.figure import Figure

from hals_studio.analysis.acoustics import directivity_levels, directivity_normalization
from hals_studio.ui.plotting.directivity_views import directivity_scale, draw_spectrogram, draw_cross_sonograms
from hals_studio.ui.plotting.plot_settings import default_config
from hals_studio.ui.view_state import restore_pane


@pytest.mark.parametrize('mode', ['On axis', 'Global peak', 'Off'])
def test_references_preserve_or_remove_frequency_level_as_selected(mode):
    levels = np.array([[30., 20., 35.], [80., 70., 90.]])
    actual = directivity_levels(levels, mode, levels[:, 0])
    expected = {'Off': levels, 'Global peak': levels-90.,
                'On axis': levels-levels[:, :1]}[mode]
    np.testing.assert_allclose(actual, expected)


@pytest.mark.parametrize('old, expected', [(False, 'Global peak'), (True, 'On axis')])
def test_saved_checkboxes_and_pins_migrate(old, expected):
    config = {'kind': 'map_h', 'directivity_on_axis': old, 'pins': ['directivity_on_axis']}
    restored = restore_pane(config)
    assert restored['directivity_normalization'] == expected
    assert restored['pins'] == ['directivity_normalization']
    assert 'directivity_on_axis' not in restored
    restored['directivity_normalization'] = 'Off'
    assert restore_pane(restored)['directivity_normalization'] == 'Off'
    assert directivity_normalization(config) == expected


def test_absolute_sonogram_uses_data_or_manual_limits_without_changing_samples():
    config = dict(default_config('map_h'), directivity_normalization='Off', span=36., contours=False)
    levels = np.array([[20., 25., 30.], [80., 85., 90.]])
    angles, freqs = np.array([-90., 0., 90.]), np.array([500., 2000.])
    ax = Figure().add_subplot()
    image = draw_spectrogram(ax, freqs, angles, levels, config)
    assert image.get_clim() == (54., 90.)
    np.testing.assert_allclose(image.get_array(), levels.T)
    config.update(auto_axes=False, ymin=10., ymax=100.)
    image = draw_spectrogram(ax, freqs, angles, levels, config)
    assert image.get_clim() == (10., 100.)
    np.testing.assert_allclose(image.get_array(), levels.T)
    config['directivity_normalization'] = 'Global peak'
    assert directivity_scale(config, levels)[0] == (-36., 0.)


def test_intersecting_planes_share_absolute_colour_range():
    config = dict(default_config('cross_sonograms'), directivity_normalization='Off', span=36., contours=False)
    horizontal = np.array([[20., 30., 40.], [50., 60., 70.]])
    vertical = horizontal + 10.
    sphere = SimpleNamespace(freqs=np.array([500., 2000.]),
                             cuts=lambda _: (np.array([-90., 0., 90.]), horizontal, vertical))
    pane = SimpleNamespace(config=config, plotter=Mock(), note=Mock())
    draw_cross_sonograms(pane, sphere, None)
    calls = pane.plotter.add_mesh.call_args_list
    assert len(calls) == 2
    for call in calls:
        assert call.kwargs['clim'] == (44., 80.)


def test_constant_absolute_level_has_a_finite_colour_range():
    limits, _ = directivity_scale({'directivity_normalization': 'Off', 'span': 36.}, np.ones((2, 3))*80)
    assert limits == (44., 80.)


@pytest.mark.parametrize('automatic, expected', [(True, (54., 90.)), (False, (10., 100.))])
def test_waterfall_receives_absolute_samples_and_selected_level_limits(automatic, expected):
    from hals_studio.ui.plotting.directivity_views import draw_directivity_map

    config = dict(default_config('map_h'), directivity_normalization='Off',
                  directivity_display='Waterfall', span=36., auto_axes=automatic, ymin=10., ymax=100.)
    pane = SimpleNamespace(config=config, cursor=Mock(), csd_view=Mock(), stack=Mock(),
                           interaction=Mock(), note=Mock())
    values = np.array([[20., 25., 30.], [80., 85., 90.]])
    draw_directivity_map(pane, np.array([500., 2000.]), np.array([-90., 0., 90.]), values)
    settings = pane.csd_view.render.call_args.args[2]
    assert settings['_level_limits'] == expected
    np.testing.assert_array_equal(settings['_surface_data'][2], values.T)


@pytest.mark.parametrize('mode', ['On axis', 'Global peak', 'Off'])
def test_export_cuts_use_explicit_reference_mode(mode):
    from hals_studio.application.export_directivity import export_cuts
    from hals_studio.application.export_engine import DEFAULT_EXPORT, geometry

    config = dict(DEFAULT_EXPORT, direction='horizontal', range_deg=90)
    layout = geometry(config)
    levels = np.arange(2*len(layout['xyz']), dtype=float).reshape(2, -1) + 60.
    result = dict(config=config, geometry=layout,
                  data={str(i): {'mag': levels[:, i]} for i in range(levels.shape[1])})
    angles, actual = export_cuts(result, {'directivity_normalization': mode})['horizontal']
    expected = {'Off': levels, 'Global peak': levels-levels.max(),
                'On axis': levels-levels[:, layout['reference'], None]}[mode]
    order = np.argsort(np.arctan2(layout['xyz'][:, 1], layout['xyz'][:, 0]))
    np.testing.assert_allclose(actual, expected[:, order])


@pytest.mark.parametrize('span', [24., 36., 48.])
def test_off_auto_uses_full_dataset_peak_and_configured_span(span):
    config = dict(default_config('map_h'), directivity_normalization='Off',
                  span=span, _directivity_peak=92.)
    # The peak can be outside the displayed cut or at another frequency.
    limits, _ = directivity_scale(config, np.array([10., 50., 80.]))
    assert limits == (92.-span, 92.)


def test_off_auto_polars_match_global_peak_geometry():
    from hals_studio.ui.plotting.plots import draw_polar_cuts

    angles = np.array([-180., -90., 0., 90.])
    levels = np.array([[40., 62., 72., 65.], [50., 80., 90., 82.]])
    chart = SimpleNamespace(fig=Figure(), width=lambda: 800, height=lambda: 400, done=Mock())
    pane = SimpleNamespace(config=dict(default_config('polar'), directivity_normalization='Off', span=36.),
                           directivity_peak=92.)
    cuts = {plane: (angles, levels) for plane in ('horizontal', 'vertical')}
    draw_polar_cuts(chart, cuts, 0, 36., pane=pane)
    absolute = [next(line for line in ax.lines if line.get_gid() == 'directivity-trace').get_xydata().copy()
                for ax in chart.fig.axes]
    pane.config['directivity_normalization'] = 'Global peak'
    cuts = {plane: (angles, levels-92.) for plane in ('horizontal', 'vertical')}
    draw_polar_cuts(chart, cuts, 0, 36., pane=pane)
    for ax, expected in zip(chart.fig.axes, absolute):
        trace = next(line for line in ax.lines if line.get_gid() == 'directivity-trace')
        np.testing.assert_allclose(trace.get_xydata(), expected)
