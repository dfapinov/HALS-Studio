"""Optional re-export from existing solved coefficients; never overwrites bundled evidence WAVs."""
from pathlib import Path
import argparse
import sys

HERE=Path(__file__).resolve().parent

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('case',choices=['synthetic','tweeter'])
    p.add_argument('--coeff',type=Path,required=True)
    p.add_argument('--repo',type=Path,default=HERE.parents[3])
    args=p.parse_args()
    sys.path.insert(0, str(args.repo))
    import bootstrap
    sys.path.insert(0,str(args.repo/'process_engine'))
    from stage5_extract_pressures import run_sweep_extraction
    synthetic=args.case=='synthetic'
    coord=(125.5,186.3,.17565) if synthetic else (41.81,3.1,.33002)
    run_sweep_extraction(coeff_path=args.coeff,output_dir=HERE/'reexports',frd_prefix=args.case,
        use_coord_list=True,coord_list=[coord],obs_mode='Internal' if synthetic else 'Full',
        offset_xyz=(0,0,0),subtract_tof='Off',c_sound=343 if synthetic else 347,
        ir_capture_padding_samples=0,apply_mic_cal=False,frd_db_offset=0,
        use_optimized_origins=not synthetic,generate_ir_files=True,use_process_pool=False)

if __name__=='__main__': main()
