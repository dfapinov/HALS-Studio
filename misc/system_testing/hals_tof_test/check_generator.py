"""Check three recorded IRs against the copied generator settings without writing WAVs."""
from pathlib import Path
import csv
import numpy as np
from scipy.io.wavfile import read
import synth_ir_gen_tof_test as s

here=Path(__file__).resolve().parent
rows=list(csv.DictReader((here/'synth_ir_grid.csv').open()))
pts=s.generate_piston_points(s.SOURCE_CENTER_M,s.PISTON_RADIUS_M,s.PISTON_POINT_COUNT,s.PISTON_FACING_AXIS)
files=list((here/'input_irs_synth/recordings').glob('*.wav'))
print('Grid rows:',len(rows),'Recorded WAVs:',len(files))
for row in [rows[0],rows[500],rows[-1]]:
    mic=s._cylindrical_to_cartesian(float(row['r_xy_mm']),float(row['phi_deg']),float(row['z_mm']))
    path=next(p for p in files if p.name.startswith('id'+row['order_idx']+'_'))
    fs,w=read(path)
    spectrum,_=s.compute_distributed_piston_spectrum(mic,pts,fs,16384,s.DEFAULT_C)
    generated=(np.fft.irfft(spectrum,n=16384)[:len(w)]*s.VOLUME_GAIN).astype(np.float32)
    print(path.name,'maximum sample difference:',np.max(np.abs(w-generated)))
