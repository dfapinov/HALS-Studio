"""Qt job adapters for the maintained processing engine."""

import traceback
from PySide6 import QtCore as C
import hals_studio.bootstrap as bootstrap
import hals_studio.application.process_service as process_service


class SharedPool:
    """Public adapter used by generic engine stages."""

    def __init__(self, pool, cancelled=lambda: False):
        self.pool = pool
        self.workers = pool.workers
        self.cancelled = cancelled

    def executor(self):
        return self.pool.get_executor(self.cancelled)

    def fail(self, exc):
        self.pool.fail(exc)


class ProcessJob(C.QThread):
    message = C.Signal(str)
    progress = C.Signal(dict)
    completed = C.Signal(dict)

    def __init__(self, request, pool, parent=None):
        super().__init__(parent)
        from copy import deepcopy

        self.request = deepcopy(request)
        self.pool = pool

    def run(self):
        from hals_studio.process_engine.runtime import EngineRuntime, ProcessingCancelled
        from hals_studio.process_engine.session_pool import PoolView

        shared = SharedPool(self.pool, self.isInterruptionRequested)
        runtime = EngineRuntime(
            output=self.message.emit,
            on_progress=self.progress.emit,
            pool_factory=lambda workers=None: PoolView(
                shared, workers, self.isInterruptionRequested
            ),
            cancelled=self.isInterruptionRequested,
        )
        try:
            runtime.print(
                f"Using shared viewer pool: {self.pool.workers} workers ({self.pool.state})"
            )
            request = dict(self.request, workers=self.pool.workers)
            cache = process_service.run(request, runtime=runtime)
            if request.get('preview_only'):
                self.completed.emit(dict(ok=True, stage=request['stage'], result=cache, preview_only=True))
            else:
                self.completed.emit(dict(ok=True, stage=request["stage"], cache=cache))
        except ProcessingCancelled:
            self.completed.emit(dict(ok=False, cancelled=True))
        except Exception as exc:
            if self.isInterruptionRequested():
                self.completed.emit(dict(ok=False, cancelled=True))
            else:
                self.message.emit(traceback.format_exc())
                self.completed.emit(dict(ok=False, error=str(exc)))


class SpatialErrorJob(C.QThread):
    progress = C.Signal(dict)
    completed = C.Signal(dict)

    def __init__(self, npz_path, coeff_path, pool, parent=None):
        super().__init__(parent)
        self.npz_path = npz_path
        self.coeff_path = coeff_path
        self.pool = pool

    def run(self):
        try:
            import hals_studio.persistence.process_cache as process_cache
            from hals_studio.process_engine.session_pool import PoolView

            result = process_cache.hydrate_stage4(
                self.npz_path,
                self.coeff_path,
                process_pool=PoolView(
                    SharedPool(self.pool, self.isInterruptionRequested),
                    cancelled=self.isInterruptionRequested,
                ),
                progress=self.progress.emit,
            )
            self.completed.emit(dict(ok=True, result=result))
        except Exception as exc:
            self.completed.emit(dict(ok=False, error=str(exc)))
