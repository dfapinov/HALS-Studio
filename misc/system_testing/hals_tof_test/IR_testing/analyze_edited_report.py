"""Plots requested in HALS_IR_Validation-tweaked.docx, using packaged evidence only."""
from pathlib import Path
import json
import inspect
import numpy as np
import soundfile as sf
from scipy.fft import next_fast_len
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import NullFormatter
from analyze_ir import spectrum_at, style, BLUE, ORANGE
from reproduction.fdw_smoothing_core import apply_peak_causal_window, get_earliest_significant_peak
from reproduction.complex_to_ir_core import complex_to_ir

HERE=Path(__file__).resolve().parent
OUT=HERE/'edited_figures'
N=131072

def save(fig,name):
    fig.tight_layout();fig.savefig(OUT/name,dpi=200);plt.close(fig)

def lf_ticks(ax):
    ax.set_xticks([20,50,100,200,500,1000],['20','50','100','200','500','1k'])
    ax.xaxis.set_minor_formatter(NullFormatter())

def delta(original,output):
    ratio=original/output
    return 20*np.log10(np.maximum(abs(ratio),1e-30)),np.angle(ratio,deg=True)

def metrics(f,ref,p,lo,hi):
    m=(f>=lo)&(f<=hi);mag,phase=delta(ref,p)
    return {'max_magnitude_db':float(max(abs(mag[m]))),'max_phase_deg':float(max(abs(phase[m]))),
            'rms_phase_deg':float(np.sqrt(np.mean(phase[m]**2)))}

def main():
    OUT.mkdir(exist_ok=True)
    plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False})
    raw,fs=sf.read(HERE/'data/tweeter_original.wav');wav,wfs=sf.read(HERE/'data/tweeter_stage5.wav');assert fs==wfs
    with np.load(HERE/'data/tweeter_stage1.npz') as z:sfreq=z['freqs'];P=z['response']
    stage1_ir=np.fft.irfft(P,n=2*(len(P)-1))
    assert len(stage1_ir)==len(wav)
    W=spectrum_at(wav,fs,sfreq)
    ref=max(abs(P[(sfreq>=1000)&(sfreq<=10000)]))
    fig,ax=plt.subplots(figsize=(8,2.5))
    for x,c,l in [(stage1_ir,BLUE,'Stage 1 output (IFFT of saved response)'),(wav,ORANGE,'Stage 5 WAV')]:
        ax.plot(np.arange(100)*1000/fs,x[:100],color=c,label=l,ls='-' if c==BLUE else '--')
    ax.set(xlim=(0,1.8),xlabel='Time from sample zero (ms)',ylabel='IR amplitude');ax.legend(fontsize=9);ax.grid(alpha=.2)
    save(fig,'tweeter_raw_timing.png')
    fig,axs=plt.subplots(2,1,figsize=(8,4.2),sharex=True)
    mask=(sfreq>=20)&(sfreq<=20000)
    for p,c,l in [(P,BLUE,'Stage 1 output (original IR)'),(W,ORANGE,'Stage 5 WAV')]:
        axs[0].plot(sfreq[mask],20*np.log10(np.maximum(abs(p[mask])/ref,1e-30)),color=c,label=l,lw=.8)
        axs[1].plot(sfreq[mask],np.angle(p[mask]*np.exp(2j*np.pi*sfreq[mask]*.0006),deg=True),color=c,lw=.8)
    style(axs[0],'Magnitude (dB)');axs[0].set_ylim(-100,5);axs[0].legend(fontsize=9);axs[0].set_title('Magnitude overlaid',loc='left',fontsize=10)
    style(axs[1],'Phase (degrees)');axs[1].set_ylim(-180,180);axs[1].set_title('Phase overlaid — 0.6 ms compensation on both traces',loc='left',fontsize=10)
    axs[1].set_xlabel('Frequency (Hz)');save(fig,'tweeter_raw_response.png')
    mag,phase=delta(P,W)
    fig,axs=plt.subplots(2,1,figsize=(8,4.5),sharex=True)
    for ax,y,label in [(axs[0],mag,'Magnitude difference (dB)'),(axs[1],phase,'Phase difference (degrees)')]:
        ax.plot(sfreq[mask],y[mask],color=ORANGE,lw=.8);style(ax,label);ax.axhline(0,color='gray',ls=':',lw=.7);ax.axvline(300,color='gray',ls='--',lw=.8)
    axs[0].set_title('Stage 1 output minus Stage 5 WAV',loc='left',fontsize=10);axs[1].set_xlabel('Frequency (Hz)')
    save(fig,'tweeter_raw_differences.png')
    windowed=apply_peak_causal_window(raw,fs,get_earliest_significant_peak(raw,fs,-12)/fs,.2,1)
    R=spectrum_at(raw,fs,sfreq);RW=spectrum_at(windowed,fs,sfreq);W=spectrum_at(wav,fs,sfreq)
    sm=(sfreq>=20)&(sfreq<=20000)
    for original,title,name in [(R,'Full original capture minus Stage 1','stage1_raw_difference.png'),
                                (RW,'Original with 200 ms window minus Stage 1','stage1_windowed_difference.png')]:
        fig,ax=plt.subplots(figsize=(8,2.6));ax.plot(sfreq[sm],np.angle((original/P)[sm],deg=True),color=BLUE,lw=.8)
        style(ax,'Phase difference (degrees)');ax.set_ylim(-180,180);ax.set_title(title,loc='left',fontsize=10)
        ax.set_xlabel('Frequency (Hz)');save(fig,name)
    with np.load(HERE/'data/tweeter_fit.npz') as z:fitf=z['freqs'];fitdb=20*np.log10(np.maximum(z['pct_error']/100,1e-30))
    fig,axs=plt.subplots(3,1,figsize=(8,5.7),sharex=True)
    axs[0].plot(sfreq[sm],np.angle((P/W)[sm],deg=True),color=ORANGE);style(axs[0],'Phase difference (degrees)');axs[0].set_ylim(-180,180)
    axs[0].set_title('Stage 1 minus Stage 5 WAV',loc='left',fontsize=10)
    axs[1].plot(fitf,fitdb,color=BLUE);style(axs[1],'Fit residual (dB)');axs[1].axhline(-20,color='gray',ls=':')
    pr=max(abs(P[(sfreq>=1000)&(sfreq<=10000)]));axs[2].plot(sfreq[sm],20*np.log10(np.maximum(abs(P[sm])/pr,1e-30)),color=BLUE)
    style(axs[2],'Stage 1 level (dB)');axs[2].set_ylim(-100,5);axs[2].set_xlabel('Frequency (Hz)')
    for ax in axs:ax.axvline(300,color='gray',ls='--',lw=.7)
    save(fig,'tweeter_stage1_fit.png')
    summary={'tweeter_stage1_300_20000':metrics(sfreq,P,W,300,20000)}

    orig,fs=sf.read(HERE/'data/synthetic_original_windowed.wav');swav,_=sf.read(HERE/'data/synthetic_stage5.wav')
    with np.load(HERE/'data/synthetic_stage5_complex.npz') as z:cf=z['freqs'];CP=z['P']
    frd=np.loadtxt(HERE/'data/synthetic_stage5.frd');ffrd=frd[:,0];FP=10**(frd[:,1]/20)*np.exp(1j*np.deg2rad(frd[:,2]))
    # The FRD's printed frequencies are rounded to 0.01 Hz; evaluate exactly there.
    def at_any(x,freqs):
        result=np.empty(len(freqs),complex);t=np.arange(len(x))/fs
        for start in range(0,len(freqs),128):
            result[start:start+128]=np.exp(-2j*np.pi*freqs[start:start+128,None]*t)@x
        return result
    cw=spectrum_at(orig,fs,cf)
    # Only plot FRD through 1 kHz; band metrics below 200 Hz use these same rows.
    fm=(ffrd>=20)&(ffrd<=1000);ffrd=ffrd[fm];FP=FP[fm];fr=at_any(orig,ffrd)
    f=np.fft.rfftfreq(N,1/fs);A=np.fft.rfft(orig,N);B=np.fft.rfft(swav,N)
    cases=[('Complex NPZ',cf,cw,CP),('FRD',ffrd,fr,FP),('IR WAV',f,A,B)]
    fig,axs=plt.subplots(3,2,figsize=(10,7.2),sharex=True)
    for row,(label,freq,ref,response) in zip(axs,cases):
        m=(freq>=20)&(freq<=1000);mag,phase=delta(ref,response)
        for ax,y,ylabel in [(row[0],mag,'Difference (dB)'),(row[1],phase,'Difference (degrees)')]:
            ax.semilogx(freq[m],y[m],color=ORANGE,lw=.9);ax.set_xlim(20,1000);ax.set_ylabel(ylabel);ax.grid(alpha=.2)
            lf_ticks(ax)
            ax.set_title('Original minus '+label,loc='left',fontsize=10)
        summary['synthetic_'+label]=metrics(freq,ref,response,20,200)
    for ax in axs[-1]:ax.set_xlabel('Frequency (Hz)')
    save(fig,'synthetic_formats.png')
    summary['synthetic_wav_200_20000']=metrics(f,A,B,200,20000)

    # Test-only variant: change exactly the LF taper operation, retaining all other steps.
    src=inspect.getsource(complex_to_ir)
    old='mag_taper[lf_indices] = 0.5 * (1 - np.cos(np.pi * full_freqs[lf_indices] / lf_taper_end))'
    assert src.count(old)==1
    ns={'np':np,'next_fast_len':next_fast_len}
    exec(src.replace(old,'mag_taper[lf_indices] = 1.0'),ns)
    no_lf=ns['complex_to_ir'](CP,cf,target_fs=fs)
    default=complex_to_ir(CP,cf,target_fs=fs)
    np.testing.assert_allclose(default,swav,atol=1e-8,rtol=1e-6)
    sf.write(HERE/'data/synthetic_stage5_no_lf_taper_TEST_ONLY.wav',no_lf,fs,subtype='FLOAT')
    nf=np.fft.rfft(no_lf,N)
    summary['synthetic_no_lf_taper_20_200']=metrics(f,A,nf,20,200)
    fig,axs=plt.subplots(2,1,figsize=(8,4.5),sharex=True)
    for response,c,label in [(B,BLUE,'Default 15 Hz LF taper'),(nf,ORANGE,'LF taper disabled — test only')]:
        mag,phase=delta(A,response);m=(f>=20)&(f<=1000)
        axs[0].semilogx(f[m],mag[m],color=c,label=label);axs[1].semilogx(f[m],phase[m],color=c)
    for ax,label in zip(axs,['Magnitude difference (dB)','Phase difference (degrees)']):
        ax.set_xlim(20,1000);ax.set_ylabel(label);ax.grid(alpha=.2)
        lf_ticks(ax)
    axs[0].legend(fontsize=9);axs[1].set_xlabel('Frequency (Hz)');save(fig,'synthetic_no_lf_taper.png')
    (OUT/'results.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary,indent=2))

if __name__=='__main__':main()
