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
        self.available_path = None
        self.loaded_stamp = None
        self.job_stamp = None
        self.analysed_options = {}
        self.pending_activation = None
        window.jobs.idle.connect(self.activate_when_idle)

    @staticmethod
    def coefficient_stamp(path):
        path = Path(path).resolve()
        stat = path.stat()
        return (str(path), stat.st_mtime_ns, stat.st_size)

    def prepare_coefficients(self, path):
        """Publish a Stage 4 result without evaluating an Analysis sphere."""
        self.available_path = str(Path(path).resolve())
        if self.loaded_stamp != self.coefficient_stamp(path):
            self.window.set_sphere(None)
            self.window.source_path = self.available_path
            self.window.source_options = None

    def activate_coefficients(self, path=None):
        """Ask for import settings on the first analysis of each file revision."""
        from hals_studio.application.job_coordinator import jobs_for
        window = self.window
        if not path and window.export_workspace is not None:
            path = window.export_workspace.config.get('coeff_path')
        path = path or self.available_path
        if not path or not Path(path).is_file() or Path(path).suffix.lower() not in ('.h5', '.hdf5'):
            return
        jobs = jobs_for(window)
        if jobs.closing or jobs.busy('analysis'): return
        if jobs.busy('process', 'export'):
            self.pending_activation = str(path)
            return
        self.pending_activation = None
        stamp = self.coefficient_stamp(path)
        if window.sphere is not None and self.loaded_stamp == stamp: return
        self.open_path(path, self.analysed_options.get(stamp))

    @C.Slot()
    def activate_when_idle(self):
        path, self.pending_activation = self.pending_activation, None
        if path and not self.window.jobs.closing and self.window.workspace_mode.currentData() == 0:
            self.activate_coefficients(path)

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
            # Migrate old session options as well as new dialog choices.
            options = dict(options, origins=True)
            options.setdefault('offset', [0., 0., 0.])
            options.setdefault('manual_padding', options.get('padding', 50) != 50)
            if not options['manual_padding']: options['padding'] = 50
            reconstruction = {key: value for key, value in options.items() if key != 'manual_padding'}
            self.start_job(
                ac.reconstruct,
                dict(path=str(path), pool=window.pool, **reconstruction),
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
        self.job_stamp = self.coefficient_stamp(source) if Path(source).suffix.lower() in (".h5", ".hdf5") and Path(source).is_file() else None
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
        self.loaded_stamp = self.job_stamp
        if self.job_stamp is not None:
            self.analysed_options[self.job_stamp] = dict(self.job_options or {})
            self.available_path = self.job_source
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
