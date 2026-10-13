"""Stage 1 annotations and the shared SPL navigation contract."""
import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.backend_bases import MouseEvent
from hals_studio.process_engine.plot_views import FDWView


def make_view():
    f = np.geomspace(10, 24000, 600)
    centers = np.geomspace(100, 19000, 24)[::-1]
    meta = dict(f_trans=3500, f_centers=centers, t_windows=16/centers,
                alpha_sched=np.full(24, .5), t_peak=.002)
    view = FDWView(figsize=(12, 8))
    FigureCanvasAgg(view.fig)
    view.update_view('sample', 0, f, 10**((-50 + 3*np.sin(np.log(f)))/20),
                     None, meta, np.zeros(4096), 48000, 5)
    return view


def test_window_labels_reposition_on_pan_and_stay_staggered():
    view = make_view()
    ax = view.ax1
    ax.set_ylim(-100, -30)
    view.fig.canvas.draw()
    labels = view.window_labels.labels
    initial = [label.get_position()[1] for label in labels]
    assert max(initial) < .5
    assert len(set(initial)) == 3
    reflection = next(t for t in ax.texts if t.get_text() == 'Reflection free range')
    assert reflection.get_window_extent().y0 > ax.bbox.y1
    # Put the trace directly through the default bottom rows.
    ax.set_ylim(-60, 10)
    view.fig.canvas.draw()
    assert min(t.get_position()[1] for t in labels) > min(initial)
    assert len(set(t.get_position()[1] for t in labels)) == 3
    ax.set_xlim(1000, 10000)
    view.fig.canvas.draw()
    assert all(t.get_visible() == (1000 <= t.get_position()[0] <= 10000) for t in labels)
    ax.set_xlim(10, 24000)
    ax.set_ylim(-100, -30)
    view.fig.canvas.draw()
    np.testing.assert_allclose([t.get_position()[1] for t in labels], initial)


def test_fdw_shared_zoom_pan_and_reset():
    from PySide6.QtWidgets import QApplication
    from hals_studio.ui.plotting.process_results import Results
    app = QApplication.instance() or QApplication([])
    view = make_view()
    host = Results()
    from types import SimpleNamespace
    from unittest.mock import patch
    workspace = SimpleNamespace(stage=1, view=SimpleNamespace(currentText=lambda: 'FDW'))
    with patch('hals_studio.ui.plotting.process_renderers.renderer_for', return_value=lambda *_: view):
        host.draw(workspace)
    host.canvas.draw()
    ax = view.ax1
    from hals_studio.ui.plotting.trace_legend import trace_legend
    legend = trace_legend(ax)
    host.canvas.draw()
    original = (ax.get_xlim(), ax.get_ylim())
    waveform_limits = (view.ax2.get_xlim(), view.ax2.get_ylim())
    x, y = ax.transAxes.transform((.5, .5))
    def send(name, **kwargs):
        event = MouseEvent(name, host.canvas, x, y, **kwargs)
        host.canvas.callbacks.process(name, event)
    send('scroll_event', button='up', step=1)
    assert np.ptp(np.log(ax.get_xlim())) < np.ptp(np.log(original[0]))
    assert np.ptp(ax.get_ylim()) < np.ptp(original[1])
    zoomed_y = ax.get_ylim()
    send('button_press_event', button=2)
    y += 30
    with patch.object(legend, '_search_position', wraps=legend._search_position) as search:
        send('motion_notify_event', button=2)
        host.canvas.draw()
        host.canvas.draw()
        assert search.call_count > 0  # Placement remains live before release.
    send('button_release_event', button=2)
    assert not np.allclose(ax.get_ylim(), zoomed_y)
    np.testing.assert_allclose(view.ax3.get_xlim(), ax.get_xlim())
    np.testing.assert_allclose((view.ax2.get_xlim(), view.ax2.get_ylim()), waveform_limits)
    host.interaction.reset()
    host.canvas.draw()
    np.testing.assert_allclose((ax.get_xlim(), ax.get_ylim()), original)
    host.close()
