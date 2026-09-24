import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import bootstrap
import numpy as np
import pytest
from experimental_smoothing import sliding_resolution, smoothing_matrix, apply_operator
from process_engine.fdw_smoothing_core import apply_complex_smoothing, calculate_cycles_from_oct_res


def test_matches_existing_complex_smoothing():
    f=np.linspace(0,24000,2001);rng=np.random.default_rng(5)
    h=rng.normal(size=len(f))+1j*rng.normal(size=len(f));peak=.007
    for resolution in (12,24):
        actual=apply_operator(smoothing_matrix(f,resolution),f,h,peak)
        expected=apply_complex_smoothing(f,h,resolution,peak)
        np.testing.assert_allclose(actual,expected,atol=1e-14,rtol=1e-13)


@pytest.mark.parametrize('rft',[5.,8.])
@pytest.mark.parametrize('onset',[0.,.25])
def test_schedule_boundaries(rft,onset):
    fc=calculate_cycles_from_oct_res(12)/(rft/1000)
    f=np.r_[0.,np.geomspace(fc/10,fc*1e7,1000),fc]
    order=np.argsort(f);f=f[order]
    r=sliding_resolution(f,rft,onset_octaves=onset)
    assert np.all(r[f<=fc]==24)
    assert np.all(np.diff(r)<=1e-10)
    assert r.min()>=12-1e-12
    assert abs(r[-1]-12)<1e-10
    assert abs(sliding_resolution(np.array([fc*(1+1e-10)]),rft,onset_octaves=onset)[0]-24)<1e-7


def test_unchanged_low_band_and_delay_covariance():
    f=np.linspace(0,24000,3001);rng=np.random.default_rng(7)
    h=rng.normal(size=len(f))+1j*rng.normal(size=len(f));peak=.004
    r=sliding_resolution(f,5);op=smoothing_matrix(f,r)
    actual=apply_operator(op,f,h,peak)
    baseline=apply_operator(smoothing_matrix(f,24),f,h,peak)
    np.testing.assert_array_equal(actual[r==24],baseline[r==24])
    delay=.00137;shift=np.exp(-2j*np.pi*f*delay)
    shifted=apply_operator(op,f,h*shift,peak+delay)
    np.testing.assert_allclose(shifted,actual*shift,atol=2e-13,rtol=2e-12)
    impulse=np.exp(-2j*np.pi*f*peak)
    np.testing.assert_allclose(apply_operator(op,f,impulse,peak),impulse,atol=2e-14)


def test_eased_schedule_has_zero_right_derivative_at_onset():
    fc=calculate_cycles_from_oct_res(12)/.005
    widths=[]
    for eps in (1e-3,1e-4):
        r=sliding_resolution(np.array([fc,fc*(1+eps)]),5,onset_octaves=.25)
        widths.append(abs(np.diff(r)[0]/(fc*eps)))
    assert widths[1]<widths[0]/50


def test_bad_settings_rejected():
    with pytest.raises(ValueError):sliding_resolution(np.arange(10.),0)
    with pytest.raises(ValueError):smoothing_matrix(np.array([0,1,3]),24)
    with pytest.raises(ValueError):smoothing_matrix(np.arange(10.),0)
