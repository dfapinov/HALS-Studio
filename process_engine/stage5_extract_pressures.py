#!/usr/bin/env python3
"""
Stage 3 – Extract FRD files from SHE coefficients and apply sound-field separation
=================================================================================
Updated to support CTA-2034-A (Spinorama) Metrics Generation and 
Dynamic Per-Frequency Inverse Coordinate Translation.

CTA-2034-A Compliance Updates (Reviewer Feedback Implemented):
--------------------------------------------------------------
1. Geometry: Generates 70 unique points (Horizontal + Vertical orbits).
2. Metrics: Delegates to the shared viewer Stage 5 implementation.
"""

from __future__ import annotations

import multiprocessing
import time
from pathlib import Path
import numpy as np
import schema
from utils import spherical_to_cartesian, cartesian_to_spherical, apply_mic_calibration, write_wav, load_she_h5

from extract_pressures_core import IR_CAPTURE_PADDING_SAMPLES, evaluate_she_field
from complex_to_ir_core import complex_to_ir
from stage5_pressure_utils import centered_sweep_angles, get_min_phase_delay, get_tof_phasor

# -------------------------------------------------
# Shared Helpers
# -------------------------------------------------

def _resolve_speed_of_sound(c_sound, coeff_path, fallback):
    if c_sound is not None:
        return float(c_sound)
    try:
        saved_speed = load_she_h5(coeff_path).get(schema.SPEED_OF_SOUND_MPS)
        if saved_speed is not None:
            resolved = float(saved_speed)
            print(f"Using Stage 2 speed of sound from coefficients: {resolved:g} m/s")
            return resolved
    except Exception:
        pass
    return float(fallback)

# -------------------------------------------------
# CTA-2034 Helpers
# -------------------------------------------------

# Shared Stage 5 / Analysis / Export CTA-2034 calculations.
from cta_coordinates import generate_cta2034_coords

def calculate_cta2034_energy_metrics(energy, indices):
    """Calculate CTA-2034 spatial metrics from squared pressure (energy)."""
    energy = np.asarray(energy, dtype=float)
    def avg(keys):
        return energy[:, [indices[k] for k in keys]].mean(axis=1)
    def keys(orbit, angles):
        return [f'{orbit}{a % 360}' for a in angles]
    groups = {
        'Floor': keys('V', [-20, -30, -40]),
        'Ceiling': keys('V', [40, 50, 60]),
        'Front wall': keys('H', range(-30, 31, 10)),
        'Side walls': keys('H', list(range(40, 81, 10)) + list(range(-80, -39, 10))),
        'Rear wall': keys('H', [90, 180, 270]),
    }
    out = {name: avg(points) for name, points in groups.items()}
    out['On axis'] = avg(['H0'])
    out['Listening window'] = avg(keys('H', range(-30, 31, 10)) + ['V10', 'V350'])
    out['Early reflections'] = np.mean([out[n] for n in groups], axis=0)
    out['Horizontal reflections'] = (out['Front wall'] + out['Side walls'] + avg(keys('H', range(90, 271, 10)))) / 3
    out['Vertical reflections'] = (out['Floor'] + out['Ceiling']) / 2
    table = np.array([.000604486, .004730189, .008955027, .012387354, .014989611,
                      .016868154, .018165962, .019006744, .019477787, .019629373,
                      .019477787, .019006744, .018165962, .016868154, .014989611,
                      .012387354, .008955027, .004730189, .000604486])
    weights = np.r_[table, table[-2:0:-1]]
    combined = np.zeros(energy.shape[1])
    for orbit in 'HV':
        for angle, weight in zip(range(0, 360, 10), weights):
            combined[indices[f'{orbit}{angle}']] += weight * (.5 if angle in (0, 180) else 1)
        values = energy[:, [indices[f'{orbit}{a}'] for a in range(0, 360, 10)]]
        out[f'{"Horizontal" if orbit == "H" else "Vertical"} sound power'] = values @ weights / weights.sum()
    out['Sound power'] = energy @ combined / combined.sum()
    out['Predicted in-room'] = .12*out['Listening window'] + .44*out['Early reflections'] + .44*out['Sound power']
    result = {name: 10*np.log10(np.maximum(value, 1e-60)) for name, value in out.items()}
    result['Sound power DI'] = result['Listening window'] - result['Sound power']
    result['Early reflections DI'] = result['Listening window'] - result['Early reflections']
    return result

def calculate_cta2034_metrics(freqs, p_matrix, map_idx, coord_deviations):
    """Adapt shared energy metrics to the Stage 5 FRD filename convention."""
    levels = calculate_cta2034_energy_metrics(np.abs(p_matrix)**2, map_idx)
    ph_ref = np.angle(p_matrix[:, map_idx['H0']], deg=True)
    names = {
        'Response_OnAxis': 'On axis', 'Response_ListeningWindow': 'Listening window',
        'Response_EarlyReflections': 'Early reflections', 'Response_SoundPower': 'Sound power',
        'Response_PIR': 'Predicted in-room', 'Response_ERDI': 'Early reflections DI',
        'Response_SPDI': 'Sound power DI',
        'reflections_breakout/Response_ER_Floor': 'Floor',
        'reflections_breakout/Response_ER_Ceiling': 'Ceiling',
        'reflections_breakout/Response_ER_FrontWall': 'Front wall',
        'reflections_breakout/Response_ER_SideWalls': 'Side walls',
        'reflections_breakout/Response_ER_RearWall': 'Rear wall',
    }
    return {filename: (levels[name], np.zeros_like(ph_ref) if name.endswith(' DI') else ph_ref)
            for filename, name in names.items()}

# -------------------------------------------------
# Writers
# -------------------------------------------------

def write_frd(freqs: np.ndarray, mags: np.ndarray, phases: np.ndarray, filepath: Path, desc: str):
    header = [f"# FRD generated ({desc})", "# freq(Hz)    magnitude(dB)    phase(deg)"]
    data = np.column_stack([freqs, mags, phases])
    np.savetxt(filepath, data, header="\n".join(header), fmt=("%.2f","%.5f","%.2f"))

def write_complex_npz(freqs: np.ndarray, pressures: np.ndarray, filepath: Path, **meta):
    save_dict = {
        "freqs": freqs.astype(np.float64),
        "P": pressures.astype(np.complex128),
    }
    save_dict.update(meta)
    np.savez_compressed(filepath, **save_dict)

# -------------------------------------------------
# CTA-2034 Driver Function
# -------------------------------------------------
def run_cta2034_extraction(
    coeff_path=None, output_dir=None, dist_mic=None,
    zero_theta=None, zero_phi=None, offset_xyz=None, c_sound=None, save_to_disk=True,
    apply_mic_cal=None, mic_cal_file=None, mic_cal_mode=None, 
    obs_mode=None, mic_cal_fade_octaves=None, use_optimized_origins=True,
    subtract_tof=None, frd_db_offset=None, ir_capture_padding_samples=None,
    use_process_pool=True
):
    start_time = time.time()

    import config_process
    coeff_path = coeff_path if coeff_path is not None else config_process.COEFF_PATH
    output_dir = Path(output_dir if output_dir is not None else config_process.OUTPUT_DIR)
    dist_mic = dist_mic if dist_mic is not None else config_process.DIST_MIC
    zero_theta = zero_theta if zero_theta is not None else config_process.ZERO_THETA_DEG
    zero_phi = zero_phi if zero_phi is not None else config_process.ZERO_PHI_DEG
    offset_xyz = offset_xyz if offset_xyz is not None else (config_process.OFFSET_MIC_X, config_process.OFFSET_MIC_Y, config_process.OFFSET_MIC_Z)
    c_sound = _resolve_speed_of_sound(c_sound, coeff_path, config_process.SPEED_OF_SOUND)
    ir_capture_padding_samples = (
        IR_CAPTURE_PADDING_SAMPLES
        if ir_capture_padding_samples is None
        else int(ir_capture_padding_samples)
    )
    
    print("\n" + "="*50)
    print(" MODE: CTA-2034-A (SPINORAMA)")
    print("="*50)
    
    cta_dir = output_dir / "CTA2034"
    breakout_dir = cta_dir / "reflections_breakout"
    if save_to_disk:
        cta_dir.mkdir(parents=True, exist_ok=True)
        breakout_dir.mkdir(parents=True, exist_ok=True)
    
    eval_dist = 2.0 
    if dist_mic != 2.0:
        print(f"Note: Using configured distance {dist_mic}m (Standard is 2.0m)")
        eval_dist = float(dist_mic)
    else:
        print("Note: Using standard reference distance 2.0m")
        
    obs_mode_val = obs_mode if obs_mode else "Internal"
    print(f"Observation Mode: {obs_mode_val}")
    
    print("Generating 70 CTA-2034 measurement angles...")
    coords_spherical, map_indices, coord_deviations = generate_cta2034_coords(
        eval_dist, float(zero_theta), float(zero_phi)
    )
    
    # Apply static offsets here in stage5
    pts_sph = np.array(coords_spherical, dtype=float)
    r_in, th_in_rad, ph_in_rad = pts_sph[:, 2], np.radians(pts_sph[:, 0]), np.radians(pts_sph[:, 1])
    x_b, y_b, z_b = spherical_to_cartesian(r_in, th_in_rad, ph_in_rad)
    off_x, off_y, off_z = offset_xyz
    x_b += off_x; y_b += off_y; z_b += off_z
    r_final, th_final_rad, ph_final_rad = cartesian_to_spherical(x_b, y_b, z_b)
    coords_spherical_final = np.column_stack((np.degrees(th_final_rad), np.degrees(ph_final_rad), r_final)).tolist()

    result_raw = evaluate_she_field(
        coords_sph=coords_spherical_final,
        she_input=coeff_path,
        obs_mode=obs_mode_val,
        c_sound=c_sound,
        use_optimized_origins=use_optimized_origins,
        ir_capture_padding_samples=ir_capture_padding_samples,
        use_process_pool=use_process_pool
    )
    
    freqs = result_raw["freqs"]
    p_raw_all = result_raw["complex"] 
    fs_val = result_raw.get("fs")
    
    apply_cal_val = apply_mic_cal if apply_mic_cal is not None else getattr(config_process, 'APPLY_MIC_CALIBRATION', False)
    if apply_cal_val:
        cal_file = mic_cal_file if mic_cal_file else getattr(config_process, 'MIC_CALIBRATION_FILE', 'MM1_Mic_Cal.txt')
        cal_mode = mic_cal_mode if mic_cal_mode is not None else getattr(config_process, 'MIC_CALIBRATION_MODE', 'subtract')
        fade_oct = float(mic_cal_fade_octaves) if mic_cal_fade_octaves is not None else getattr(config_process, 'MIC_CALIBRATION_FADE_OCTAVES', 1.0)
        print(f"Applying mic calibration: {cal_file} (Mode: {cal_mode}, Fade: {fade_oct} oct)")
        p_raw_all = apply_mic_calibration(p_raw_all, freqs, cal_file, cal_mode, fade_oct)

    frd_offset_val = float(frd_db_offset) if frd_db_offset is not None else getattr(config_process, 'FRD_DB_OFFSET', 0.0)

    subtract_tof = subtract_tof if subtract_tof is not None else getattr(config_process, 'SUBTRACT_TOF', "Off")
    if isinstance(subtract_tof, bool):
        subtract_tof = "Ref Origin" if subtract_tof else "Off"
        
    if subtract_tof.lower() == "ref origin":
        # Geometry-only mode. r_in is the configured observation radius before
        # Cartesian mic/reference offsets; those offsets move the reference and
        # microphone together and therefore must not change the subtracted delay.
        tof_ref_dist = np.min(r_in)
        print(f"TOF subtraction ON (ref {tof_ref_dist:.6f} m from Ref Origin)")
        p_raw_all *= get_tof_phasor(freqs, tof_ref_dist, c_sound)[:, np.newaxis]
    elif subtract_tof.lower() == "ir peak":
        # Time-domain mode. Generate only the on-axis full-resolution IR, use its
        # earliest significant peak as the physical delay, then apply that same
        # delay to every CTA response so relative timing remains unchanged.
        from fdw_smoothing_core import get_earliest_significant_peak
        idx_on_axis = map_indices['H0']
        p_on_axis = p_raw_all[:, idx_on_axis]
        ir_on_axis = complex_to_ir(p_on_axis, freqs)
        target_fs = fs_val if fs_val else (44100 if freqs[-1] < 23000.0 else 48000)
        peak_idx = get_earliest_significant_peak(ir_on_axis, target_fs, -12.0)
        peak_time = peak_idx / target_fs
        tof_ref_dist = peak_time * c_sound
        print(f"TOF subtraction ON (IR Peak detection)")
        print(f"Detected IR peak at {peak_time*1000:.3f} ms (ref {tof_ref_dist:.6f} m)")
        p_raw_all *= get_tof_phasor(freqs, tof_ref_dist, c_sound)[:, np.newaxis]
    elif subtract_tof.lower() == "min phase ref":
        # Frequency-domain mode. Compare the on-axis complex response with the
        # minimum-phase response implied by its magnitude and robustly estimate
        # the remaining linear excess group delay. Apply it to the whole set.
        idx_on_axis = map_indices['H0']
        p_on_axis = p_raw_all[:, idx_on_axis]
        tof_ref_dist = get_min_phase_delay(p_on_axis, freqs, c_sound)
        print(f"TOF subtraction ON (Min Phase Ref)")
        print(f"Detected Min Phase delay: {tof_ref_dist/c_sound*1000:.3f} ms (ref {tof_ref_dist:.6f} m)")
        p_raw_all *= get_tof_phasor(freqs, tof_ref_dist, c_sound)[:, np.newaxis]
    else:
        # Off: retain physical propagation phase. The separate artificial
        # capture-padding correction has already occurred in evaluate_she_field.
        print("TOF subtraction: OFF")

    print("Computing Spinorama metrics...")
    metrics = calculate_cta2034_metrics(freqs, p_raw_all, map_indices, coord_deviations)
    
    if save_to_disk:
        print(f"Writing files to {cta_dir}...")
        for name, (mag, phase) in metrics.items():
            if frd_offset_val != 0.0 and name not in ("Response_ERDI", "Response_SPDI"):
                mag = mag + frd_offset_val
            fpath = cta_dir / f"{name}.frd"
            if "/" in name:
                fpath = cta_dir / f"{name.split('/')[0]}" / f"{name.split('/')[1]}.frd"
            write_frd(freqs, mag, phase, fpath, "CTA-2034")
            
        print("Success. CTA-2034 generation complete.")
        
    elapsed = time.time() - start_time
    print(f"\nStage 5 processing completed in {elapsed:.2f} seconds.")

    return {"freqs": freqs, "metrics": metrics}

# -------------------------------------------------
# Standard Sweep Driver Function
# -------------------------------------------------
def run_sweep_extraction(
    coeff_path=None, output_dir=None, use_coord_list=None, coord_list=None,
    direction=None, range_deg=None, increment_deg=None, zero_theta=None,
    zero_phi=None, dist_mic=None, obs_mode=None, offset_xyz=None, subtract_tof=None,
    frd_prefix=None, c_sound=None, save_to_disk=True, generate_ir_files=None,
    apply_mic_cal=None, mic_cal_file=None, mic_cal_mode=None,
    mic_cal_fade_octaves=None, use_optimized_origins=True, frd_db_offset=None,
    ir_capture_padding_samples=None, use_process_pool=True
):
    start_time = time.time()

    import config_process
    coeff_path = coeff_path if coeff_path is not None else config_process.COEFF_PATH
    output_dir = Path(output_dir if output_dir is not None else config_process.OUTPUT_DIR)
    use_coord_list = use_coord_list if use_coord_list is not None else config_process.USE_COORD_LIST
    coord_list = coord_list if coord_list is not None else config_process.COORD_LIST
    direction = direction if direction is not None else config_process.DIRECTION
    range_deg = range_deg if range_deg is not None else config_process.RANGE_DEG
    increment_deg = increment_deg if increment_deg is not None else config_process.INCREMENT_DEG
    zero_theta = zero_theta if zero_theta is not None else config_process.ZERO_THETA_DEG
    zero_phi = zero_phi if zero_phi is not None else config_process.ZERO_PHI_DEG
    dist_mic = dist_mic if dist_mic is not None else config_process.DIST_MIC
    obs_mode = obs_mode if obs_mode is not None else config_process.OBSERVATION_MODE
    offset_xyz = offset_xyz if offset_xyz is not None else (config_process.OFFSET_MIC_X, config_process.OFFSET_MIC_Y, config_process.OFFSET_MIC_Z)
    subtract_tof = subtract_tof if subtract_tof is not None else getattr(config_process, 'SUBTRACT_TOF', "Off")
    frd_prefix = frd_prefix if frd_prefix is not None else config_process.FRD_PREFIX
    c_sound = _resolve_speed_of_sound(c_sound, coeff_path, config_process.SPEED_OF_SOUND)
    gen_ir = generate_ir_files if generate_ir_files is not None else getattr(config_process, 'GENERATE_IR_FILES', False)
    ir_capture_padding_samples = (
        IR_CAPTURE_PADDING_SAMPLES
        if ir_capture_padding_samples is None
        else int(ir_capture_padding_samples)
    )

    output_dir = output_dir / frd_prefix
    complex_dir = output_dir / "complex"
    ir_dir = output_dir / "ir"
    if save_to_disk:
        output_dir.mkdir(parents=True, exist_ok=True)
        complex_dir.mkdir(parents=True, exist_ok=True)
        if gen_ir:
            ir_dir.mkdir(parents=True, exist_ok=True)

    coords_spherical = []
    prefixes = []
    default_r = float(dist_mic)

    if not use_coord_list:
        print(f"Sweep Mode: Direction={direction.upper()}, ±{range_deg}°, step={increment_deg}°")
    else:
        print(f"List Mode: {len(coord_list)} coordinate points")
    print(f"Observation mode: {obs_mode}")

    if use_coord_list:
        for entry in coord_list:
            if len(entry) == 2:
                th, ph = entry; r = default_r
            else:
                th, ph, r = entry
            coords_spherical.append((th, ph, r))
            r_str = f"{int(round(r*1000))}mm"
            prefixes.append((f"{frd_prefix}_{r_str}_th{th}_ph{ph}", ""))
    else:
        rng = int(range_deg); inc = int(increment_deg)
        
        th_rad = np.radians(float(zero_theta))
        ph_rad = np.radians(float(zero_phi))
        # Define the local coordinate system basis vectors robustly to avoid gimbal lock
        # Forward vector (local X')
        F = np.array([np.sin(th_rad) * np.cos(ph_rad), np.sin(th_rad) * np.sin(ph_rad), np.cos(th_rad)])
        
        # Right vector (local Y')
        R = np.array([-np.sin(ph_rad), np.cos(ph_rad), 0])

        # Up vector (local Z'), derived from the other two to ensure a right-handed system
        U = np.cross(F, R)
        rot_matrix = np.array([F, R, U]).T

        off_range = centered_sweep_angles(rng, inc)
        for ang_deg in off_range:
            ang_rad = np.radians(ang_deg)
            val_str = f"+{ang_deg}" if ang_deg >= 0 else f"{ang_deg}"
            
            if direction.lower() in ("horizontal", "hor_vert"):
                p_local = np.array([default_r * np.cos(ang_rad), default_r * np.sin(ang_rad), 0])
                p_global = rot_matrix @ p_local
                r_s, th_s, ph_s = cartesian_to_spherical(p_global[0], p_global[1], p_global[2])
                coords_spherical.append((np.degrees(th_s), np.degrees(ph_s), r_s))
                prefixes.append((f"{frd_prefix}_{int(default_r*1000)}mm_hor{val_str}", ""))
            if direction.lower() in ("vertical", "hor_vert"):
                if direction.lower() == "hor_vert" and ang_deg == 0: continue
                p_local = np.array([default_r * np.cos(ang_rad), 0, default_r * np.sin(ang_rad)])
                p_global = rot_matrix @ p_local
                r_s, th_s, ph_s = cartesian_to_spherical(p_global[0], p_global[1], p_global[2])
                coords_spherical.append((np.degrees(th_s), np.degrees(ph_s), r_s))
                prefixes.append((f"{frd_prefix}_{int(default_r*1000)}mm_ver{val_str}", ""))

    # Apply static offsets here in stage5, unless in manual mode where coords are absolute
    pts_sph = np.array(coords_spherical, dtype=float)
    r_in, th_in_rad, ph_in_rad = pts_sph[:, 2], np.radians(pts_sph[:, 0]), np.radians(pts_sph[:, 1])
    x_b, y_b, z_b = spherical_to_cartesian(r_in, th_in_rad, ph_in_rad)

    if not use_coord_list:
        off_x, off_y, off_z = offset_xyz
        x_b += off_x; y_b += off_y; z_b += off_z

    r_final, th_final_rad, ph_final_rad = cartesian_to_spherical(x_b, y_b, z_b)
    coords_spherical_final = np.column_stack((np.degrees(th_final_rad), np.degrees(ph_final_rad), r_final)).tolist()

    if isinstance(subtract_tof, bool):
        subtract_tof = "Ref Origin" if subtract_tof else "Off"

    tof_ref_dist = None
    if subtract_tof.lower() == "ref origin":
        # Geometry-only mode. Use the configured radius before Cartesian offsets;
        # offsets move the reference and mic together, leaving this delay at (for
        # example) 1 m. No response analysis is needed for this mode.
        r_acous = r_in
        tof_ref_dist = np.min(r_acous)
        print(f"TOF subtraction ON (ref {tof_ref_dist:.6f} m from Ref Origin)")
    elif subtract_tof.lower() == "ir peak":
        # Deferred until the calibrated full-resolution complex responses exist.
        # Only then can the on-axis reference IR be synthesized and peak-tested.
        pass
    elif subtract_tof.lower() == "min phase ref":
        # Also deferred until the calibrated on-axis complex response exists.
        # This mode remains entirely in the frequency domain.
        pass
    else:
        # Off retains physical propagation phase; evaluate_she_field still
        # removes the separate artificial capture-padding phase.
        print("TOF subtraction: OFF")

    result_raw = evaluate_she_field(
        coords_sph=coords_spherical_final,
        she_input=coeff_path,
        obs_mode=obs_mode,
        c_sound=c_sound,
        use_optimized_origins=use_optimized_origins,
        ir_capture_padding_samples=ir_capture_padding_samples,
        use_process_pool=use_process_pool
    )
    
    freqs = result_raw["freqs"]
    p_raw_all = result_raw["complex"] 
    fs_val = result_raw.get("fs")

    apply_cal_val = apply_mic_cal if apply_mic_cal is not None else getattr(config_process, 'APPLY_MIC_CALIBRATION', False)
    if apply_cal_val:
        cal_file = mic_cal_file if mic_cal_file else getattr(config_process, 'MIC_CALIBRATION_FILE', 'MM1_Mic_Cal.txt')
        cal_mode = mic_cal_mode if mic_cal_mode is not None else getattr(config_process, 'MIC_CALIBRATION_MODE', 'subtract')
        fade_oct = float(mic_cal_fade_octaves) if mic_cal_fade_octaves is not None else getattr(config_process, 'MIC_CALIBRATION_FADE_OCTAVES', 1.0)
        print(f"Applying mic calibration: {cal_file} (Mode: {cal_mode}, Fade: {fade_oct} oct)")
        p_raw_all = apply_mic_calibration(p_raw_all, freqs, cal_file, cal_mode, fade_oct)
        
    frd_offset_val = float(frd_db_offset) if frd_db_offset is not None else getattr(config_process, 'FRD_DB_OFFSET', 0.0)

    if subtract_tof.lower() == "ir peak":
        # Time-domain mode. Select the on-axis (or manual-list reference) response,
        # synthesize one full-resolution IR, and use its earliest significant peak.
        # The resulting single delay is shared by all exported observation points.
        from fdw_smoothing_core import get_earliest_significant_peak
        
        if use_coord_list:
            idx_ref = int(np.argmin(r_in))
        else:
            target_th = float(zero_theta)
            target_ph = float(zero_phi)
            
            idx_ref = 0
            min_err = float('inf')
            for i, (th, ph, r) in enumerate(coords_spherical):
                err = abs(th - target_th) + abs(ph - target_ph)
                if err < min_err:
                    min_err = err
                    idx_ref = i
                
        p_ref = p_raw_all[:, idx_ref]
        ir_ref = complex_to_ir(p_ref, freqs)
        target_fs = fs_val if fs_val else (44100 if freqs[-1] < 23000.0 else 48000)
        peak_idx = get_earliest_significant_peak(ir_ref, target_fs, -12.0)
        peak_time = peak_idx / target_fs
        tof_ref_dist = peak_time * c_sound
        print(f"TOF subtraction ON (IR Peak detection)")
        print(f"Detected IR peak at {peak_time*1000:.3f} ms (ref {tof_ref_dist:.6f} m) from index {idx_ref}")

    if subtract_tof.lower() == "min phase ref":
        # Frequency-domain mode. The calibrated on-axis/reference response is
        # divided by its magnitude-derived minimum-phase equivalent; robust local
        # excess group delay yields one common delay for the complete export set.
        if use_coord_list:
            idx_ref = int(np.argmin(r_in))
        else:
            target_th = float(zero_theta)
            target_ph = float(zero_phi)
            
            idx_ref = 0
            min_err = float('inf')
            for i, (th, ph, r) in enumerate(coords_spherical):
                err = abs(th - target_th) + abs(ph - target_ph)
                if err < min_err:
                    min_err = err
                    idx_ref = i
                
        p_ref = p_raw_all[:, idx_ref]
        tof_ref_dist = get_min_phase_delay(p_ref, freqs, c_sound)
        print(f"TOF subtraction ON (Min Phase Ref)")
        print(f"Detected Min Phase delay at {tof_ref_dist/c_sound*1000:.3f} ms (ref {tof_ref_dist:.6f} m) from index {idx_ref}")

    if subtract_tof.lower() in ("ref origin", "ir peak", "min phase ref") and tof_ref_dist is not None:
        # A positive phase rotation advances every response by the chosen delay.
        # Sharing this phasor preserves relative TOF between observation points.
        tof_phasor = get_tof_phasor(freqs, tof_ref_dist, c_sound)
    else:
        # Off writes the pressure phase after capture-padding correction only.
        tof_phasor = None

    if save_to_disk:
        print("Writing files...")
    coords_log = []
    extracted_data = {}
    
    # SHE data is capped at 24kHz, so IRs are strictly generated at standard rates
    target_fs = 44100 if freqs[-1] < 23000.0 else 48000
    
    for idx, (prefix, subdir) in enumerate(prefixes):
        p_raw = p_raw_all[:, idx]
        th_in, ph_in, r_in = coords_spherical_final[idx]
        coords_log.append(f"{prefix}    {th_in:.2f}    {ph_in:.2f}    {r_in:.6f}")

        p_frd = p_raw.copy()
        if tof_phasor is not None:
            p_frd *= tof_phasor

        # --- IR Generation ---
        if save_to_disk and gen_ir:
            ir_out_dir = ir_dir / subdir if subdir else ir_dir
            
            ir_audio = complex_to_ir(
                p_complex=p_raw,
                freqs=freqs
            )
            
            write_wav(
                ir_audio,
                target_fs,
                ir_out_dir / f"{prefix}.wav",
                "Impulse Response"
            )

        eps = np.finfo(float).eps
        mags = 20 * np.log10(np.abs(p_frd) + eps)
        if frd_offset_val != 0.0:
            mags += frd_offset_val
        phases = np.angle(p_frd, deg=True)
        
        extracted_data[prefix] = {
            "complex": p_raw,
            "mag": mags,
            "phase": phases,
            "theta": th_in,
            "phi": ph_in,
            "r": r_in
        }

        if save_to_disk:
            out_subdir = output_dir / subdir if subdir else output_dir
            comp_subdir = complex_dir / subdir if subdir else complex_dir
            
            write_complex_npz(
                freqs, p_raw, 
                comp_subdir / f"{prefix}_complex.npz",
                theta_in=th_in, phi_in=ph_in, r_in=r_in
            )
            write_frd(freqs, mags, phases, out_subdir / f"{prefix}.frd", obs_mode)
        
    if save_to_disk:
        with open(output_dir / "coordinates.txt", "w") as f:
            f.write("# prefix    theta(deg)    phi(deg)    r(m)\n")
            f.write("\n".join(coords_log))
            
        print(f"Success. Files written to {output_dir}")
        
    elapsed = time.time() - start_time
    print(f"\nStage 5 processing completed in {elapsed:.2f} seconds.")

    return {"freqs": freqs, "data": extracted_data}

# -------------------------------------------------


# -------------------------------------------------
# Main CLI Execution
# -------------------------------------------------
def main():
    try:
        import config_process
        
        if getattr(config_process, 'CTA_MODE', False):
            run_cta2034_extraction()
        else:
            run_sweep_extraction()
    except ImportError:
        print("Error: config_process.py not found.")

if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
