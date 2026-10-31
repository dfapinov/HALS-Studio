from types import SimpleNamespace
from unittest.mock import Mock, patch
from pathlib import Path
import pytest

import numpy as np
from matplotlib.figure import Figure

from hals_studio.ui.plotting.origin_editing import metadata_points, line_edits, OriginLineEditor


def test_waypoints_use_captured_geometry_and_exclude_structural_points():
    grid = dict(wp_tw_r=100, wp_tw_phi=90, wp_tw_z=250,
                wp_ref_origin_r=500, wp_ref_origin_phi=0, wp_ref_origin_z=0,
                user_positions=[dict(name='Port', r=50, phi=180, z=-80), dict(r='bad')])
    points = metadata_points(grid)
    assert [name for name, _ in points] == ['Tweeter', 'Port']
    np.testing.assert_allclose(points[0][1], [0, 100, 250], atol=1e-10)
    np.testing.assert_allclose(points[1][1], [-50, 0, -80], atol=1e-10)
    assert metadata_points({}) == []


def test_drag_interpolates_in_log_frequency_without_mutating_other_coordinates():
    rows = {f: dict(final_c=[1, 2, 3]) for f in [10, 100, 1000, 10000, 20000]}
    edits = line_edits(rows, 1, (10000, 40), (100, 20))
    assert [f for f, _ in edits] == [100, 1000, 10000]
    np.testing.assert_allclose([xyz for _, xyz in edits], [[1, 20, 3], [1, 30, 3], [1, 40, 3]])
    assert all(row['final_c'] == [1, 2, 3] for row in rows.values())
    assert line_edits(rows, 0, (100, 1), (100, 5)) == []


def test_pen_gate_cancel_and_save():
    fig = Figure(); ax = fig.add_subplot()
    workspace = SimpleNamespace(job=False, draw_origin_line=Mock(), run=Mock(),
                                results={2: [{100: dict(final_c=[1, 2, 3])}]})
    editor = OriginLineEditor(fig.canvas, [ax], workspace)
    event = lambda x, y: SimpleNamespace(button=1, inaxes=ax, xdata=x, ydata=y)
    workspace.draw_origin_line.isChecked.return_value = False
    editor.press(event(50, 10)); assert editor.start is None
    workspace.draw_origin_line.isChecked.return_value = True
    editor.press(event(50, 10)); editor.key(SimpleNamespace(key='escape'))
    editor.release(event(200, 30)); workspace.run.assert_not_called()
    editor.press(event(50, 10)); editor.move(event(200, 30)); editor.release(event(200, 30))
    workspace.run.assert_called_once()
    action, edits = workspace.run.call_args.args
    assert action == 'save_origins' and edits[0][0] == 100
    np.testing.assert_allclose(edits[0][1], [20, 2, 3])


@pytest.mark.parametrize('preview_only', [False, True])
def test_saved_graph_edits_recalculate_error_with_cached_order_caps(monkeypatch, preview_only):
    from hals_studio.application import process_stages
    from hals_studio.process_engine import stage2_centre_origin as engine
    rows = {100.: dict(final_c=np.zeros(3), error=1.)}
    cfg = dict(speed_of_sound=340., target_n_max_origins=4,
               manual_order_table={200.: 6}, N_grid=3)
    result = (rows, np.array([100.]), ['mic'], {'mic': np.array([2j])}, ([], [], []), cfg, {})
    monkeypatch.setattr(process_stages.process_cache, 'load', lambda *args: result)
    monkeypatch.setattr(process_stages.process_cache, 'hydrate_stage2', lambda *args: result)
    solve = Mock(return_value=12.5)
    monkeypatch.setattr(engine, 'solve_physics_3d', solve)
    class ReachedExport(Exception):
        pass
    def export(*args, **kwargs):
        raise ReachedExport
    monkeypatch.setattr(engine, 'export_interpolated_origins', export)
    export_mock=Mock(side_effect=export)
    monkeypatch.setattr(engine, 'export_interpolated_origins', export_mock)
    request=dict(name='test', action='save_origins', cache='cache', preview_only=preview_only,
                 origin_result=result, settings={'target_n_max_origins': 9}, edits=[(100., [10., 20., 30.])])
    if preview_only:
        preview=process_stages.search_origins(request, None, Path('.'), 'data.npz', 'input')
        export_mock.assert_not_called()
        assert preview[0][100.]['error']==12.5
        assert preview[3] is None
    else:
        with pytest.raises(ReachedExport):
            process_stages.search_origins(request, None, Path('.'), 'data.npz', 'input')
    assert solve.call_args.args[:3] == (10., 20., 30.)
    assert solve.call_args.args[3][-2] == 3
    assert rows[100.]['error'] == 12.5
    np.testing.assert_array_equal(rows[100.]['original_c'], [0, 0, 0])


def test_pen_motion_reuses_background_and_preserves_limits(monkeypatch):
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    fig = Figure(); canvas = FigureCanvasAgg(fig); ax = fig.add_subplot()
    ax.plot([100, 1000], [0, 10]); ax.set_xscale('log'); canvas.draw()
    limits = (ax.get_xlim(), ax.get_ylim())
    workspace = SimpleNamespace(job=False, draw_origin_line=Mock())
    editor = OriginLineEditor(canvas, [ax], workspace)
    event = lambda x, y: SimpleNamespace(button=1, inaxes=ax, xdata=x, ydata=y)
    editor.press(event(100, 2))
    draw = Mock(wraps=canvas.draw); monkeypatch.setattr(canvas, 'draw', draw)
    for x in range(200, 900, 10):
        editor.move(event(x, 6))
    draw.assert_not_called()
    assert (ax.get_xlim(), ax.get_ylim()) == limits
    editor.on_resize(None)
    editor.move(event(900, 7))
    assert editor.background is not None
    editor.clear()
    assert editor.background is None and len(ax.lines) == 1


def test_preview_service_returns_in_memory_without_writing_cache(monkeypatch):
    from hals_studio.application import process_service
    result=object()
    monkeypatch.setitem(process_service.STAGE_RUNNERS, 2, lambda *args: result)
    monkeypatch.setattr(Path, 'is_file', lambda self: True)
    mkdir=Mock(); save=Mock()
    monkeypatch.setattr(Path, 'mkdir', mkdir)
    monkeypatch.setattr(process_service.process_cache, 'save', save)
    assert process_service.run(dict(stage=2, settings={}, folder='.', name='test',
        cache='cache.pkl', action='save_origins', preview_only=True)) is result
    mkdir.assert_not_called(); save.assert_not_called()


def test_validation_navigation_and_current_positions_only(monkeypatch):
    from PySide6.QtWidgets import QApplication
    from matplotlib.backend_bases import MouseEvent
    from hals_studio.ui.plotting.process_results import Results
    app=QApplication.instance() or QApplication([])
    host=Results()
    rows={f:dict(final_c=[i, i+10, i+20], original_c=[50, 60, 70], error=i+1.2345, original_error=99)
          for i,f in enumerate([100., 200., 400., 800.])}
    workspace=SimpleNamespace(stage=2, owner=SimpleNamespace(project_path='test'),
        results={2:[rows]}, view=SimpleNamespace(currentText=lambda:'Validation'),
        selected_origin_waypoints=lambda:[], draw_origin_line=SimpleNamespace(isChecked=lambda:True),
        job=False, run=Mock())
    host.draw(workspace); host.canvas.draw()
    ax=host.interaction.axes[0]
    assert len(ax.lines)==2
    from matplotlib.text import Annotation
    error_labels=[text for text in ax.texts if isinstance(text,Annotation)]
    offsets=[text.get_position()[1] for text in error_labels]
    assert min(offsets)<0<max(offsets)
    assert offsets==[7, -7, 7, -7]
    assert [text.get_text() for text in error_labels]==['1%', '2%', '3%', '4%']
    assert all(text.get_fontsize()==7 for text in error_labels)
    assert host.box.count()==1
    assert host.origin_point_details in host.fig.texts
    assert host.origin_point_details.axes is None
    assert all(axis.get_legend() is None for axis in host.fig.axes)
    from PySide6.QtWidgets import QToolTip
    show=Mock()
    monkeypatch.setattr(QToolTip,'showText',show)
    for axis_index,axis in enumerate(host.interaction.axes):
        px,py=axis.transData.transform((200.,rows[200.]['final_c'][axis_index]))
        event=MouseEvent('motion_notify_event',host.canvas,px,py)
        host.canvas.callbacks.process('motion_notify_event',event)
    show.assert_not_called()
    px,py=host.interaction.axes[2].transData.transform((200.,11.+10))
    for name in ('button_press_event','button_release_event'):
        host.canvas.callbacks.process(name,MouseEvent(name,host.canvas,px,py,button=1))
    assert host.origin_selection.selected_frequency==200.
    assert host.origin_point_details.get_text()=='200 Hz | Fit error: 2.23%\nX: 1.00 mm | Y: 11.00 mm | Z: 21.00 mm'
    for axis,marker in enumerate(host.origin_selection.markers):
        np.testing.assert_allclose(marker.get_xdata(),[200.])
        np.testing.assert_allclose(marker.get_ydata(),[rows[200.]['final_c'][axis]])
    workspace.run.assert_not_called()
    x,y=ax.transData.transform((300.,1.5))
    host.interaction.wheel(MouseEvent('scroll_event',host.canvas,x,y,button='up',step=1))
    zoomed=ax.get_xlim(); assert zoomed!=host.interaction.full[0][0]
    host.interaction.press(MouseEvent('button_press_event',host.canvas,x,y,button=2))
    assert host.interaction.pan_preview is not None
    with patch.object(host.canvas,'draw_idle',wraps=host.canvas.draw_idle) as redraw:
        with patch.object(host.canvas,'blit',wraps=host.canvas.blit) as blit:
            for delta in range(2,11,2):
                host.interaction.move(MouseEvent('motion_notify_event',host.canvas,x+delta,y+delta,button=2))
            assert blit.call_count==5
            redraw.assert_not_called()
        host.interaction.release(MouseEvent('button_release_event',host.canvas,x+10,y+10,button=2))
        redraw.assert_called_once()
    assert host.interaction.pan_preview is None
    assert all(not item.get_animated() for axis in host.interaction.axes for item in [*axis.lines,*axis.texts])
    panned=(ax.get_xlim(),ax.get_ylim()); assert panned[0]!=zoomed
    host.draw(workspace)
    assert host.origin_selection.selected_frequency==200.
    assert 'Fit error: 2.23%' in host.origin_point_details.get_text()
    assert (host.interaction.axes[0].get_xlim(),host.interaction.axes[0].get_ylim())==panned
    host.interaction.reset()
    assert host.interaction.axes[0].get_xlim()==host.interaction.full[0][0]
    host.close()


def test_save_project_applies_pending_origins_and_retains_them_on_failure(monkeypatch):
    from hals_studio.ui.process_workspace import ProcessWorkspace
    from hals_studio.application import process_stages
    from hals_studio.persistence import process_cache
    result=object()
    hydrate=Mock(return_value=result); persist=Mock(return_value=result); save=Mock()
    monkeypatch.setattr(process_cache,'hydrate_stage2',hydrate)
    monkeypatch.setattr(process_cache,'save',save)
    monkeypatch.setattr(process_cache,'compact',lambda *args:result)
    monkeypatch.setattr(process_stages,'persist_origin_result',persist)
    workspace=SimpleNamespace(origin_edits_pending=True,job=False,results={2:result},
        measurement_path=lambda:Path('outputs/test.npz'),values={2:{}},cache=lambda _:Path('stage2.pkl'),
        origin_edit_note=Mock())
    save.side_effect=OSError('disk unavailable')
    with pytest.raises(OSError):ProcessWorkspace.save_pending_origins(workspace)
    assert workspace.origin_edits_pending
    save.side_effect=None
    ProcessWorkspace.save_pending_origins(workspace)
    persist.assert_called_with(result,{},Path('outputs'),'test.npz')
    assert not workspace.origin_edits_pending
    save.reset_mock()
    ProcessWorkspace.save_pending_origins(workspace)
    save.assert_not_called()
