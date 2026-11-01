"""Legend placement follows response data, including independent phase/DI axes."""
from types import SimpleNamespace
from unittest.mock import Mock

import hals_studio.bootstrap as bootstrap
import numpy as np
import pytest
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from hals_studio.ui.plotting.trace_legend import trace_legend


def test_frequency_cursor_does_not_displace_an_upper_right_legend():
    fig = Figure(figsize=(6, 4))
    canvas = FigureCanvasAgg(fig)
    ax = fig.add_subplot()
    ax.set(xlim=(0, 1), ylim=(0, 1))
    ax.plot([0, 1], [.3, .3], label='SPL')
    cursor = ax.axvline(.96, gid='frequency-cursor')
    legend = trace_legend(ax)
    canvas.draw()
    box = legend.get_window_extent().frozen()
    assert box.x1 > ax.bbox.x1 - 10
    assert box.y1 > ax.bbox.y1 - 10
    assert cursor.get_transform().transform_path(cursor.get_path()).intersects_bbox(box)
    cursor.set_xdata([.1, .1])
    canvas.draw()
    np.testing.assert_allclose(legend.get_window_extent().bounds, box.bounds)


def test_legend_uses_space_above_shortened_di_axis_without_covering_fit_note():
    fig = Figure(figsize=(5.8, 4.2))
    canvas = FigureCanvasAgg(fig)
    ax = fig.add_axes([.1, .12, .78, .82])
    di = fig.add_axes([.1, .12, .78, .36], frameon=False, sharex=ax)
    di.xaxis.set_visible(False)
    di.yaxis.tick_right()
    di.yaxis.set_label_position('right')
    di.set_ylabel('DI / dB')
    ax.set(xlim=(0, 1), ylim=(0, 1))
    di.set_ylim(0, 15)
    for i, label in enumerate(['On axis', 'Listening window', 'Early reflections', 'Sound power']):
        ax.plot([0, 1], [.55 + i * .04] * 2, label=label)
    ax.plot([0, 1], [.7, .7], '--', label='Fit - On axis')
    di.plot([0, 1], [2, 9], label='Sound power DI')
    di.plot([0, 1], [1, 6], label='Early reflections DI')
    note = ax.text(.02, .97, 'On axis: -0.16 dB/oct | 3.01 dB max\n100-10k Hz | RMS 0.97 dB',
                   va='top', fontsize=8, transform=ax.transAxes,
                   bbox=dict(pad=3, facecolor='black'))
    ax.axvline(.65, gid='frequency-cursor')
    legend = trace_legend(ax, [di])
    canvas.draw()
    box = legend.get_window_extent()
    assert box.y1 > ax.bbox.y1 - 10
    assert ax.bbox.x1 < box.x1 < fig.bbox.x1
    assert not box.overlaps(note.get_bbox_patch().get_window_extent())
    for axis in [ax, di]:
        for line in axis.lines:
            if line.get_gid() != 'frequency-cursor':
                assert not line.get_transform().transform_path(line.get_path()).intersects_bbox(box)


def test_hidden_traces_do_not_block_legend_and_sampling_does_not_bias_placement():
    fig = Figure(figsize=(6, 4))
    canvas = FigureCanvasAgg(fig)
    ax = fig.add_subplot()
    di = ax.twinx()
    ax.set(xlim=(0, 1), ylim=(0, 1))
    di.set_ylim(0, 1)
    spl, = ax.plot([0, 1], [.85, .85], label='SPL')
    di.plot([0, 1], [.1, .9], label='DI')
    hidden, = di.plot([0, 1], [.98, .98], label='Hidden DI', visible=False)
    legend = trace_legend(ax, [di])
    canvas.draw()
    before = legend.get_window_extent().frozen()
    level = di.transData.inverted().transform((before.x0, (before.y0 + before.y1) / 2))[1]
    hidden.set_ydata([level, level])
    spl.set_data(np.linspace(0, 1, 10000), np.full(10000, .85))
    canvas.draw()
    np.testing.assert_allclose(legend.get_window_extent().bounds, before.bounds)
    # Invisible lines remain in the legend but do not reserve plotting space.
    assert hidden.get_transform().transform_path(hidden.get_path()).intersects_bbox(before)


def test_automatic_legend_does_not_shrink_axes_on_repeated_draws():
    fig = Figure(figsize=(5.8, 4.2), layout='constrained')
    canvas = FigureCanvasAgg(fig)
    ax = fig.add_subplot()
    di = fig.add_axes([.1, .1, .8, .35], frameon=False, sharex=ax)
    di.set_in_layout(False)
    di.xaxis.set_visible(False)
    ax.set(xlim=(0, 1), ylim=(0, 1))
    di.set_ylim(0, 1)
    ax.plot([0, 1], [.3, .3], label='Sound power')
    di.plot([0, 1], [.1, .2], label='Sound power DI')
    trace_legend(ax, [di])
    canvas.draw()
    original = ax.get_position().frozen()
    for _ in range(3):
        canvas.draw()
        np.testing.assert_allclose(ax.get_position().bounds, original.bounds, atol=1e-6)


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


@pytest.mark.parametrize('kind, fit', [('probe', False), ('sweep_h', True),
                                      ('cea', True), ('reflections', False),
                                      ('cea_Sound power DI', False)])
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
    expected = [line.get_label() for ax in fig.axes for line in ax.lines
                if not line.get_label().startswith('_')]
    assert [text.get_text() for text in legend.texts] == expected


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
                                  pane=SimpleNamespace(config={}, chart=SimpleNamespace(canvas=canvas)))
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


def test_collision_simplification_preserves_narrow_peaks():
    fig = Figure(figsize=(6, 4))
    canvas = FigureCanvasAgg(fig)
    ax = fig.add_subplot()
    ax.set(xlim=(0, 1), ylim=(0, 1))
    x = np.linspace(0, 1, 16000)
    y = np.full_like(x, .1)
    y[np.argmin(abs(x - .95))] = 1
    line, = ax.plot(x, y, label='Narrow peak')
    legend = trace_legend(ax)
    canvas.draw()
    assert not line.get_transform().transform_path(line.get_path()).intersects_bbox(
        legend.get_window_extent(), filled=False)


def test_legend_placement_does_not_modify_plotted_data():
    fig = Figure(figsize=(6, 4))
    canvas = FigureCanvasAgg(fig)
    ax = fig.add_subplot()
    x = np.linspace(0, 1, 16000)
    line, = ax.plot(x, np.sin(x * 10), label='SPL')
    legend = trace_legend(ax)
    original = line.get_path().vertices.copy()
    threshold = line.get_path().simplify_threshold
    canvas.draw()
    np.testing.assert_array_equal(line.get_path().vertices, original)
    assert line.get_path().simplify_threshold == threshold


@pytest.mark.parametrize('blocked_corners', range(5))
def test_legend_avoids_traces_as_corners_become_occupied(blocked_corners):
    fig = Figure(figsize=(6, 4))
    canvas = FigureCanvasAgg(fig)
    ax = fig.add_subplot()
    ax.set(xlim=(0, 1), ylim=(0, 1))
    ax.plot([.4, .6], [.5, .5], label='SPL')
    # Block corners in preference order, leaving the top middle clear.
    for x, y in [( .95, .96), (.05, .96), (.95, .04), (.05, .04)][:blocked_corners]:
        ax.plot([x, x], [y - .04, y + .04], label='_nolegend_')
    legend = trace_legend(ax)
    canvas.draw()
    renderer = canvas.get_renderer()
    box = legend.get_window_extent(renderer)
    for line in ax.lines:
        assert not line.get_transform().transform_path(line.get_path()).intersects_bbox(box, filled=False)
