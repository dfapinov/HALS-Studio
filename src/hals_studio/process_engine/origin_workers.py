"""Coarse origin-search tasks on the app-owned pool; callbacks stay in the parent."""
from concurrent.futures import ThreadPoolExecutor
from copy import copy
import multiprocessing
import queue
from .runtime import EngineRuntime


def _worker(payload):
    kind, data, cancelled, messages = payload
    pending = ['']
    def output(text):
        # Send complete lines so simultaneous directions cannot interleave text.
        pending[0] += text
        while '\n' in pending[0]:
            line, pending[0] = pending[0].split('\n', 1)
            messages.put(('text', line+'\n'))
    runtime = EngineRuntime(output=output, cancelled=cancelled.is_set)
    from .press_origins import sweep_direction, refine_anchor
    if kind == 'refine':
        result = refine_anchor(data, runtime)
        messages.put(('tick', None))
        return result
    result = sweep_direction(data, runtime, lambda: messages.put(('tick', None)))
    return data[0], result


def _run(pool, tasks, runtime, label, total):
    # Manager proxies are spawn-safe. Check cancellation inside every simplex
    # objective, rather than leaving long searches running in the shared pool.
    with multiprocessing.get_context('spawn').Manager() as manager:
        cancelled, messages = manager.Event(), manager.Queue()
        view = copy(pool)
        # Drain this operation before releasing its proxies; worker cancellation
        # is cooperative, and must not close or poison the app-owned pool.
        view.cancelled = lambda: False
        progress = runtime.progress(label, total)
        payloads = [(kind, data, cancelled, messages) for kind, data in tasks]
        def collect():
            return list(view.imap_unordered(_worker, payloads))
        def drain():
            while True:
                try:
                    kind, value = messages.get_nowait()
                except queue.Empty:
                    return
                if kind == 'tick':
                    progress.advance()
                else:
                    runtime.stream.write(value)
        with ThreadPoolExecutor(max_workers=1) as coordinator:
            future = coordinator.submit(collect)
            try:
                while not future.done():
                    runtime.check()
                    drain()
                    try:
                        future.result(timeout=.1)
                    except TimeoutError:
                        pass
                result = future.result()
                drain()
                return result
            finally:
                cancelled.set()


def pooled_search(pool, xyz, hull, frequencies, pressures, cap, baseline, cfg,
                  tweeter, residual, runtime):
    sweeps = [('sweep', (direction, xyz, hull, frequencies, pressures, cap, cfg, tweeter, residual))
              for direction in ('up', 'down')]
    paths = dict(_run(pool, sweeps, runtime, 'Stage 2 - origin search (both directions)', 2*len(frequencies)))
    initial = {i: min((paths['up'][i], paths['down'][i]), key=lambda row: row['press_pct'])
               for i in range(len(frequencies))}
    from .press_origins import announce_order_phase
    announce_order_phase(frequencies, baseline, cap, runtime)
    tasks = [('refine', (i, xyz, pressures, frequencies, cap, baseline, initial, cfg, hull))
             for i in range(len(frequencies))]
    return dict(_run(pool, tasks, runtime, 'Stage 2 LF order comparisons', len(tasks)))
