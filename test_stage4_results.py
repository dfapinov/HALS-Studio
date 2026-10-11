"""Spatial diagnostics are reconstructed from saved NPZ/H5, without a cache."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import bootstrap
import uuid
import time
import threading
from concurrent.futures import ProcessPoolExecutor
import multiprocessing
from types import SimpleNamespace
from unittest.mock import patch
import h5py
import numpy as np
import pytest
from PySide6 import QtCore as C, QtWidgets as W
import process_cache
from process_workspace import ProcessWorkspace
from process_engine.extract_pressures_core import evaluate_she_field


def saved_solve():
    root = bootstrap.HERE/'artifacts'/('stage4-results-'+uuid.uuid4().hex)
    out = root/'outputs'
    (out/'coefficients').mkdir(parents=True)
    freqs = np.array([100., 1000.])
    she = dict(freqs=freqs, coeffs=np.array([[1+1j, .2+.1j], [2+1j, .3+.1j]]),
               N_used=np.array([0, 0]), origins_mm=np.array([[100., 20., 0.], [80., 0., 10.]]))
    coords = np.array([[90., 0., 1.], [90., 120., 1.], [90., 240., 1.]])
    reconstructed = evaluate_she_field(coords, she, obs_mode='Full', c_sound=315.,
                                       corr_ir_pad_phase=False, use_process_pool=False,
                                       show_progress=False)['complex']
    # NPZ has DC and an extra bin; insertion order differs from natural sorting.
    data = {}
    for i in (2, 0, 1):
        data[f'point{i}_r1000_ph{i*120}_z0.wav'] = np.r_[0j, reconstructed[0,i]*1.1, 0j, reconstructed[1,i]*1.1]
    npz = out/'speaker_complex_data.npz'
    np.savez(npz, freqs=np.array([0., 100., 500., 1000.]), data=data, speed_of_sound_mps=343.)
    coeff = out/'coefficients'/'speaker_coefficients.h5'
    with h5py.File(coeff, 'w') as source:
        for key, value in she.items():source[key] = value
        source['speed_of_sound_mps'] = 315.
        source['cond'] = np.array([2., 3.])
        source['pct_error'] = np.array([10., 10.])
    return root, npz, coeff, reconstructed


@pytest.mark.parametrize('cached', [False, True])
def test_reopened_stage4_spatial_view_without_solving(cached):
    root, npz, coeff, expected = saved_solve()
    app = W.QApplication.instance() or W.QApplication([])
    executor = ProcessPoolExecutor(max_workers=2, mp_context=multiprocessing.get_context('spawn'))
    ready = threading.Event();ready.set()
    pool = SimpleNamespace(workers=2, state='ready', executor=executor,
                           start=lambda:None, _ready=ready)
    owner = SimpleNamespace(project_path=str(root/'project.json'), pool=pool,
                            settings=C.QSettings(str(root/'settings.ini'), C.QSettings.IniFormat))
    pane = ProcessWorkspace(owner)
    def await_spatial():
        deadline=time.monotonic()+10
        while 'spatial_data' not in pane.results[4] and time.monotonic()<deadline:
            app.processEvents();time.sleep(.01)
        assert 'spatial_data' in pane.results[4], pane.results[4].get('spatial_error')
        app.processEvents()
    try:
        pane.project_name.setText('speaker')
        if cached:process_cache.save(pane.cache(4), 4, process_cache.load_stage4_summary(coeff))
        with patch('process_cache.hydrate_stage4', wraps=process_cache.hydrate_stage4) as hydrate, \
             patch('process_engine.spatial_error_viewer.evaluate_she_field', wraps=evaluate_she_field) as bulk:
            pane.select_stage(4)
            pane.load_existing()
            pane.view.setCurrentText('Sound Power vs Harmonic Degree')
            assert pane.last_plot_error is None
            assert pane.original_results.fig.axes[0].lines[0].get_label() == 'Total sound power'
            assert [pane.power_field.itemText(i) for i in range(pane.power_field.count())] == ['Internal field','External field']
            internal = pane.original_results.fig.axes[0].lines[0].get_ydata().copy()
            pane.power_field.setCurrentText('External field')
            assert pane.last_plot_error is None
            assert not np.allclose(pane.original_results.fig.axes[0].lines[0].get_ydata(), internal)
            assert 'external_field' in pane.image_path().name
            canvas = pane.original_results.canvas;canvas.draw()
            interaction = pane.original_results.interaction;ax = interaction.main_ax
            full_x, full_y = ax.get_xlim(), ax.get_ylim()
            from matplotlib.backend_bases import MouseEvent
            x, y = ax.transAxes.transform((.5,.5))
            canvas.callbacks.process('scroll_event', MouseEvent('scroll_event',canvas,x,y,button='up',step=2))
            assert ax.get_xlim()[1]/ax.get_xlim()[0] < full_x[1]/full_x[0]
            zoom_y = ax.get_ylim()
            canvas.callbacks.process('button_press_event', MouseEvent('button_press_event',canvas,x,y,button=2))
            canvas.callbacks.process('motion_notify_event', MouseEvent('motion_notify_event',canvas,x+20,y+20,button=2))
            canvas.callbacks.process('button_release_event', MouseEvent('button_release_event',canvas,x+20,y+20,button=2))
            assert not np.allclose(ax.get_ylim(),zoom_y)
            pane.stack.setCurrentWidget(pane.original_results);pane.reset()
            np.testing.assert_allclose(ax.get_xlim(),full_x)
            np.testing.assert_allclose(ax.get_ylim(),full_y)
            assert pane.view.model().item(pane.view.findText('Spatial error')).isEnabled()
            hydrate.assert_not_called()
            pane.view.setCurrentText('Spatial error')
            await_spatial()
            assert pane.last_plot_error is None
            hydrate.assert_called_once()
            spatial = pane.spatial_results()
            bulk.assert_called_once()
            assert bulk.call_args.kwargs['obs_mode'] == 'Full'
            assert bulk.call_args.kwargs['process_pool'].workers == 2
            assert len(bulk.call_args.kwargs['she_input']['freqs']) == 2
            assert len(bulk.call_args.kwargs['coords_sph']) == 3
            assert spatial['speed_of_sound_mps'] == 315.
            np.testing.assert_allclose(spatial['P_measured'], expected*1.1)
            for i in range(2):
                np.testing.assert_allclose(process_cache.spatial_reconstruction(spatial, i), expected[i])
            with patch('process_engine.spatial_error_viewer.evaluate_she_field') as evaluate:
                pane.original_results.spatial_sliders[1].set_val(-45.)
                evaluate.assert_not_called()
            pane.select_stage(3)
            pane.select_stage(4)
            pane.view.setCurrentText('Spatial error')
            assert pane.last_plot_error is None
            hydrate.assert_called_once()
        # A fresh solve completion discards prior reconstructed diagnostics.
        process_cache.save(pane.cache(4), 4, process_cache.load_stage4_summary(coeff))
        with patch.object(pane, 'autosave_plots'), patch.object(pane, 'reload_coefficients'):
            pane.finished(dict(ok=True, stage=4, cache=str(pane.cache(4))))
        assert 'spatial_data' not in pane.results[4]
        pane.view.setCurrentText('Spatial error')
        await_spatial()
        assert pane.last_plot_error is None
        for missing in (npz, coeff):
            hidden = missing.with_suffix('.hidden')
            missing.rename(hidden)
            pane.update_selectors()
            assert not pane.view.model().item(pane.view.findText('Spatial error')).isEnabled()
            hidden.rename(missing)
            pane.update_selectors()
            assert pane.view.model().item(pane.view.findText('Spatial error')).isEnabled()
    finally:
        for job in list(getattr(pane,'_spatial_jobs',[])):job.wait()
        app.processEvents()
        pane.close()
        executor.shutdown()


def test_mismatched_npz_frequencies_are_rejected():
    _, npz, coeff, _ = saved_solve()
    with np.load(npz, allow_pickle=True) as source:data = source['data'].item()
    np.savez(npz, freqs=np.array([0., 101., 500., 1000.]), data=data)
    with pytest.raises(ValueError, match='different frequency bins'):
        process_cache.hydrate_stage4(npz, coeff)


def test_saved_files_keep_original_96th_octave_bin_selection():
    _, npz, coeff, _ = saved_solve()
    freqs = np.arange(10., 20001., 10.)
    measured = freqs.astype(complex) * (1+1j)
    np.savez(npz, freqs=freqs, data={'point0_r1000_ph0_z0.wav': measured})
    with h5py.File(coeff, 'w') as source:
        source['freqs'] = freqs
        source['coeffs'] = np.column_stack((freqs, freqs*.1)).astype(complex)
        source['N_used'] = np.zeros(len(freqs), int)
        source['origins_mm'] = np.zeros((len(freqs), 3))
    targets = 20. * 2.**(np.arange(957)/96.)
    targets = targets[targets <= freqs[-1]]
    indices = np.unique([np.argmin(abs(freqs-target)) for target in targets])
    pool = object()
    def reconstruct(**kwargs):
        return {'complex': kwargs['she_input']['freqs'][:, None].astype(complex)}
    with patch('process_engine.spatial_error_viewer.evaluate_she_field', side_effect=reconstruct) as bulk:
        result = process_cache.hydrate_stage4(npz, coeff, process_pool=pool)
    bulk.assert_called_once()
    assert bulk.call_args.kwargs['process_pool'] is pool
    assert len(indices) < len(freqs)
    np.testing.assert_array_equal(result['freqs'], freqs[indices])
    np.testing.assert_array_equal(result['P_measured'][:, 0], measured[indices])
    np.testing.assert_array_equal(result['P_reconstructed'][:, 0], freqs[indices])


def test_spatial_drag_locks_roll_without_changing_other_views():
    import matplotlib as mpl
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from process_results import VIEWS
    view = VIEWS['SpatialErrorView']()
    canvas = FigureCanvasAgg(view.fig)
    canvas.draw()
    ax = view.ax
    ax.button_pressed = 1
    ax._sx, ax._sy = 0., 0.
    before = ax.elev, ax.azim
    with mpl.rc_context({'axes3d.mouserotationstyle': 'arcball'}):
        for x, y in ((.02, .01), (.04, -.03), (-.01, .02)):
            ax._on_move(SimpleNamespace(xdata=x, ydata=y, inaxes=ax))
            assert ax.roll == 0
            assert mpl.rcParams['axes3d.mouserotationstyle'] == 'arcball'
    assert (ax.elev, ax.azim) != before


def test_spatial_reconstruction_emits_frequency_progress():
    from concurrent.futures import ThreadPoolExecutor
    from session_pool import PoolView
    _, npz, coeff, expected = saved_solve()
    events = []
    with ThreadPoolExecutor(max_workers=2) as executor:
        pool = PoolView(SimpleNamespace(workers=2, executor=lambda: executor))
        result = process_cache.hydrate_stage4(npz, coeff, process_pool=pool, progress=events.append)
    assert events[0]['completed'] == 0
    assert events[-1]['completed'] == events[-1]['total'] == 2
    assert events[-1]['eta'] == 0
    assert all(e['label'] == 'Spatial error reconstruction' for e in events)
    np.testing.assert_allclose(result['P_reconstructed'], expected)
