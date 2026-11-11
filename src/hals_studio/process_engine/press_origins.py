"""Production Stage 2 leave-one-out prediction origins, local LF order selection and saved schedules."""
import json
import hashlib
from concurrent.futures import ThreadPoolExecutor
import numpy as np
from scipy.optimize import minimize
from scipy.spatial import ConvexHull
from .press_fitting import basis, prediction_fit
from .utils import spherical_to_cartesian, cartesian_to_spherical, get_grid_limit, grid_reference

PLAN_KEY = 'press_plan_json'
ORDER_KEY = 'press_lf_orders'
VERSION = 4


def measurement_digest(frequencies, names, spectra):
    digest = hashlib.sha256(np.asarray(frequencies, dtype=np.float64).tobytes())
    for name in names:
        digest.update(name.encode('utf-8'))
        digest.update(np.asarray(spectra[name], dtype=np.complex128).tobytes())
    return digest.hexdigest()


def plain_orders(frequencies, radius, speed, cap, offset=2.):
    return np.maximum(2, np.minimum(cap, np.floor(2*np.pi*np.asarray(frequencies)*radius/speed+offset))).astype(int)


def observer_points(centre):
    i = np.arange(120)+.5
    z = 1-2*i/120
    phi = i*np.pi*(3-np.sqrt(5))
    directions = np.column_stack((np.sqrt(1-z*z)*np.cos(phi), np.sqrt(1-z*z)*np.sin(phi), z))
    return np.vstack((centre+directions, centre+2*directions))


def compare_fields(field, reference):
    return float(np.max(100*np.linalg.norm((field-reference).reshape(2, 120), axis=1)
                        /np.maximum(np.linalg.norm(reference.reshape(2, 120), axis=1), 1e-300)))


def search_one(xyz, p, f, n, seed, cfg, hull, runtime):
    k = 2*np.pi*f/cfg['speed_of_sound']
    start = np.asarray(seed, float).copy()
    # Project endpoint seeds towards the interior if necessary (including zero).
    centre = np.asarray(cfg['grid_centre_m'])
    interior = xyz.mean(axis=0)
    for _ in range(60):
        if np.all(hull[:, :3]@start+hull[:, 3] < -1e-9):
            break
        start = (start+interior)/2
    if np.any(hull[:, :3]@start+hull[:, 3] >= -1e-9):
        raise ValueError('Retained microphone grid has no feasible interior origin.')
    def objective(origin):
        runtime.check()
        if np.any(hull[:, :3]@origin+hull[:, 3] >= -1e-10):
            return 1e6
        try:
            return min(prediction_fit(basis(xyz, origin, n, k), p)[1]['press_pct'], 1e6)
        except (ValueError, np.linalg.LinAlgError):
            return 1e6
    step = cfg['initial_simplex_step']/1000
    simplex = np.vstack((start, start+np.eye(3)*step))
    for j in range(1, 4):
        while np.any(hull[:, :3]@simplex[j]+hull[:, 3] >= -1e-10):
            simplex[j] = (simplex[j]+start)/2
    result = minimize(objective, start, method='Nelder-Mead', options=dict(
        maxiter=cfg['max_iterations'], initial_simplex=simplex, xatol=step/150, fatol=1e-5))
    origin = result.x
    coeff, metric = prediction_fit(basis(xyz, origin, n, k), p)
    if not np.isfinite(metric['press_pct']) or np.any(hull[:, :3]@origin+hull[:, 3] >= 0):
        raise ValueError(f'No usable leave-one-out prediction fit at {f:g} Hz, N={n}.')
    field = basis(observer_points(centre), origin, n, k)[:, ::2]@coeff[::2]
    return dict(order=n, origin=origin, field=field, power_db=float(10*np.log10(sum(abs(coeff[::2])**2)/(4*np.pi*k*k))),
                press_pct=metric['press_pct'], training_pct=metric['training_pct'],
                converged=bool(result.success), evaluations=int(result.nfev))


def select_local(candidates, baseline, ceiling):
    reference = candidates[ceiling]
    for n, c in candidates.items():
        c['field_difference_pct'] = compare_fields(c['field'], reference['field'])
        c['power_difference_db'] = c['power_db']-reference['power_db']
        c['adequate'] = bool(c['converged'] and c['press_pct'] < 100 and c['field_difference_pct'] <= 5
                             and abs(c['power_difference_db']) <= 1)
    choices = [n for n, c in candidates.items() if n >= baseline and c['adequate']]
    return min(choices) if choices else ceiling


def sweep_direction(payload, runtime, advance):
    direction, xyz, hull, anchor_f, pressures, cap, cfg, tweeter_mm, residual_seeds = payload
    label = 'HF->LF' if direction == 'down' else 'LF->HF'
    runtime.print(f'{label}: starting from '+('the tweeter seed.' if direction == 'down' else 'coordinate zero.'))
    results = {}
    seed = np.asarray(tweeter_mm)/1000 if direction == 'down' else np.zeros(3)
    indices = range(len(anchor_f)-1, -1, -1) if direction == 'down' else range(len(anchor_f))
    for i in indices:
        f = float(anchor_f[i])
        candidate = search_one(xyz, pressures[i], f, cap, seed, cfg, hull, runtime)
        if residual_seeds is not None:
            extra = search_one(xyz, pressures[i], f, cap, np.asarray(residual_seeds[f]['final_c'])/1000,
                               cfg, hull, runtime)
            candidate = min((candidate, extra), key=lambda c: c['press_pct'])
        seed = candidate['origin']
        results[i] = candidate
        runtime.print(f'{label}  {len(results):2d}/{len(anchor_f)} | {f:8.1f} Hz | error {candidate["press_pct"]:6.2f}%'+
                      ('' if candidate['converged'] else ' [limit]'))
        advance()
    runtime.print(f'{label}: complete.')
    return results


def refine_anchor(payload, runtime):
    i, xyz, pressures, anchor_f, cap, base, initial, cfg, hull = payload
    f = anchor_f[i]
    runtime.check()
    top = initial[i]
    candidates = {cap: top}
    if base[i] < cap:
        # Centre candidate avoids carrying a local basin through the LF band.
        alternative = search_one(xyz, pressures[i], float(f), cap, np.asarray(cfg['grid_centre_m']), cfg, hull, runtime)
        candidates[cap] = min((top, alternative), key=lambda c: c['press_pct'])
        for n in range(int(base[i]), cap):
            fitted = [search_one(xyz, pressures[i], float(f), n, seed, cfg, hull, runtime)
                      for seed in (candidates[cap]['origin'], np.asarray(cfg['grid_centre_m']))]
            candidates[n] = min(fitted, key=lambda c: c['press_pct'])
        selected = select_local(candidates, int(base[i]), cap)
    else:
        selected = cap
        top.update(field_difference_pct=0., power_difference_db=0., adequate=top['converged'] and top['press_pct'] < 100)
    chosen = candidates[selected]
    previous = candidates.get(cap-1)
    settled = None if previous is None else bool(previous['converged'] and candidates[cap]['converged'] and
        compare_fields(previous['field'], candidates[cap]['field']) <= 5 and abs(previous['power_db']-candidates[cap]['power_db']) <= 1)
    diagnostic = [{k: v for k, v in c.items() if k not in ('field', 'origin')} |
                  dict(origin_mm=(c['origin']*1000).tolist()) for n, c in sorted(candidates.items())]
    row = dict(final_c=chosen['origin']*1000, original_c=chosen['origin']*1000,
        error=chosen['training_pct'], grid=None, X_vals=None, Y_vals=None, Z_vals=None,
        press_order=selected, press_pct=chosen['press_pct'], press_candidates=diagnostic,
        press_reference_settled=settled)
    if base[i] < cap:
        runtime.print(f'{f:8.1f} Hz | N={selected} | pressure {chosen["field_difference_pct"]:.1f}% | '
                      f'power {abs(chosen["power_difference_db"]):.2f} dB')
    reasons = []
    if not chosen['converged']:
        reasons.append('selected origin reached the iteration limit')
    if chosen['press_pct'] >= 100:
        reasons.append('prediction error is too high')
    if settled is False:
        if not candidates[cap]['converged'] or not previous['converged']:
            reasons.append('upper-order comparison did not converge')
        else:
            reasons.append(f'N={cap-1} and N={cap} still differ by more than 5% pressure or 1 dB power')
    if reasons:
        runtime.print(f'Warning at {f:.2f} Hz: provisional result - '+ '; '.join(reasons)+'.')
    return float(f), row


def announce_order_phase(frequencies, baseline, cap, runtime):
    count = int(np.count_nonzero(baseline < cap))
    runtime.print('\n--- 2. LF order selection ---')
    runtime.print('Using the better origin from the two search directions.')
    runtime.print(f'{count} frequencies to compare; {len(frequencies)-count} use KR directly.')
    runtime.print(f'Reference: N={cap}. Limits: 5% pressure, 1 dB power.')


def report_order_completion(rows, cfg, runtime):
    runtime.print('\nLF order selection complete.')
    crossover = max(0., cfg['press_search_cap']-cfg['kr_offset'])*cfg['speed_of_sound']/(2*np.pi*cfg['grid_radius_m'])
    runtime.print(f'Handover to the KR rule at about {crossover:.1f} Hz, where KR reaches N={cfg["press_search_cap"]}.')
    runtime.print('Stage 4 controls order growth above this frequency.')
    provisional = sum(row['press_reference_settled'] is False or any(
        c['order'] == row['press_order'] and not c['adequate'] for c in row['press_candidates'])
        for row in rows.values())
    if provisional:
        runtime.print(f'{provisional} of {len(rows)} frequencies have provisional results; see the warnings above.')


def run_search(frequencies, anchor_indices, names, spectra, geometry, cfg, tweeter_mm, runtime, residual_seeds=None):
    xyz = np.column_stack(spherical_to_cartesian(*geometry))
    cap = min(int(cfg['target_n_max_origins']), cfg['N_grid'], int(np.sqrt((len(names)-1)/2)-1))
    if cap < 2:
        raise ValueError('Not enough retained recordings for leave-one-out prediction N=2.')
    cfg['press_search_cap'] = cap
    cfg['press_plan_version'] = VERSION
    cfg['press_measurement_hash'] = measurement_digest(frequencies, names, spectra)
    hull = ConvexHull(xyz).equations
    anchor_f = np.asarray(frequencies)[anchor_indices]
    pressures = [np.array([spectra[name][i] for name in names]) for i in anchor_indices]
    base = plain_orders(anchor_f, cfg['grid_radius_m'], cfg['speed_of_sound'], cap, cfg['kr_offset'])
    runtime.print('\n--- 1. Origin search ---')
    runtime.print('Method: leave-one-out prediction')
    runtime.print(f'{len(names)} recordings | {len(anchor_f)} frequencies | '
                  f'{anchor_f[0]:.1f}-{anchor_f[-1]:.1f} Hz')
    runtime.print(f'Search N={cap} | prediction error (%) | [limit] = iteration limit')
    if cap < int(cfg['target_n_max_origins']):
        runtime.print(f'Requested N={cfg["target_n_max_origins"]} reduced to N={cap} by measurement support.')
    runtime.print('LF->HF = low to high; HF->LF = high to low.')
    pool = runtime.borrow_pool() if cfg.get('use_process_pool', True) else None
    if pool is not None:
        from .origin_workers import pooled_search
        rows = pooled_search(pool, xyz, hull, anchor_f, pressures, cap, base, cfg,
                             tweeter_mm, residual_seeds, runtime)
        report_order_completion(rows, cfg, runtime)
        return rows
    runtime.print('Using local threads.')
    progress = runtime.progress('Stage 2 - origin search (both directions)', 2*len(anchor_f), console=False)
    def sweep(direction):
        return sweep_direction((direction, xyz, hull, anchor_f, pressures, cap, cfg,
                                tweeter_mm, residual_seeds), runtime, progress.advance)
    with ThreadPoolExecutor(max_workers=2) as executor:
        up = executor.submit(sweep, 'up')
        down = executor.submit(sweep, 'down')
        up, down = up.result(), down.result()
    initial = {i: min((up[i], down[i]), key=lambda c: c['press_pct']) for i in range(len(anchor_f))}
    rows = {}
    announce_order_phase(anchor_f, base, cap, runtime)
    refining = runtime.progress('Stage 2 LF order comparisons', len(anchor_f), console=False)
    def refine(i):
        return refine_anchor((i, xyz, pressures, anchor_f, cap, base, initial, cfg, hull), runtime)
    with ThreadPoolExecutor(max_workers=4) as executor:
        for f, row in runtime.completed(executor, refine, range(len(anchor_f))):
            rows[f] = row
            refining.advance()
    report_order_completion(rows, cfg, runtime)
    return rows


def finalize(rows, frequencies, geometry, cfg, runtime):
    """Save full-resolution origins/LF requirements, independent of the HF cap."""
    f = np.asarray(frequencies)
    anchors = np.array(sorted(rows))
    positions = np.array([rows[x]['final_c'] for x in anchors])
    if cfg.get('press_plan_version') != VERSION:
        raise ValueError('Cached origin-search results use an older format. Rerun Stage 2.')
    signature = (positions.tobytes(), tuple(rows[x]['press_order'] for x in anchors),
                 bool(cfg['hold_origin_lf']),
                 bool(cfg['hold_origin_hf']), cfg['speed_of_sound'], cfg['kr_offset'])
    if cfg.get('_press_signature') == signature:
        return cfg['press_plan'], cfg['press_lf_orders'], cfg['press_origins_mm']
    origins = np.column_stack([np.interp(f, anchors, positions[:, axis]) for axis in range(3)])
    lo, hi = cfg['origin_test_range_hz']
    if not cfg['hold_origin_lf']:
        origins[f < lo] = 0
    if not cfg['hold_origin_hf']:
        origins[f > hi] = 0
    cap = cfg['press_search_cap']
    ordinary = plain_orders(f, cfg['grid_radius_m'], cfg['speed_of_sound'], cap, cfg['kr_offset'])
    budget = np.array([rows[x]['press_order'] for x in anchors])
    lf = np.ceil(np.interp(np.log2(np.maximum(f, 1e-300)), np.log2(anchors), budget)-1e-10).astype(int)
    active = (f > 0) & (f >= min(lo, anchors[0])) & (f <= max(hi, anchors[-1]))
    # No permanent LF floor or monotonic constraint: local corrections may fall.
    orders = np.where(active & (ordinary < cap), lf, 0).astype(int)
    plan = dict(version=VERSION, names=list(cfg['press_names']), speed=cfg['speed_of_sound'], search_cap=cap,
        measurement_hash=cfg.get('press_measurement_hash'),
        weighting=False,
        centre_m=list(cfg['grid_centre_m']), radius_m=cfg['grid_radius_m'], kr_offset=cfg['kr_offset'],
        range_hz=list(cfg['origin_test_range_hz']), field_limit_pct=5., power_limit_db=1.,
        anchors=[dict(frequency=float(x), order=rows[x]['press_order'], origin_mm=np.asarray(rows[x]['final_c']).tolist(),
            manually_edited=not any(c['order'] == rows[x]['press_order'] and np.allclose(c['origin_mm'], rows[x]['final_c'], atol=1e-8, rtol=0) for c in rows[x]['press_candidates']),
            reference_settled=rows[x]['press_reference_settled'], candidates=rows[x]['press_candidates']) for x in anchors])
    plan['warnings'] = [f'{x:g} Hz: upper reference unsettled' for x in anchors if rows[x]['press_reference_settled'] is False]
    plan['warnings'] += [f'{a["frequency"]:g} Hz: manually edited origin; convergence not revalidated'
                         for a in plan['anchors'] if a['manually_edited']]
    cfg['press_plan'] = plan
    cfg['press_lf_orders'] = orders
    cfg['press_origins_mm'] = origins
    cfg['_press_signature'] = signature
    return plan, orders, origins


def load_plan(data):
    value = data.get(PLAN_KEY)
    if value is None:
        return None
    plan = json.loads(str(np.asarray(value).item()))
    if plan.get('version') != VERSION or plan.get('weighting', False):
        raise ValueError('This saved origin-search plan uses an older or unsupported format. Rerun Stage 2.')
    return plan


def retained_data(data, plan):
    names = data['filenames']
    expected = plan['names']
    if len(expected) != len(set(expected)) or not set(expected).issubset(names):
        raise ValueError('Saved leave-one-out prediction recordings do not match the measurements. Rerun Stage 2.')
    index = np.array([names.index(n) for n in expected])
    return dict(data, filenames=expected, **{key: data[key][index] for key in ('r_arr', 'th_arr', 'ph_arr')})


def validate_saved(data, plan, speed, target, manual, use_origins, kr_offset=2.):
    if not use_origins or manual or not np.isclose(speed, plan['speed'], atol=1e-8, rtol=0):
        raise ValueError('Saved leave-one-out prediction plan requires its Stage 2 origins/speed and no manual order table.')
    if not np.isclose(kr_offset, plan['kr_offset'], rtol=0, atol=1e-12):
        raise ValueError('KR offset changed. Rerun Stage 2.')
    if plan.get('measurement_hash') and measurement_digest(data['freqs'], plan['names'], data['complex_data']) != plan['measurement_hash']:
        raise ValueError('Measurement data changed after leave-one-out prediction fitting. Rerun Stage 2.')
    f = data['freqs']
    values = data.get(ORDER_KEY)
    origins = data.get('origins_mm')
    if values is None or np.shape(values) != np.shape(f) or origins is None or np.shape(origins) != (len(f), 3):
        raise ValueError('Incomplete leave-one-out prediction NPZ. Save or rerun Stage 2.')
    if not np.isfinite(values).all() or np.any(values != np.asarray(values, int)) or np.any(values < 0) or np.any(values > plan['search_cap']):
        raise ValueError('Invalid saved leave-one-out prediction LF order requirements.')
    if np.any(values > target):
        raise ValueError('Stage 4 maximum is below the saved LF requirement. Increase the final maximum or rerun Stage 2 with a lower search ceiling.')
    # Validate coordinates against the explicit per-bin schedule saved alongside it.
    saved = data.get('press_origins_mm')
    if saved is None or not np.array_equal(saved, origins):
        raise ValueError('Origins changed after the leave-one-out prediction schedule was saved. Save Stage 2 again.')
    return np.asarray(values, int)


def solve_schedule(data, plan, lf_orders, target, optimize_growth, runtime):
    """Stage 4 merges saved LF requirements and runs only HF growth optimization."""
    from .condition_preflight import optimise_transitions
    from .she_solver_core import matrix_condition
    f = data['freqs']
    grid, _ = get_grid_limit(data['th_arr'], data['ph_arr'])
    target = min(target, grid)
    if np.any(lf_orders > target):
        raise ValueError('Retained sampling/final maximum cannot support the saved LF requirement.')
    cap = plan['search_cap']
    ordinary = plain_orders(f, plan['radius_m'], plan['speed'], target, plan['kr_offset'])
    orders = np.maximum(ordinary, lf_orders)
    growth = dict(status='disabled' if not optimize_growth else 'not_needed', transitions=[])
    positive = np.flatnonzero((f > 0) & (f <= 24000))
    reference = np.flatnonzero(ordinary[positive] >= cap)
    if optimize_growth and target > cap and reference.size:
        xyz = np.column_stack(spherical_to_cartesian(data['r_arr'], data['th_arr'], data['ph_arr']))
        def condition(n, i):
            runtime.check()
            j = positive[i]
            return matrix_condition(cartesian_to_spherical(*(xyz-data['origins_mm'][j]/1000).T),
                                    n, 2*np.pi*f[j]/plan['speed'])
        growth = optimise_transitions(f[positive], ordinary[positive], condition, runtime=runtime,
            reference_order=cap, reference_index=int(reference[0]), label_prefix='Stage 4 HF growth')
        if growth['status'] == 'ok':
            above = ordinary[positive] >= cap
            orders[positive[above]] = growth['adjusted_orders'][above]
            runtime.print(f'HF growth reference: N={cap} at {f[positive[reference[0]]]:g} Hz; condition={growth["target_condition"]:.4g}')
            for row in growth['transitions']:
                runtime.print(f'  N={row["order"]}: {row["original_hz"]:g} Hz -> {row["activation_hz"]:g} Hz'+
                              ('; condition target exceeded at delay limit' if row['forced'] else ''))
        else:
            runtime.print('HF growth unavailable; using ordinary KR: '+growth.get('reason', 'unknown'))
    return orders, growth
