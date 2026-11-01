"""Recovery, exact IR export, and automatic HF seed regression tests."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import json
import numpy as np
import pytest
import soundfile as sf
from hals_studio.application.ir_recovery import scan_ir_folder, metadata_availability
from hals_studio.application.stage1_export import export_ir


def test_scan_filters_filenames_and_rejects_mixed_rates_and_duplicate_positions(tmp_path):
    name = 'mic_r100_ph0_z0.wav'
    sf.write(tmp_path / name, np.zeros(128), 48000)
    sf.write(tmp_path / 'unrelated.wav', np.zeros(128), 44100)
    assert scan_ir_folder(tmp_path) == ([name], ['unrelated.wav'])
    other = tmp_path / 'mic_r100_ph90_z0.WAV'
    sf.write(other, np.zeros(128), 44100)
    with pytest.raises(ValueError, match='same sample rate'):
        scan_ir_folder(tmp_path)
    other.unlink()
    sf.write(tmp_path / 'duplicate_r100_ph360_z0.wav', np.zeros(128), 48000)
    with pytest.raises(ValueError, match='Duplicate'):
        scan_ir_folder(tmp_path)


@pytest.mark.parametrize('length', [1001, 1024])
def test_stage1_export_preserves_samples_levels_and_fft_length(tmp_path, length):
    original = np.zeros(length)
    original[49] = 2.5
    original[-1] = -.3
    path = tmp_path / 'export.wav'
    export_ir(path, np.fft.rfftfreq(length, 1/48000), np.fft.rfft(original), 48000)
    actual, fs = sf.read(path)
    assert fs == 48000
    assert sf.info(path).subtype == 'FLOAT'
    np.testing.assert_allclose(actual, original, atol=1e-7)


def test_fallback_provenance_survives_saved_numeric_defaults():
    project = dict(stage2_vars=dict(tweeter_x=0, tweeter_y=0, tweeter_z=0),
                   stage3_vars=dict(fdw_rft_ms=5),
                   measurement_metadata=dict(tweeter_supplied=False, rft_supplied=False))
    assert metadata_availability(project) == (False, False)
    project.pop('measurement_metadata')
    assert metadata_availability(project) == (True, True)


def test_missing_rft_keeps_taper_but_has_no_reflection_free_highlight(tmp_path):
    from hals_studio.process_engine.stage1_fdwsmooth import fdwsmooth
    from hals_studio.process_engine.plot_views import FDWView
    name = 'mic_r100_ph0_z0.wav'
    original = np.zeros(2048); original[49] = 1
    sf.write(tmp_path/name, original, 48000, subtype='FLOAT')
    result = fdwsmooth(str(tmp_path), str(tmp_path), 'data.npz', 5, 6, 20, False, 12,
                       use_process_pool=False, enable_auto_gain=False, rft_supplied=False,
                       input_filenames=[name])
    f, raw, smooth, meta = result
    assert not meta[name]['rft_supplied']
    assert meta[name]['rft_ms'] == 5
    view = FDWView()
    view.update_view(name, 0, f, raw[name], None, meta[name], original, 48000, 5)
    assert not view.ax1.patches
    assert not any(t.get_text() == 'Reflection free range' for t in view.ax1.texts)
    with np.load(tmp_path/'data.npz', allow_pickle=True) as data:
        assert not data['stage1_settings'].item()['rft_supplied']


def test_hf_seed_scans_cylinder_at_capped_bin_and_refines(monkeypatch):
    from hals_studio.process_engine import stage2_centre_origin as stage
    from hals_studio.process_engine.runtime import EngineRuntime
    seen = []
    def scan(context, runtime, *, cylindrical=False):
        assert cylindrical
        seen.append(context)
        return np.array([0, 20]), np.array([0]), np.array([0]), np.array([[[3]], [[1]]])
    monkeypatch.setattr(stage, 'generate_3d_landscape_volumetric', scan)
    monkeypatch.setattr(stage, 'run_simplex_descent_3d', lambda seed, context, runtime: (np.asarray(seed)+1, []))
    monkeypatch.setattr(stage, 'solve_physics_3d', lambda x,y,z,context: -x)
    cfg = dict(speed_of_sound=343, manual_order_table={}, target_n_max_origins=4, N_grid=4)
    f = np.array([0., 10000, 19000, 21000, 24000])
    result = stage.estimate_hf_seed(f, {'a': np.ones(5)}, ['a'],
        (np.array([.1, .2]), np.array([np.pi/2, np.pi/2]), np.zeros(2)),
        cfg, 24000, EngineRuntime(output=lambda text: None))
    assert seen[0][0][0][0] == 19000
    assert seen[0][-1]['grid_res_mm'] == 20
    assert seen[0][-1]['scan_radius_mm'] == 200
    np.testing.assert_array_equal(result, [21, 1, 1])
    assert cfg['estimated_tweeter_mm'] == [21, 1, 1]


def test_wav_open_stage1_save_and_estimated_tweeter_roundtrip(tmp_path, monkeypatch):
    from PySide6 import QtCore as C, QtWidgets as W
    from hals_studio.ui.workspace import Workspace
    from hals_studio.ui.process_workspace import ProcessWorkspace
    from hals_studio.ui.project_ui import open_data_path
    from hals_studio.process_engine.stage1_fdwsmooth import fdwsmooth
    app = W.QApplication.instance() or W.QApplication([])
    monkeypatch.setattr(ProcessWorkspace, 'start_host', lambda self: None)
    monkeypatch.setattr(ProcessWorkspace, 'autosave_plots', lambda self: None)
    monkeypatch.setattr(W.QMessageBox, 'information', lambda *args: None)
    window = Workspace(start_pool=False, settings=C.QSettings(str(tmp_path/'prefs.ini'), C.QSettings.IniFormat))
    folder = tmp_path/'measurements'; folder.mkdir()
    name = 'mic_r100_ph0_z0.wav'
    signal = np.zeros(1024); signal[49] = 1
    sf.write(folder/name, signal, 48000, subtype='FLOAT')
    try:
        existing = tmp_path/'capture_project.json'
        existing.write_text('{"project_name": "capture"}')
        open_data_path(window, folder/name)
        assert existing.read_text() == '{"project_name": "capture"}'
        pane = window.process_workspace
        path = tmp_path/'direct_wav_import_project.json'
        assert window.project_path == str(path)
        assert not path.exists()
        assert not pane.rft_supplied and not pane.tweeter_supplied
        outputs = tmp_path/'outputs'
        npz = outputs/'direct_wav_import_complex_data.npz'
        fdwsmooth(str(folder), str(outputs), npz.name, 5, 6, 20, False, 12,
                  use_process_pool=False, rft_supplied=False)
        pane.finished(dict(ok=True, stage=1, cache=str(npz)))
        assert path.exists()
        payload = json.loads(path.read_text())
        assert payload['input_ir_folder'] == 'measurements'
        assert metadata_availability(payload) == (False, False)
        assert not payload['grid_vars']
        selected_export = tmp_path/'selected.wav'
        monkeypatch.setattr(W.QFileDialog, 'getSaveFileName', lambda *args: (str(selected_export), 'WAV (*.wav)'))
        pane.export_stage1_ir()
        exported, fs = sf.read(selected_export)
        np.testing.assert_allclose(np.fft.rfft(exported), pane.results[1][1][name], atol=1e-6)
        batch = tmp_path/'batch';batch.mkdir()
        monkeypatch.setattr(W.QFileDialog, 'getExistingDirectory', lambda *args: str(batch))
        pane.export_stage1_ir(True)
        assert len(list(batch.glob('*.wav'))) == 1
        pane.results[2] = (None, None, None, None, None, {'estimated_tweeter_mm': [30., 40., 80.]})
        pane.save_estimated_tweeter()
        payload = json.loads(path.read_text())
        assert payload['grid_vars']['wp_tw_r'] == 50
        assert payload['grid_vars']['wp_tw_z'] == 80
        assert metadata_availability(payload) == (True, False)
        assert 'automatic' in payload['grid_vars']['tweeter_coordinate_source']
        monkeypatch.setattr(pane, 'choose_stage1_settings', lambda differences: False)
        pane.adopt_project(force=True)
        assert pane.tweeter_supplied and not pane.rft_supplied
        assert pane.ir_folder.text() == str(folder)
        window.save_project()
        assert set(tmp_path.glob('*_project.json')) == {existing, path}
        saved_project = path.read_bytes()
        open_data_path(window, folder/name)
        assert not pane.tweeter_supplied and not pane.rft_supplied
        assert window.project_path == str(tmp_path/'direct_wav_import_2_project.json')
        assert pane.project_name.text() == 'direct_wav_import_2'
        assert path.read_bytes() == saved_project
        assert not (tmp_path/'direct_wav_import_2_project.json').exists()
    finally:
        window.close()
        for _ in range(10):app.processEvents()


def test_padding_49_matches_reference_capture_origin():
    from hals_studio.process_engine.stage5_pressure_utils import apply_ir_padding_phase
    samples = np.zeros(1024);samples[49] = 1
    f = np.fft.rfftfreq(len(samples), 1/48000)
    spectrum = np.fft.rfft(samples)
    corrected = np.fft.irfft(apply_ir_padding_phase(spectrum, f, 49, 48000))
    overcorrected = np.fft.irfft(apply_ir_padding_phase(spectrum, f, 50, 48000))
    assert np.argmax(corrected) == 0
    assert np.argmax(overcorrected) == len(samples)-1  # One sample before zero.


def test_shared_wav_writer_preserves_set_levels_above_full_scale(tmp_path):
    from hals_studio.process_engine.utils import write_wav
    original = np.array([0., .5, -.25, 0.])
    decoded = []
    for index, gain in enumerate((1., 8.)):
        path = tmp_path / f'angle{index}.wav'
        write_wav(original * gain, 48000, path)
        samples, _ = sf.read(path)
        decoded.append(samples)
        np.testing.assert_array_equal(samples, original * gain)
    np.testing.assert_array_equal(decoded[1], 8 * decoded[0])
