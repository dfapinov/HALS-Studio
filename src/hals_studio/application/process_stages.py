"""Individual processing use cases; numerical work remains in the engine."""

import numpy as np
from hals_studio.persistence import process_cache
from hals_studio.application.process_contracts import OriginResult


class FileMapping(dict):
    @property
    def files(self):
        return list(self)


def prepare_measurements(request, runtime, out, filename, input_name):
    v = request["settings"]
    name = request["name"]
    from hals_studio.process_engine.stage1_fdwsmooth import fdwsmooth

    smooth = v["smoothing_oct_res"]
    result = fdwsmooth(
        input_dir=request["ir_folder"],
        input_filenames=request.get("input_filenames"),
        rft_supplied=request.get("rft_supplied", True),
        out_dir=str(out),
        output_filename=filename,
        fdw_rft_ms=float(request.get("rft_ms", v.get("fdw_rft_ms", 5.0))),
        fdw_oct_res=float(v["fdw_oct_res"]),
        fdw_max_cap_ms=float(v["fdw_max_cap_ms"]),
        enable_smoothing=v["enable_smoothing"],
        smoothing_oct_res=smooth,
        show_plot=False,
        save_to_disk=True,
        fdw_alpha_hf=float(v["fdw_alpha_hf"]),
        fdw_alpha_lf=float(v["fdw_alpha_lf"]),
        fdw_windows_per_oct=int(v["fdw_windows_per_oct"]),
        peak_detect_threshold_db=float(v["peak_detect_threshold_db"]),
        enable_auto_gain=False,
        keep_raw_and_smoothed=v["keep_raw_and_smoothed"],
        use_process_pool=True,
        workers=request.get("workers"),
        runtime=runtime,
    )

    return result


def search_origins(request, runtime, out, filename, input_name):
    v = request["settings"]
    name = request["name"]
    from hals_studio.process_engine.stage2_centre_origin import (
        run_origin_search,
        export_interpolated_origins,
    )

    if request.get("action") in ("save_origins", "rescan"):
        result = process_cache.hydrate_stage2(
            process_cache.load(request["cache"], 2), out / filename
        )
        for row in result[0].values():
            row.setdefault("original_c", np.array(row["final_c"]).copy())
            row.setdefault("original_error", row["error"])
        for freq, xyz in request.get("edits", []):
            result[0][float(freq)]["final_c"] = np.asarray(xyz)
        if request["action"] == "rescan":
            from hals_studio.process_engine.stage2_centre_origin import (
                get_order_for_frequency,
                generate_3d_landscape_volumetric,
                run_simplex_descent_3d,
            )

            rows, freqs, keys, d, geom, cfg, data = result
            # A rescan starts from cached Stage 2 data, but its scan region and
            # resolution come from the settings currently displayed in the UI.
            for axis in "xyz":
                cfg[f"{axis}_bounds"] = tuple(
                    float(part.strip()) for part in v[f"{axis}_bounds"].split(",")
                )
            cfg.pop("scan_radius_mm", None)  # Full grid re-scans use only manual XYZ bounds.
            cfg["grid_res_mm"] = float(v["grid_res_mm"])
            for f in request["rescan"]:
                i = np.argmin(abs(freqs - f))
                N = get_order_for_frequency(
                    f,
                    cfg.get("manual_order_table", {}),
                    cfg.get("target_n_max_origins", 4),
                    cfg.get("N_grid", 999),
                )
                pc = (
                    [
                        (
                            float(f),
                            float(2 * np.pi * f / cfg["speed_of_sound"]),
                            np.array([d[k][i] for k in keys]),
                        )
                    ],
                    *geom,
                    N,
                    cfg,
                )
                x, y, z, grid = generate_3d_landscape_volumetric(pc, runtime=runtime)
                idx = np.unravel_index(np.argmin(grid), grid.shape)
                seed = (x[idx[0]], y[idx[1]], z[idx[2]])
                from hals_studio.process_engine.process_progress import Progress

                refining = runtime.progress("Stage 2 refining grid origin", 1)
                centre, path = run_simplex_descent_3d(seed, pc, runtime=runtime)
                rows[f].update(grid=grid, X_vals=x, Y_vals=y, Z_vals=z, final_c=centre, path=path)
                refining.advance()
    else:
        result = run_origin_search(
            input_dir_origins=str(out),
            input_filename_origins=filename,
            output_filename_origins=filename,
            tweeter_coords_mm=(tuple(float(v["tweeter_" + k]) for k in "xyz")
                               if request.get("tweeter_supplied", True) else None),
            octave_resolution=1 / float(v["octave_resolution"]),
            freq_start_hz=float(v["freq_start_hz"]),
            freq_end_hz=float(v["freq_end_hz"]),
            initial_simplex_step=float(v["initial_simplex_step"]),
            max_iterations=int(v["max_iterations"]),
            target_n_max_origins=int(v["target_n_max_origins"]),
            manual_order_table=None,
            save_to_disk=False,
            plot_results_origins=False,
            speed_of_sound=float(request.get("speed", 343)),
            optimize_speed_of_sound=not request.get("manual_speed", False),
            use_process_pool=True,
            return_state=True,
            use_cache=request.get("action") == "load_origins",
            read_cache_file=request.get("origin_cache", ""),
            hold_origin_lf=v.get("hold_origin_lf", True),
            hold_origin_hf=v.get("hold_origin_hf", True),
            runtime=runtime,
        )
    if result is None:
        raise ValueError("Origin search returned no results")
    rows, freqs, keys, d, geom, cfg, data = result
    if request.get("action") in ("rescan", "save_origins"):
        from hals_studio.process_engine.stage2_centre_origin import (
            solve_physics_3d,
            get_order_for_frequency,
        )

        for f, row in rows.items():
            i = np.argmin(abs(freqs - f))
            N = get_order_for_frequency(
                f,
                cfg.get("manual_order_table", {}),
                cfg.get("target_n_max_origins", 4),
                cfg.get("N_grid", 999),
            )
            pc = (
                [
                    (
                        float(f),
                        float(2 * np.pi * f / cfg["speed_of_sound"]),
                        np.array([d[k][i] for k in keys]),
                    )
                ],
                *geom,
                N,
                cfg,
            )
            row["error"] = solve_physics_3d(*row["final_c"], pc)
    cfg.update(
        hold_origin_lf=v.get("hold_origin_lf", True), hold_origin_hf=v.get("hold_origin_hf", True)
    )
    source = data
    data = FileMapping(source)
    if hasattr(source, "close"):
        source.close()
    usable = [(f, r["final_c"]) for f, r in sorted(rows.items()) if r["final_c"] is not None]
    if not usable:
        raise ValueError("No valid acoustic origins")
    xyz = np.array([p for f, p in usable])
    export_interpolated_origins(
        [f for f, p in usable],
        *xyz.T,
        freqs,
        data,
        str(out),
        filename,
        True,
        speed_of_sound=cfg.get("speed_of_sound", 343),
        test_range_hz=cfg.get("origin_test_range_hz"),
        hold_origin_lf=v.get("hold_origin_lf", True),
        hold_origin_hf=v.get("hold_origin_hf", True),
        runtime=runtime,
    )
    result = OriginResult(rows, freqs, keys, d, geom, cfg, dict(data))

    return result


def choose_order(request, runtime, out, filename, input_name):
    v = request["settings"]
    name = request["name"]
    from hals_studio.process_engine.stage3_optimize_she_settings import run_open_branch_optimizer

    orders = tuple(int(x.strip()) for x in v["test_order_range"].split(","))
    action = request.get("action")
    if action == "reference":
        from hals_studio.process_engine.stage3_optimize_she_settings import (
            stage3_order_choices,
            recommended_stage3_choice,
        )

        result = process_cache.load(request["cache"], 3)
        result.pop("condition_preflight", None)
        result.pop("selected_order_N", None)
        step = result["step1"]
        selected = step["tail_by_reference"][str(request["reference"])]
        tail_only = result.get("tail_only", False)
        step["internal_tail_power_db"] = selected["power_db"]
        step["tail_reference"].update(selected, manual=True)
        updated = stage3_order_choices(
            step["orders"],
            step["ratios"],
            step["residuals"],
            step.get("rolloff_knee"),
            selected["power_db"],
            selected["n"],
            tail_only=tail_only,
            manual_reference=tail_only,
        )
        for key in ("knee", "tail"):
            result["options"].pop(key, None)
        result["options"].update(updated)
        result["recommended_key"] = recommended_stage3_choice(result["options"])
    else:
        result = run_open_branch_optimizer(
            input_dir_opti=str(out),
            input_filename_opti=input_name,
            test_order_range=orders,
            octave_resolution=int(v["octave_resolution"]),
            spl_change_enabled=True,
            spl_sphere_points=int(v["spl_sphere_points"]),
            spl_radius_m=float(v["spl_radius_m"]),
            spl_floor_db=-40.0,
            freq_start_hz=float(v["freq_start_hz"]),
            freq_end_hz=float(v["freq_end_hz"]),
            use_optimized_origins=True,
            speed_of_sound=343.0,
            kr_offset=2.0,
            use_process_pool=True,
            process_pool=runtime.borrow_pool(6),
            rft_ms=float(v.get("fdw_rft_ms", request.get("rft_ms", 5.0))),
            project_oct_res=float(request.get("project_oct_res", 12.0)),
            runtime=runtime,
        )

    return result


def solve_model(request, runtime, out, filename, input_name):
    v = request["settings"]
    name = request["name"]
    from hals_studio.process_engine.stage4_run_she_solve import run_she_solve

    result = run_she_solve(
        input_filename_she=filename,
        output_filename_she=name + "_coefficients.h5",
        input_dir_she=str(out),
        output_dir_she=str(out / "coefficients"),
        target_n_max=int(v["target_n_max"]),
        kr_offset=float(v["kr_offset"]),
        use_manual_table=v["use_manual_table"],
        manual_order_table={float(k): int(n) for k, n in request["manual_table"].items()},
        noise_floor_start_db=float(v["noise_floor_start_db"]),
        noise_floor_max_db=float(v["noise_floor_max_db"]),
        max_lambda=float(v["max_lambda"]) if v["enable_regularization"] else 0.0,
        condition_metrics=True,
        use_optimized_origins=True,
        save_to_disk=True,
        speed_of_sound=343.0,
        jobs=None,
        show_plot=False,
        use_process_pool=True,
        condition_preflight=v.get("condition_preflight", True),
        runtime=runtime,
    )

    return result
