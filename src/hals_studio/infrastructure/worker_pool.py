"""Viewer-owned warm spawn pool, using an isolated snapshot of HALS Stage 5."""

from __future__ import annotations
import hals_studio.bootstrap as bootstrap
import numpy as np


def evaluate_task(task):
    """Keep HALS's vectorized harmonic/point engine; bound temporary arrays."""
    from hals_studio.process_engine.extract_pressures_core import _worker_calc_chunk

    indices, freqs, coeffs, orders, r, theta, phi, origins, mode, speed = task
    size = max(16, min(4096, 250000 // max((int(np.max(orders)) + 1) ** 2, 1)))
    result = np.empty((len(freqs), len(r)), complex)
    for start in range(0, len(r), size):
        end = start + size
        _, result[:, start:end] = _worker_calc_chunk(
            (
                indices,
                freqs,
                coeffs,
                orders,
                r[start:end],
                theta[start:end],
                phi[start:end],
                origins,
                mode,
                speed,
            )
        )
    return indices, result


class WarmPool:
    """Pressure-evaluation adapter over the shared process-pool lifecycle."""

    def __init__(self, workers=None):
        from hals_studio.process_engine.session_pool import SessionPool

        self._session = SessionPool(workers, startup_timeout=90)

    @property
    def workers(self):
        return self._session.workers

    @property
    def state(self):
        state = self._session.state
        return "warming" if state == "starting" else state

    @property
    def error(self):
        return self._session.error

    @property
    def initialized(self):
        return self._session.initialized_workers

    def start(self):
        self._session.start()

    def get_executor(self, cancelled=lambda: False):
        self.start()
        return self._session.executor(cancelled)

    def fail(self, exc):
        self._session.fail(exc)

    def close(self):
        self._session.close()

    def map(self, tasks, cancelled=lambda: False):
        from hals_studio.analysis.acoustics import Cancelled
        from hals_studio.process_engine.runtime import ProcessingCancelled
        from hals_studio.process_engine.session_pool import PoolView

        try:
            self.get_executor(cancelled)
            view = PoolView(self._session, cancelled=cancelled)
            yield from view.imap_unordered(evaluate_task, tasks)
        except ProcessingCancelled:
            raise Cancelled() from None
