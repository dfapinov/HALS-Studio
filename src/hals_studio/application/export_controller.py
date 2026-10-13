"""Own export threads and deliver results on the GUI thread through explicit signals."""

from PySide6 import QtCore as C

from hals_studio.application.export_engine import validate
from hals_studio.infrastructure.export_job import ExportWorker


class ExportController(C.QObject):
    started = C.Signal(bool)
    completed = C.Signal(object, int, bool)
    finished = C.Signal(bool)
    progress = C.Signal(int, str)
    message = C.Signal(str)
    failed = C.Signal(str)

    def __init__(self, jobs, parent=None):
        super().__init__(parent)
        self.jobs = jobs
        self.job = None
        self.generation = 0

    def start(self, config, pool, writing, preview_cache, point_index, generation):
        if self.job is not None or self.jobs.closing:
            return False
        validate(config, writing)
        job = ExportWorker(config, pool, writing, preview_cache, point_index)
        self.jobs.track("export", job, self.cancel)
        self.job = job
        self.generation = generation
        job.result.connect(self._completed)
        job.failed.connect(self.failed)
        job.message.connect(self.message)
        job.progress.connect(self.progress)
        job.finished.connect(self._finished)
        self.started.emit(writing)
        job.start()
        return True

    @C.Slot()
    def cancel(self):
        if self.job is not None:
            self.job.stop.set()

    @C.Slot(object)
    def _completed(self, result):
        if self.job is not None and not self.job.stop.is_set():
            self.completed.emit(result, self.generation, self.job.writing)

    @C.Slot()
    def _finished(self):
        job = self.job
        self.job = None
        cancelled = job.stop.is_set()
        job.deleteLater()
        self.finished.emit(cancelled)
