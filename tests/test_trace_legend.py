"""Legend placement follows response data, including independent phase/DI axes."""
from types import SimpleNamespace
from unittest.mock import Mock

import hals_studio.bootstrap as bootstrap
import numpy as np
import pytest
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from hals_studio.ui.plotting.trace_legend import trace_legend


def test_legend_moves_with_secondary_trace_and_avoids_fit_note():
    fig = Figure(figsize=(8, 5))
    canvas = FigureCanvasAgg(fig)
    ax = fig.add_subplot()
    secondary = ax.twinx()
    ax.set(xlim=(0, 1), ylim=(0, 1))
    secondary.set_ylim(0, 1)
    ax.plot([0, 1], [.5, .5], label='SPL')
    line, = secondary.plot([0, 1], [.95, .95], label='DI')
    ax.text(.02, .97, 'Trend fit annotation', va='top', transform=ax.transAxes)
    legend = trace_legend(ax, [secondary])
    canvas.draw()
    first = legend.get_window_extent().frozen()
    assert not line.get_transform().transform_path(line.get_path()).intersects_bbox(first)
    assert not first.overlaps(ax.texts[0].get_window_extent())
    # Move a trace through the chosen location: the next draw must choose again.
    level = secondary.transData.inverted().transform((first.x0, (first.y0+first.y1)/2))[1]
    line.set_ydata([level, level])
    canvas.draw()
    second = legend.get_window_extent().frozen()
    assert not np.allclose(first.bounds, second.bounds)
    assert not line.get_transform().transform_path(line.get_path()).intersects_bbox(second)
    assert [text.get_text() for text in legend.texts] == ['SPL', 'DI']
    # Manual placement remains stable across redraws.
    legend.set_loc((.2, .3))
    canvas.draw()
    manual = legend.get_window_extent().frozen()
    line.set_ydata([.1, .1])
    canvas.draw()
    np.testing.assert_allclose(legend.get_window_extent().bounds, manual.bounds)
    legend.remove()
    assert ax.get_legend() is None


@pytest.mark.parametrize('kind', ['probe', 'reference', 'sweep_h', 'sweep_v',
                                 'cea', 'reflections', 'cea_Sound power DI'])
@pytest.mark.parametrize('fit', [False, True])
def test_response_kinds_share_automatic_legend(kind, fit):
    from hals_studio.analysis.acoustics import demo
    from hals_studio.ui.plotting.plot_settings import default_config
    from hals_studio.ui.plotting.response_plot import draw_chart

    sphere = demo()
    levels = sphere.levels()
    metrics = {name: levels[:, 0, 0] for name in
               ['On axis', 'Listening window', 'Early reflections', 'Sound power',
                'Sound power DI', 'Early reflections DI', 'Floor', 'Ceiling',
                'Front wall', 'Side walls', 'Rear wall']}
    owner = SimpleNamespace(axis=(0, 0), azimuth=Mock(value=lambda: 0),
                            elevation=Mock(value=lambda: 0), get_cea=lambda _: metrics)
    fig = Figure()
    canvas = FigureCanvasAgg(fig)
    pane = SimpleNamespace(config=dict(default_config(kind), fit=fit, overlays=False),
                           owner=owner, chart=SimpleNamespace(fig=fig, done=canvas.draw),
                           interaction=Mock(), cursor=Mock(), note=Mock(),
                           delay_ms=lambda: 0, delay_note='')
    draw_chart(pane, sphere, levels, levels, 0)
    legend = fig.axes[0].get_legend()
    assert legend is not None
    assert legend._loc == 0  # Matplotlib's automatic 'best' placement.
    expected = [line.get_label() for ax in fig.axes for line in ax.lines
                if not line.get_label().startswith('_')]
    assert [text.get_text() for text in legend.texts] == expected
    assert len(fig.axes[0].artists) == 0  # No duplicate legend artists.


def test_fit_box_has_priority_over_dense_traces_and_reset_restores_auto():
    from hals_studio.ui.plotting.plot_interaction import PlotInteraction
    fig = Figure(figsize=(8, 5))
    canvas = FigureCanvasAgg(fig)
    ax = fig.add_subplot()
    ax.set(xlim=(0, 1), ylim=(0, 1))
    x = np.linspace(0, 1, 10000)
    ax.plot(x, .45+.4*np.sin(x*1000), label='Dense SPL')
    note = ax.text(.02, .97, 'Fit info: slope and deviation', va='top',
                   transform=ax.transAxes, bbox=dict(pad=6, facecolor='black'))
    legend = trace_legend(ax)
    canvas.draw()
    assert not legend.get_window_extent().overlaps(note.get_bbox_patch().get_window_extent())
    legend.set_loc((.1, .8))
    interaction = SimpleNamespace(saved={0: 'zoom'}, axes=[ax],
                                  full={0: ((0, 1), (0, 1))},
                                  pane=SimpleNamespace(chart=SimpleNamespace(canvas=canvas)))
    PlotInteraction.reset(interaction)
    assert legend._loc == 0
    assert not interaction.saved
    assert not legend.get_window_extent().overlaps(note.get_bbox_patch().get_window_extent())


def test_double_click_di_legend_selects_marker_readout():
    from matplotlib.backend_bases import MouseEvent
    from hals_studio.ui.plotting.spl_cursor import SPLCursor
    fig = Figure()
    canvas = FigureCanvasAgg(fig)
    ax = fig.add_subplot()
    di_ax = ax.twinx()
    ax.plot([100, 1000], [80, 85], label='Sound power')
    di_ax.plot([100, 1000], [2, 6], label='Sound power DI')
    legend = trace_legend(ax, [di_ax])
    label = Mock()
    pane = SimpleNamespace(chart=SimpleNamespace(canvas=canvas), owner=SimpleNamespace(
        sphere=SimpleNamespace(freqs=np.array([100, 1000])), frequency=Mock(value=lambda: 1)))
    cursor = SPLCursor(pane, label)
    cursor.bind(ax, di_ax=di_ax)
    canvas.draw()
    box = legend.texts[1].get_window_extent()
    cursor.press(MouseEvent('button_press_event', canvas, (box.x0+box.x1)/2,
                            (box.y0+box.y1)/2, button=1, dblclick=True))
    assert cursor.active == 'Sound power DI'
    label.setText.assert_called_with('1000 Hz, 6.0 dB')
    assert not cursor.phase
