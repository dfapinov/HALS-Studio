"""Project speed defaults, legacy migration, and explicit overrides."""
import numpy as np
import h5py
import pytest
from hals_studio.persistence.project_speed import project_speed


def test_default_legacy_saved_and_manual_speed(tmp_path):
    npz = tmp_path/'input.npz'; coeff = tmp_path/'coeff.h5'
    assert project_speed({}, npz, coeff) == 343.
    assert project_speed({'speed_of_sound': '339.5'}, npz, coeff) == 339.5
    with h5py.File(coeff, 'w') as data:
        data['speed_of_sound_mps'] = 332.5
    assert project_speed({}, npz, coeff) == 332.5
    np.savez(npz, speed_of_sound_mps=328.5, data=np.array({'a': [1j]}, dtype=object))
    assert project_speed({'speed_of_sound': '343'}, npz, coeff) == 328.5
    assert project_speed(dict(speed_of_sound='345.5', enable_manual_speed_of_sound=True), npz, coeff) == 345.5


@pytest.mark.parametrize('stage', [1, 2, 3, 4])
@pytest.mark.parametrize('manual', [False, True])
def test_all_processing_stages_receive_resolved_project_speed(tmp_path, monkeypatch, stage, manual):
    from hals_studio.application import process_service
    out = tmp_path/'outputs';out.mkdir()
    np.savez(out/'speaker_complex_data.npz', speed_of_sound_mps=328.5)
    class ReachedStage(Exception): pass
    def runner(request, *args):
        assert request['speed'] == (345.5 if manual else 328.5)
        raise ReachedStage
    monkeypatch.setitem(process_service.STAGE_RUNNERS, stage, runner)
    with pytest.raises(ReachedStage):
        process_service.run(dict(stage=stage, settings={}, folder=str(tmp_path), name='speaker',
            cache=str(tmp_path/'cache'), speed=345.5, manual_speed=manual))


def test_stage1_retains_project_speed_when_rebuilding_measurements(tmp_path):
    import soundfile as sf
    from hals_studio.process_engine.stage1_fdwsmooth import fdwsmooth
    from hals_studio.process_engine.runtime import EngineRuntime
    ir=np.zeros(4096);ir[96]=1.
    sf.write(tmp_path/'point.wav', ir, 48000)
    fdwsmooth(str(tmp_path), str(tmp_path), 'output.npz', 5, 12, 50, False, 24,
        speed_of_sound=328.5, use_process_pool=False, workers=1,
        runtime=EngineRuntime(output=lambda text: None))
    with np.load(tmp_path/'output.npz', allow_pickle=False) as data:
        assert data['speed_of_sound_mps'].item() == 328.5


def test_stage4_explicit_project_speed_overrides_old_input_metadata(tmp_path, monkeypatch):
    from hals_studio.process_engine import stage4_run_she_solve as stage
    from hals_studio.process_engine.runtime import EngineRuntime
    (tmp_path/'input.npz').touch()
    data=dict(freqs=np.array([0., 1000.]), filenames=['a'],complex_data={'a':np.ones(2,complex)},
              r_arr=np.array([1.]),th_arr=np.array([1.]),ph_arr=np.array([0.]),
              origins_mm=None,speed_of_sound_mps=328.5)
    monkeypatch.setattr(stage,'load_and_parse_npz',lambda path:data)
    class ReachedSolve(Exception): pass
    def solve(**kwargs):
        assert kwargs['k_val'] == pytest.approx(2*np.pi*1000/345.5)
        raise ReachedSolve
    monkeypatch.setattr(stage,'_solve_one_frequency',solve)
    with pytest.raises(ReachedSolve):
        stage.run_she_solve('input.npz','unused.h5',str(tmp_path),str(tmp_path),2,
            speed_of_sound=345.5,use_saved_speed=False,save_to_disk=False,show_plot=False,
            jobs=1,use_process_pool=False,runtime=EngineRuntime(output=lambda text:None))
