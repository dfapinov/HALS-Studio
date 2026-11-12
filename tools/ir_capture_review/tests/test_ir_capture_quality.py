"""Raw-IR diagnosis and reversible exclusion contracts, independent of SHE."""
import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest
from scipy.io import wavfile

sys.path.insert(0, str(Path(__file__).parents[1]))
spec = importlib.util.spec_from_file_location('ir_quality_test_backend', Path(__file__).parents[1]/'ir_capture_quality.py')
quality = importlib.util.module_from_spec(spec)
spec.loader.exec_module(quality)


def write_ir(folder, name='NA_r300p0_ph0p0_z0p0_ir.wav', silent=False):
    signal = np.zeros(24000, np.float32)
    if not silent:
        signal[96] = 1
    path = folder/name
    wavfile.write(path, 48000, signal)
    return path


def reviewed(path):
    return dict(filename=path.name, identity=quality.file_identity(path))


@pytest.mark.parametrize('rate', [48000, 96000])
def test_features_preserve_delay_phase_and_amplitude(tmp_path, rate):
    signal = np.zeros(int(.4*rate), np.float32)
    signal[int(.002*rate)] = 1
    path = tmp_path/'delayed.wav'
    wavfile.write(path, rate, signal)
    response, info = quality.features(path)
    truth = np.exp(-2j*np.pi*quality.FREQUENCIES*.002)
    assert max(abs(response/truth-1)) < .003
    assert info['arrival_ms'] == pytest.approx(2.)
    assert info['leading_samples_read'] == int(.35*rate)


def test_spatial_detector_preserves_clean_detail_and_finds_injected_lf_error():
    phi = np.arange(16)*2*np.pi/16
    xyz = np.array([[.4*np.cos(p), .4*np.sin(p), z] for z in np.linspace(-.3,.3,8) for p in phi])
    # Known locally affine complex field, including real spatial variation.
    clean = (1+xyz[:,0,None]+.3j*xyz[:,2,None])*np.exp(-.003j*quality.FREQUENCIES)[None,:]
    findings = quality.inspect_all(xyz, clean)
    assert all(f['status']=='pass' for f in findings)
    dirty = clean.copy()
    dirty[42] += 4*np.exp(-.5*(np.log2(quality.FREQUENCIES/60)/.15)**2)
    findings = quality.inspect_all(xyz, dirty)
    assert {i for i,f in enumerate(findings) if f['status']=='repeat'} == {42}
    assert findings[42]['band_low_hz']==40


def test_scan_is_read_only_and_reports_technical_and_insufficient_data(tmp_path):
    good = write_ir(tmp_path)
    silent = write_ir(tmp_path, 'NA_r300p0_ph10p0_z0p0_ir.wav', silent=True)
    bad_name = write_ir(tmp_path, 'unknown_ir.wav')
    before = {p.name:p.read_bytes() for p in tmp_path.iterdir()}
    rows = quality.scan_directory(tmp_path)
    by_name = {r['filename']:r for r in rows}
    assert by_name[good.name]['status']=='insufficient_neighbours'
    assert by_name[silent.name]['status']=='technical'
    assert by_name[bad_name.name]['status']=='technical'
    assert not any(r['marked'] for r in rows)
    assert before == {p.name:p.read_bytes() for p in tmp_path.iterdir()}


def test_duplicates_are_reported_instead_of_used_as_independent_neighbours(tmp_path):
    write_ir(tmp_path)
    write_ir(tmp_path, 'repeat_r300p0_ph0p0_z0p0_ir.wav')
    rows = quality.scan_directory(tmp_path)
    assert all(r['status']=='technical' and 'Duplicate' in r['reason'] for r in rows)


def test_rename_excludes_wav_import_and_restore_preserves_bytes(tmp_path):
    path = write_ir(tmp_path)
    original = path.read_bytes()
    row = reviewed(path)
    renamed = quality.rename_reviewed(tmp_path, [row])
    excluded = tmp_path/renamed[0]
    assert not path.exists() and excluded.read_bytes()==original
    assert not [p for p in tmp_path.iterdir() if p.name.lower().endswith('.wav')]
    rows = quality.scan_directory(tmp_path)  # All-excluded directories must still support restore.
    assert len(rows)==1 and rows[0]['status']=='excluded'
    quality.rename_reviewed(tmp_path, rows, restore=True)
    assert path.read_bytes()==original and not excluded.exists()


def test_restore_never_overwrites_replacement_capture(tmp_path):
    original = write_ir(tmp_path)
    name = quality.rename_reviewed(tmp_path, [reviewed(original)])[0]
    excluded = tmp_path/name
    replacement = write_ir(tmp_path, silent=True)
    before = replacement.read_bytes()
    with pytest.raises(FileExistsError, match='overwrite'):
        quality.rename_reviewed(tmp_path, [reviewed(excluded)], restore=True)
    assert replacement.read_bytes()==before and excluded.exists()


def test_changed_file_and_batch_collision_are_detected_before_any_rename(tmp_path):
    first = write_ir(tmp_path)
    second = write_ir(tmp_path, 'NA_r300p0_ph10p0_z0p0_ir.wav')
    rows = [reviewed(first), reviewed(second)]
    second.write_bytes(second.read_bytes()+b'changed')
    with pytest.raises(ValueError, match='changed since review'):
        quality.rename_reviewed(tmp_path, rows)
    assert first.exists() and second.exists()
    rows[1] = reviewed(second)
    second.with_name(second.name+'.blacklisted').write_bytes(b'older attempt')
    with pytest.raises(FileExistsError):
        quality.rename_reviewed(tmp_path, rows)
    assert first.exists() and second.exists()


def test_batch_failure_rolls_back_completed_renames(tmp_path, monkeypatch):
    first = write_ir(tmp_path)
    second = write_ir(tmp_path, 'NA_r300p0_ph10p0_z0p0_ir.wav')
    original_rename = Path.rename
    def rename(path, destination):
        if path == second:
            raise PermissionError('Capture file is busy')
        return original_rename(path, destination)
    monkeypatch.setattr(Path, 'rename', rename)
    with pytest.raises(PermissionError, match='busy'):
        quality.rename_reviewed(tmp_path, [reviewed(first), reviewed(second)])
    assert first.exists() and second.exists()
    assert not list(tmp_path.glob('*.blacklisted'))


def test_cancel_and_invalid_rename_paths(tmp_path):
    path = write_ir(tmp_path)
    with pytest.raises(InterruptedError):
        quality.scan_directory(tmp_path, cancelled=lambda: True)
    row = reviewed(path)
    row['filename'] = '../'+path.name
    with pytest.raises(ValueError, match='inside'):
        quality.rename_reviewed(tmp_path, [row])
