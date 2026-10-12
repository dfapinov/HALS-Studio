"""Per-operation engine dependencies, shared explicitly with origin-search threads.

Runtime objects stay in the calling process. Numerical worker payloads contain
only numerical data and settings, so spawn workers never need Qt callbacks.
"""

import builtins
import logging
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable


class ProcessingCancelled(Exception):
    """The caller requested cancellation at a safe processing boundary."""


class CallbackStream:
    def __init__(self, output):
        self.output = output

    def write(self, text):
        self.output(text)
        return len(text)

    def flush(self):
        pass


@dataclass(frozen=True)
class EngineRuntime:
    output: Callable[[str], None] | None = None
    on_progress: Callable[[dict], None] | None = None
    pool_factory: Callable | None = None
    cancelled: Callable[[], bool] = lambda: False

    def check(self):
        if self.cancelled():
            raise ProcessingCancelled()

    @property
    def stream(self):
        return CallbackStream(self.output) if self.output else sys.stdout

    def print(self, *parts, **kwargs):
        self.check()
        kwargs.setdefault("file", self.stream)
        builtins.print(*parts, **kwargs)

    def progress(self, label, total, **kwargs):
        from hals_studio.process_engine.process_progress import Progress

        self.check()
        kwargs.setdefault("callback", self.on_progress)
        return Progress(label, total, stream=self.stream, cancelled=self.cancelled, **kwargs)

    def borrow_pool(self, workers=None):
        self.check()
        if self.pool_factory is not None:
            return self.pool_factory(workers)
        # Backwards-compatible standalone entry points may install a session pool.
        from hals_studio.process_engine.session_pool import borrow_pool

        return borrow_pool(workers)

    def collect(self, executor, function, tasks, label, chunksize=1):
        from hals_studio.process_engine.process_progress import collect_tasks

        return collect_tasks(executor, function, tasks, label, chunksize, runtime=self)

    def completed(self, executor, function, items, chunksize=1):
        from hals_studio.process_engine.process_progress import completed_map

        return completed_map(executor, function, items, chunksize, cancelled=self.cancelled)

    @contextmanager
    def logging(self, handlers):
        """A private solver logger; never reconfigure the application's root logger."""
        logger = logging.Logger("hals_studio.solver", level=logging.INFO)
        for handler in handlers:
            handler.setFormatter(logging.Formatter("%(message)s"))
            logger.addHandler(handler)
        try:
            yield logger
        finally:
            for handler in handlers:
                handler.close()
                logger.removeHandler(handler)
