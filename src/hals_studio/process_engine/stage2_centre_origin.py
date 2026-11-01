#!/usr/bin/env python3

"""
Acoustic Origin Finder
======================

This script identifies the optimal acoustic center (origin) of a loudspeaker 
in 3D space across a specified frequency range. By finding the true acoustic 
origin, the Spherical Harmonic Expansion (SHE) solver requires fewer coefficients 
to accurately model the sound field, improving overall mathematical stability 
and physical accuracy.

Purpose of Origin Optimization:
-------------------------------
A loudspeaker's acoustic origin is rarely at its physical center and often 
shifts depending on the frequency. At high frequencies, the origin aligns with 
the tweeter; at low frequencies, it aligns with the woofer or the port.
If the measurement grid's center does not match the acoustic origin, the SHE 
solve becomes unnecessarily complex (less sparse), requiring higher-order 
spherical harmonics to describe simple wavefronts. This exacerbates numerical 
singularities and noise amplification.

Search Strategy
---------------
The script performs a 3D Simplex (Nelder-Mead) optimization to find the 
coordinate (X, Y, Z) that minimizes the SHE residual fit error. 
The search performs two concurrent full sweeps across the frequency range 
(Low-to-High and High-to-Low) starting from a user-defined physical coordinate 
(typically the tweeter). For each frequency, it compares the residual error 
from both branches and selects the coordinate that yields the lowest error.

If enabled, a full brute-force 3D volumetric grid scan mode can also be performed. 
This helps if the Nelder-Mead search gets stuck in a local valley, or simply to 
visualize the error landscape. Note this is extreamly CPU intensive. Building a
3D landscape for a single frequency may take 5 minutes. For 20Hz - 20KHz in
1/6oct steps may take 5+ hours. 

Usage
-----

Configured via:  config_process.py

Run from the command line:

    python stage2_centre_origin.py

Or import as a module:

    from stage2_centre_origin import run_origin_search
    
Input Arguments:
    input_dir_origins (str): Directory containing the input complex data.
    input_filename_origins (str): Name of the input .npz file.
    output_filename_origins (str): Name of the output .npz file.
    tweeter_coords_mm (tuple): Initial seed coordinate (X, Y, Z) in mm.
    octave_resolution (float): Target octave resolution for the frequency sweep.
    freq_start_hz (float): Lower bound frequency for the search.
    freq_end_hz (float): Upper bound frequency for the search.
    initial_simplex_step (float): Size of the initial Nelder-Mead simplex in mm.
    max_iterations (int): Maximum iterations per frequency optimization.
    x_bounds (tuple | float): Full grid scan boundaries for the X axis (Depth).
    y_bounds (tuple | float): Full grid scan boundaries for the Y axis (Width).
    z_bounds (tuple | float): Full grid scan boundaries for the Z axis (Height).
    grid_res_mm (float): Resolution of the volumetric scan grid in mm.
    target_n_max_origins (int): Hard upper cap on harmonic order N for origin search.
    manual_order_table (dict): Dictionary mapping maximum frequency to N order.
    save_to_disk (bool): Whether to save the origins array to the .npz archive.
    plot_results_origins (bool): Launch the interactive validation UI.
    speed_of_sound (float): Initial speed of sound in m/s. Stage 2 will optimize this before the main origin sweep.
    use_cache (bool): Read previously computed results from a .pkl cache file.
    read_cache_file (str): Path to the cache file.
    enable_full_grid_scan (bool): Run the heavy 3D volumetric landscape rendering.
    optimize_speed_of_sound (bool): Run the Stage 2 speed-of-sound optimizer before the origin sweep.

Returns:
    origins_full (np.ndarray | None): Array of interpolated [X, Y, Z] origins across the full FFT frequency resolution, or None if validation was rejected.

Code Pipeline Overview
----------------------

1) Load the complex frequency data and raw spherical coordinates.
2) Setup frequency targets based on standard octave resolution (e.g., 1/6 oct).
3) Optimize speed of sound using six 5-10 kHz probe bins with non-coherent wavelength ratios.
4) Launch two threaded search branches (High-to-Low and Low-to-High).
   – For each frequency, run Nelder-Mead optimization to find the lowest residual error.
   – Use the result as the seed for the next adjacent frequency.
5) Compare results from both branches for each frequency and select the minimum error.
6) Present an interactive validation UI for user review and manual edits.
7) Interpolate the approved origins across the full FFT frequency resolution.
8) Append the origins array to the original dataset and save as a new .npz file.

"""

import os

os.environ['OPENBLAS_NUM_THREADS'] = '1'
os.environ['OMP_NUM_THREADS'] = '1'
os.environ['MKL_NUM_THREADS'] = '1'
os.environ['VECLIB_MAXIMUM_THREADS'] = '1'
os.environ['NUMEXPR_NUM_THREADS'] = '1'

import numpy as np
import pickle
import sys
import re
import math
import tempfile
import threading
import time
from datetime import datetime
from multiprocessing import Pool, cpu_count, get_context
from concurrent.futures import ThreadPoolExecutor
from hals_studio.process_engine.session_pool import borrow_pool
from scipy.optimize import minimize
import hals_studio.process_engine.schema as schema

from hals_studio.process_engine.utils import translate_coordinates, load_and_parse_npz, get_grid_limit, get_kr_limit

# --- Import Core Solver & Config ---
try:
    from hals_studio.process_engine.she_solver_core import _solve_one_frequency
except ImportError as e:
    sys.exit(f"Error: Could not import required module. {e}")

# =============================================================================
# CONFIGURATION
# =============================================================================

# Fixed regularization overrides for Origin Search
NOISE_FLOOR_START_DB = -12.0
NOISE_FLOOR_MAX_DB = -24.0
MAX_LAMBDA = 0.01

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_order_for_frequency(f_hz, manual_order_table, target_n_max_origins, N_grid=999):
    """Returns the order N based on the manual_order_table limits, capped by target_n_max_origins and N_grid."""
    N_cap = min(target_n_max_origins, N_grid)
    if not manual_order_table:
        return N_cap
    sorted_cuts = sorted(manual_order_table.keys())
    for cutoff in sorted_cuts:
        if f_hz <= cutoff:
            return min(manual_order_table[cutoff], N_cap)
    return min(manual_order_table[sorted_cuts[-1]], N_cap)

def build_stage2_frequency_targets(f_all, freq_start_hz, freq_end_hz, octave_resolution):
    target_freqs = []
    current_f = freq_start_hz
    while current_f <= freq_end_hz:
        target_freqs.append(current_f)
        if freq_start_hz == freq_end_hz:
            break
        current_f *= (2 ** octave_resolution)

    actual_freqs_asc = []
    f_indices_asc = []
    for tf in target_freqs:
        idx = int(np.abs(f_all - tf).argmin())
        af = float(f_all[idx])
        if af not in actual_freqs_asc:
            actual_freqs_asc.append(af)
            f_indices_asc.append(idx)

    return actual_freqs_asc, f_indices_asc

def build_speed_of_sound_candidates(center_mps=343.0, half_range_mps=12.0, step_mps=1.0):
    center = float(center_mps)
    half_range = abs(float(half_range_mps))
    step = abs(float(step_mps))
    if step == 0:
        raise ValueError("Speed-of-sound optimization step must not be zero.")

    start = center - half_range
    stop = center + half_range
    candidates = np.arange(start, stop + step * 0.5, step, dtype=float)
    if not np.any(np.isclose(candidates, center)):
        candidates = np.append(candidates, center)
    return np.array(sorted(set(np.round(candidates, 10))), dtype=float)

def _is_simple_frequency_ratio(freq_a, freq_b, max_integer=4, tolerance=0.01):
    ratio = max(float(freq_a), float(freq_b)) / max(min(float(freq_a), float(freq_b)), 1e-12)
    for numerator in range(1, max_integer + 1):
        for denominator in range(1, max_integer + 1):
            simple_ratio = numerator / denominator
            if simple_ratio < 1.0:
                continue
            if abs(ratio - simple_ratio) / simple_ratio <= tolerance:
                return True
    return False

def _is_noncoherent_probe_set(freqs):
    for i in range(len(freqs)):
        for j in range(i + 1, len(freqs)):
            if _is_simple_frequency_ratio(freqs[i], freqs[j]):
                return False
    return True

def select_speed_of_sound_probe_bins(actual_freqs_asc, f_indices_asc, count=6, min_freq_hz=5000.0, max_freq_hz=10000.0):
    freq_index_pairs = sorted({
        float(f): int(idx)
        for f, idx in zip(actual_freqs_asc, f_indices_asc)
        if float(min_freq_hz) <= float(f) <= float(max_freq_hz)
    }.items())
    if len(freq_index_pairs) < count:
        raise ValueError(
            f"Stage 2 speed-of-sound optimization needs at least {count} measured frequency bins from "
            f"{min_freq_hz:g} Hz to {max_freq_hz:g} Hz. Found {len(freq_index_pairs)}. "
            "Check the input data's frequency coverage."
        )

    freqs = np.array([pair[0] for pair in freq_index_pairs], dtype=float)
    target_freqs = np.geomspace(freqs[0], freqs[-1], count)
    # Cover the whole band even for dense FFT data. Eight adjacent bins can all
    # have the same unwanted ratio; exhaustively trying every combination of
    # native bins after that failure is prohibitively expensive.
    pool = np.unique(np.linspace(0, len(freqs) - 1, min(128, len(freqs))).astype(int))
    candidates = [pool[np.argsort(np.abs(np.log(freqs[pool] / target)))].tolist()
                  for target in target_freqs]
    remaining = 100000

    def choose(selected):
        nonlocal remaining
        if len(selected) == count:
            return selected
        for idx in candidates[len(selected)]:
            if remaining <= 0:
                return None
            remaining -= 1
            if selected and idx <= selected[-1]:
                continue
            if len(freqs) - idx < count - len(selected):
                continue
            if any(_is_simple_frequency_ratio(freqs[idx], freqs[other]) for other in selected):
                continue
            found = choose(selected + [idx])
            if found is not None:
                return found
        return None

    selected = choose([])
    if selected is None:
        raise ValueError(
            f"Could not select {count} non-coherent measured speed-of-sound probe bins from "
            f"{min_freq_hz:g} Hz to {max_freq_hz:g} Hz within the bounded search. "
            "Check the input data's frequency coverage or use a custom project speed of sound."
        )
    return [freq_index_pairs[idx] for idx in selected]

def score_speed_of_sound_candidates(raw_results, worst_penalty_weight=0.15):
    sorted_results = sorted(raw_results, key=lambda item: item[0])
    scored = []
    for speed, mean_error, probe_results in sorted_results:
        probe_errors = {float(row['freq']): float(row['error']) for row in probe_results}
        finite_errors = [err for err in probe_errors.values() if np.isfinite(err)]
        worst_error = float(np.max(finite_errors)) if finite_errors else float('inf')
        mean_error = float(mean_error)
        score = mean_error + worst_penalty_weight * max(0.0, worst_error - mean_error)
        scored.append({
            'speed': float(speed),
            'mean_error': mean_error,
            'probe_results': probe_results,
            'probe_errors': probe_errors,
            'worst_error': worst_error,
            'score': score,
        })
    return scored

def _worker_speed_of_sound_candidate(args):
    candidate_speed, probe_data, tweeter_coords_mm, r_arr, th_arr, ph_arr, cfg_base = args
    cfg = dict(cfg_base)
    cfg['speed_of_sound'] = float(candidate_speed)
    cfg['enable_full_grid_scan'] = False

    probe_results = []
    for probe_freq, p_list in probe_data:
        order = get_order_for_frequency(
            probe_freq,
            cfg['manual_order_table'],
            cfg['target_n_max_origins'],
            cfg.get('N_grid', 999)
        )
        context = (
            [(float(probe_freq), float(2 * np.pi * probe_freq / cfg['speed_of_sound']), np.array(p_list))],
            r_arr,
            th_arr,
            ph_arr,
            order,
            cfg
        )
        opt_c, _path = run_simplex_descent_3d(tweeter_coords_mm, context)
        error = solve_physics_3d(opt_c[0], opt_c[1], opt_c[2], context) if opt_c is not None else float('inf')
        probe_results.append({'freq': float(probe_freq), 'error': float(error), 'origin': opt_c})

    finite_errors = [row['error'] for row in probe_results if np.isfinite(row['error'])]
    mean_error = float(np.mean(finite_errors)) if finite_errors else float('inf')
    return float(candidate_speed), mean_error, probe_results

def run_speed_of_sound_candidate_batch(
    label, candidates, probe_data, tweeter_coords_mm, r_arr, th_arr, ph_arr, cfg,
    use_process_pool=True, runtime=None
):
    from hals_studio.process_engine.runtime import EngineRuntime
    runtime = runtime or EngineRuntime()
    runtime.check()
    workers = min(cpu_count(), len(candidates) * len(probe_data))
    shared_pool = runtime.borrow_pool() if use_process_pool else None
    if shared_pool is not None:
        workers = shared_pool.workers
    runtime.print(f"\n{label}: {candidates[0]:g} to {candidates[-1]:g} m/s ({len(candidates)} candidates)")
    runtime.print(f"Parallel candidate workers: {workers}")

    from hals_studio.process_engine.process_progress import collect_tasks
    # Each speed/probe fit is independent. Report them separately instead of
    # waiting for all six probe fits belonging to a candidate to finish.
    worker_args = [
        (float(speed), [probe], tweeter_coords_mm, r_arr, th_arr, ph_arr, cfg)
        for speed in candidates for probe in probe_data
    ]
    def collect(pool):
        rows = runtime.collect(pool, _worker_speed_of_sound_candidate, worker_args,
                             'Stage 2 speed of sound - '+label)
        result = []
        for speed in candidates:
            probes = [probe for value, _, data in rows if value == float(speed) for probe in data]
            finite = [probe['error'] for probe in probes if np.isfinite(probe['error'])]
            result.append((float(speed), float(np.mean(finite)) if finite else float('inf'), probes))
        return result
    if use_process_pool:
        ctx = get_context('spawn')
        with shared_pool or ctx.Pool(processes=workers) as pool:
            return collect(pool)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        return collect(executor)


# =============================================================================
# 1. 3D PHYSICS ENGINE
# =============================================================================

def solve_physics_3d(x, y, z, context):
    freq_data_list, r_geom, th_geom, ph_geom, order, cfg = context
    off_vec = np.array([x, y, z]) / 1000.0
    
    r_n, th_n, ph_n = translate_coordinates(r_geom, th_geom, ph_geom, off_vec)
    
    avg_resid_pct = 0.0
    
    for (f_hz, k, P) in freq_data_list:
        N_kr = get_kr_limit(f_hz, r_n, cfg['speed_of_sound'], cfg['kr_offset'])
        safe_order = min(order, N_kr)

        _, metrics_out = _solve_one_frequency(
            f_hz=f_hz, P_complex=P, coords_sph=(r_n, th_n, ph_n),
            order_N=safe_order, k_val=k,
            noise_floor_start_db=cfg['noise_floor_start_db'],
            noise_floor_max_db=cfg['noise_floor_max_db'],
            max_lambda=cfg['max_lambda']
        )
        if isinstance(metrics_out, dict):
            r_norm = metrics_out.get('residual_norm', 0.0)
        else:
            r_norm = float(metrics_out) 
            
        p_norm = np.linalg.norm(P)
        pct = (r_norm / p_norm * 100.0) if p_norm > 1e-12 else 0.0
        avg_resid_pct += pct
    
    return avg_resid_pct / len(freq_data_list)

# =============================================================================
# 2. 3D SIMPLEX DESCENT
# =============================================================================

def run_simplex_descent_3d(start_point, context, runtime=None
):
    from hals_studio.process_engine.runtime import EngineRuntime
    runtime = runtime or EngineRuntime()
    runtime.check()
    cfg = context[-1]
    from .origin_scan_region import inside_scan, project_to_cylinder
    current_pos = (project_to_cylinder(start_point, cfg) if 'scan_radius_mm' in cfg
                   else np.array(start_point))
    path = [current_pos.copy()]
    
    def objective(p):
        if not inside_scan(p, cfg):
            return 1e6
        return solve_physics_3d(p[0], p[1], p[2], context)
        
    def callback(xk):
        runtime.check()
        path.append(xk.copy())

    # Create a 3D Tetrahedron (Simplex)
    initial_simplex = np.array([
        current_pos,
        current_pos + [cfg['initial_simplex_step'], 0.0, 0.0],
        current_pos + [0.0, cfg['initial_simplex_step'], 0.0],
        current_pos + [0.0, 0.0, cfg['initial_simplex_step']]
    ])
        
    if 'scan_radius_mm' in cfg:
        for axis in range(3):
            vertex = project_to_cylinder(initial_simplex[axis + 1], cfg)
            if np.allclose(vertex, current_pos):
                vertex = current_pos.copy()
                vertex[axis] -= cfg['initial_simplex_step']
                vertex = project_to_cylinder(vertex, cfg)
            initial_simplex[axis + 1] = vertex

    res = minimize(
        objective, 
        current_pos, 
        method='Nelder-Mead', 
        callback=callback,
        options={'maxiter': cfg['max_iterations'], 'initial_simplex': initial_simplex, 'xatol': 0.1, 'fatol': 0.1}
    )
                
    return res.x, np.array(path)


# =============================================================================
# 3. 3D LANDSCAPE GENERATOR (WITH ETA)
# =============================================================================

def estimate_hf_seed(freqs, spectra, keys, geometry, cfg, end_hz, runtime):
    """One coarse cylinder scan, followed by refinement of its best candidates."""
    from .origin_scan_region import measurement_cylinder
    candidates = np.flatnonzero((freqs > 0) & (freqs <= min(float(end_hz), 20000.0)))
    if not len(candidates):
        raise ValueError('No positive frequency bin at or below the HF seed scan limit.')
    index = candidates[-1]
    frequency = float(freqs[index])
    scan_cfg = dict(cfg, **measurement_cylinder(geometry[0], geometry[1]))
    scan_cfg['grid_res_mm'] = 20.0
    order = get_order_for_frequency(frequency, cfg['manual_order_table'],
                                    cfg['target_n_max_origins'], cfg['N_grid'])
    context = ([(frequency, 2 * np.pi * frequency / cfg['speed_of_sound'],
                 np.array([spectra[key][index] for key in keys]))], *geometry, order, scan_cfg)
    runtime.print(f'No tweeter seed supplied: scanning measurement cylinder at {frequency:g} Hz, 20 mm spacing.')
    x, y, z, grid = generate_3d_landscape_volumetric(
        context, runtime=runtime, cylindrical=True)
    finite = np.flatnonzero(np.isfinite(grid.ravel()))
    if not len(finite):
        raise ValueError('HF seed scan found no valid origin inside the measurement cylinder.')
    best = None
    for flat in finite[np.argsort(grid.ravel()[finite])[:3]]:
        runtime.check()
        i, j, k = np.unravel_index(flat, grid.shape)
        point, _ = run_simplex_descent_3d((x[i], y[j], z[k]), context, runtime=runtime)
        error = solve_physics_3d(*point, context)
        if np.isfinite(error) and (best is None or error < best[0]):
            best = error, point
    if best is None:
        raise ValueError('HF seed refinement found no valid origin.')
    cfg['estimated_tweeter_mm'] = np.asarray(best[1]).tolist()
    cfg['seed_scan_frequency_hz'] = frequency
    runtime.print(f'Estimated tweeter seed (mm): {cfg["estimated_tweeter_mm"]}')
    return best[1]


def _worker_landscape_3d(args):
    x, y, z, context = args
    return solve_physics_3d(x, y, z, context)

def generate_3d_landscape_volumetric(context, runtime=None, *, cylindrical=False
):
    """Evaluate an editable XYZ box; only the automatic HF seed uses a cylinder."""
    from hals_studio.process_engine.runtime import EngineRuntime
    runtime = runtime or EngineRuntime()
    runtime.check()
    cfg = context[-1]
    # Shared scans use the configured pool capacity; concurrent branches share
    # the same executor. Keep the standalone per-branch fallback conservative.
    grid_workers = max(1, cpu_count() // 2)
    shared_pool = runtime.borrow_pool() if cfg.get('use_process_pool', True) else None
    if shared_pool is not None:
        grid_workers = shared_pool.workers
    res = cfg['grid_res_mm']
    def box_axis(axis):
        lo, hi = cfg[axis + '_bounds']
        return np.unique(np.r_[np.arange(lo, hi, res), hi])
    x_vals, y_vals, z_vals = (box_axis(axis) for axis in 'xyz')
    if cylindrical:
        def cylinder_axis(axis):
            lo, hi = cfg[axis + '_bounds']
            return np.unique(np.r_[np.arange(lo, hi, res), hi, np.clip(0., lo, hi)])
        x_vals, y_vals, z_vals = (cylinder_axis(axis) for axis in 'xyz')
    
    X_mesh, Y_mesh, Z_mesh = np.meshgrid(x_vals, y_vals, z_vals, indexing='ij')
    from .origin_scan_region import inside_scan
    indices = ([i for i in range(X_mesh.size)
                if inside_scan((X_mesh.flat[i], Y_mesh.flat[i], Z_mesh.flat[i]), cfg)]
               if cylindrical else list(range(X_mesh.size)))
    pixels = [(X_mesh.flat[i], Y_mesh.flat[i], Z_mesh.flat[i], context) for i in indices]
    grid = np.full(X_mesh.shape, np.inf)
    
    total_pixels = len(pixels)
    runtime.print(f"      -> Computations to process: {total_pixels:,}")
    
    from hals_studio.process_engine.process_progress import collect_tasks
    def collect(pool):
        values = runtime.collect(pool, _worker_landscape_3d, pixels, 'Stage 2 grid scan', chunksize=200)
        grid.flat[indices] = np.asarray(values)
    if cfg.get('use_process_pool', True):
        with shared_pool or get_context('spawn').Pool(grid_workers) as pool:
            collect(pool)
    else:
        with ThreadPoolExecutor(max_workers=grid_workers) as executor:
            collect(executor)
    return x_vals, y_vals, z_vals, grid


# =============================================================================
# SWEEP MANAGER
# =============================================================================

class DynamicBranchSweeper:
    def __init__(self, actual_freqs_asc, f_indices_asc, keys, d_dict, r_arr, th_arr, ph_arr, cfg, runtime=None):
        from hals_studio.process_engine.runtime import EngineRuntime
        self.runtime = runtime or EngineRuntime()
        self.actual_freqs_asc = actual_freqs_asc
        self.f_indices_asc = f_indices_asc
        self.keys = keys
        self.d_dict = d_dict
        self.r_arr = r_arr
        self.th_arr = th_arr
        self.ph_arr = ph_arr
        
        self.num_freqs = len(actual_freqs_asc)
        self.cfg = cfg
        self.lf_idx = 0
        self.hf_idx = self.num_freqs - 1
        
        self.lock = threading.Lock()
        self.console_lock = threading.Lock()
        from hals_studio.process_engine.process_progress import Progress
        self.progress = self.runtime.progress("Stage 2 origin search", 2*self.num_freqs, console=False)
        
    def process_frequency(self, branch_name, f_hz, f_idx, current_seed, i_step, is_first):
        out_buf = []
        current_order_N = get_order_for_frequency(f_hz, self.cfg['manual_order_table'], self.cfg['target_n_max_origins'], self.cfg.get('N_grid', 999))
        prefix = f"[{branch_name}] " if branch_name else ""
        out_buf.append(f"{prefix}[{i_step}/{self.num_freqs}] Processing {f_hz:.1f} Hz (Order N={current_order_N})...")
        
        P_list = [self.d_dict[k][f_idx] for k in self.keys]
        phys_context = ([(float(f_hz), float(2*np.pi*f_hz/self.cfg['speed_of_sound']), np.array(P_list))], 
                        self.r_arr, self.th_arr, self.ph_arr, current_order_N, self.cfg)

        if self.cfg['enable_full_grid_scan']:
            out_buf.append(f"{prefix}      -> Running Volumetric Grid Scan...")
            with self.console_lock:
                self.runtime.print("\n".join(out_buf))
            out_buf = []
            
            x_vals, y_vals, z_vals, grid = generate_3d_landscape_volumetric(phys_context, runtime=self.runtime)
            min_idx = np.unravel_index(np.argmin(grid), grid.shape)
            true_coords = (x_vals[min_idx[0]], y_vals[min_idx[1]], z_vals[min_idx[2]])
            val_true = np.min(grid)
            
            out_buf.append(f"{prefix}      -> 3D Amoeba descending (Grid-Seeded)...")
            opt_c, path = run_simplex_descent_3d(true_coords, phys_context, runtime=self.runtime)
        else:
            seed_source = "Tweeter" if is_first else "Previous"
            out_buf.append(f"{prefix}      -> 3D Amoeba descending ({seed_source}-Seeded)...")
            opt_c, path = run_simplex_descent_3d(current_seed, phys_context, runtime=self.runtime)
            
            x_vals = np.array([self.cfg['x_bounds'][0], self.cfg['x_bounds'][1]])
            y_vals = np.array([self.cfg['y_bounds'][0], self.cfg['y_bounds'][1]])
            z_vals = np.array([self.cfg['z_bounds'][0], self.cfg['z_bounds'][1]])
            grid = None
            true_coords = (float('nan'), float('nan'), float('nan'))
            val_true = float('nan')
        
        p_opt = opt_c if opt_c is not None else (float('nan'), float('nan'), float('nan'))
        val_opt = solve_physics_3d(p_opt[0], p_opt[1], p_opt[2], phys_context) if opt_c is not None else float('nan')

        out_buf.append(f"{prefix}   -> Simplex Final    : ({p_opt[0]:>6.1f}, {p_opt[1]:>6.1f}, {p_opt[2]:>6.1f}) | Fit Error: {val_opt:>5.2f}%")
        if self.cfg['enable_full_grid_scan']:
            out_buf.append(f"{prefix}   -> Grid Scan Minima : ({true_coords[0]:>6.1f}, {true_coords[1]:>6.1f}, {true_coords[2]:>6.1f}) | Fit Error: {val_true:>5.2f}%\n")
        else:
            out_buf.append(f"{prefix}   -> Grid Scan Minima : Skipped (Grid Scan Bypassed)\n")

        with self.console_lock:
            self.runtime.print("\n".join(out_buf))

        return {
            'X_vals': x_vals, 'Y_vals': y_vals, 'Z_vals': z_vals, 'grid': grid,
            'final_c': opt_c, 'path': path, 'true': true_coords, 'error': val_opt
        }

    def get_next_lf(self):
        with self.lock:
            if self.lf_idx >= self.num_freqs:
                return None
            idx = self.lf_idx
            self.lf_idx += 1
            return idx

    def get_next_hf(self):
        with self.lock:
            if self.hf_idx < 0:
                return None
            idx = self.hf_idx
            self.hf_idx -= 1
            return idx

    def run_dynamic_branch(self, branch_name, get_next_func, start_seed):
        results = {}
        current_seed = np.array(start_seed, dtype=float)
        with self.console_lock:
            self.runtime.print(f"\n--- Starting {branch_name} Search Branch ---")
        
        steps_taken = 0
        while True:
            self.runtime.check()
            idx = get_next_func()
            if idx is None:
                break
                
            steps_taken += 1
            f_hz = self.actual_freqs_asc[idx]
            f_idx = self.f_indices_asc[idx]
            
            res_dict = self.process_frequency(branch_name, f_hz, f_idx, current_seed, idx + 1, steps_taken == 1)
            
            if res_dict['final_c'] is not None:
                current_seed = res_dict['final_c']
            results[f_hz] = res_dict
            self.progress.advance()

        return results

def export_interpolated_origins(history_freq, history_search_x, history_search_y, history_search_z, f_all, data, input_dir, output_filename, save_to_disk, speed_of_sound=None, test_range_hz=None, hold_origin_lf=True, hold_origin_hf=True, runtime=None
):
    from hals_studio.process_engine.runtime import EngineRuntime
    runtime = runtime or EngineRuntime()
    runtime.check()
    from hals_studio.process_engine.process_progress import Progress
    runtime.progress('Stage 2 exporting origins', 0, console=False)
    runtime.print("\nInterpolating optimized origins across the full frequency resolution...")
    if len(history_freq) > 0:
        xp = np.array(history_freq)
        
        interp_x = np.interp(f_all, xp, np.array(history_search_x))
        interp_y = np.interp(f_all, xp, np.array(history_search_y))
        interp_z = np.interp(f_all, xp, np.array(history_search_z))
        
        origins_full = np.column_stack((interp_x, interp_y, interp_z))
        # np.interp holds endpoint coordinates by default. Clear either tail
        # only when its hold option is off, preserving the requested test bounds.
        lower, upper = test_range_hz if test_range_hz is not None else (xp.min(), xp.max())
        if not hold_origin_lf: origins_full[np.asarray(f_all) < lower] = 0.0
        if not hold_origin_hf: origins_full[np.asarray(f_all) > upper] = 0.0
        
        if save_to_disk:
            save_dict = {k: data[k] for k in data.files if k not in (schema.ORIGINS_MM, schema.SPEED_OF_SOUND_MPS)}
            save_dict[schema.ORIGINS_MM] = origins_full
            if speed_of_sound is not None:
                save_dict[schema.SPEED_OF_SOUND_MPS] = np.array(float(speed_of_sound), dtype=np.float64)
            if hasattr(data, "close"):
                data.close()
            
            export_filename = os.path.join(input_dir, output_filename)
            export_dir = os.path.dirname(export_filename) or "."
            fd, tmp_filename = tempfile.mkstemp(
                prefix=f".{os.path.basename(output_filename)}.",
                suffix=".tmp.npz",
                dir=export_dir
            )
            os.close(fd)
            try:
                np.savez(tmp_filename, **save_dict)
                os.replace(tmp_filename, export_filename)
            except Exception:
                if os.path.exists(tmp_filename):
                    os.remove(tmp_filename)
                raise
            runtime.print(f"Successfully exported full resolution data with appended origins to: {export_filename}\n")
        return origins_full
    else:
        runtime.print("Warning: No optimized origins found to interpolate.\n")
        return None


# =============================================================================
# MAIN EXECUTION
# =============================================================================
def run_origin_search(
    input_dir_origins: str,
    input_filename_origins: str,
    output_filename_origins: str,
    tweeter_coords_mm: tuple,
    octave_resolution: float,
    freq_start_hz: float = 20.0,
    freq_end_hz: float = 20000.0,
    initial_simplex_step: float = 15.0,
    max_iterations: int = 50,
    x_bounds: tuple | float = (-500.0, 500.0),
    y_bounds: tuple | float = (-500.0, 500.0),
    z_bounds: tuple | float = (-500.0, 500.0),
    grid_res_mm: float = 15.0,
    target_n_max_origins: int = 4,
    manual_order_table: dict = None,
    save_to_disk: bool = False,
    plot_results_origins: bool = True,
    speed_of_sound: float = 343.0,
    use_cache: bool = False,
    read_cache_file: str = "origins_cache_3D.pkl",
    enable_full_grid_scan: bool = False,
    kr_offset: float = 2.0,
    optimize_speed_of_sound: bool = True,
    use_process_pool: bool = True,
    return_state: bool = False,
    hold_origin_lf: bool = True,
    hold_origin_hf: bool = True, runtime=None
):
    from hals_studio.process_engine.runtime import EngineRuntime
    runtime = runtime or EngineRuntime()
    runtime.check()
    stage_start_time = time.time()

    runtime.print("--- Stage 2 Acoustic Origin Search ---")
    runtime.print(
        "Search mode: full volumetric grid scan with simplex refinement."
        if enable_full_grid_scan else
        "Search mode: simplex origin search (full grid scan disabled)."
    )
    
    if isinstance(x_bounds, (int, float)): x_bounds = (-float(x_bounds), float(x_bounds))
    if isinstance(y_bounds, (int, float)): y_bounds = (-float(y_bounds), float(y_bounds))
    if isinstance(z_bounds, (int, float)): z_bounds = (-float(z_bounds), float(z_bounds))
    
    cfg = {
        'origin_test_range_hz': (float(freq_start_hz), float(freq_end_hz)),
        'hold_origin_lf': hold_origin_lf, 'hold_origin_hf': hold_origin_hf,
        'noise_floor_start_db': NOISE_FLOOR_START_DB,
        'noise_floor_max_db': NOISE_FLOOR_MAX_DB,
        'max_lambda': MAX_LAMBDA,
        'speed_of_sound': speed_of_sound,
        'full_grid_bounds': dict(x_bounds=x_bounds, y_bounds=y_bounds, z_bounds=z_bounds),
        'x_bounds': x_bounds,
        'y_bounds': y_bounds,
        'z_bounds': z_bounds,
        'grid_res_mm': grid_res_mm,
        'max_iterations': max_iterations,
        'initial_simplex_step': initial_simplex_step,
        'enable_full_grid_scan': enable_full_grid_scan,
        'target_n_max_origins': target_n_max_origins,
        'manual_order_table': manual_order_table if manual_order_table is not None else {},
        'kr_offset': kr_offset,
        'use_process_pool': use_process_pool,
    }
    
    # 1. ALWAYS load the input data to ensure geometry and frequencies are available for plotting later
    input_file = os.path.join(input_dir_origins, input_filename_origins)
    if not os.path.exists(input_file):
        raise FileNotFoundError(f"Error: {input_file} not found.")

    parsed_data = load_and_parse_npz(input_file)
    f_all = parsed_data['freqs']
    d_dict = parsed_data['complex_data']
    keys = parsed_data['filenames']
    r_arr = parsed_data['r_arr']
    th_arr = parsed_data['th_arr']
    ph_arr = parsed_data['ph_arr']
    data = parsed_data['raw_data'] # Used for dict re-saving at the very end

    if not enable_full_grid_scan:
        from .origin_scan_region import measurement_cylinder
        cfg.update(measurement_cylinder(r_arr, th_arr))
        runtime.print(f"Automatic scan cylinder: radius {cfg['scan_radius_mm']:g} mm; "
                      f"Z {cfg['z_bounds'][0]:g} to {cfg['z_bounds'][1]:g} mm")


    N_grid, M_unique = get_grid_limit(th_arr, ph_arr)
    cfg['N_grid'] = N_grid

    actual_freqs_asc, f_indices_asc = build_stage2_frequency_targets(f_all, freq_start_hz, freq_end_hz, octave_resolution)

    if not actual_freqs_asc:
        if optimize_speed_of_sound:
            raise ValueError("Stage 2 frequency range produced no probe frequency for speed optimization.")
        raise ValueError("Stage 2 frequency range produced no origin search frequencies.")

    automatic_seed = tweeter_coords_mm is None
    if automatic_seed:
        tweeter_coords_mm = estimate_hf_seed(f_all, d_dict, keys, (r_arr, th_arr, ph_arr),
                                            cfg, freq_end_hz, runtime)
    lf_seed = (0.0, 0.0, 0.0) if automatic_seed else tweeter_coords_mm

    if optimize_speed_of_sound:
        speed_probe_bins = select_speed_of_sound_probe_bins(
            f_all,
            np.arange(len(f_all)),
            count=6,
            min_freq_hz=5000.0,
            max_freq_hz=10000.0
        )
        candidates = build_speed_of_sound_candidates(
            center_mps=343.0,
            half_range_mps=12.0,
            step_mps=1.0
        )

        runtime.print("\n--- Speed of Sound Optimization ---")
        runtime.print("Probe frequencies from 5 kHz to 10 kHz with non-coherent wavelength ratios:")
        for probe_freq, _probe_index in speed_probe_bins:
            runtime.print(f"  {probe_freq:.1f} Hz")
        probe_data = [
            (probe_freq, [d_dict[k][probe_index] for k in keys])
            for probe_freq, probe_index in speed_probe_bins
        ]

        coarse_results = run_speed_of_sound_candidate_batch(
            "Coarse pass",
            candidates,
            probe_data,
            tweeter_coords_mm,
            r_arr,
            th_arr,
            ph_arr,
            cfg,
            use_process_pool=use_process_pool
        , runtime=runtime)
        candidate_scores = score_speed_of_sound_candidates(coarse_results)
        best_candidate = min(candidate_scores, key=lambda item: item['score'])
        best_speed = best_candidate['speed']
        best_error = best_candidate['mean_error']
        runtime.print("\nSpeed-of-sound optimization results:")
        for row in candidate_scores:
            candidate_speed = row['speed']
            marker = " <== selected" if candidate_speed == best_speed else ""
            runtime.print(
                f"  {candidate_speed:>8.3f} m/s : score={row['score']:>8.3f} "
                f"mean={row['mean_error']:>8.3f}% worst={row['worst_error']:>8.3f}%{marker}"
            )
        runtime.print(f"Selected speed of sound: {best_speed:g} m/s (mean fit error {best_error:.3f}%, score {best_candidate['score']:.3f})\n")
        speed_of_sound = best_speed
        cfg['speed_of_sound'] = speed_of_sound
    else:
        runtime.print(f"\nSpeed-of-sound optimization skipped. Using custom project value: {speed_of_sound:g} m/s")

    sweep_results = None

    # 2. EITHER read from cache OR execute the sweep
    if use_cache and os.path.exists(read_cache_file):
        runtime.print(f"Loading data from cache: {read_cache_file}\n")
        with open(read_cache_file, 'rb') as f:
            sweep_results = pickle.load(f)
            
        for i, f_hz in enumerate(sorted(sweep_results.keys())):
            d = sweep_results[f_hz]
            opt_c = d['final_c'] if d['final_c'] is not None else (float('nan'),)*3
            true_coords = d.get('true', (float('nan'),)*3)
            
            def nearest_val(pt):
                if math.isnan(pt[0]) or d.get('grid') is None: return float('nan')
                idx_x = (np.abs(d['X_vals'] - pt[0])).argmin()
                idx_y = (np.abs(d['Y_vals'] - pt[1])).argmin()
                idx_z = (np.abs(d['Z_vals'] - pt[2])).argmin()
                return d['grid'][idx_x, idx_y, idx_z]
            
            runtime.print(f"[{i+1}/{len(sweep_results)}] Cached Frequency {f_hz:.1f} Hz...")
            runtime.print(f"   -> Simplex Final    : ({opt_c[0]:>6.1f}, {opt_c[1]:>6.1f}, {opt_c[2]:>6.1f}) | Fit Error: {nearest_val(opt_c):>5.2f}% (approx)")
            if d.get('grid') is not None:
                runtime.print(f"   -> Grid Scan Minima : ({true_coords[0]:>6.1f}, {true_coords[1]:>6.1f}, {true_coords[2]:>6.1f}) | Fit Error: {np.min(d['grid']):>5.2f}%\n")
            else:
                runtime.print(f"   -> Grid Scan Minima : Skipped (Grid Scan Bypassed)\n")

    else:
        runtime.print("Starting 3D frequency sweep...\n")

        runtime.print(f"Discovered {len(actual_freqs_asc)} distinct frequencies to evaluate.\n")
        
        start_time = time.time()
        
        sweeper = DynamicBranchSweeper(actual_freqs_asc, f_indices_asc, keys, d_dict, r_arr, th_arr, ph_arr, cfg, runtime=runtime)

        with ThreadPoolExecutor(max_workers=2) as executor:
            future_hf = executor.submit(sweeper.run_dynamic_branch, "HF -> LF", sweeper.get_next_hf, tweeter_coords_mm)
            future_lf = executor.submit(sweeper.run_dynamic_branch, "LF -> HF", sweeper.get_next_lf, lf_seed)
            
            hf_results = future_hf.result()
            lf_results = future_lf.result()
            
        sweep_results = {}
        
        runtime.print("\n--- Both branches completed. Choosing coordinates with lowest error per frequency. ---")
        for f_hz in actual_freqs_asc:
            hf_res = hf_results.get(f_hz)
            lf_res = lf_results.get(f_hz)
            
            hf_err = hf_res.get('error', float('inf')) if hf_res else float('inf')
            lf_err = lf_res.get('error', float('inf')) if lf_res else float('inf')
            
            if math.isnan(hf_err): hf_err = float('inf')
            if math.isnan(lf_err): lf_err = float('inf')
            
            if lf_res and hf_res:
                if lf_err < hf_err:
                    sweep_results[f_hz] = lf_res
                    runtime.print(f"[{f_hz:>7.1f} Hz] Selected LF -> HF ({lf_err:.2f}% vs {hf_err:.2f}%)")
                else:
                    sweep_results[f_hz] = hf_res
                    runtime.print(f"[{f_hz:>7.1f} Hz] Selected HF -> LF ({hf_err:.2f}% vs {lf_err:.2f}%)")
            elif lf_res:
                sweep_results[f_hz] = lf_res
            elif hf_res:
                sweep_results[f_hz] = hf_res

        runtime.print(f"\nSweep completed in {time.time() - start_time:.1f} seconds.")
        

    if save_to_disk:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        save_filename = f"origins_cache_3D_{timestamp}.pkl"
        
        runtime.print(f"Saving cache to {save_filename}...")
        with open(save_filename, 'wb') as f:
            pickle.dump(sweep_results, f)
            
    if return_state:
        return sweep_results, f_all, keys, d_dict, (r_arr, th_arr, ph_arr), cfg, data

    def _do_export():
        history_freq = []
        history_search_x, history_search_y, history_search_z = [], [], []

        for f_hz in sorted(sweep_results.keys()):
            d = sweep_results[f_hz]
            if d['final_c'] is not None:
                history_freq.append(f_hz)
                history_search_x.append(d['final_c'][0])
                history_search_y.append(d['final_c'][1])
                history_search_z.append(d['final_c'][2])

        return export_interpolated_origins(
            history_freq, history_search_x, history_search_y, history_search_z, 
            f_all, data, input_dir_origins, output_filename_origins, save_to_disk, speed_of_sound=speed_of_sound,
            test_range_hz=cfg['origin_test_range_hz'],
            hold_origin_lf=cfg['hold_origin_lf'], hold_origin_hf=cfg['hold_origin_hf']
        , runtime=runtime)

    # Save immediately upon completion
    initial_origins = _do_export()

    elapsed = time.time() - stage_start_time
    runtime.print(f"\nStage 2 processing completed in {elapsed:.2f} seconds.")

    # --- PLOT 1: Build the Summary Validation Graph (Macro View) ---
    if plot_results_origins:
        runtime.print("\nOpening Validation UI...")
        from hals_studio.process_engine.viewers import ValidationUI
        save_path = os.path.splitext(os.path.join(input_dir_origins, output_filename_origins))[0] + "_origins.png" if save_to_disk else None
        ui = ValidationUI(sweep_results, f_all, keys, d_dict, (r_arr, th_arr, ph_arr), cfg, save_path=save_path)
        
        if ui.accepted:
            runtime.print("Validation accepted. Saving adjusted results...")
            return _do_export()
        else:
            runtime.print("Validation UI closed.")
            return initial_origins
    else:
        runtime.print("\nPlotting bypassed. Results were saved automatically.")
        return initial_origins


def main():
    try:
        import hals_studio.process_engine.config_process as config_process
    except ImportError as e:
        sys.exit(f"Error: Could not import config_process. {e}")
        
    try:
        from hals_studio.process_engine.config_process import KR_OFFSET
    except ImportError:
        KR_OFFSET = 2.0

    run_origin_search(
        input_dir_origins=config_process.INPUT_DIR_ORIGINS,
        input_filename_origins=config_process.INPUT_FILENAME_ORIGINS,
        output_filename_origins=config_process.OUTPUT_FILENAME_ORIGINS,
        tweeter_coords_mm=config_process.TWEETER_COORDS_MM,
        octave_resolution=config_process.OCTAVE_RESOLUTION,
        freq_start_hz=config_process.FREQ_START_HZ,
        freq_end_hz=config_process.FREQ_END_HZ,
        initial_simplex_step=config_process.INITIAL_SIMPLEX_STEP,
        max_iterations=config_process.MAX_ITERATIONS,
        x_bounds=config_process.X_BOUNDS,
        y_bounds=config_process.Y_BOUNDS,
        z_bounds=config_process.Z_BOUNDS,
        grid_res_mm=config_process.GRID_RES_MM,
        target_n_max_origins=getattr(config_process, "TARGET_N_MAX_ORIGINS", 4),
        manual_order_table=getattr(config_process, "MANUAL_ORDER_TABLE", None),
        save_to_disk=True,
        plot_results_origins=getattr(config_process, "PLOT_RESULTS_ORIGINS", True),
        speed_of_sound=getattr(config_process, "SPEED_OF_SOUND", 343.0),
        use_cache=getattr(config_process, "USE_CACHE", False),
        read_cache_file=getattr(config_process, "READ_CACHE_FILE", "origins_cache_3D.pkl"),
        enable_full_grid_scan=getattr(config_process, "ENABLE_FULL_GRID_SCAN", False),
        kr_offset=KR_OFFSET
    )

if __name__ == "__main__":
    main()
