"""Read test_exports and create the metrics and three graphics used in the PDF."""
from pathlib import Path
import json
import h5py
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon, Rectangle, Circle, Arc, FancyBboxPatch
from synth_ir_gen_tof_test import generate_piston_points, SOURCE_CENTER_M, PISTON_RADIUS_M, PISTON_POINT_COUNT, PISTON_FACING_AXIS

HERE=Path(__file__).resolve().parent
OUT=HERE/'simple_graphs'
C=343.

def delay(f,p,lo=20,hi=20000):
    m=(f>=lo)&(f<=hi)
    return float(-np.polyfit(f[m],np.unwrap(np.angle(p))[m],1)[0]/(2*np.pi)*1e6)

def main():
    OUT.mkdir(exist_ok=True)
    plt.rcParams.update({'font.size':11,'axes.spines.top':False,'axes.spines.right':False,
                         'axes.grid':True,'grid.alpha':.2})
    blue='#176788'; orange='#b85522'; gray='#313b45'
    curves={}; raw={}
    for mode in ['Off','RefOrigin']:
        for z in [0,500]:
            folder=HERE/'test_exports'/f'{mode}_z{z}'
            a=np.loadtxt(next(folder.glob('*.frd')))
            f=a[:,0]; curves[mode,z]=10**(a[:,1]/20)*np.exp(1j*np.deg2rad(a[:,2]))
            with np.load(next((folder/'complex').glob('*.npz'))) as n:
                rf=n['freqs'].copy(); raw[mode,z]=n['P'].copy()
    expected=(np.hypot(2,.5)-2)/C*1e6
    measured=delay(f,curves['Off',500]/curves['Off',0])
    npz_delay=delay(rf,raw['Off',500]/raw['Off',0])
    source=generate_piston_points(SOURCE_CENTER_M,PISTON_RADIUS_M,PISTON_POINT_COUNT,PISTON_FACING_AXIS)[0]
    actual=(np.linalg.norm(np.array([2,0,.5])-source)-np.linalg.norm(np.array([2,0,0])-source))/C*1e6
    metrics=dict(expected_path_mm=expected*C/1000, measured_path_mm=measured*C/1000,
        expected_delay_us=expected,measured_delay_us=measured,error_us=measured-expected,
        error_ns=(measured-expected)*1000,error_mm=(measured-expected)*C/1000,
        expected_slope_deg_khz=-.36*expected,measured_slope_deg_khz=-.36*measured,
        error_percent=(measured-expected)/expected*100,npz_delay_us=npz_delay,
        npz_frd_difference_ns=(measured-npz_delay)*1000,actual_source_mm=(source*1000).tolist(),
        actual_source_prediction_us=actual,actual_source_error_ns=(measured-actual)*1000)
    absolute_expected=np.hypot(2,.5)/C*1e6
    absolute_measured=delay(f,curves['Off',500])
    metrics['absolute_b']={
        'expected_path_mm':np.hypot(2,.5)*1000,
        'measured_path_mm':absolute_measured*C/1000,
        'expected_delay_us':absolute_expected, 'measured_delay_us':absolute_measured,
        'error_us':absolute_measured-absolute_expected,
        'error_mm':(absolute_measured-absolute_expected)*C/1000,
        'expected_slope_deg_khz':-.36*absolute_expected,
        'measured_slope_deg_khz':-.36*absolute_measured}
    metrics['fit_band_hz']=[20,20000]
    settings=json.loads((HERE/'test_exports/settings.json').read_text())
    with h5py.File(settings['coefficient_file']) as h:
        sf=h['freqs'][()]; pct=h['pct_error'][()]; orders=h['N_used'][()]
        metrics['stage4_origins_max_mm']=float(np.max(np.abs(h['origins_mm'][()])))
        metrics['stage4_order_range']=[int(orders.min()),int(orders.max())]
    sm=(sf>=20)&(sf<=20000)
    metrics['stage4_fit_percent_median']=float(np.median(pct[sm]))
    metrics['stage4_fit_percent_max']=float(np.max(pct[sm]))
    metrics['ref_origin_delays_us']={str(z):delay(f,curves['RefOrigin',z]) for z in [0,500]}
    metrics['broadband_delay_us']=delay(f,curves['Off',500]/curves['Off',0],20,20000)
    def save(fig,name):
        fig.savefig(OUT/f'{name}.png',dpi=230,bbox_inches='tight',facecolor='white')
        plt.close(fig)
    # Speaker and microphone icons are schematic; the path triangle is to scale.
    fig,ax=plt.subplots(figsize=(8,3.2))
    ax.plot([0,2],[0,0],color=blue,lw=2)
    ax.plot([0,2],[0,.5],color=orange,lw=2)
    ax.plot([2,2],[0,.5],ls='--',color=gray)
    ax.plot([1.94,1.94,2],[0,.06,.06],color=gray,lw=.8)
    ax.add_patch(Rectangle((-.17,-.035),.06,.07,color=gray))
    ax.add_patch(Polygon([[-.11,-.035],[-.03,-.09],[-.03,.09],[-.11,.035]],color=gray))
    ax.scatter([0],[0],s=18,c=gray,zorder=5)
    for z,col in [(0,blue),(.5,orange)]:
        ax.scatter([2],[z],s=24,c=col,zorder=5)
        # Flat grille at the left tip; tapered handle/cable extends to the right.
        ax.add_patch(Polygon([[2.015,z-.035],[2.065,z-.035],[2.13,z-.018],
                             [2.13,z+.018],[2.065,z+.035],[2.015,z+.035]],color=col))
        ax.plot([2.015,2.015],[z-.035,z+.035],color='white',lw=1.4)
        ax.plot([2.13,2.24],[z,z],color=col,lw=2)
    ax.text(-.03,-.20,'Omni source\nR = 0, Z = 0',ha='center',va='top')
    ax.text(2,-.20,'Mic A\nR = 2 m, Z = 0',ha='center',va='top',color=blue)
    ax.text(2,.63,'Mic B\nR = 2 m, Z = 0.5 m',ha='center',color=orange)
    ax.text(1,-.09,'2.000000 m',ha='center',color=blue)
    ax.text(.85,.30,'2.061553 m',rotation=14,color=orange)
    ax.text(2.10,.25,'500 mm\nhigher',va='center')
    ax.set(xlim=(-.35,2.6),ylim=(-.4,.85),aspect='equal'); ax.axis('off')
    save(fig,'geometry')
    m=(f>=20)&(f<=20000)
    fig,ax=plt.subplots(figsize=(8,3.3))
    for z,col,label in [(0,blue,'Mic A: no height offset'),(500,orange,'Mic B: 500 mm higher')]:
        ax.plot(f[m]/1000,np.rad2deg(np.unwrap(np.angle(curves['RefOrigin',z])))[m],color=col,lw=2,label=label)
    ax.plot(f[m][::55]/1000,(-.00036*f*expected)[m][::55],ls='none',marker='o',ms=4,mfc='white',mec=gray,label='Geometry prediction for Mic B')
    ax.set(xlabel='Frequency (kHz)',ylabel='Phase (degrees)'); ax.legend(fontsize=9)
    fig.tight_layout(); save(fig,'reference_phase')
    phase=np.rad2deg(np.unwrap(np.angle(curves['Off',500]/curves['Off',0])))
    prediction=-.00036*f*expected
    fig,ax=plt.subplots(figsize=(8,2.9))
    ax.plot(f[m]/1000,(phase-prediction)[m],color=orange,lw=.8)
    ax.axhline(0,color=gray,lw=.7)
    ax.set(xlabel='Frequency (kHz)',ylabel='Phase error\n(degrees)')
    fig.tight_layout(); save(fig,'differential_phase')
    metrics['max_phase_error_deg']=float(np.max(np.abs((phase-prediction)[m])))
    fig,ax=plt.subplots(figsize=(8,2.7))
    ax.semilogx(sf[sm],20*np.log10(np.maximum(pct[sm]/100,1e-12)),color=blue,lw=1.2)
    ax.set(xlabel='Frequency (Hz)',ylabel='Stage 4 fit error (dB)',xlim=(20,20000))
    ax.set_xticks([20,100,1000,10000,20000],['20','100','1,000','10,000','20,000'])
    fig.tight_layout(); save(fig,'stage4_fit_error')
    (HERE/'simple_results.json').write_text(json.dumps(metrics,indent=2))
    print(json.dumps(metrics,indent=2))

if __name__=='__main__':
    main()
