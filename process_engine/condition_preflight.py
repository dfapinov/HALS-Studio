"""Experimental, bounded-cost transition preflight (no pressure solves)."""
import numpy as np
from she_solver_core import matrix_condition
from utils import get_grid_limit, translate_coordinates
from stage4_run_she_solve import proposed_order


def optimise_transitions(freqs, proposed, condition):
    """Search a bounded set of entry bins for a two-sided condition target.

    For each higher degree, sample five log-spaced frequency offsets. If a
    sample is inside the target band after a sample above it, bisect twice to
    refine the first crossing. A degree is activated only on a checked bin;
    an unqualified degree and higher degrees remain inactive.
    """
    freqs = np.asarray(freqs, float)
    proposed = np.asarray(proposed, int)
    entries = {n: int(np.flatnonzero(proposed >= n)[0])
               for n in range(3, int(proposed.max()) + 1)}
    cache = {}

    def check(n, i):
        if (n, i) not in cache:
            cache[n, i] = float(condition(n, i))
        return cache[n, i]

    initial = {n: check(n, i) for n, i in entries.items()}
    reference = np.flatnonzero(proposed == 4)
    target = check(4, int(reference[0])) if reference.size else float('inf')
    if not np.isfinite(target) or target < 1:
        return dict(status='unavailable', reason='No finite first N=4 reference; original schedule retained.',
                    evaluations=len(cache), transitions=[])

    upper = target * 10.0
    lower = target / 5.0
    adjusted = np.minimum(proposed, 4)
    rows = []
    previous = entries[4]
    blocked = False
    sample_factors = (1.15, 1.30, 1.50, 1.80, 2.20)

    for n, entry in entries.items():
        chosen = entry if n <= 4 else None
        if n > 4 and not blocked:
            start = max(entry, previous + 1)
            sample_indices = [start]
            sample_indices.extend(
                int(np.searchsorted(freqs, freqs[start] * factor))
                for factor in sample_factors)
            sample_indices = sorted({min(len(freqs)-1, max(start, i)) for i in sample_indices})

            checked = []
            for i in sample_indices:
                value = check(n, i)
                checked.append((i, value))
                if lower <= value <= upper:
                    chosen = i
                    # Refine a descending crossing from above the band. Each
                    # checked midpoint must still satisfy the full band.
                    prior = [(j, c) for j, c in checked[:-1] if c > upper]
                    if prior:
                        lo = prior[-1][0]
                        hi = i
                        best = i
                        for _ in range(2):
                            mid = (lo + hi) // 2
                            if mid <= lo or mid >= hi:
                                break
                            cmid = check(n, mid)
                            if lower <= cmid <= upper:
                                best = mid
                                hi = mid
                            elif cmid > upper:
                                lo = mid
                            else:
                                # The condition skipped below the band; retain
                                # the already verified in-band sample.
                                hi = mid
                        chosen = best
                    break

            if chosen is None:
                blocked = True
            else:
                adjusted[chosen:] = np.maximum(adjusted[chosen:], np.minimum(proposed[chosen:], n))
                previous = chosen
        rows.append(dict(order=n, original_hz=float(freqs[entry]), original_condition=initial[n],
                         activation_hz=None if chosen is None else float(freqs[chosen]),
                         condition=None if chosen is None else check(n, chosen),
                         target_lower=lower if n > 4 else None,
                         target_upper=upper if n > 4 else None))

    ends = np.r_[np.flatnonzero(np.diff(adjusted)), len(freqs)-1]
    table = {float(freqs[i]): int(adjusted[i]) for i in ends}
    proposed_ends = np.r_[np.flatnonzero(np.diff(proposed)), len(freqs)-1]
    proposed_table = {float(freqs[i]): int(proposed[i]) for i in proposed_ends}
    return dict(status='ok', target_condition=target, target_band=[lower, upper],
                tolerance_decades=1, evaluations=len(cache), transitions=rows,
                manual_table=table, proposed_manual_table=proposed_table, frequencies_hz=freqs,
                proposed_orders=proposed, adjusted_orders=adjusted)


def run_condition_preflight(data, cfg):
    freqs_all = data['freqs']
    indices = np.flatnonzero((freqs_all >= freqs_all[1]) & (freqs_all <= 24000))
    if not len(indices):
        return dict(status='unavailable', reason='No Stage 4 frequency bins.')
    if int(cfg['target_n_max']) < 4:
        return dict(status='unavailable', reason='Selected Stage 3 maximum order is below N=4; condition preflight needs the N=4 reference.')
    origins = data.get('origins_mm') if cfg['use_optimized_origins'] else None
    static = (data['r_arr'], data['th_arr'], data['ph_arr'])
    grid, _ = get_grid_limit(static[1], static[2])
    speed = float(data.get('speed_of_sound_mps') or 343.)
    cfg = dict(cfg, speed_of_sound=speed)
    def coords(i):
        origin = np.zeros(3) if origins is None else origins[indices[i]]/1000.
        return translate_coordinates(*static, origin)
    freqs = freqs_all[indices]
    proposed = [proposed_order(f, coords(i)[0], grid, cfg)[0] for i, f in enumerate(freqs)]
    def condition(n, i):
        value = matrix_condition(coords(i), n, 2*np.pi*freqs[i]/speed)
        print(f'Preflight N={n} at {freqs[i]:.2f} Hz: condition={value:.3g}', flush=True)
        return value
    result = optimise_transitions(freqs, proposed, condition)
    result['settings'] = cfg
    print(f"Condition preflight: {result['status']}; {result.get('evaluations', 0)} matrix checks; target band={result.get('target_band')}", flush=True)
    for row in result.get('transitions', []):
        print(f"  N={row['order']}: {row['original_hz']:g} Hz -> {row['activation_hz']} Hz", flush=True)
    return result
