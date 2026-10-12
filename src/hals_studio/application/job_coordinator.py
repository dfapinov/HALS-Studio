"""Window-owned background-job registry and asynchronous pool shutdown."""

from dataclasses import dataclass
from PySide6 import QtCore as C


@dataclass
class ActiveJob:
    thread: C.QThread
    cancel: object
    state: str = "running"


class PoolShutdown(C.QThread):
    failed = C.Signal(str)

    def __init__(self, pool, parent=None):
        super().__init__(parent)
        self.pool = pool

    def run(self):
        try:
            self.pool.close()
        except Exception as exc:
            self.failed.emit(str(exc))


class JobCoordinator(C.QObject):
    idle = C.Signal()
    changed = C.Signal()
    failed = C.Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.active = {}
        self.closing = False
        self._pool_shutdowns = {}
        self._pool_callbacks = {}

    def busy(self, *kinds):
        if kinds:
            return self.closing or any(key in self.active for key in kinds)
        return bool(self.active)

    def track(self, key, thread, cancel=None):
        if self.closing:
            raise RuntimeError("The application is closing.")
        if key in self.active:
            raise RuntimeError(f"{key} is already running.")
        self.active[key] = ActiveJob(thread, cancel or thread.requestInterruption)
        thread.finished.connect(self._job_finished)
        self.changed.emit()

    @C.Slot()
    def _job_finished(self):
        thread = self.sender()
        for key, job in list(self.active.items()):
            if job.thread is thread:
                self._finished(key, thread)
                break

    def _finished(self, key, thread):
        current = self.active.get(key)
        if current is not None and current.thread is thread:
            del self.active[key]
        self.changed.emit()
        if not self.active:
            self.idle.emit()

    def cancel(self, key):
        job = self.active.get(key)
        if job is not None and job.state != "cancelling":
            job.state = "cancelling"
            job.cancel()
            self.changed.emit()

    def stop_pool(self, pool, callback=None):
        """Terminate/join workers on a helper thread, never on the Qt thread."""
        identity = id(pool)
        if identity in self._pool_shutdowns:
            return
        job = PoolShutdown(pool, self)
        self._pool_shutdowns[identity] = job
        self._pool_callbacks[identity] = callback
        key = f"pool:{identity}"
        self.active[key] = ActiveJob(job, lambda: None)
        job.finished.connect(self._pool_finished)
        job.failed.connect(self.failed)
        job.start()

    @C.Slot()
    def _pool_finished(self):
        job = self.sender()
        identity = id(job.pool)
        self._pool_shutdowns.pop(identity, None)
        callback = self._pool_callbacks.pop(identity, None)
        if callback is not None:
            callback()
        self._finished(f"pool:{identity}", job)
        job.deleteLater()

    def shutdown(self, pool):
        self.closing = True
        for key in list(self.active):
            self.cancel(key)
        self.stop_pool(pool)


def jobs_for(owner):
    """Allow isolated workspace tests to supply a small owner object."""
    jobs = getattr(owner, "jobs", None)
    if jobs is None:
        jobs = JobCoordinator(owner if isinstance(owner, C.QObject) else None)
        owner.jobs = jobs
    return jobs
