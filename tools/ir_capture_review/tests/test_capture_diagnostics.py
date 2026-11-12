"""Exercise physical signal variations and faults through the optional scan path."""
import json
import hashlib
import sys
from pathlib import Path

import numpy as np
import pytest
from scipy.io import wavfile
from scipy.signal import chirp, butter, sosfilt
from scipy.ndimage import shift

sys.path.insert(0, str(Path(__file__).parents[1]))
from capture_diagnostics import aligned, augment_rows, RATE, load_reference, full_band_envelope


def session(folder, count=31):
    fs = RATE
    debug = folder/'debug'; refs = debug/'references'/'session'
    refs.mkdir(parents=True)
    (folder/'Distortion').mkdir()
    marker = .05*chirp(np.arange(2400)/fs, 1000, .1, 5000)*np.hanning(2400)
    sweep = .05*chirp(np.arange(fs)/fs, 30, 1, 9000, method='logarithmic')*np.hanning(fs)
    layout = dict(schema='marker_then_dual_sweep_v1', playback_marker_starts=[4800],
                  sweep_offset_samples=3600, sweep_samples=fs, total_samples=48000)
    meta = dict(raw_capture_channels=['electrical_loopback', 'microphone'],
                layout=layout, num_sweeps=1, sample_rate=fs)
    np.savez(refs/'reference.npz', metadata_json=json.dumps(meta), loopback_sweep=sweep, marker=marker)
    expected = np.zeros(48000); expected[4800:7200] = marker; expected[8400:32400] = sweep
    # An interface's normal bandwidth/phase response must not be a fault.
    loop = sosfilt(butter(3, 6000, fs=fs, output='sos'), expected)
    loop = shift(loop, 480., order=3, mode='constant')
    rng = np.random.default_rng(7)
    rows = []
    for i in range(count):
        name = f'T_r300p0_ph{i}p0_z0p0_ir.wav'
        ir = np.zeros(12000, np.float32); ir[48] = .01
        wavfile.write(folder/name, fs, ir)
        full = np.r_[rng.normal(0, 1e-8, 12000), ir].astype(np.float32)
        wavfile.write(folder/'Distortion'/name.replace('_ir.wav', '_ir_dist.wav'), fs, full)
        electrical = shift(loop, (i%5-2)*.17, order=3, mode='constant')*(1+(i%3-1)*.002)
        mic = .02*shift(loop, 60+i, order=3, mode='constant')+rng.normal(0, 1e-6, len(loop))
        raw = np.column_stack([electrical, mic]).astype(np.float32)
        wavfile.write(debug/name.replace('_ir.wav', '_capture.wav'), fs, raw)
        rows.append(dict(filename=name, status='pass', score=0., reason='', xyz=np.array([i*.01, 0., 0.])))
    return rows


def mutate(folder, row, operation):
    path = folder/'debug'/row['filename'].replace('_ir.wav', '_capture.wav')
    fs, x = wavfile.read(path); operation(x); wavfile.write(path, fs, x)


def test_session_separates_electrical_and_acoustic_faults(tmp_path):
    rows = session(tmp_path)
    mutate(tmp_path, rows[4], lambda x: x.__setitem__((slice(18000, 19200), 0), 0))
    mutate(tmp_path, rows[8], lambda x: x.__setitem__((slice(25000, 25020), 0), .5))
    mutate(tmp_path, rows[12], lambda x: x.__setitem__((slice(1500, 4000), 1), .002))
    mutate(tmp_path, rows[16], lambda x: x.__setitem__((slice(19000, 19020), 1), 1.))
    mutate(tmp_path, rows[20], lambda x: x.__setitem__((slice(None), 0), 0))
    original = {p: hashlib.sha256(p.read_bytes()).digest() for p in tmp_path.rglob('*') if p.is_file()}
    augment_rows(tmp_path, rows, lambda *args: None, lambda: False)
    assert all(hashlib.sha256(p.read_bytes()).digest() == digest for p, digest in original.items())
    codes = lambda i: {issue['code'] for issue in rows[i]['issues']}
    assert 'loopback_dropout' in codes(4)
    assert rows[4]['status'] == 'repeat'
    assert 'loopback_mismatch' in codes(8)
    assert codes(12) == {'pre_sweep_noise'}
    assert rows[12]['category'] == 'Acoustic/microphone'
    assert rows[12]['status'] == 'review'
    assert 'clipping' in codes(16)
    assert 'silent_channel' in codes(20)
    for i, row in enumerate(rows):
        if i not in (4, 8, 12, 16, 20):
            assert row['status'] == 'pass', (i, row['issues'])
        assert 'Full IR' in row['coverage']


@pytest.mark.parametrize('other_status', ['review', 'repeat', 'technical'])
def test_loopback_loss_overrides_other_findings_without_discarding_them(tmp_path, other_status):
    rows = session(tmp_path, 9)
    rows[4].update(status=other_status, reason='Invalid cropped IR')
    mutate(tmp_path, rows[4], lambda x: x.__setitem__((slice(18000, 19200), 0), 0))
    augment_rows(tmp_path, rows, lambda *args: None, lambda: False)
    row = rows[4]
    assert row['status'] == 'repeat'
    assert row['primary_issue'] == 'loopback_dropout'
    assert row['reason'].startswith('Loopback signal loss')
    assert row['category'].startswith('Electrical/capture')
    secondary = 'invalid_ir' if other_status == 'technical' else 'spatial_discrepancy'
    assert any(issue['code'] == secondary for issue in row['issues'][1:])
    assert json.loads(row['evidence'])['issues'][0]['code'] == 'loopback_dropout'


def test_missing_and_ambiguous_references_are_not_guessed(tmp_path):
    rows = session(tmp_path, 1)
    path = next((tmp_path/'debug/references').rglob('*.npz'))
    path.with_name('second.npz').write_bytes(path.read_bytes())
    with pytest.raises(ValueError, match='unambiguous'):
        load_reference(tmp_path)
    augment_rows(tmp_path, rows, lambda *args: None, lambda: False)
    assert rows[0]['status'] == 'review'
    assert rows[0]['issues'][0]['code'] == 'reference_unavailable'


def test_full_ir_nonfinite_tail_is_reported(tmp_path):
    rows = session(tmp_path, 1)
    path = next((tmp_path/'Distortion').glob('*.wav'))
    fs, x = wavfile.read(path); x[-1] = np.nan; wavfile.write(path, fs, x)
    augment_rows(tmp_path, rows, lambda *args: None, lambda: False)
    assert any(i['code'] == 'invalid_full_ir' for i in rows[0]['issues'])


def test_fractional_latency_and_gain_are_removed_without_hiding_dropout():
    rng = np.random.default_rng(14)
    x = np.zeros(24000)
    x[2000:18000] = sosfilt(butter(4, 3000, fs=RATE, output='sos'), rng.normal(size=16000))
    shifted = shift(x, 234.3, order=3, mode='constant')*1.2
    fitted, delay, gain = aligned(shifted, x)
    assert delay == pytest.approx(234.3/RATE, abs=.01/RATE)
    assert gain == pytest.approx(1.2, rel=.003)
    assert np.linalg.norm(fitted-x)/np.linalg.norm(x) < .005
    shifted[10000:11000] = 0
    fitted, _, _ = aligned(shifted, x)
    assert np.linalg.norm(fitted-x)/np.linalg.norm(x) > .15


def test_cancellation_during_template_build(tmp_path):
    rows = session(tmp_path, 9)
    with pytest.raises(InterruptedError):
        augment_rows(tmp_path, rows, lambda *args: None, lambda: True)


def test_late_noise_and_far_prefix_are_reviewed_but_harmonic_region_is_not(tmp_path):
    rows = session(tmp_path)
    mutate(tmp_path, rows[3], lambda x: x.__setitem__((slice(-4800, None), 1), .001))
    for index, region in ((7, slice(0, 1500)), (10, slice(11000, 11500))):
        path = tmp_path/'Distortion'/rows[index]['filename'].replace('_ir.wav', '_ir_dist.wav')
        fs, x = wavfile.read(path); x[region] = .001; wavfile.write(path, fs, x)
    augment_rows(tmp_path, rows, lambda *args: None, lambda: False)
    assert {i['code'] for i in rows[3]['issues']} == {'late_noise'}
    assert {i['code'] for i in rows[7]['issues']} == {'full_ir_prefix'}
    assert rows[3]['status'] == rows[7]['status'] == 'review'
    assert rows[10]['status'] == 'pass'


def test_full_rate_envelope_covers_ultrasonic_dropout():
    fs = 96000
    x = np.sin(2*np.pi*30000*np.arange(fs)/fs)
    expected = full_band_envelope(x, fs, 100)
    x[48000:57600] = 0
    measured = full_band_envelope(x, fs, 100)
    assert np.all(expected > .7)
    assert np.all(measured[50:60] == 0)
    assert np.allclose(measured[:50], expected[:50])


def test_inconsistent_loopback_majority_is_not_a_trusted_baseline(tmp_path):
    rows = session(tmp_path)
    for index in range(16):
        mutate(tmp_path, rows[index], lambda x, i=index: x.__setitem__(
            (slice(9000+i*700, 13000+i*700), 0), 0))
    augment_rows(tmp_path, rows, lambda *args: None, lambda: False)
    assert all('Loopback consensus' not in row['coverage'] for row in rows)
    assert all(any(i['code'] == 'unstable_reference' for i in row['issues']) for row in rows)


def test_review_ui_displays_categories_evidence_and_exports(tmp_path, monkeypatch):
    import tkinter as tk
    import csv
    import ir_capture_review as ui
    from ir_capture_quality import scan_directory
    session(tmp_path, 9)
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip('Tk display unavailable')
    root.withdraw()
    try:
        app = ui.ReviewApp(root)
        app.folder = tmp_path
        app.rows = scan_directory(tmp_path)
        app.populate()
        app.tree.selection_set('0')
        app.inspect()
        app.canvas.draw()
        assert len(app.figure.axes) == 5
        assert [ax.get_title() for ax in app.figure.axes] == [
            'Electrical loopback', 'Microphone capture', 'Full IR before cropping',
            'LF response and local predictions', 'Measurement locations']
        assert not any(isinstance(w, tk.Toplevel) for w in root.winfo_children())
        assert len(app.figure.axes[0].collections) == 1
        assert len(app.figure.axes[1].collections) == 1
        assert len(app.figure.axes[2].collections) == 1
        app.figure.savefig(tmp_path/'main_review.png')
        assert 'category' in app.tree['columns']
        report = tmp_path/'report.csv'
        monkeypatch.setattr(ui.filedialog, 'asksaveasfilename', lambda **kwargs: str(report))
        app.export_report()
        with report.open(encoding='utf-8') as stream:
            exported = list(csv.DictReader(stream))
        assert len(exported) == 9
        assert 'Loopback consensus' in exported[0]['coverage']
        assert 'metrics' in json.loads(exported[0]['evidence'])
    finally:
        root.destroy()
