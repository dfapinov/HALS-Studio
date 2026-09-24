"""Viewer-only Stage 1 integration, including saved comparison and pool reporting."""
import bootstrap
import sys
import io
from pathlib import Path
from contextlib import redirect_stdout
import numpy as np
import soundfile as sf
import process_service  # installs the viewer-owned engine import path
from process_engine.fdw_smoothing_core import apply_complex_smoothing
from experimental_smoothing import sliding_resolution, smoothing_matrix, apply_operator


def test_sliding_stage1_pipeline():
    import stage1_fdwsmooth as stage
    from unittest.mock import patch
    root=bootstrap.HERE/'artifacts'/'sliding-stage1-test'
    inputs=root/'input';outputs=root/'output';inputs.mkdir(parents=True,exist_ok=True)
    ir=np.zeros(4096);ir[96]=1;ir[144]=.4
    sf.write(inputs/'NA_r100_ph0_z0_ir.wav',ir,48000,subtype='FLOAT')
    class BorrowedPool:
        workers=12
        def __enter__(self):return self
        def __exit__(self,*_):pass
        def map(self,fn,items):return map(fn,items)
    log=io.StringIO()
    with patch('session_pool.borrow_pool',return_value=BorrowedPool()), redirect_stdout(log):
        f,raw,smoothed,meta=stage.fdwsmooth(str(inputs),str(outputs),'comparison.npz',5,12,50,True,24,
            compare_smoothing=True,workers=24,enable_auto_gain=False)
    assert 'Using 12 processes' in log.getvalue()
    assert 'sliding HF' in log.getvalue()
    name=next(iter(raw));peak=meta[name]['t_peak'];resolution=sliding_resolution(f,5)
    fixed=apply_complex_smoothing(f,raw[name],24,peak)
    np.testing.assert_array_equal(meta[name]['fixed_smoothing'],fixed)
    np.testing.assert_array_equal(smoothed[name][resolution==24],fixed[resolution==24])
    expected=apply_operator(smoothing_matrix(f,resolution),f,raw[name],peak)
    np.testing.assert_allclose(smoothed[name],expected,atol=1e-14,rtol=1e-12)
    assert not np.allclose(smoothed[name],fixed)
    assert (outputs/'comparison_fixed_smoothing.npz').is_file()
    with patch('session_pool.borrow_pool',return_value=BorrowedPool()), redirect_stdout(log):
        _,_,ordinary,_=stage.fdwsmooth(str(inputs),str(outputs),'fixed.npz',5,12,50,True,24,
                                      sliding_hf=False,enable_auto_gain=False,save_to_disk=False)
    np.testing.assert_array_equal(ordinary[name],smoothed[name])


def test_viewer_schema_exposes_persisted_options():
    from process_workspace import SCHEMA,MAIN
    for key in ('sliding_hf','compare_smoothing'):
        assert key not in SCHEMA['1']
        assert key not in MAIN[1]


def test_cross_sonogram_setup_matches_directivity():
    from panes import setting_keys
    assert set(('directivity_on_axis','contours','directivity_contour_step')) <= set(setting_keys('cross_sonograms'))
