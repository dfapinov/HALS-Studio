"""Stage 1 fixed smoothing, HF window coverage, and saved RFT metadata."""
import hals_studio.bootstrap as bootstrap
import sys
import io
from pathlib import Path
from contextlib import redirect_stdout
import numpy as np
import soundfile as sf
import hals_studio.application.process_service as process_service  # installs the viewer-owned engine import path
from hals_studio.process_engine.fdw_smoothing_core import apply_complex_smoothing
from hals_studio.process_engine.fdw_smoothing_core import calculate_cycles_from_oct_res, calculate_fdw_durations


def test_fixed_stage1_pipeline():
    import hals_studio.process_engine.stage1_fdwsmooth as stage
    from unittest.mock import patch
    root=bootstrap.HERE/'artifacts'/'stage1-fdw-test'
    inputs=root/'input';outputs=root/'output';inputs.mkdir(parents=True,exist_ok=True)
    ir=np.zeros(4096);ir[96]=1;ir[144]=.4
    sf.write(inputs/'NA_r100_ph0_z0_ir.wav',ir,48000,subtype='FLOAT')
    class BorrowedPool:
        workers=12
        def __enter__(self):return self
        def __exit__(self,*_):pass
        def imap_unordered(self,fn,items,chunksize=1):return map(fn,items)
    log=io.StringIO()
    with patch('hals_studio.process_engine.session_pool.borrow_pool',return_value=BorrowedPool()), redirect_stdout(log):
        f,raw,smoothed,meta=stage.fdwsmooth(str(inputs),str(outputs),'comparison.npz',5,12,50,True,24,
            compare_smoothing=True,workers=24,enable_auto_gain=False)
    assert 'Using 12 processes' in log.getvalue()
    assert 'Complex smoothing: fixed; 1/24 octave' in log.getvalue()
    assert 'Stage 1 peak scan: 1/1 complete' in log.getvalue()
    assert 'Stage 1 FDW / smoothing: 1/1 complete' in log.getvalue()
    name=next(iter(raw));peak=meta[name]['t_peak']
    fixed=apply_complex_smoothing(f,raw[name],24,peak)
    np.testing.assert_array_equal(smoothed[name],fixed)
    assert meta[name]['sliding_hf'] is False
    cycles=calculate_cycles_from_oct_res(12)
    centers=meta[name]['f_centers'];windows=meta[name]['t_windows']
    high=centers>cycles/.005
    np.testing.assert_allclose(windows[high]*centers[high],cycles)
    with np.load(outputs/'comparison.npz',allow_pickle=True) as saved:
        import hals_studio.process_engine.schema as schema
        assert schema.STAGE3_RFT_LOWER_HZ not in saved
        settings=saved[schema.STAGE1_SETTINGS].item()
        assert settings['fdw_oct_res'] == 12
        assert settings['fdw_rft_ms'] == 5
        assert settings['effective_smoothing_oct_res'] == 24
        assert settings['enable_auto_gain'] is False
        assert settings['fdw_max_cap_ms'] == 50
        assert saved[schema.META].item()[name]['rft_ms'] == 5
    for auto in (None, 'Auto', 0):
        with patch('hals_studio.process_engine.session_pool.borrow_pool',return_value=BorrowedPool()), redirect_stdout(log):
            _,_,ordinary,_=stage.fdwsmooth(str(inputs),str(outputs),'fixed.npz',5,12,50,True,auto,
                                          sliding_hf=True,enable_auto_gain=False,save_to_disk=False)
        np.testing.assert_array_equal(ordinary[name],fixed)


def test_fdw_continues_through_hf_with_existing_lf_cap():
    freqs=np.array([20.,100.,1000.,4000.,8000.,16000.,24000.])
    cycles=calculate_cycles_from_oct_res(12)
    for rft in (3.,5.,10.):
        np.testing.assert_allclose(calculate_fdw_durations(freqs,12,rft,200),np.minimum(cycles/freqs,.2))
    np.testing.assert_allclose(calculate_fdw_durations(freqs,12,5,None),cycles/freqs)


def test_hf_tail_uses_shortest_retained_window():
    from hals_studio.process_engine.fdw_smoothing_core import process_single_ir, apply_peak_causal_window
    fs=48000; n=4096
    freqs=np.fft.rfftfreq(n,1/fs)
    ir=np.zeros(n);ir[96]=1;ir[130]=.4;ir[140]=.2
    response,meta=process_single_ir(ir,fs,n,freqs,96/fs,5,12,50,3,.2,1.)
    top=meta['f_centers'][0]
    np.testing.assert_allclose(top,24000/2**(1/3))
    assert top*2**(0.5/3) <= freqs[-1]
    windowed=apply_peak_causal_window(ir,fs,96/fs,meta['t_windows'][0],meta['alpha_sched'][0])
    expected=np.fft.rfft(windowed,n=n)
    taper=freqs>24000*.98
    expected[taper]*=.5*(1+np.cos(np.pi*(freqs[taper]-24000*.98)/(24000*.02)))
    np.testing.assert_allclose(response[freqs>=top],expected[freqs>=top],atol=1e-14)


def test_short_capture_keeps_one_window():
    from hals_studio.process_engine.fdw_smoothing_core import process_single_ir
    ir=np.zeros(32);ir[0]=1
    freqs=np.fft.rfftfreq(len(ir),1/48000)
    response,meta=process_single_ir(ir,48000,len(ir),freqs,0,5,12,50,3,.2,1.)
    assert len(meta['f_centers'])==1
    np.testing.assert_allclose(response[:-1],1)



def test_viewer_schema_exposes_persisted_options():
    from hals_studio.ui.process_workspace import SCHEMA,MAIN
    for key in ('sliding_hf','compare_smoothing'):
        assert key not in SCHEMA['1']
        assert key not in MAIN[1]


def test_cross_sonogram_setup_matches_directivity():
    from hals_studio.ui.panes import setting_keys
    assert set(('directivity_on_axis','contours','directivity_contour_step')) <= set(setting_keys('cross_sonograms'))
