"""Circular plots share rotation gestures and persist angles in saved views."""
from types import SimpleNamespace
from unittest.mock import Mock
import json

import hals_studio.bootstrap as bootstrap
import numpy as np
import pytest
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg
from hals_studio.ui.panes import default_config
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
    assert default_config('globe_hv')['globe_rotation']['vertical'] == 90.
