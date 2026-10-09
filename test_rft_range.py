"""Stage 3 derives RFT limits from project settings and preserves manual ranges."""
import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
import pytest
import process_service
from process_engine.rft_range import default_lower_hz, project_rft_ms, transition_frequency_hz


def test_project_rft_migration_and_boundary():
    assert project_rft_ms({'stage1_vars': {'fdw_rft_ms': '8'}}) == '8'
    assert project_rft_ms({'stage1_vars': {'fdw_rft_ms': '8'},
                           'stage3_vars': {'fdw_rft_ms': '10'}}) == '10'
    assert default_lower_hz(5, 12) == 4000
    assert default_lower_hz(10, 12) == 2000
    assert transition_frequency_hz(10, 12) == transition_frequency_hz(5, 12) / 2
    for rft, resolution in ((0, 12), (5, 0), (float('nan'), 12)):
        with pytest.raises(ValueError): transition_frequency_hz(rft, resolution)


def test_legacy_npz_resolution_and_numeric_settings_comparison():
    from process_engine.stage1_settings import settings_from_npz, settings_differences
    for resolution in (1, 6, 12, 24):
        meta={'measurement': {'rft_ms': 5, 'f_trans': transition_frequency_hz(5,resolution)}}
        assert settings_from_npz({'meta': np.array(meta,dtype=object)})['fdw_oct_res']==resolution
    assert settings_from_npz({})=={}
    assert settings_differences({'fdw_oct_res':12.,'enable_smoothing':True},
                                {'fdw_oct_res':'12','enable_smoothing':True})=={}


def test_optimizer_uses_current_project_rft_over_old_npz_metadata():
    import stage3_optimize_she_settings as stage
    data=dict(freqs=np.array([1000., 2000.]), complex_data={}, filenames=[],
              r_arr=np.array([]), th_arr=np.array([]), ph_arr=np.array([]),
              origins_mm=None, stage3_rft_lower_hz=99999., stage1_settings={'fdw_oct_res': 24})
    class BandReached(Exception): pass
    with patch.object(stage, 'load_and_parse_npz', return_value=data), \
         patch.object(stage, 'get_grid_limit', return_value=(10, 100)), \
         patch.object(stage, 'stage3_test_band', side_effect=BandReached) as band:
        with pytest.raises(BandReached):
            stage.run_open_branch_optimizer('.', 'unused.npz', (2, 4),
                rft_ms=10, project_oct_res=6)
    assert band.call_args.args[2] == transition_frequency_hz(10, 24)


def test_stage3_controls_import_reset_and_manual_persistence(tmp_path):
    from PySide6 import QtCore as C, QtWidgets as W
    from process_workspace import ProcessWorkspace
    app=W.QApplication.instance() or W.QApplication([])
    owner=SimpleNamespace(settings=C.QSettings(str(tmp_path/'ui.ini'), C.QSettings.IniFormat),
        project_path=None, dataset_label=W.QLabel(), worker=None, export_workspace=None, pool=Mock())
    view=ProcessWorkspace(owner)
    try:
        assert (1, 'fdw_rft_ms') not in view.controls
        assert view.values[3]['freq_start_hz'] == '4000.0'
        view.set_value(3, 'freq_start_hz', 1500)
        view.set_value(3, 'fdw_rft_ms', 10)
        assert view.values[3]['freq_start_hz'] == '1500'
        view.rft_reset_button.click()
        assert view.values[3]['freq_start_hz'] == '2000.0'
        view.set_value(1, 'fdw_oct_res', 6)
        assert view.values[3]['freq_start_hz'] == '1000.0'
        project=tmp_path/'project.json'
        project.write_text(json.dumps({'stage1_vars': {'fdw_rft_ms': '8', 'fdw_oct_res': '12'},
                                      'stage3_vars': {'freq_start_hz': '1800'}}))
        owner.project_path=str(project)
        with patch.object(view, 'start_host'):
            view.adopt_project()
        assert view.values[3]['fdw_rft_ms'] == '8'
        assert view.values[3]['freq_start_hz'] == '1800'
        assert view.project_payload()['stage3_vars']['fdw_rft_ms'] == '8'
        # Without an existing NPZ, new project settings remain the fallback.
        view.set_value(1, 'fdw_oct_res', 24)
        view.select_stage(3)
        with patch.object(view, 'start_host'), patch('process_job.ProcessJob'):
            view.run()
        assert view.active_request['project_oct_res'] == '24'
        assert view.active_request['rft_ms'] == '8'
        assert json.loads(project.read_text())['stage1_vars']['fdw_oct_res'] == '12'
        view.job=False
        recorded=dict(view.values[1],fdw_oct_res=6,fdw_rft_ms=8)
        outputs=tmp_path/'outputs';outputs.mkdir()
        np.savez(outputs/'project_complex_data.npz',freqs=np.array([100.,200.]),
                 data=np.array({},dtype=object),meta=np.array({},dtype=object),fs=48000,
                 stage1_settings=np.array(recorded,dtype=object))
        with patch.object(view,'start_host'), patch.object(view,'choose_stage1_settings',return_value=False) as choice:
            view.adopt_project(force=True)
        choice.assert_called_once()
        assert view.values[1]['fdw_oct_res']=='12'
        assert view.stage1_resolution()==6
        view.set_value(1,'fdw_oct_res',24)
        view.set_range_from_rft()
        assert view.values[3]['freq_start_hz']==str(default_lower_hz(8,6))
        view.select_stage(3)
        with patch.object(view,'start_host'),patch('process_job.ProcessJob'):
            view.run()
        assert view.active_request['project_oct_res']==6
        view.job=False
        with patch.object(view,'start_host'),patch.object(view,'choose_stage1_settings',return_value=True):
            view.adopt_project(force=True)
        assert view.values[1]['fdw_oct_res']=='6'
        (outputs/'project_complex_data.npz').unlink()
        project.write_text(json.dumps({'stage1_vars': {'fdw_rft_ms': '10', 'fdw_oct_res': '12'}}))
        with patch.object(view, 'start_host'):
            view.adopt_project(force=True)
        assert view.values[3]['freq_start_hz'] == '2000.0'
    finally:
        view.close()
