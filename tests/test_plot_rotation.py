"""Circular plots share rotation gestures and persist angles in saved views."""
from types import SimpleNamespace
from unittest.mock import Mock
import json

import hals_studio.bootstrap as bootstrap
import numpy as np
import pytest
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg
from hals_studio.ui.plotting.plot_settings import default_config
from hals_studio.ui.plotting.plot_interaction import PlotInteraction
from hals_studio.ui.plotting.plots import draw_zoomable_polars


def test_polar_rotation_handle_rotates_plot_and_survives_redraw():
    fig = Figure(figsize=(9, 5))
    canvas = FigureCanvasAgg(fig)
    canvas.setCursor = Mock()
    canvas.unsetCursor = Mock()
    chart = SimpleNamespace(fig=fig, canvas=canvas, width=lambda: 900,
                            height=lambda: 500, done=canvas.draw)
    sphere = SimpleNamespace(cuts=lambda _: (np.arange(-180, 181, 90),
                                            np.zeros((1, 5)), np.zeros((1, 5))))
    pane = SimpleNamespace(chart=chart, config=default_config('polar'))
    draw_zoomable_polars(chart, sphere, None, 0, 36, pane=pane)
    ax = fig.axes[1]
    np.testing.assert_allclose(pane._polar_transforms[ax].transform([0, 1]), [1, 0], atol=1e-10)
    center = ax.transAxes.transform((.5, .5))
    grip = ax.transAxes.transform(pane._rotation_handles[ax])
    interaction = SimpleNamespace(pane=pane, main_ax=fig.axes[0], axes=fig.axes,
                                  rotation_drag=None, pan=None, dragging=False)
    PlotInteraction.press(interaction, SimpleNamespace(button=1, x=grip[0], y=grip[1]))
    assert interaction.rotation_drag is not None
    delta = grip-center
    target = center + np.array([-delta[1], delta[0]])
    PlotInteraction.move(interaction, SimpleNamespace(x=target[0], y=target[1]))
    PlotInteraction.release(interaction, None)
    assert pane.config['polar_rotation'] == {'horizontal': 0., 'vertical': 0.}
    draw_zoomable_polars(chart, sphere, None, 0, 36, pane=pane)
    np.testing.assert_allclose(pane._polar_transforms[fig.axes[1]].transform([0, 1]), [0, 1], atol=1e-10)


@pytest.mark.parametrize('enabled', [False, True])
@pytest.mark.parametrize('workspace', ['analysis', 'export'])
def test_sample_angle_dots_follow_pane_option(enabled, workspace):
    from hals_studio.ui.plotting.export_directivity import ExportDirectivityPanel
    from unittest.mock import patch
    fig = Figure(figsize=(9, 5)); canvas = FigureCanvasAgg(fig)
    chart = SimpleNamespace(fig=fig, canvas=canvas, width=lambda: 900,
                            height=lambda: 500, done=canvas.draw)
    angles = np.array([-90., 0., 90.]); values = np.zeros((1, 3))
    pane = SimpleNamespace(chart=chart, config=default_config('polar'))
    pane.config['polar_sample_points'] = enabled
    if workspace == 'analysis':
        sphere = SimpleNamespace(cuts=lambda _: (angles, values, values))
        draw_zoomable_polars(chart, sphere, None, 0, 36, pane=pane)
    else:
        pane.options = {'polar_sample_points': enabled}
        pane.result = {'freqs': np.array([1000.])}; pane.kind = 'polar'
        pane.frequency = Mock(); pane.frequency.value.return_value = 1000.
        pane.span = Mock(); pane.span.value.return_value = 36.
        pane.settings_button = Mock(); pane.interaction = Mock(); pane.note = Mock()
        with patch('hals_studio.ui.plotting.export_directivity.export_cuts',
                   return_value={key: (angles, values) for key in ('horizontal', 'vertical')}):
            ExportDirectivityPanel.redraw(pane)
    traces = [line for ax in fig.axes for line in ax.lines if line.get_gid() == 'directivity-trace']
    assert len(traces) == 2
    assert all(line.get_marker() == ('.' if enabled else 'None') for line in traces)


def test_view_round_trip_preserves_independent_rotations():
    from hals_studio.ui.workspace import Workspace
    panes = [SimpleNamespace(config=default_config(kind), plotter=None, invalidate=Mock())
             for kind in ['globe_hv', 'polar', 'probe', 'reference']]
    panes[0].config['globe_rotation'] = {'horizontal': 30., 'vertical': 120.}
    panes[1].config['polar_rotation'] = {'horizontal': 10., 'vertical': 90.}
    workspace = SimpleNamespace(panes=panes, outer=Mock(sizes=lambda: [600, 400]),
                                rows=[Mock(sizes=lambda: [1, 1])]*2,
                                valid_view=lambda _: True, rebuild_pins=Mock(), refresh=Mock())
    saved = json.loads(json.dumps(Workspace.view_dict(workspace)))
    panes[0].config['globe_rotation']['vertical'] = 0.
    Workspace.apply_view(workspace, saved)
    assert panes[0].config['globe_rotation'] == {'horizontal': 30., 'vertical': 120.}
    assert panes[1].config['polar_rotation'] == {'horizontal': 10., 'vertical': 90.}


@pytest.mark.parametrize('export_points', [False, True])
def test_polar_signed_directions_match_top_and_side_views(export_points):
    from hals_studio.ui.plotting.plots import draw_polar_cuts
    fig = Figure(figsize=(9, 5)); canvas = FigureCanvasAgg(fig)
    chart = SimpleNamespace(fig=fig, canvas=canvas, width=lambda: 900,
                            height=lambda: 500, done=canvas.draw)
    angles = np.array([-90., 0., 90.])
    values = np.array([[-12., 0., -6.]])
    pane = SimpleNamespace(chart=chart, config=default_config('polar'))
    draw_polar_cuts(chart, {plane: (angles, values) for plane in ('horizontal', 'vertical')},
                    0, 36, pane=pane, close_curves=not export_points, show_points=export_points)
    for ax, expected in zip(fig.axes, ([[-30., 0.], [24., 0.]], [[0., 30.], [0., -24.]])):
        trace = next(line for line in ax.lines if line.get_gid() == 'directivity-trace')
        points = np.column_stack([trace.get_xdata(), trace.get_ydata()])
        displayed = ax.transData.inverted().transform(trace.get_transform().transform(points))
        np.testing.assert_allclose(displayed[[2, 0]], expected, atol=1e-10)
        for prefix, direction in zip(('+90', '\N{MINUS SIGN}90'), expected):
            label = next(text for text in ax.texts if text.get_text().startswith(prefix))
            location = ax.transData.inverted().transform(label.get_transform().transform(label.get_position()))
            np.testing.assert_allclose(location/np.linalg.norm(location), np.array(direction)/np.linalg.norm(direction), atol=1e-10)


@pytest.mark.parametrize('close_curves', [True, False])
def test_globe_coordinates_match_top_and_side_views(close_curves):
    from hals_studio.ui.plotting.directivity_views import draw_globe_cuts
    fig = Figure(figsize=(9, 5)); canvas = FigureCanvasAgg(fig)
    chart = SimpleNamespace(fig=fig, canvas=canvas, done=canvas.draw)
    pane = SimpleNamespace(chart=chart, config=default_config('globe_hv'),
                           interaction=SimpleNamespace(finish=lambda axes: None), note=Mock())
    f = np.array([100., 1000., 10000.]); angles = np.arange(-180., 181., 90.)
    cuts = {plane: (angles, np.zeros((3, 5))) for plane in ('horizontal', 'vertical')}
    draw_globe_cuts(pane, f, cuts, close_curves=close_curves)
    horizontal, vertical = fig.axes[:2]
    assert horizontal.get_theta_offset() % (2*np.pi) == pytest.approx(np.pi/2)
    assert vertical.get_theta_offset() % (2*np.pi) == pytest.approx(0.)
    for ax in (horizontal, vertical):
        assert ax.get_theta_direction() == 1
