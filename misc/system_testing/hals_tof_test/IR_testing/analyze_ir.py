"""Recreate report plots using only the bundled data. No full measurement set needed."""
from pathlib import Path
import json
import numpy as np
import soundfile as sf
from scipy.signal import czt
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from reproduction.fdw_smoothing_core import apply_peak_causal_window, get_earliest_significant_peak

HERE=Path(__file__).resolve().parent
OUT=HERE/'figures'
BLUE='#176788'; ORANGE='#be592e'

def spectrum_at(x,fs,f):
    # Evaluate the windowed reference at the saved Stage 1 frequency grid.
    df=f[1]-f[0]
    assert np.allclose(np.diff(f),df)
    return czt(x,m=len(f),w=np.exp(-2j*np.pi*df/fs),a=np.exp(2j*np.pi*f[0]/fs))

def style(ax, ylabel):
    ax.set_xscale('log');ax.set_xlim(20,20000);ax.set_ylabel(ylabel)
    ax.set_xticks([20,100,300,1000,3000,10000,20000],['20','100','300','1k','3k','10k','20k'])
    ax.grid(alpha=.2)

def save(fig,name):
    fig.tight_layout();fig.savefig(OUT/name,dpi=200);plt.close(fig)

def main():
    OUT.mkdir(exist_ok=True)
    plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False})
    stats={}; spectra={}
    for kind in ['synthetic','tweeter']:
        a,fs=sf.read(HERE/f'data/{kind}_original.wav');b,fs2=sf.read(HERE/f'data/{kind}_stage5.wav')
        assert fs==fs2 and a.ndim==b.ndim==1
        peak=get_earliest_significant_peak(a,fs,-12)
        original_samples=len(a)
        a=apply_peak_causal_window(a,fs,peak/fs,.2,1.0)
        sf.write(HERE/f'data/{kind}_original_windowed.wav',a,fs,subtype='FLOAT')
        delay_ms=.512 if kind=='synthetic' else .6
        n=2**int(np.ceil(np.log2(max(len(a),len(b),131072))))
        f=np.fft.rfftfreq(n,1/fs);A=np.fft.rfft(a,n);B=np.fft.rfft(b,n)
        m=(f>=20)&(f<=20000); ratio=A/B
        levels=20*np.log10(np.maximum(abs(A),1e-20)); reference=max(levels[(f>=1000)&(f<=10000)])
        ph=np.angle(ratio,deg=True);mag=20*np.log10(np.maximum(abs(ratio),1e-20))
        stats[kind]={'fs':fs,'original_samples':original_samples,'export_samples':len(b),
            'window_ms':200,'window_alpha':1,'window_anchor_sample':int(peak),
            'available_post_peak_ms':(original_samples-peak)/fs*1000,'display_delay_ms':delay_ms,
            'original_peak':int(np.argmax(abs(a))),'export_peak':int(np.argmax(abs(b))), 'bands':{}}
        for lo,hi in [(20,200),(200,20000),(1000,20000)]:
            sel=(f>=lo)&(f<=hi)
            stats[kind]['bands'][f'{lo}-{hi}']={'max_abs_phase_deg':float(max(abs(ph[sel]))),
                  'max_abs_level_db':float(max(abs(mag[sel]))), 'rms_phase_deg':float(np.sqrt(np.mean(ph[sel]**2)))}
        spectra[kind]=(a,b,fs,f,A,B)
        fig,ax=plt.subplots(figsize=(8,2.5))
        ax.plot(np.arange(min(100,len(a)))*1000/fs,a[:100],color=BLUE,label='Original IR, 200 ms window')
        ax.plot(np.arange(min(100,len(b)))*1000/fs,b[:100],color=ORANGE,ls='--',label='Stage 5 exported WAV')
        ax.set(xlabel='Time from sample zero (ms)',ylabel='WAV amplitude',xlim=(0,1.8));ax.grid(alpha=.2);ax.legend(fontsize=9)
        save(fig,f'{kind}_timing.png')
        fig,axs=plt.subplots(2,1,figsize=(8,4.2),sharex=True)
        axs[0].plot(f[m],levels[m]-reference,color=BLUE,label='Original')
        axs[0].plot(f[m],20*np.log10(np.maximum(abs(B[m]),1e-20))-reference,color=ORANGE,lw=.8,label='Stage 5 WAV')
        style(axs[0],'Magnitude (dB)');axs[0].legend(fontsize=9)
        axs[0].set_ylim(-30 if kind=='synthetic' else -100,5)
        axs[0].set_title('Magnitude overlaid',loc='left',fontsize=10)
        for v,c,l in [(A,BLUE,'Original'),(B,ORANGE,'Stage 5 WAV')]:
            axs[1].plot(f[m],np.angle(v[m]*np.exp(2j*np.pi*f[m]*delay_ms/1000),deg=True),color=c,lw=.8,label=l)
        style(axs[1],'Phase (degrees)');axs[1].set_ylim(-180,180);axs[1].set_xlabel('Frequency (Hz)')
        if kind=='synthetic':
            axs[1].set_ylim(-45,45)
            axs[1].set_yticks([-45,-30,-15,0,15,30,45])
        axs[1].set_title(f'Phase overlay — {delay_ms:g} ms compensation on both traces',loc='left',fontsize=10)
        save(fig,f'{kind}_response.png')
        fig,axs=plt.subplots(2,1,figsize=(8,4.5),sharex=True)
        for ax,values,label in [(axs[0],mag,'Level difference (dB)'),(axs[1],ph,'Phase difference (degrees)')]:
            ax.plot(f[m],values[m],color=ORANGE,lw=.8)
            style(ax,label);ax.axhline(0,color='gray',ls=':',lw=.6)
        axs[0].set_title('Windowed original minus Stage 5 WAV',loc='left',fontsize=10)
        axs[1].set_xlabel('Frequency (Hz)');save(fig,f'{kind}_differences.png')
        for field,ylabel,filename in [(mag,'Level difference (dB)','magnitude_difference'),(ph,'Phase difference (degrees)','phase_difference')]:
            fig,ax=plt.subplots(figsize=(8,2.5));ax.plot(f[m],field[m],color=ORANGE,lw=.8)
            style(ax,ylabel);ax.set_xlabel('Frequency (Hz)');save(fig,f'{kind}_{filename}.png')
        np.savez_compressed(HERE/f'data/{kind}_comparison.npz',freqs=f[m],level_difference_db=mag[m],phase_difference_deg=ph[m])

    a,b,fs,f,A,B=spectra['tweeter']
    with np.load(HERE/'data/tweeter_stage1.npz') as z: sfreq=z['freqs'];P=z['response']
    R=spectrum_at(a,fs,sfreq);W=spectrum_at(b,fs,sfreq)
    s=(sfreq>=20)&(sfreq<=20000)
    # Both curves use exactly the same frequency samples, avoiding misleading density differences.
    fig,axs=plt.subplots(2,1,figsize=(8,4.3),sharex=True)
    for ax,v,title,c in [(axs[0],P/R,'Stage 1 minus original with 200 ms window',BLUE),
                        (axs[1],W/R,'Stage 5 WAV minus original with 200 ms window',ORANGE)]:
        ax.plot(sfreq[s],np.angle(v[s],deg=True),color=c,lw=.8)
        style(ax,'Difference (degrees)');ax.set_ylim(-180,180);ax.set_title(title,loc='left',fontsize=10)
    axs[1].set_xlabel('Frequency (Hz)');save(fig,'phase_differences.png')
    with np.load(HERE/'data/tweeter_fit.npz') as z: fitf=z['freqs'];fitdb=20*np.log10(np.maximum(z['pct_error']/100,1e-15))
    fig,axs=plt.subplots(3,1,figsize=(8,6.1),sharex=True)
    axs[0].plot(sfreq[s],np.angle((W/P)[s],deg=True),color=ORANGE,lw=.8)
    style(axs[0],'Phase difference (°)');axs[0].set_ylim(-180,180);axs[0].set_title('Stage 5 WAV minus Stage 1',loc='left',fontsize=10)
    axs[1].plot(fitf,fitdb,color=BLUE);axs[1].axhline(-20,color='gray',ls=':',lw=1)
    style(axs[1],'Solve fit error (dB)');axs[1].set_ylim(-65,5)
    ref=max(abs(A[(f>=1000)&(f<=10000)]))
    axs[2].plot(f,20*np.log10(np.maximum(abs(A)/ref,1e-15)),color=BLUE,lw=.6)
    style(axs[2],'Original level (dB)');axs[2].set_ylim(-100,5);axs[2].set_xlabel('Frequency (Hz)')
    for ax in axs: ax.axvline(300,color='gray',ls='--',lw=.8)
    save(fig,'error_sources.png')
    stats['fit_db_near_hz']={str(hz):float(fitdb[np.argmin(abs(fitf-hz))]) for hz in [100,200,300,500,1000]}
    np.savez_compressed(HERE/'data/tweeter_processing_comparison.npz',freqs=sfreq[s],
        stage1_minus_original_deg=np.angle((P/R)[s],deg=True),stage5_minus_original_deg=np.angle((W/R)[s],deg=True),
        stage5_minus_stage1_deg=np.angle((W/P)[s],deg=True))
    (HERE/'results.json').write_text(json.dumps(stats,indent=2))
    print(json.dumps(stats,indent=2))

if __name__=='__main__':main()
