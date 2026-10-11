"""Shared phase progress for command-line runs and the Studio processing host."""
import sys
import time
import threading
from concurrent.futures import wait, FIRST_COMPLETED


def duration(seconds):
    if seconds is None:
        return 'estimating...'
    seconds = max(0, int(round(seconds)))
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f'{hours}h {minutes:02d}m {seconds:02d}s' if hours else f'{minutes}m {seconds:02d}s'


class Progress:
    def __init__(self, label, total, *, console=True, callback=None):
        self.label, self.total, self.done = label, int(total), 0
        self.console = console
        self.callback = callback
        self.stream = sys.stdout
        self.start = time.monotonic()
        self.last = self.start
        self.lock = threading.Lock()
        self.report()

    def report(self):
        elapsed = time.monotonic()-self.start
        remaining = max(0, self.total-self.done)
        eta = elapsed*remaining/self.done if self.done >= 3 else None
        if not remaining and self.total: eta = 0.
        event = dict(label=self.label, completed=self.done, total=self.total,
                     remaining=remaining, elapsed=elapsed, eta=eta)
        emit = self.callback if self.callback is not None else getattr(self.stream, 'progress', None)
        if emit is not None: emit(event)
        if self.console:
            ending = '\n' if self.done >= self.total else ''
            self.stream.write(f'\r{self.label}: {self.done}/{self.total} complete | {remaining} remaining | ETA {duration(eta)}\033[K'+ending)
            self.stream.flush()
        self.last = time.monotonic()

    def advance(self, count=1):
        with self.lock:
            self.done = min(self.total, self.done+count)
            # Show the first returns immediately, then keep the UI responsive
            # without flooding it when hundreds of tiny tasks finish together.
            if self.done <= 3 or self.done == self.total or time.monotonic()-self.last >= .1:
                self.report()


def completed_map(executor, function, items, chunksize=1):
    """Yield work as it completes, keeping submissions bounded."""
    if hasattr(executor, 'imap_unordered'):
        yield from executor.imap_unordered(function, items, chunksize=chunksize)
        return
    items = iter(items)
    pending = set()
    capacity = max(1, getattr(executor, '_max_workers', 4))
    try:
        while True:
            while len(pending) < capacity:
                try: item = next(items)
                except StopIteration: break
                pending.add(executor.submit(function, item))
            if not pending: break
            done, pending = wait(pending, return_when=FIRST_COMPLETED)
            for future in done: yield future.result()
    finally:
        for future in pending: future.cancel()


def _indexed_task(args):
    index, function, item = args
    return index, function(item)


def collect_tasks(executor, function, tasks, label, chunksize=1):
    """Count actual completions, then return results in original task order."""
    progress = Progress(label, len(tasks))
    results = [None]*len(tasks)
    for index, result in completed_map(executor, _indexed_task,
                                      ((i, function, task) for i, task in enumerate(tasks)), chunksize=chunksize):
        results[index] = result
        progress.advance()
    return results
