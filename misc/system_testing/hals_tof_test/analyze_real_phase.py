"""Read-only comparison of the real tweeter capture and zero-padding Stage 5 export."""
from pathlib import Path
import json
import numpy as np
import soundfile as sf
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

HERE=Path(__file__).resolve().parent
PROJECT=HERE.parents[3].parent/'Tweeter'
name='NA_r219p999_ph3p1_z246p0_ir.wav'
original,fs=sf.read(HERE/'real_tweeter'/name)
export,efs=sf.read(next((HERE/'real_tweeter/hals_export').glob('*.wav')))
assert fs==efs
with np.load(next((PROJECT/'outputs').glob('*.npz')),allow_pickle=True) as n:
    f=n['freqs'].copy(); stage1=n['data'].item()[name].copy()
with np.load(next((PROJECT/'outputs/response_files/DirectivaR2-Tweeter/complex').glob('*.npz'))) as n:
    nf=n['freqs'].copy(); pressure=n['P'].copy()

# Same time zero and FFT grid for both WAVs. No fitted delay or minimum-phase subtraction.
N=131072
ff=np.fft.rfftfreq(N,1/fs)
raw=np.fft.rfft(original,n=N); wav=np.fft.rfft(export,n=N)
def interp(p): return np.interp(nf,ff,p.real)+1j*np.interp(nf,ff,p.imag)
ref=interp(raw); wav_model_grid=interp(wav)
proc=np.interp(nf,f,stage1.real)+1j*np.interp(nf,f,stage1.imag)
pk=np.max(np.abs(raw[(ff>=1000)&(ff<=10000)]))
ratio=wav/raw
band=(ff>=2000)&(ff<=10000)
linear=np.polyfit(ff[band],np.unwrap(np.angle(ratio[band])),1)
summary={'fs':fs,'original_samples':len(original),'export_samples':len(export),
         'peak_samples':[int(np.argmax(abs(original))),int(np.argmax(abs(export)))],
         'stage1_saved_data':'smoothed complex response from the saved project settings',
         'raw_phase_delay_difference_us_fit_2k_10k':float(-linear[0]/(2*np.pi)*1e6),
         'points':[]}
for hz in [50,100,200,500,1000,2000,5000,10000,20000]:
    i=int(np.argmin(abs(nf-hz)))
    row={'frequency_hz':float(nf[i]),'original_level_relative_to_passband_db':float(20*np.log10(abs(ref[i])/pk)),
         'magnitude_difference_db':float(20*np.log10(abs(wav_model_grid[i]/ref[i]))),
         'raw_phase_difference_deg':float(np.angle(wav_model_grid[i]/ref[i],deg=True)),
         'stage1_vs_original_phase_deg':float(np.angle(proc[i]/ref[i],deg=True)),
         'she_vs_stage1_phase_deg':float(np.angle(pressure[i]/proc[i],deg=True)),
         'wav_vs_complex_phase_deg':float(np.angle(wav_model_grid[i]/pressure[i],deg=True))}
    summary['points'].append(row)

# Compare equal-length input slices to quantify the influence of the long capture tail.
truncated=np.fft.rfft(original[:len(export)],n=N)
summary['original_tail_energy_fraction']=float(np.sum(original[len(export):]**2)/np.sum(original**2))
summary['tail_cut_phase_difference_deg']={str(hz):float(np.angle(truncated[np.argmin(abs(ff-hz))]/raw[np.argmin(abs(ff-hz))],deg=True)) for hz in [100,200,500,1000]}
out=HERE/'real_tweeter/phase_analysis';out.mkdir(exist_ok=True)
(out/'comparison.json').write_text(json.dumps(summary,indent=2))
plt.rcParams.update({'font.size':10,'axes.grid':True,'grid.alpha':.2,'axes.spines.top':False,'axes.spines.right':False})
fig,axs=plt.subplots(3,1,figsize=(10,9),sharex=True)
sel=(ff>=20)&(ff<=20000)
axs[0].semilogx(ff[sel],20*np.log10(np.maximum(abs(raw[sel])/pk,1e-12)),label='Original capture')
axs[0].semilogx(ff[sel],20*np.log10(np.maximum(abs(wav[sel])/pk,1e-12)),label='HALS WAV',alpha=.8)
axs[0].set_ylabel('Level relative to\noriginal passband (dB)');axs[0].legend();axs[0].set_ylim(-110,5)
axs[1].semilogx(ff[sel],np.angle(ratio[sel],deg=True),lw=.7)
axs[1].set_ylabel('HALS minus original\nraw phase (degrees)');axs[1].set_ylim(-180,180)
sel2=(nf>=20)&(nf<=20000)
for p,q,label in [(proc,ref,'Stage 1 vs original'),(pressure,proc,'SHE vs Stage 1'),(wav_model_grid,pressure,'WAV vs complex export')]:
    axs[2].semilogx(nf[sel2],np.angle(p[sel2]/q[sel2],deg=True),lw=.8,label=label)
axs[2].set_ylabel('Phase change through\nprocessing (degrees)');axs[2].legend(fontsize=8);axs[2].set_ylim(-180,180)
axs[2].set_xlabel('Frequency (Hz)');axs[2].set_xlim(20,20000)
fig.suptitle('Real tweeter: same time zero, no independent delay compensation')
fig.tight_layout();fig.savefig(out/'direct_phase_comparison.png',dpi=180);plt.close(fig)

# Explicit Stage 1 comparison: original full-length capture against this file's
# saved Stage 1 smoothed complex response, with no fitted delay adjustment.
raw_on_stage1=interp(raw)
fig,axs=plt.subplots(2,1,figsize=(10,7),sharex=True)
band1=(nf>=20)&(nf<=20000)
axs[0].semilogx(nf[band1],20*np.log10(np.maximum(abs(raw_on_stage1[band1])/pk,1e-12)),
                label='Original IR, full capture')
axs[0].semilogx(nf[band1],20*np.log10(np.maximum(abs(proc[band1])/pk,1e-12)),
                label='Stage 1 saved response (smoothed)')
axs[0].axhline(-40,color='gray',ls=':',lw=1,label='-40 dB of passband level')
axs[0].set_ylabel('Level relative to original\n1–10 kHz passband (dB)')
axs[0].set_ylim(-110,5);axs[0].legend(fontsize=9)
axs[1].semilogx(nf[band1],np.angle(proc[band1]/raw_on_stage1[band1],deg=True),lw=.8)
axs[1].set_ylabel('Stage 1 minus original\nphase (degrees)')
axs[1].set_xlabel('Frequency (Hz)');axs[1].set_ylim(-180,180);axs[1].set_xlim(20,20000)
fig.suptitle('Original tweeter IR compared directly with Stage 1 output')
fig.tight_layout();fig.savefig(out/'stage1_vs_original.png',dpi=180);plt.close(fig)

# Requested side-by-side phase differences, each referenced to the original
# full capture. Stage 5 uses the exported WAV samples, not the complex NPZ.
phase_stage1=np.angle(proc/raw_on_stage1,deg=True)
phase_stage5=np.angle(wav/raw,deg=True)
fig,axs=plt.subplots(2,1,figsize=(10,7),sharex=True)
axs[0].semilogx(nf[band1],phase_stage1[band1],lw=.8,color='#2878b5')
axs[0].set_ylabel('Phase difference (°)')
axs[0].set_title('Stage 1 (FDW + complex smoothing) minus original full-capture IR',loc='left',fontsize=10)
selwav=(ff>=20)&(ff<=20000)
axs[1].semilogx(ff[selwav],phase_stage5[selwav],lw=.7,color='#d05a35')
axs[1].set_ylabel('Phase difference (°)')
axs[1].set_title('Stage 5 exported IR WAV minus original full-capture IR',loc='left',fontsize=10)
axs[1].set_xlabel('Frequency (Hz)')
for ax in axs:
    ax.set_ylim(-180,180)
    ax.set_xlim(20,20000)
    ax.set_yticks([-180,-90,0,90,180])
fig.suptitle('Phase change relative to the original IR — shared sample-zero timing, no delay fit',y=.99)
fig.tight_layout(rect=(0,0,1,.96))
fig.savefig(out/'phase_difference_stage1_and_stage5.png',dpi=200)
plt.close(fig)
print(json.dumps(summary,indent=2))
