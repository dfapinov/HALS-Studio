"""Export the two test microphones with capture padding disabled.

Run from the repository root:
    python misc/system_testing/hals_tof_test/export_test.py --coeff path/to/coefficients.h5
"""
import argparse
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))
import bootstrap
sys.path.insert(0, str(ROOT / 'process_engine'))
from stage5_extract_pressures import run_sweep_extraction

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--coeff', type=Path, default=ROOT/'misc/system_testing/hals_tof_test/input_irs_synth/outputs/coefficients/MySpeaker_coefficients.h5')
    args = parser.parse_args()
    if not args.coeff.is_file():
        parser.error('Coefficient file not found. Use --coeff to select your solved H5 file.')
    for mode in ['Off', 'Ref Origin']:
        for z in [0, 0.5]:
            run_sweep_extraction(coeff_path=args.coeff, output_dir=HERE/'test_exports',
                frd_prefix=f'{mode.replace(" ", "")}_z{int(z*1000)}',
                use_coord_list=False, direction='horizontal', range_deg=0, increment_deg=10,
                zero_theta=90, zero_phi=0, dist_mic=2, offset_xyz=(0,0,z),
                obs_mode='Internal', subtract_tof=mode, c_sound=343,
                ir_capture_padding_samples=0, apply_mic_cal=False, frd_db_offset=0,
                use_optimized_origins=False, generate_ir_files=False, use_process_pool=False)
    (HERE/'test_exports'/'settings.json').write_text(json.dumps({
        'coefficient_file': str(args.coeff.resolve()), 'speed_of_sound_mps': 343,
        'capture_padding_samples': 0, 'use_optimized_origins': False,
        'radius_m': 2, 'offsets_z_m': [0, 0.5]}, indent=2))

if __name__ == '__main__':
    main()
