"""Reconstruction centres affect all sampled pressures and survive option reuse."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import json
import numpy as np
import h5py
from PySide6 import QtWidgets as W
from hals_studio.analysis.reconstruction_centres import reconstruction_centres
from hals_studio.analysis import acoustics as ac


def coefficients(path):
    with h5py.File(path, 'w') as data:
        data['freqs'] = [1000., 2000.]
        data['coeffs'] = np.array([[1.+0j, 0.], [1.+0j, 0.]])
        data['N_used'] = [0, 0]
        data['origins_mm'] = np.zeros((2, 3))
        data['speed_of_sound_mps'] = 337.
        data['fs'] = 48000.


def test_waypoints_convert_cylindrical_mm_to_cartesian_metres():
    grid=dict(wp_tw_r='200', wp_tw_phi='90', wp_tw_z='900',
        wp_ref_origin_r='', wp_ref_origin_phi='', wp_ref_origin_z='',
        user_positions=[dict(name='Woofer', r=100, phi=180, z=350),
                        dict(name='Port', r='bad', phi=0, z=0)])
    for prefix in ('top', 'bot', 'baffle_bl', 'baffle_tl', 'baffle_tr'):
        grid.update({f'wp_{prefix}_{axis}': value for axis, value in zip(('r', 'phi', 'z'), (100, 0, 200))})
    centres=dict(reconstruction_centres(grid))
    assert set(centres) == {'Scanner Origin (0, 0, 0)', 'Tweeter', 'Woofer'}
    np.testing.assert_allclose(centres['Tweeter'], [0, .2, .9], atol=1e-12)
    np.testing.assert_allclose(centres['Woofer'], [-.1, 0, .35], atol=1e-12)
    assert 'Reference Origin' not in centres and 'Port' not in centres


def test_dialog_selects_available_waypoints_and_restores_centres(tmp_path):
    from hals_studio.ui.app import ReconstructionDialog
    app=W.QApplication.instance() or W.QApplication([])
    parent=W.QWidget();parent.export_workspace=None
    parent.project_path=str(tmp_path/'project.json')
    (tmp_path/'project.json').write_text(json.dumps(dict(grid_vars=dict(
        wp_tw_r=200,wp_tw_phi=0,wp_tw_z=900,
        user_positions=[dict(name='Cabinet centre',r=100,phi=180,z=450)]))))
    path=tmp_path/'speaker.h5';coefficients(path)
    dialog=ReconstructionDialog(path,parent)
    assert dialog.options()['offset'] == [0.,0.,0.]
    dialog.centre.setCurrentText('Tweeter')
    np.testing.assert_allclose(dialog.options()['offset'], [.2,0,.9])
    saved=dialog.options()
    dialog.restore_centre([.01,.02,.03])
    assert dialog.centre.currentText() == 'Scanner Origin (0, 0, 0)'
    assert dialog.options()['offset'] == [0., 0., 0.]
    dialog.restore_centre(saved['offset'],saved['centre_name'])
    assert dialog.centre.currentText() == 'Tweeter'
    dialog.close();parent.close()


def test_offset_reconstruction_matches_exact_physical_points_and_cache(tmp_path):
    from hals_studio.process_engine.extract_pressures_core import evaluate_she_field
    from hals_studio.process_engine.utils import cartesian_to_spherical
    path=tmp_path/'speaker.h5';coefficients(path)
    offset=[.2,0,.5]
    sphere=ac.reconstruct(path,step=15,bins=0,radius=2.,fmin=1000,fmax=2000,
        padding=0,offset=offset,centre_name='Tweeter')
    xyz=ac.directions(sphere.elevation,sphere.azimuth).reshape(-1,3)*2+offset
    r,th,ph=cartesian_to_spherical(*xyz.T)
    direct=evaluate_she_field(np.column_stack((np.degrees(th),np.degrees(ph),r)),path,
        c_sound=337.,corr_ir_pad_phase=False,use_process_pool=False,show_progress=False)['complex']
    np.testing.assert_allclose(sphere.pressure.reshape(2,-1),direct,rtol=1e-12,atol=1e-14)
    original=ac.reconstruct(path,step=15,bins=0,radius=2.,fmin=1000,fmax=2000,padding=0)
    assert not np.allclose(sphere.pressure,original.pressure)
    saved=tmp_path/'sphere.npz';ac.save_sphere(sphere,saved)
    loaded=ac.load_sphere(saved)
    assert loaded.metadata['offset_m'] == offset
    assert loaded.metadata['centre_name'] == 'Tweeter'
    np.testing.assert_array_equal(loaded.pressure,sphere.pressure)
