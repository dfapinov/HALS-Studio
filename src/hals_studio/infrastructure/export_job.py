"""Qt thread adapter for export writing and cached point previews."""

from copy import deepcopy
import threading
from PySide6 import QtCore as C
from hals_studio.analysis.acoustics import Cancelled
from hals_studio.application.export_engine import run_export, needs_aggregate_preview


class ExportWorker(C.QThread):
    progress = C.Signal(int, str)
    message = C.Signal(str)
    result = C.Signal(object)
    failed = C.Signal(str)

    def __init__(self, config, pool, writing, preview_cache=None, point_index=0, aggregate=False):
        super().__init__()
        self.config, self.pool, self.writing = deepcopy(config), pool, writing
        self.stop = threading.Event()
        self.preview_cache, self.point_index, self.aggregate = preview_cache, point_index, aggregate

    def run(self):
        try:
            if not self.writing and not self.aggregate and not needs_aggregate_preview(self.config):
                result = self.preview_cache.run(
                    self.config, self.point_index, self.pool, self.progress.emit, self.stop.is_set
                )
            else:
                result = run_export(
                    self.config,
                    self.pool,
                    self.writing,
                    self.progress.emit,
                    self.stop.is_set,
                    self.message.emit,
                )
            if not self.stop.is_set():
                self.result.emit(result)
        except Cancelled:
            self.message.emit("Cancelled; no incomplete export was published.")
        except Exception as exc:
            if self.stop.is_set():
                self.message.emit("Cancelled; no incomplete export was published.")
            else:
                self.failed.emit(str(exc))
