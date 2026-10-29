"""Populated views, settings dialogs and export cancellation regression checks."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from copy import deepcopy
import threading
import time

import numpy as np
import pytest
from PySide6 import QtCore as C, QtWidgets as W

from hals_studio.ui.view_state import default_views, restore_view, template_views, valid_view


@pytest.fixture
def window(tmp_path):
    from hals_studio.ui.workspace import Workspace

    app = W.QApplication.instance() or W.QApplication([])
    widget = Workspace(
        start_pool=False,
        settings=C.QSettings(str(tmp_path / "workspace.ini"), C.QSettings.IniFormat),
    )
    yield widget
    widget.close()
    pump_until(app, lambda: widget._close_ready)


def pump_until(app, predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    assert predicate()


def test_export_set_gain_controls_and_restore(window):
    from hals_studio.ui.project_ui import ensure_export
    pane = ensure_export(window)
    assert not pane.config['normalize_ir_set']
    assert pane.config['ir_target_peak_dbfs'] == -6
    pane.apply_config(dict(pane.config, mode='Arc sweep', generate_ir_files=True,
                           normalize_ir_set=True, ir_target_peak_dbfs=-9))
    assert pane.controls['generate_ir_files'].isEnabled()
    assert pane.controls['normalize_ir_set'].isEnabled()
    assert pane.controls['ir_target_peak_dbfs'].isEnabled()
    assert pane.controls['ir_target_peak_dbfs'].value() == -9
    pane.apply_config(dict(pane.config, mode='CTA-2034'))
    for key in ('generate_ir_files', 'normalize_ir_set', 'ir_target_peak_dbfs'):
        assert not pane.controls[key].isEnabled()
    pane.apply_config(dict(pane.config, mode='Arc sweep'))
    assert pane.controls['ir_target_peak_dbfs'].isEnabled()
    pane.controls['normalize_ir_set'].setChecked(False)
    assert not pane.controls['ir_target_peak_dbfs'].isEnabled()
    pane.controls['generate_ir_files'].setChecked(False)
    assert not pane.controls['normalize_ir_set'].isEnabled()


def test_process_forms_keep_stage_values_and_control_dependencies(window):
    from hals_studio.ui.process_forms import StageForms
    from hals_studio.ui.process_workspace import SCHEMA

    values = {
        int(stage): {key: deepcopy(spec["default"]) for key, spec in fields.items()}
        for stage, fields in SCHEMA.items()
    }
    forms = StageForms(SCHEMA, values, window)
    assert forms.count() == 4
    assert len(forms.controls) == sum(len(fields) for fields in SCHEMA.values())
    previous = values[2]["freq_start_hz"]
    forms.controls[3, "freq_start_hz"].setText("1234")
    assert values[3]["freq_start_hz"] == "1234"
    assert values[2]["freq_start_hz"] == previous
    gain, peak = forms.controls[1, "enable_auto_gain"], forms.controls[1, "target_peak_db"]
    for enabled in (True, False):
        gain.setChecked(enabled)
        assert values[1]["enable_auto_gain"] is enabled
        assert peak.isEnabled() is enabled
    edit = next(
        button
        for button in forms.findChildren(W.QPushButton)
        if button.text() == "Edit manual order table"
    )
    optimizer = forms.controls[4, "condition_preflight"]
    for manual in (True, False):
        forms.controls[4, "use_manual_table"].setChecked(manual)
        assert optimizer.isEnabled() is not manual
        assert edit.isEnabled() is manual
    for enabled in (True, False):
        forms.controls[4, "enable_regularization"].setChecked(enabled)
        for key in ("noise_floor_start_db", "noise_floor_max_db", "max_lambda"):
            field = forms.controls[4, key]
            label = field.parentWidget().layout().labelForField(field)
            assert field.isHidden() is not enabled
            assert label.isHidden() is not enabled
    toggle, group = forms.advanced[2]
    toggle.click()
    assert not group.isHidden() and toggle.arrowType() == C.Qt.DownArrow
    toggle.click()
    assert group.isHidden() and toggle.arrowType() == C.Qt.RightArrow
    requested = []
    forms.rft_reset_requested.connect(lambda: requested.append("rft"))
    forms.edit_orders_requested.connect(lambda: requested.append("orders"))
    forms.rft_reset_button.click()
    forms.controls[4, "use_manual_table"].setChecked(True)
    edit.click()
    assert requested == ["rft", "orders"]
    forms.deleteLater()


@pytest.mark.parametrize("kind", ["impulse", "csd", "wavelet"])
def test_time_renderer_rejects_sparse_bins_and_recovers_with_native_bins(window, kind):
    from hals_studio.analysis.acoustics import demo

    sphere = demo()
    window.set_sphere(sphere)
    pane = window.panes[1]
    pane.set_kind(kind)
    pane.config.update(csd_mode="Sonogram", csd_auto_time=False, csd_time=5.0, wavelet_duration=5.0)
    pane.invalidate()
    pane.render()
    assert pane.stack.currentWidget() is pane.chart_frame
    assert "unavailable" in pane.note.text()
    assert "native frequency bins" in pane.chart.fig.axes[0].texts[0].get_text()
    # Changing data must replace the error view with an actual time plot.
    sphere.freqs = np.linspace(100, 20000, len(sphere.freqs))
    pane.invalidate()
    pane.render()
    if kind == "impulse":
        assert pane.stack.currentWidget() is pane.ir_panel
        assert pane.ir_panel.chart.fig.axes[0].lines
    else:
        assert pane.stack.currentWidget() is pane.csd_view
        assert pane.csd_view.config["csd_method"] == ("CSD" if kind == "csd" else "Morlet wavelet")
        assert all(np.isfinite(array).all() for array in pane.csd_view.data)
    pane.set_kind("probe")
    pane.render()
    assert pane.stack.currentWidget() is pane.chart_frame
    assert pane.chart.fig.axes[0].lines


@pytest.mark.parametrize("kind", ["map_h", "map_v"])
def test_directivity_renderer_switches_surface_and_chart_without_losing_settings(window, kind):
    from hals_studio.analysis.acoustics import demo

    window.set_sphere(demo())
    pane = window.panes[1]
    pane.set_kind(kind)
    pane.config.update(directivity_display="Waterfall", span=42.0)
    pane.render()
    assert pane.stack.currentWidget() is pane.csd_view
    view = pane.csd_view
    expected = tuple(array.copy() for array in view.data)
    pane.config["directivity_display"] = "Sonogram"
    pane.render()
    assert pane.stack.currentWidget() is pane.chart_frame
    pane.config["directivity_display"] = "Waterfall"
    pane.render()
    assert pane.csd_view is view
    assert pane.config["span"] == 42.0
    for actual, original in zip(view.data, expected):
        np.testing.assert_array_equal(actual, original)


def test_analysis_scene_switching_reuses_plotter_and_restores_probe_controls(window):
    from hals_studio.analysis.acoustics import demo

    window.set_sphere(demo())
    pane = window.panes[1]
    pane.set_kind("balloon")
    pane.render()
    plotter = pane.plotter
    assert pane._scene_kind == "balloon"
    assert not pane.probe_controls.isHidden()
    pane.set_kind("cross_sonograms")
    pane.render()
    assert pane.plotter is plotter
    assert pane._scene_kind == "cross_sonograms"
    assert pane.probe_controls.isHidden()
    pane.set_kind("polar")
    pane.render()
    assert pane.stack.currentWidget() is pane.chart_frame
    pane.set_kind("balloon")
    pane.render()
    assert pane.plotter is plotter
    assert pane._scene_kind == "balloon"
    assert not pane.probe_controls.isHidden()
    assert not pane.frequency_controls.isHidden()


def test_view_restoration_keeps_user_choices_and_does_not_alias_snapshots():
    view = default_views()["Sound field"]
    legacy = dict(
        kind="volume",
        symmetric=False,
        pins=["symmetric"],
        smoothing="1/12 octave",
        volume_mode="Coverage envelopes",
    )
    view["panes"][0] = legacy
    view["panes"][1]["smoothing"] = "1/3 octave"
    view["panes"][1]["overlay_traces"] = [dict(name="saved", magnitude=[1.0, 2.0])]
    original = deepcopy(view)
    restored = restore_view(view)
    assert restored["panes"][0]["kind"] == "cross_sonograms"
    assert restored["panes"][0]["sweep_direction"] == "+"
    assert restored["panes"][0]["pins"] == ["sweep_direction"]
    assert restored["panes"][0]["smoothing"] == "None"
    assert restored["panes"][1]["smoothing"] == "1/3 octave"
    restored["panes"][1]["overlay_traces"][0]["magnitude"][0] = 99
    assert view == original


@pytest.mark.parametrize("panes", [None, {}, [None] * 4, ["probe"] * 4, [{"kind": "unknown"}] * 4])
def test_invalid_view_is_rejected_before_use(panes):
    assert not valid_view({"panes": panes})
    with pytest.raises(ValueError, match="four recognized"):
        restore_view({"panes": panes})


def test_templates_skip_invalid_entries_and_keep_valid_views():
    import json

    view = default_views()["CEA2034"]
    assert template_views(json.dumps({"bad": {"panes": None}, "saved": view})) == {"saved": view}
    assert template_views("not json") == default_views()


def test_view_collection_rename_reorder_and_delete_preserve_other_snapshots():
    from hals_studio.ui.view_state import ViewCollection

    original = default_views()
    collection = ViewCollection(original)
    collection.current = "Sound field"
    collection.rename("Directivity", "Custom")
    assert collection.current == "Sound field"
    collection.reorder(["Custom", "missing", "Sound field", "Custom"])
    assert list(collection.views) == ["Custom", "Sound field", "Globes", "CEA2034"]
    target = collection.remove("Sound field")
    assert target == "Custom"
    collection.remember(original["Sound field"])
    assert collection.views[target] == original["Directivity"]
    collection.current = target
    snapshot = deepcopy(collection.views[target])
    collection.add("New view", snapshot)
    snapshot["panes"][0]["offset"] = 123
    assert collection.views["New view"]["panes"][0]["offset"] == 0
    assert collection.views["Custom"] == original["Directivity"]


def test_delete_current_view_does_not_overwrite_destination(window):
    window.load_view("Directivity")
    expected = deepcopy(window.views["Sound field"])
    window.delete_view()
    assert window.current_view == "Sound field"
    assert "Directivity" not in window.views
    assert window.views["Sound field"] == expected
    assert [pane.config["kind"] for pane in window.panes] == [p["kind"] for p in expected["panes"]]


def test_populated_view_switching_and_session_restoration(window):
    from hals_studio.analysis.acoustics import demo

    window.set_sphere(demo())
    window.load_view("Sound field")
    pane = window.panes[1]
    pane.config.update(offset=7.0, smoothing="1/3 octave", pins=["offset"])
    pane.config["overlay_traces"] = [
        dict(
            name="reference take",
            visible=False,
            freqs=[100.0, 1000.0],
            real=[1.0, 2.0],
            imag=[0.0, 0.0],
        )
    ]
    pane.invalidate()
    window.refresh()
    before = [
        np.asarray(line.get_ydata()).copy() for axis in pane.chart.fig.axes for line in axis.lines
    ]
    window.load_view("CEA2034")
    window.load_view("Sound field")
    assert pane.config["offset"] == 7.0
    assert pane.config["smoothing"] == "1/3 octave"
    after = [np.asarray(line.get_ydata()) for axis in pane.chart.fig.axes for line in axis.lines]
    assert len(before) == len(after)
    for expected, actual in zip(before, after):
        np.testing.assert_allclose(actual, expected)
    state = deepcopy(window.session_dict())
    window.load_view("Directivity")
    window.pending_session = state
    window.apply_pending_session()
    assert pane.config["overlay_traces"][0]["name"] == "reference take"
    assert pane.config["pins"] == ["offset"]
    assert window.pending_session is None
    # A malformed fourth pane cannot replace the first three visible panes.
    existing = [deepcopy(p.config) for p in window.panes]
    invalid = deepcopy(state["view"])
    invalid["panes"][3] = None
    with pytest.raises(ValueError):
        window.apply_view(invalid)
    assert [p.config for p in window.panes] == existing


def test_plot_setup_applies_manual_limits_only_when_accepted(window):
    from hals_studio.ui.pane_setup import Setup

    pane = window.panes[1]
    original = deepcopy(pane.config)
    dialog = Setup(pane)
    dialog.controls["ymin"].setValue(-75.0)
    assert not dialog.values["auto_axes"]
    assert pane.config == original
    dialog.reject()
    assert pane.config == original
    dialog.deleteLater()
    dialog = Setup(pane)
    dialog.controls["ymin"].setValue(-65.0)
    dialog.pin_checks["ymin"].setChecked(True)
    dialog.accept()
    assert dialog.result() == W.QDialog.Accepted
    assert dialog.values["ymin"] == -65.0
    assert "ymin" in dialog.values["pins"]
    dialog.deleteLater()


def test_export_controller_cancellation_and_restart_run_on_gui_thread(tmp_path):
    from hals_studio.application.export_controller import ExportController
    from hals_studio.application.export_engine import DEFAULT_EXPORT
    from hals_studio.application.job_coordinator import JobCoordinator
    from hals_studio.analysis.acoustics import Cancelled

    app = W.QApplication.instance() or W.QApplication([])
    jobs = JobCoordinator()
    controller = ExportController(jobs)
    source = tmp_path / "coefficients.h5"
    source.touch()
    config = dict(deepcopy(DEFAULT_EXPORT), coeff_path=str(source), range_deg=0.0)
    entered = threading.Event()
    release = threading.Event()
    snapshots = []

    class Preview:
        def run(self, request, index, pool, progress, cancelled):
            snapshots.append(request)
            entered.set()
            while not release.wait(0.005):
                if cancelled():
                    raise Cancelled()
            return {"point": index}

    received, completions = [], []
    controller.completed.connect(
        lambda result, generation, writing: received.append(
            (result, generation, writing, C.QThread.currentThread() is app.thread())
        )
    )
    controller.finished.connect(
        lambda cancelled: completions.append((cancelled, jobs.busy(), controller.job))
    )
    try:
        assert controller.start(config, None, False, Preview(), 2, 7)
        assert entered.wait(3)
        config["frd_prefix"] = "changed while working"
        assert snapshots[0]["frd_prefix"] != config["frd_prefix"]
        assert not controller.start(config, None, False, Preview(), 3, 8)
        controller.cancel()
        pump_until(app, lambda: controller.job is None)
        assert received == []
        assert completions == [(True, False, None)]
        release.set()
        assert controller.start(config, None, False, Preview(), 3, 8)
        pump_until(app, lambda: controller.job is None)
        assert received == [({"point": 3}, 8, False, True)]
        assert completions[-1] == (False, False, None)
    finally:
        controller.cancel()
        release.set()
        pump_until(app, lambda: controller.job is None)


def test_export_ignores_stale_preview_and_closes_running_work(window, tmp_path):
    from hals_studio.analysis.acoustics import Cancelled

    app = W.QApplication.instance()
    export = window.export_workspace
    export.completed({"unexpected": "stale"}, export.generation - 1, False)
    assert export.result is None
    entered = threading.Event()

    class Preview:
        def run(self, config, index, pool, progress, cancelled):
            entered.set()
            deadline = time.monotonic() + 3
            while not cancelled() and time.monotonic() < deadline:
                time.sleep(0.005)
            assert cancelled()
            raise Cancelled()

    source = tmp_path / "coefficients.h5"
    source.touch()
    export.config["coeff_path"] = str(source)
    export.preview_cache = Preview()
    export.start(False)
    assert entered.wait(3)
    export.pending_preview = True
    window.close()
    pump_until(app, lambda: window._close_ready)
    assert export.job is None and export.result is None
    assert not export.timer.isActive()


def test_export_restores_analysis_panes_as_export_defaults(window):
    from hals_studio.ui.project_ui import ensure_export
    workspace = ensure_export(window)
    for pane, expected in zip(workspace.custom_panes, ('response', 'csd', 'impulse')):
        pane.restore(dict(mode='analysis', native_kind='response', plot=dict(kind='phase')))
        assert pane.mode == 'native'
        assert pane.native_kind == expected
        assert 'plot' not in pane.state()
        assert not hasattr(pane, 'analysis')
    assert workspace.previous.parent() is not workspace.response_panel
    assert workspace.next.parent() is workspace.previous.parent()


def test_export_cursor_uses_displayed_response_and_survives_rebuild():
    from types import SimpleNamespace
    from matplotlib.backend_bases import MouseEvent
    from hals_studio.ui.plotting.export_charts import ResponsePanel
    app = W.QApplication.instance() or W.QApplication([])
    panel = ResponsePanel(SimpleNamespace(config={}))
    panel.resize(1000, 500)
    f = np.array([100., 1000., 10000.])
    mag = np.array([-20., -10., -30.])
    phase = np.array([170., -170., -150.])
    panel.update_response(f, mag, phase, 'Point 1', 'source')
    panel.chart.canvas.draw()
    x, y = panel.ax.transData.transform((1000., -15.))
    event = MouseEvent('button_press_event', panel.chart.canvas, x, y, button=1)
    panel.select_frequency(event)
    assert '1000 Hz, -10.0 dB, -170.0' in panel.cursor_label.text()
    assert panel.frequency_marker.get_visible()
    panel.config['wrapped'] = False
    panel.update_response(f, mag+5, phase, 'Point 2', 'source')
    assert '-5.0 dB, 190.0' in panel.cursor_label.text()
    np.testing.assert_allclose(panel.frequency_marker.get_xdata(), [1000., 1000.])
    panel.chart.canvas.draw()
    assert panel.background is not None
    panel.close()


def test_cta_export_panes_show_metrics_and_restore_sweep(window):
    from hals_studio.ui.project_ui import ensure_export
    from hals_studio.process_engine.stage5_extract_pressures import CTA2034_METRIC_NAMES
    workspace = ensure_export(window)
    workspace.config.update(mode='CTA-2034', coeff_path='example.h5', frd_db_offset=12.)
    f = np.array([100., 1000., 10000.])
    workspace.result = dict(freqs=f, config=dict(workspace.config), metrics={
        key: (np.full(3, 2. if name.endswith(' DI') else 60.), np.zeros(3))
        for key, name in CTA2034_METRIC_NAMES.items()})
    workspace.dirty = False
    workspace.draw_response()
    first, second, third = workspace.custom_panes
    assert first.cta_kind == 'cea' and second.cta_kind == 'reflections'
    assert third.stack.currentWidget() is third.cta_info
    assert '70' in third.cta_info.text() and 'Arc Sweep mode' in third.cta_info.text()
    assert workspace.rows[1].widget(0) is third
    assert workspace.rows[1].widget(1) is second
    panel = first.cta_panel
    np.testing.assert_allclose(panel.cursor.lines['On axis'].get_ydata(), 72.)
    np.testing.assert_allclose(panel.cursor.lines['Sound power DI'].get_ydata(), 2.)
    menu = W.QMenu(); first.add_export_choices(menu)
    titles = [action.text() for action in menu.actions()]
    assert 'Spinorama overview' in titles and 'SPL / phase' not in titles
    assert 'Directivity' not in titles
    third.select_cta('cea_On axis')
    assert third.stack.currentWidget() is third.cta_panel
    third.select_cta_info()
    assert third.stack.currentWidget() is third.cta_info
    first.select_cta('cea_Predicted in-room')
    assert list(panel.cursor.lines) == ['Predicted in-room']
    first.select_cta('cea_Sound power DI')
    assert list(panel.cursor.lines) == ['Sound power DI']
    workspace.dirty = True
    workspace.draw_response()
    assert first.stack.currentWidget() is first.empty
    workspace.config['mode'] = 'Arc sweep'
    workspace.draw_response()
    assert first.stack.currentWidget() is first.native
    assert workspace.rows[1].widget(0) is second
    menu = W.QMenu(); first.add_export_choices(menu)
    assert 'Spinorama overview' not in [action.text() for action in menu.actions()]


def test_cta_preview_worker_uses_aggregate_export(monkeypatch):
    from types import SimpleNamespace
    from hals_studio.infrastructure import export_job
    calls = []
    monkeypatch.setattr(export_job, 'run_export', lambda *args: calls.append(args) or {})
    cache = SimpleNamespace(run=lambda *args: pytest.fail('CTA preview must evaluate all points'))
    worker = export_job.ExportWorker({'mode': 'CTA-2034'}, None, False, cache)
    worker.run()
    assert len(calls) == 1 and calls[0][2] is False


def test_export_partial_directivity_and_preview_demand(window):
    from hals_studio.ui.project_ui import ensure_export
    from hals_studio.application.export_engine import DEFAULT_EXPORT, geometry, needs_aggregate_preview
    from hals_studio.application.export_directivity import export_cuts
    workspace = ensure_export(window)
    config = dict(DEFAULT_EXPORT, coeff_path='example.h5', direction='horizontal', range_deg=90)
    layout = geometry(config)
    frequencies = np.array([100., 1000., 10000.])
    data = {str(i): dict(mag=np.array([60., 65., 70.])-i) for i in range(len(layout['xyz']))}
    result = dict(config=config, geometry=layout, freqs=frequencies, data=data)
    cuts = export_cuts(result)
    angles, levels = cuts['horizontal']
    assert angles[0] == -90 and angles[-1] == 90
    assert len(cuts['vertical'][0]) == 0
    np.testing.assert_allclose(levels[:, np.flatnonzero(angles == 0)[0]], 0.)
    workspace.config.update(config); workspace.result = result; workspace.dirty = False
    pane = workspace.custom_panes[0]
    pane.select_directivity('polar')
    assert needs_aggregate_preview(workspace.config)
    panel = pane.directivity_panel
    assert panel is pane.stack.currentWidget()
    trace = next(line for line in panel.chart.fig.axes[0].lines if line.get_gid() == 'directivity-trace')
    assert trace.get_marker() == '.'
    assert len(trace.get_xdata()) == len(angles)
    assert set(panel._rotation_axes.values()) == {'horizontal'}
    panel.chart.canvas.draw()
    from types import SimpleNamespace
    axis = next(iter(panel._rotation_axes))
    center = axis.transAxes.transform((.5, .5))
    handle = axis.transAxes.transform(panel._rotation_handles[axis])
    panel.interaction.press(SimpleNamespace(button=1, x=handle[0], y=handle[1], inaxes=None))
    assert panel.interaction.rotation_drag is not None
    angle = np.deg2rad(30)
    rotated = np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]]) @ (handle-center) + center
    panel.interaction.move(SimpleNamespace(x=rotated[0], y=rotated[1]))
    panel.interaction.release(None)
    assert panel.config['polar_rotation']['horizontal'] == 30.
    panel.frequency.setValue(2000.)
    assert panel.config['polar_rotation']['horizontal'] == 30.
    assert not panel.chart.fig.axes[1].axison
    for kind in ('map_h', 'map_v', 'globe_hv'):
        pane.select_directivity(kind)
        panel.chart.canvas.draw()
        if kind == 'globe_hv':
            assert set(panel._rotation_axes.values()) == {'horizontal'}
    workspace.dirty = True
    pane.select_native('response')
    assert not needs_aggregate_preview(workspace.config)


def test_preview_demand_tracks_visible_cta_and_directivity_panes():
    from hals_studio.application.export_engine import needs_aggregate_preview
    assert needs_aggregate_preview(dict(mode='CTA-2034'))
    panes = [dict(mode='cli'), dict(mode='cli'), dict(mode='native')]
    assert not needs_aggregate_preview(dict(mode='CTA-2034', plot_panes=panes))
    panes[0] = dict(mode='native')
    assert needs_aggregate_preview(dict(mode='CTA-2034', plot_panes=panes))
    assert not needs_aggregate_preview(dict(mode='Arc sweep', plot_panes=panes))
    panes[1] = dict(mode='directivity')
    assert needs_aggregate_preview(dict(mode='Arc sweep', plot_panes=panes))


def test_export_selection_recolours_existing_point(window):
    from hals_studio.ui.project_ui import ensure_export
    workspace = ensure_export(window)
    mesh = workspace.plotter.renderer.actors['points'].mapper.dataset
    original = mesh['base_rgb'].copy()
    workspace.selected = 1
    workspace.highlight()
    np.testing.assert_array_equal(mesh['rgb'][1], [255, 69, 69])
    workspace.selected = 2
    workspace.highlight()
    np.testing.assert_array_equal(mesh['rgb'][1], original[1])
    np.testing.assert_array_equal(mesh['rgb'][2], [255, 69, 69])
    assert 'selected' not in workspace.plotter.renderer.actors


def test_stage4_defers_analysis_and_prompts_for_each_new_revision(window, tmp_path, monkeypatch):
    from hals_studio.analysis.acoustics import demo
    from hals_studio.application import analysis_controller
    from hals_studio.ui.project_ui import ensure_export
    import h5py
    path = tmp_path/'coefficients.h5'
    with h5py.File(path, 'w') as stream: stream['freqs'] = [100., 1000., 10000.]
    window.set_workspace(2)
    process = window.process_workspace
    monkeypatch.setattr(process, 'coefficient_path', lambda: path)
    prompts, jobs = [], []
    accepted = [False, True, True]
    class Dialog:
        def __init__(self, source, parent): prompts.append(str(source))
        def exec(self): return W.QDialog.Accepted if accepted.pop(0) else W.QDialog.Rejected
        def options(self): return {'radius': 3.5, 'bins': 120}
    monkeypatch.setattr(analysis_controller, 'ReconstructionDialog', Dialog)
    def start(fn, kwargs, source, options):
        jobs.append((source, options))
        controller = window.analysis
        controller.job_source = str(path.resolve()); controller.job_options = options
        controller.job_stamp = controller.coefficient_stamp(path)
        controller.job_loaded(demo())
    monkeypatch.setattr(window.analysis, 'start_job', start)
    # Completion publishes coefficients to Export but must not open a dialog or start Analysis.
    assert process.reload_coefficients(force=True)
    assert not prompts and not jobs and window.sphere is None
    export = ensure_export(window)
    monkeypatch.setattr(export, 'preview_if_live', lambda: None)
    process.publish(1)
    assert not prompts and not jobs
    window.set_workspace(0)
    assert len(prompts) == 1 and not jobs  # Cancellation is not a successful analysis.
    window.set_workspace(2); process.publish(0)
    assert len(prompts) == 2 and jobs[0][1]['radius'] == 3.5
    window.set_workspace(1); window.set_workspace(0)
    assert len(prompts) == 2 and len(jobs) == 1
    # Stage 4 may overwrite the same filename; it needs its own first-use settings.
    with h5py.File(path, 'a') as stream: stream['new_revision'] = [1., 2., 3.]
    window.set_workspace(2)
    assert process.reload_coefficients(force=True)
    assert len(jobs) == 1 and window.sphere is None
    process.publish(0)
    assert len(prompts) == 3 and len(jobs) == 2


def test_analysis_magnitude_categories_are_exclusive(window):
    from hals_studio.ui.plotting.plot_settings import selected_magnitudes
    from hals_studio.ui.view_state import restore_pane
    pane = window.panes[1]
    pane.set_kind('probe')
    pane.toggle_magnitude('reference')
    assert selected_magnitudes(pane.config) == ['probe', 'reference']
    pane.toggle_magnitude('cea')
    assert selected_magnitudes(pane.config) == ['cea']
    assert pane.config['phase_mode'] == 'None'
    pane.toggle_magnitude('cea_Predicted in-room')
    assert selected_magnitudes(pane.config) == ['cea', 'cea_Predicted in-room']
    pane.toggle_magnitude('probe')
    assert selected_magnitudes(pane.config) == ['probe']
    pane.set_kind('cea'); pane.select_phase('Total phase')
    assert selected_magnitudes(pane.config) == ['probe']
    restored = restore_pane(dict(kind='cea', magnitude_selection=['probe', 'cea'], phase_mode='Total phase'))
    assert restored['magnitude_selection'] == ['cea'] and restored['phase_mode'] == 'None'


def test_cta_and_cursor_rendering_match_analysis(window):
    from types import SimpleNamespace
    from hals_studio.analysis.acoustics import demo
    from hals_studio.ui.plotting.export_cta import CTAPanel
    from hals_studio.ui.plotting.export_charts import ResponsePanel
    from hals_studio.process_engine.stage5_extract_pressures import CTA2034_METRIC_NAMES
    sphere = demo(); window.set_sphere(sphere)
    analysis = window.panes[1]
    analysis.set_kind('cea'); analysis.config['overlays'] = False; analysis.render()
    metrics = window.get_cea('None')
    result = dict(freqs=sphere.freqs, config={'frd_db_offset': 0.}, metrics={
        key: (metrics[name], np.zeros(len(sphere.freqs))) for key, name in CTA2034_METRIC_NAMES.items()})
    export = CTAPanel(); export.update_metrics(result, 'cea')
    for panel in (analysis, export):
        assert panel.phase_handle is not None
        assert panel.interaction.phase_ax is panel.phase_axis
    for left, right in zip(analysis.chart.fig.axes, export.chart.fig.axes):
        assert left.get_ylabel() == right.get_ylabel()
        np.testing.assert_allclose(left.get_ylim(), right.get_ylim())
        ltraces = {line.get_label(): line for line in left.lines if not line.get_label().startswith('_')}
        rtraces = {line.get_label(): line for line in right.lines if not line.get_label().startswith('_')}
        assert ltraces.keys() == rtraces.keys()
        for name in ltraces:
            np.testing.assert_allclose(ltraces[name].get_ydata(), rtraces[name].get_ydata())
            assert ltraces[name].get_color() == rtraces[name].get_color()
    spl = ResponsePanel(SimpleNamespace(config={}))
    spl.update_response(sphere.freqs, metrics['On axis'], np.zeros(len(sphere.freqs)), 'Selected mic', 'source')
    for marker in (export.frequency_marker, spl.frequency_marker):
        for getter in ('get_color', 'get_linewidth', 'get_linestyle', 'get_alpha'):
            assert getattr(marker, getter)() == getattr(analysis.frequency_marker, getter)()
    export.close(); spl.close()


def test_analysis_entry_waits_for_export_but_not_after_leaving(window, tmp_path, monkeypatch):
    path = tmp_path/'coefficients.h5'; path.write_bytes(b'available')
    controller = window.analysis
    controller.available_path = str(path)
    requests = []
    monkeypatch.setattr(controller, 'open_path', lambda *args: requests.append(args))
    window.jobs.active['export'] = object()
    controller.activate_coefficients()
    assert not requests
    window.jobs.active.clear(); window.jobs.idle.emit()
    assert len(requests) == 1
    window.jobs.active['export'] = object()
    controller.activate_coefficients()
    window.set_workspace(2)
    window.jobs.active.clear(); window.jobs.idle.emit()
    assert len(requests) == 1


def test_import_controls_and_legacy_options_use_automatic_origins(window, tmp_path, monkeypatch):
    import h5py
    from hals_studio.ui.app import ReconstructionDialog
    from hals_studio.ui.project_ui import ensure_export
    from hals_studio.ui.process_workspace import SCHEMA
    path = tmp_path/'coefficients.h5'
    with h5py.File(path, 'w') as stream: stream['freqs'] = [100., 1000., 10000.]
    dialog = ReconstructionDialog(path, window)
    assert not hasattr(dialog, 'origins') and not hasattr(dialog, 'offsets')
    assert not dialog.padding.isEnabled()
    dialog.manual_padding.setChecked(True); dialog.padding.setValue(75)
    assert dialog.padding.isEnabled() and dialog.options()['padding'] == 75
    dialog.manual_padding.setChecked(False)
    assert not dialog.padding.isEnabled() and dialog.options()['padding'] == 50
    requests = []
    monkeypatch.setattr(window.analysis, 'start_job', lambda *args: requests.append(args))
    window.analysis.open_path(path, dict(origins=False, offset=[1., 2., 3.], padding=75))
    _, kwargs, _, saved = requests[-1]
    assert kwargs['origins'] is True and kwargs['offset'] == [0., 0., 0.]
    assert kwargs['padding'] == 75 and saved['manual_padding'] is True
    assert 'manual_padding' not in kwargs
    window.analysis.open_path(path, dict(padding=75, manual_padding=False))
    assert requests[-1][1]['padding'] == 50
    export = ensure_export(window)
    export.apply_config(dict(export.config, use_optimized_origins=False))
    assert 'use_optimized_origins' not in export.controls
    assert export.config['use_optimized_origins'] is True
    assert 'use_optimized_origins' not in SCHEMA['4']
    dialog.close()
