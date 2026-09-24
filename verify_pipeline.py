"""Standalone Stages 1-4 smoke test with generated IRs and two shared workers."""
import multiprocessing
import json
import os
from pathlib import Path
import bootstrap
import numpy as np
import soundfile as sf


def main():
    from process_service import run
    from process_job import SharedPool
    from session_pool import install_session_pool
    from worker_pool import WarmPool
    root = (bootstrap.HERE/'artifacts/pipeline-smoke').resolve()
    recordings = root/'recordings'; recordings.mkdir(parents=True, exist_ok=True)
    for radius in (100., 150.):
        for elevation in (-60., -30., 0., 30., 60.):
            for azimuth in range(0, 360, 45):
                r = radius*np.cos(np.deg2rad(elevation)); z = radius*np.sin(np.deg2rad(elevation))
                ir = np.zeros(2048); delay = 64+radius/1000/343*48000
                i = int(delay); fraction = delay-i
                gain = .05/radius*(1+.2*np.cos(np.deg2rad(azimuth))*np.cos(np.deg2rad(elevation)))
                ir[i:i+2] = gain*np.array([1-fraction, fraction])
                number = lambda x: f'{x:.3f}'.replace('.', 'p')
                sf.write(recordings/f"NA_r{number(r)}_ph{azimuth}_z{number(z)}_ir.wav", ir, 48000, subtype='FLOAT')
    schema = json.loads((bootstrap.HERE/'process_schema.json').read_text(encoding='utf-8'))
    values = {int(stage): {k:v['default'] for k,v in fields.items()} for stage,fields in schema.items()}
    values[1].update(fdw_max_cap_ms='40')
    values[2].update(freq_start_hz='1000', freq_end_hz='2100', octave_resolution='1', target_n_max_origins='1', max_iterations='3', x_bounds='-20,20', y_bounds='-20,20', z_bounds='-20,20', grid_res_mm='20')
    values[3].update(freq_start_hz='1000', freq_end_hz='1100', test_order_range='1, 2', octave_resolution='1', spl_sphere_points='30')
    values[4].update(target_n_max='2')
    pool = WarmPool(2); original = Path.cwd()
    try:
        install_session_pool(SharedPool(pool))
        for stage in range(1,5):
            run(dict(stage=stage, settings=values[stage], folder=str(root), name='StudioSmoke', ir_folder=str(recordings), cache=str(root/f'stage{stage}.pkl'), manual_table={}, speed=343., manual_speed=True, workers=2))
            print(f'STAGE {stage} PASS', flush=True)
        assert (root/'outputs/coefficients/StudioSmoke_coefficients.h5').is_file()
        print('PASS: standalone processing pipeline and coefficient output', flush=True)
    finally:
        pool.close(); os.chdir(original)

if __name__ == '__main__':
    multiprocessing.freeze_support()
    main()
