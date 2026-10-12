"""Reconstruction/import orchestration composed by the main window."""

from pathlib import Path
from PySide6 import QtCore as C, QtWidgets as W
import hals_studio.analysis.acoustics as ac
from hals_studio.ui.app import Worker, ReconstructionDialog


class AnalysisController(C.QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.worker = None
        self.job_cancelled = False
        self.job_source = None
        self.job_options = None

    def open_path(self, path, options=None):
        window = self.window
        if self.worker and self.worker.isRunning():
            window.statusBar().showMessage(
                "A reconstruction is already running. Cancel it before opening another dataset."
            )
            return
        path = Path(path)
        if path.suffix.lower() in (".h5", ".hdf5"):
            if options is None:
                try:
                    dialog = ReconstructionDialog(path, window)
                except Exception as exc:
                    window.error(str(exc))
                    return
                if dialog.exec() != W.QDialog.Accepted:
                    return
                options = dialog.options()
            self.start_job(
                ac.reconstruct,
                dict(path=str(path), pool=window.pool, **options),
                str(path),
                options,
            )
        elif path.is_dir():
            self.start_job(ac.import_exports, {"folder": str(path)}, str(path), None)
        else:
            try:
                sphere = ac.load_sphere(path)
                window.set_sphere(sphere)
                window.source_path, window.source_options = str(path.resolve()), None
                window.apply_pending_session()
            except Exception as exc:
                window.error(str(exc))

    def start_job(self, fn, kwargs, source, options):
        window = self.window
        from hals_studio.application.job_coordinator import jobs_for

        jobs = jobs_for(window)
        if jobs.closing or jobs.busy("process", "export", "analysis"):
            window.statusBar().showMessage("Wait for the current operation to finish.")
            return
        window.play_timer.stop()
        window.play.setChecked(False)
        self.job_source, self.job_options = str(Path(source).resolve()), options
        self.job_cancelled = False
        self.worker = Worker(fn, kwargs)
        self.worker.progress.connect(self.job_progress)
        self.worker.loaded.connect(self.job_loaded)
        self.worker.failed.connect(window.error)
        self.worker.finished.connect(self.job_finished)
        window.progress.setValue(0)
        window.progress.show()
        window.cancel_button.show()
        window.open_button.setEnabled(False)
        window.statusBar().showMessage("Preparing complex sphere…")
        jobs.track("analysis", self.worker, self.cancel_load)
        self.worker.start()

    @C.Slot(int, str)
    def job_progress(self, value, message):
        window = self.window
        window.progress.setValue(value)
        window.statusBar().showMessage(message)

    @C.Slot(object)
    def job_loaded(self, sphere):
        window = self.window
        if self.job_cancelled:
            return
        window.source_path, window.source_options = self.job_source, self.job_options
        window.set_sphere(sphere)
        window.apply_pending_session()

    @C.Slot()
    def job_finished(self):
        window = self.window
        window.progress.hide()
        window.cancel_button.hide()
        window.open_button.setEnabled(True)
        if self.job_cancelled:
            window.statusBar().showMessage("Reconstruction cancelled. Previous dataset retained.")
        window.pending_session = None

    def cancel_load(self):
        window = self.window
        if self.worker:
            self.job_cancelled = True
            self.worker.requestInterruption()
            window.statusBar().showMessage("Cancelling after the current frequency…")
