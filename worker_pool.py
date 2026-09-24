"""Viewer-owned warm spawn pool, using an isolated snapshot of HALS Stage 5."""
from __future__ import annotations
import bootstrap
import multiprocessing as mp
import os
import queue
import threading
import time
from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED
from concurrent.futures.process import BrokenProcessPool
import numpy as np


def _initialize(ready, release):
    import sys
    sys.path.insert(0,str(bootstrap.HERE/'process_engine'))
    import stage1_fdwsmooth, stage2_centre_origin, stage3_optimize_she_settings, stage4_run_she_solve
    import extract_pressures_core  # preload Stage 5 and SciPy in every process
    ready.put(os.getpid())
    release.wait()


def _ping():
    return os.getpid()


def evaluate_task(task):
    """Keep HALS's vectorized harmonic/point engine; bound temporary arrays."""
    from extract_pressures_core import _worker_calc_chunk
    indices, freqs, coeffs, orders, r, theta, phi, origins, mode, speed = task
    size = max(16, min(4096, 250000 // max((int(np.max(orders)) + 1)**2, 1)))
    result = np.empty((len(freqs), len(r)), complex)
    for start in range(0, len(r), size):
        end = start + size
        _, result[:, start:end] = _worker_calc_chunk((indices, freqs, coeffs, orders,
            r[start:end], theta[start:end], phi[start:end], origins, mode, speed))
    return indices, result


class WarmPool:
    def __init__(self, workers=None):
        self.workers = workers or min(61, max(1, (os.cpu_count() or 2) // 2))
        self.state = "new"
        self.error = ""
        self.initialized = 0
        self.executor = None
        self._ready = threading.Event()
        self._lock = threading.RLock()

    def start(self):
        with self._lock:
            if self.state != "new":
                return
            self.state = "warming"
            threading.Thread(target=self._warm, daemon=True, name="atlas-worker-warmup").start()

    def _warm(self):
        ctx = mp.get_context("spawn")
        ready = release = None
        try:
            ready, release = ctx.Queue(), ctx.Event()
            with self._lock:
                if self.state == "closed":
                    return
                self.executor = ProcessPoolExecutor(self.workers, mp_context=ctx,
                    initializer=_initialize, initargs=(ready, release))
                probes = [self.executor.submit(_ping) for _ in range(self.workers)]
            deadline = time.monotonic() + 90
            pids = set()
            while len(pids) < self.workers:
                if self.state == "closed":
                    return
                if time.monotonic() > deadline:
                    raise TimeoutError("Worker warmup exceeded 90 seconds")
                for f in probes:
                    if f.done():
                        f.result()
                try:
                    pids.add(ready.get(timeout=.1))
                    self.initialized = len(pids)
                except queue.Empty:
                    pass
            release.set()
            for f in probes:
                f.result(timeout=15)
            with self._lock:
                if self.state != "closed":
                    self.state = "ready"
        except Exception as exc:
            with self._lock:
                if self.state != "closed":
                    self.state, self.error = "failed", str(exc)
        finally:
            if release is not None:
                release.set()
            if ready is not None:
                ready.close()
            self._ready.set()

    def map(self, tasks, cancelled=lambda: False):
        from acoustics import Cancelled
        self.start()
        while not self._ready.wait(.1):
            if cancelled():
                raise Cancelled()
        if self.state != "ready":
            raise RuntimeError(f"Viewer workers {self.state}: {self.error}. Use File → Restart workers.")
        tasks = iter(tasks)
        pending = set()
        try:
            while True:
                if cancelled():
                    raise Cancelled()
                while len(pending) < self.workers:
                    task = next(tasks, None)
                    if task is None:
                        break
                    pending.add(self.executor.submit(evaluate_task, task))
                if not pending:
                    break
                done, pending = wait(pending, timeout=.1, return_when=FIRST_COMPLETED)
                for future in done:
                    yield future.result()
        except BrokenProcessPool as exc:
            self.state, self.error = "failed", str(exc)
            raise
        finally:
            for future in pending:
                future.cancel()

    def close(self):
        with self._lock:
            self.state = "closed"
            self._ready.set()
            executor, self.executor = self.executor, None
        if executor is not None:
            terminate = getattr(executor, "terminate_workers", None)
            if terminate:
                terminate()
            else:
                processes = list((getattr(executor, "_processes", None) or {}).values())
                executor.shutdown(wait=False, cancel_futures=True)
                for process in processes:
                    if process.is_alive():
                        process.terminate()
                    process.join(timeout=2)
