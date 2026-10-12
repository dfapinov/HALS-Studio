"""Regression contracts for engine isolation, cancellation, and persisted state."""

import json
import logging
import os
import pickle
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import hals_studio.bootstrap as bootstrap
import numpy as np
import pytest
from PySide6 import QtCore as C, QtWidgets as W
from hals_studio.process_engine.runtime import EngineRuntime, ProcessingCancelled
from hals_studio.application.process_contracts import ProcessRequest, OriginResult


def pump_until(predicate, timeout=5):
    app = W.QApplication.instance() or W.QApplication([])
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    assert predicate()


@pytest.mark.parametrize("stage", [0, 5, True, 1.5, "bad"])
def test_invalid_stage_has_no_filesystem_side_effect(tmp_path, stage):
    import hals_studio.application.process_service as process_service

    with pytest.raises(ValueError):
        process_service.run(
            dict(
                stage=stage,
                settings={},
                folder=str(tmp_path),
                name="speaker",
                cache=str(tmp_path / "cache.pkl"),
            )
        )
    assert list(tmp_path.iterdir()) == []


def test_processing_job_does_not_redirect_other_threads(monkeypatch):
    import hals_studio.infrastructure.process_job as process_job

    app = W.QApplication.instance() or W.QApplication([])
    before = os.getcwd(), sys.stdout, sys.stderr
    entered, release = threading.Event(), threading.Event()

    def run(request, *, runtime):
        entered.set()
        assert release.wait(3)
        runtime.print("Stage message")
        runtime.progress("Test phase", 1).advance()
        raise ValueError("deliberate failure")

    monkeypatch.setattr(process_job.process_service, "run", run)
    job = process_job.ProcessJob({"stage": 1}, SimpleNamespace(workers=1, state="ready"))
    messages, results, events = [], [], []
    job.message.connect(messages.append)
    job.completed.connect(results.append)
    job.progress.connect(events.append)
    job.start()
    try:
        assert entered.wait(3)
        assert (os.getcwd(), sys.stdout, sys.stderr) == before
    finally:
        release.set()
        assert job.wait(3000)
    app.processEvents()
    assert not results[0]["ok"]
    assert results[0]["error"] == "deliberate failure"
    assert any("Stage message" in message for message in messages)
    assert events[-1]["completed"] == 1
    assert (os.getcwd(), sys.stdout, sys.stderr) == before


def test_stage1_service_uses_explicit_paths_and_runtime(tmp_path, monkeypatch):
    import hals_studio.application.process_service as process_service
    import hals_studio.process_engine.stage1_fdwsmooth as stage1_fdwsmooth

    settings = json.loads((bootstrap.RESOURCES / "process_schema.json").read_text())["1"]
    settings = {key: field["default"] for key, field in settings.items()}
    before = os.getcwd()
    seen = {}

    def process(**kwargs):
        seen.update(kwargs)
        assert os.getcwd() == before
        return {}

    monkeypatch.setattr(stage1_fdwsmooth, "fdwsmooth", process)
    runtime = EngineRuntime()
    request = dict(
        stage=1,
        settings=settings,
        folder=str(tmp_path),
        name="speaker",
        cache=str(tmp_path / "cache.pkl"),
        ir_folder=str(tmp_path / "recordings"),
    )
    output = process_service.run(request, runtime=runtime)
    assert output == str(tmp_path / "outputs" / "speaker_complex_data.npz")
    assert seen["out_dir"] == str(tmp_path / "outputs")
    assert seen["runtime"] is runtime
    assert os.getcwd() == before


def test_solver_logger_is_private_and_closes_handlers(tmp_path):
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    messages = []
    runtime = EngineRuntime(output=messages.append)
    handler = logging.FileHandler(tmp_path / "solve.log")
    with pytest.raises(ValueError):
        with runtime.logging([handler, logging.StreamHandler(runtime.stream)]) as logger:
            logger.info("solver output")
            raise ValueError("failure")
    assert handler.stream is None
    assert root.handlers == handlers and root.level == level
    assert "solver output" in "".join(messages)
    assert "solver output" in (tmp_path / "solve.log").read_text()


def test_cancelled_runtime_does_not_publish_progress():
    events = []
    runtime = EngineRuntime(on_progress=events.append, cancelled=lambda: True)
    with pytest.raises(ProcessingCancelled):
        runtime.progress("Cancelled phase", 1)
    assert not events


def test_pool_shutdown_never_blocks_qt_thread():
    from hals_studio.application.job_coordinator import JobCoordinator

    app = W.QApplication.instance() or W.QApplication([])
    entered, release = threading.Event(), threading.Event()
    threads = []

    def close():
        threads.append(threading.get_ident())
        entered.set()
        assert release.wait(3)

    jobs = JobCoordinator()
    jobs.stop_pool(SimpleNamespace(close=close))
    try:
        assert entered.wait(3)
        timer = []
        C.QTimer.singleShot(0, lambda: timer.append(True))
        pump_until(lambda: bool(timer))
        assert jobs.busy()
        assert threads == [threads[0]] and threads[0] != threading.get_ident()
    finally:
        release.set()
        pump_until(lambda: not jobs.busy())


def test_coordinator_cancels_once_and_releases_job():
    from hals_studio.application.job_coordinator import JobCoordinator

    app = W.QApplication.instance() or W.QApplication([])
    release = threading.Event()

    class WaitingJob(C.QThread):
        def run(self):
            release.wait(3)

    job = WaitingJob()
    calls = []
    jobs = JobCoordinator()
    jobs.track("process", job, lambda: (calls.append(True), release.set()))
    job.start()
    jobs.cancel("process")
    jobs.cancel("process")
    pump_until(lambda: not jobs.busy())
    assert calls == [True]
    assert job.wait(3000)


def test_legacy_and_versioned_origin_caches(tmp_path):
    import hals_studio.persistence.process_cache as process_cache

    rows = {100.0: dict(final_c=np.zeros(3), error=1.0)}
    legacy = (rows, None, None, None, None, {"speed_of_sound": 343.0}, None)
    path = tmp_path / "origins.pkl"
    path.write_bytes(pickle.dumps(legacy))
    loaded = process_cache.load(path, 2)
    assert isinstance(loaded, OriginResult)
    assert loaded.config["speed_of_sound"] == 343.0
    np.testing.assert_array_equal(loaded.rows[100.0]["final_c"], legacy[0][100.0]["final_c"])
    process_cache.save(path, 2, loaded)
    assert process_cache.load(path, 2).config == loaded.config
    with pytest.raises(ValueError, match="different stage"):
        process_cache.load(path, 3)
    path.write_bytes(pickle.dumps(dict(hals_cache_version=999, stage=2, result=legacy)))
    with pytest.raises(ValueError, match="version"):
        process_cache.load(path, 2)


def test_project_migration_preserves_unknown_fields_and_failed_save(tmp_path, monkeypatch):
    import hals_studio.persistence.project_repository as repo

    original = dict(custom_metadata={"keep": True}, hals_viewer={"session": {"version": 2}})
    path = tmp_path / "project.json"
    repo.write_project(path, original)
    payload = repo.read_project(path)
    assert payload == original
    assert repo.studio_state(payload)["session"]["version"] == 2
    before = path.read_bytes()

    def fail(*args):
        raise OSError("disk unavailable")

    monkeypatch.setattr(repo.os, "replace", fail)
    with pytest.raises(OSError):
        repo.write_project(path, {"changed": True})
    assert path.read_bytes() == before
    assert list(tmp_path.iterdir()) == [path]
    with pytest.raises(ValueError, match="version"):
        repo.studio_state({"hals_studio": {"version": 999}})


def test_invalid_settings_fail_before_creating_outputs(tmp_path):
    import hals_studio.application.process_service as process_service

    request = dict(
        stage=1,
        settings={"fdw_oct_res": "nan"},
        folder=str(tmp_path),
        name="speaker",
        cache=str(tmp_path / "cache.pkl"),
    )
    with pytest.raises(ValueError, match="finite"):
        process_service.run(request)
    assert not (tmp_path / "outputs").exists()


def test_analysis_completion_and_close_run_on_qt_thread(tmp_path):
    from hals_studio.ui.workspace import Workspace
    import hals_studio.analysis.acoustics as acoustics

    app = W.QApplication.instance() or W.QApplication([])
    window = Workspace(
        start_pool=False,
        settings=C.QSettings(str(tmp_path / "settings.ini"), C.QSettings.IniFormat),
    )
    received = []
    original = window.set_sphere

    def loaded(sphere):
        received.append(C.QThread.currentThread() is app.thread())
        original(sphere)

    window.set_sphere = loaded

    def calculate(progress, cancelled):
        progress(50, "Reconstructing")
        return acoustics.demo()

    try:
        window.analysis.start_job(calculate, {}, str(tmp_path / "source.h5"), {})
        pump_until(lambda: not window.jobs.busy())
        assert received == [True]
        assert window.sphere is not None
        assert window.source_path == str(tmp_path / "source.h5")
    finally:
        window.close()
        pump_until(lambda: window._close_ready)


def test_window_close_cancels_running_analysis_without_waiting(tmp_path):
    from hals_studio.ui.workspace import Workspace
    from hals_studio.analysis.acoustics import Cancelled

    app = W.QApplication.instance() or W.QApplication([])
    window = Workspace(
        start_pool=False,
        settings=C.QSettings(str(tmp_path / "settings.ini"), C.QSettings.IniFormat),
    )
    entered = threading.Event()

    def calculate(progress, cancelled):
        entered.set()
        deadline = time.monotonic() + 3
        while not cancelled() and time.monotonic() < deadline:
            time.sleep(0.005)
        assert cancelled()
        raise Cancelled()

    window.analysis.start_job(calculate, {}, str(tmp_path / "source.h5"), {})
    assert entered.wait(3)
    window.close()
    assert window.jobs.closing
    pump_until(lambda: window._close_ready)
    assert window.sphere is None


def test_cancelled_analysis_does_not_show_pool_shutdown_error():
    from hals_studio.ui.app import Worker
    app = W.QApplication.instance() or W.QApplication([])
    entered = threading.Event()
    def calculate(progress, cancelled):
        entered.set()
        deadline = time.monotonic() + 3
        while not cancelled() and time.monotonic() < deadline:
            time.sleep(.005)
        raise RuntimeError('Pool terminated during cancellation')
    job = Worker(calculate, {})
    errors = []
    job.failed.connect(errors.append)
    job.start()
    assert entered.wait(3)
    job.requestInterruption()
    assert job.wait(3000)
    app.processEvents()
    assert not errors


def test_export_workspace_completes_and_releases_job(tmp_path):
    import h5py
    from hals_studio.ui.workspace import Workspace
    from hals_studio.infrastructure.worker_pool import WarmPool
    app = W.QApplication.instance() or W.QApplication([])
    source = tmp_path / 'speaker.h5'
    frequencies = np.arange(100., 10001., 100.)
    with h5py.File(source, 'w') as data:
        data['freqs'] = frequencies
        data['N_used'] = np.zeros(len(frequencies), int)
        data['coeffs'] = np.column_stack((np.ones(len(frequencies)), np.zeros(len(frequencies))))
        data['origins_mm'] = np.zeros((len(frequencies), 3))
        data['fs'] = 48000.
    window = Workspace(start_pool=False, settings=C.QSettings(str(tmp_path/'settings.ini'), C.QSettings.IniFormat))
    window.pool = WarmPool(1)
    export = window.export_workspace
    try:
        export.apply_config(dict(export.config, coeff_path=str(source), output_dir=str(tmp_path/'exports'),
                                 range_deg=0, live_preview=False), refresh_metadata=False)
        export.start(True)
        pump_until(lambda: not window.jobs.busy(), timeout=30)
        assert export.job is None
        assert export.destination
        destination = Path(export.destination)
        assert (destination/'hals-studio-export.json').is_file()
        assert list(destination.rglob('*.frd'))
    finally:
        window.close()
        pump_until(lambda: window._close_ready, timeout=30)
