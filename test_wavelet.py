"""Numerical checks for the viewer's Morlet transform."""
import bootstrap
import numpy as np
from csd_plot import DEFAULTS, wavelet_map


def config(**changes):
    return {**DEFAULTS, 'csd_method': 'Morlet wavelet', 'wavelet_units':'Milliseconds', 'wavelet_cycles':6., 'csd_auto_time': False,
            'csd_fmin': 500., 'csd_fmax': 2000., 'csd_time': 8., 'csd_pre_time': 4., **changes}


def test_impulse_matches_gaussian_envelope():
    fs = 48000
    ir = np.zeros(4800); ir[1000] = 1
    f, t, db = wavelet_map(ir, fs, config())
    for j in [0, 80, 191]:
        sigma_ms = 6/(2*np.pi*f[j])*1000
        expected = -10/np.log(10)*(t/sigma_ms)**2
        relative = db[:,j]-np.interp(0,t,db[:,j])
        mask = abs(t) < 2*sigma_ms
        np.testing.assert_allclose(relative[mask],expected[mask],atol=.12)


def test_peak_reference_is_shift_invariant():
    ir = np.zeros(4800); ir[1000] = 1; ir[950] = .3; ir[1200] = .2
    shifted = np.zeros(6000); shifted[500:5300] = ir
    a = wavelet_map(ir,48000,config())[2]
    b = wavelet_map(shifted,48000,config())[2]
    np.testing.assert_allclose(a[a>-100],b[a>-100],atol=1e-7)


def test_cycle_axis_resamples_each_frequency():
    ir = np.zeros(4800); ir[1000] = 1
    f, cycles, db = wavelet_map(ir,48000,config(wavelet_units='Cycles',wavelet_pre=2.,wavelet_duration=4.))
    # The impulse's width in cycles is independent of frequency.
    relative = db-np.array([np.interp(0,cycles,row) for row in db.T])
    mask = abs(cycles)<1.5
    np.testing.assert_allclose(relative[mask,0],relative[mask,-1],atol=.12)
    assert cycles[0]==-2 and cycles[-1]==4


def test_negative_display_limit_does_not_gate_input():
    ir = np.zeros(4800); ir[1000] = 1; ir[960] = .7
    f,t,a = wavelet_map(ir,48000,config(csd_pre_time=0.))
    _,u,b = wavelet_map(ir,48000,config(csd_pre_time=4.))
    # Compare zero-time values: the earlier arrival is retained in both cases.
    np.testing.assert_allclose(a[0], [np.interp(0,u,row) for row in b.T],atol=.12)


def test_flat_spectrum_has_flat_wavelet_peak_across_frequency():
    ir = np.zeros(4800); ir[1000] = 1
    f,t,db = wavelet_map(ir,48000,config(csd_fmin=100.,csd_fmax=16000.,csd_pre_time=0.,csd_time=2.))
    np.testing.assert_allclose(db[0],0.,atol=1e-8)


def test_per_frequency_peak_alignment_and_level():
    ir = np.zeros(4800); ir[1000] = 1; ir[1300] = .8
    for units in ['Milliseconds', 'Cycles']:
        f,t,db = wavelet_map(ir,48000,config(wavelet_units=units,
            wavelet_time_reference='Each frequency peak',wavelet_level_reference='Each frequency peak'))
        np.testing.assert_allclose(db[t==0],0.,atol=1e-9)
        assert db.max()<1e-9


def test_csd_zero_slice_normalization():
    from csd_plot import decay_map
    ir = np.zeros(4800); ir[1000] = 1; ir[1100] = .6
    f,t,db = decay_map(ir,48000,config(csd_level_reference='IR peak slice per frequency'))
    np.testing.assert_allclose(db[t==0],0.,atol=1e-9)


def test_csd_cycles_and_normalization():
    from csd_plot import decay_map
    ir=np.zeros(4800); ir[1000]=1.; ir[1100]=.3
    f,t,db=decay_map(ir,48000,config(wavelet_units='Cycles',wavelet_pre=2.,wavelet_duration=12.,csd_level_reference=True))
    assert t[0]==-2 and t[-1]==12
    np.testing.assert_allclose(db[t==0],0.,atol=1e-9)


def test_boolean_wavelet_normalization():
    ir=np.zeros(4800); ir[1000]=1.; ir[1100]=.3
    f,t,db=wavelet_map(ir,48000,config(wavelet_time_reference=True,wavelet_level_reference=True))
    np.testing.assert_allclose(db[t==0],0.,atol=1e-9)
