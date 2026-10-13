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
