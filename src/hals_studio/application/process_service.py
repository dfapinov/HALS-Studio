"""Processing orchestration shared by Studio jobs and the command-line host."""

import sys
import json
import traceback
import multiprocessing
from pathlib import Path
import hals_studio.persistence.process_cache as process_cache

from hals_studio.application.process_stages import (
    prepare_measurements,
    search_origins,
    choose_order,
    solve_model,
)

STAGE_RUNNERS = {1: prepare_measurements, 2: search_origins, 3: choose_order, 4: solve_model}


def run(request, *, runtime=None):
    from hals_studio.process_engine.runtime import EngineRuntime
    from hals_studio.application.process_contracts import ProcessRequest

    runtime = runtime or EngineRuntime()
    runtime.check()
    request = ProcessRequest.from_mapping(request).to_mapping()
    stage = int(request["stage"])
    v = request["settings"]
    root = Path(request["folder"])
    name = request["name"]
    out = root / "outputs"
    out.mkdir(exist_ok=True)
    filename = name + "_complex_data.npz"
    input_name = (
        name + "_complex_data_centered.npz"
        if stage == 3 and (out / (name + "_complex_data_centered.npz")).exists()
        else filename
    )
    if stage > 1 and not (out / input_name).is_file():
        raise ValueError("Run Stage 1 first: " + str(out / input_name))
    result = STAGE_RUNNERS[stage](request, runtime, out, filename, input_name)
    if result is None:
        raise ValueError("Processing returned no results; inspect the CLI output")
    cache = Path(request["cache"])
    if stage == 1:
        cache.unlink(missing_ok=True)
        return str(out / filename)
    runtime.progress(f"Stage {stage} saving results", 0, console=False)
    runtime.check()
    process_cache.save(cache, stage, result)
    return str(cache)


def main():
    from hals_studio.process_engine.session_pool import SessionPool, install_session_pool

    pool = SessionPool()
    install_session_pool(pool)
    pool.start()
    print("HALS Process worker pool warming", flush=True)
    try:
        for line in sys.stdin:
            try:
                request = json.loads(line)
                result = run(request)
                print(
                    "\n@@HALS@@"
                    + json.dumps({"ok": True, "stage": request["stage"], "cache": result}),
                    flush=True,
                )
            except Exception:
                traceback.print_exc()
                print("\n@@HALS@@" + json.dumps({"ok": False}), flush=True)
    finally:
        pool.close()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
