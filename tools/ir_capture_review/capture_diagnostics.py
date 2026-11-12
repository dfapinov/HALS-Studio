"""Optional capture evidence. No processing results or source files are modified.

Electrical attribution identifies a signal path, never a particular driver.
Thresholds are conservative engineering limits, not calibrated probabilities.
"""
import json
import warnings

import numpy as np
from scipy.io import wavfile
from scipy.signal import correlate, resample_poly
from scipy.optimize import minimize_scalar
from scipy.fft import rfft, irfft, rfftfreq, next_fast_len
from scipy.spatial import cKDTree

RATE = 24000
REPORT_COLUMNS = ['filename', 'status', 'category', 'primary_issue', 'score', 'spatial_score',
                  'band_low_hz', 'band_high_hz', 'coverage', 'reason', 'evidence']


def read_audio(path):
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', wavfile.WavFileWarning)
        fs, raw = wavfile.read(path)
    x = np.asarray(raw, dtype=float)
    if raw.dtype == np.uint8:
        x = (x-128)/128
    elif np.issubdtype(raw.dtype, np.integer):
        x /= float(np.iinfo(raw.dtype).max)+1
    if not len(x) or not np.isfinite(x).all():
        raise ValueError('Empty or non-finite audio')
    return fs, x


def db(x):
    return float(20*np.log10(max(float(x), 1e-15)))


def rms(x):
    return float(np.sqrt(np.mean(np.square(x)))) if len(x) else 0.


def block_rms(x, size=240):
    n = len(x)//size
    return np.sqrt(np.mean(x[:n*size].reshape(n, size)**2, axis=1))


def full_band_envelope(x, fs, count):
    size = max(1, round(fs*.01))
    values = block_rms(x, size)
    return np.interp((np.arange(count)+.5)*.01,
                     (np.arange(len(values))+.5)*size/fs, values)


def aligned(x, reference):
    """Remove constant capture latency and gain, but preserve intra-sweep faults.

    Fourier interpolation estimates sub-sample delay without a parabolic-peak
    bias on a broadband sweep. Zero padding prevents circular wraparound.
    """
    if len(x) != len(reference) or rms(x) < 1e-12:
        raise ValueError('Silent loopback or incompatible capture length')
    corr = correlate(x, reference, mode='full', method='fft')
    center = len(reference)-1
    span = min(int(.1*RATE), center)
    lag = int(np.argmax(corr[center-span:center+span+1]))-span
    n = next_fast_len(2*len(x))
    xf, rf = rfft(x, n), rfft(reference, n)
    frequency = rfftfreq(n)
    cross = xf*np.conj(rf)
    # The real FFT's interior bins have double weight.
    weights = np.full(len(cross), 2.); weights[0] = 1.
    if n % 2 == 0:
        weights[-1] = 1.
    def objective(delay):
        return -float(np.sum(weights*np.real(cross*np.exp(2j*np.pi*frequency*delay))))
    fit = minimize_scalar(objective, bounds=(lag-1, lag+1), method='bounded',
                          options={'xatol': 1e-4})
    delay = float(fit.x)
    shifted = irfft(xf*np.exp(2j*np.pi*frequency*delay), n)[:len(x)]
    gain = float(shifted@reference/max(reference@reference, 1e-30))
    if gain <= .05:
        raise ValueError('Loopback cannot be aligned to session reference')
    return shifted/gain, delay/RATE, gain


def load_reference(folder):
    paths = sorted((folder/'debug'/'references').glob('*/*.npz'))
    if len(paths) != 1:
        raise ValueError('No unambiguous shared reference (expected one reference archive)')
    with np.load(paths[0], allow_pickle=False) as archive:
        meta = json.loads(str(archive['metadata_json'].item()))
        if meta.get('raw_capture_channels') != ['electrical_loopback', 'microphone']:
            raise ValueError('Unknown capture channel layout')
        layout = meta['layout']
        if layout['schema'] != 'marker_then_dual_sweep_v1' or meta['num_sweeps'] != 1:
            raise ValueError('Unsupported capture sequence')
        fs = int(meta['sample_rate'])
        marker_start = int(layout['playback_marker_starts'][0])
        sweep_start = marker_start+int(layout['sweep_offset_samples'])
        sweep_end = sweep_start+int(layout['sweep_samples'])
        expected = np.zeros(int(layout['total_samples']))
        sweep = archive['loopback_sweep']
        if len(sweep) != int(layout['sweep_samples']) or sweep_end > len(expected):
            raise ValueError('Invalid reference sweep length')
        expected[sweep_start:sweep_end] = sweep
        expected[marker_start:marker_start+len(archive['marker'])] = archive['marker']
    return dict(fs=fs, samples=len(expected), marker=marker_start/fs,
                start=sweep_start/fs, end=sweep_end/fs,
                expected=resample_poly(expected, RATE//np.gcd(fs, RATE), fs//np.gcd(fs, RATE)),
                reference=str(paths[0].relative_to(folder)))


def capture_path(folder, row):
    return folder/'debug'/row['filename'].replace('_ir.wav', '_capture.wav')


def capture_audio(path, ref):
    fs, x = read_audio(path)
    if fs != ref['fs'] or x.shape != (ref['samples'], 2):
        raise ValueError('Capture rate, length or channels disagree with shared reference')
    return x, resample_poly(x[:, 0], RATE//np.gcd(fs, RATE), fs//np.gcd(fs, RATE))


def add_issue(row, category, code, severity, message, **metrics):
    row['issues'].append(dict(category=category, code=code, severity=severity,
                              message=message, **metrics))


def full_ir_metrics(folder, row):
    path = folder/'Distortion'/row['filename'].replace('_ir.wav', '_ir_dist.wav')
    if not path.exists():
        return False
    fs, full = read_audio(path)
    rate, cropped = read_audio(folder/row['filename'])
    if fs != rate or full.ndim != 1 or cropped.ndim != 1:
        raise ValueError('Full IR format differs from cropped IR')
    # Locate and verify the actual crop; do not assume its origin is the midpoint.
    offset = int(np.argmax(abs(full))-np.argmax(abs(cropped)))
    count = min(len(cropped), len(full)-offset)
    if offset < int(.1*fs) or count < int(.05*fs) or not np.allclose(
            full[offset:offset+count], cropped[:count], rtol=1e-4, atol=max(rms(cropped)*1e-5, 1e-20)):
        raise ValueError('Cannot verify full-IR crop origin')
    # Far prefix only: the region immediately before the linear response contains
    # legitimate ESS harmonic responses. Even this metric is corroborative only.
    prefix = full[:max(1, int(offset*.2))]
    row['metrics']['full_ir_prefix_db'] = db(rms(prefix)/max(rms(cropped[:int(.2*fs)]), 1e-30))
    row['metrics']['full_ir_origin_s'] = offset/fs
    return True


def augment_rows(folder, rows, progress, cancelled):
    """Fuse optional evidence with existing spatial findings, bounded-memory."""
    active = [r for r in rows if r['status'] != 'excluded']
    for row in active:
        row.update(issues=[], metrics={}, category='', coverage='Cropped IR only',
                   spatial_score=row['score'], spatial_status=row['status'])
        if row['status'] in ('repeat', 'review'):
            add_issue(row, 'Acoustic/spatial', 'spatial_discrepancy', row['status'],
                      'LF response differs from nearby positions; cause is unconfirmed.')
        elif row['status'] == 'technical':
            add_issue(row, 'File/metadata', 'invalid_ir', 'technical', row['reason'])
    try:
        ref = load_reference(folder)
        reference_error = ''
    except (OSError, ValueError, KeyError, TypeError, IndexError) as error:
        ref, reference_error = None, str(error)

    available = [r for r in active if capture_path(folder, r).exists()]
    template = None
    if ref and len(available) >= 9:
        candidates, full_envelopes = [], []
        for i in np.unique(np.linspace(0, len(available)-1, min(31, len(available))).astype(int)):
            if cancelled():
                raise InterruptedError('Scan cancelled.')
            try:
                raw, loop = capture_audio(capture_path(folder, available[i]), ref)
                if np.max(abs(raw[:, 0])) >= .999:
                    continue
                # First capture is an alignment anchor only; the median is the model.
                delay, gain = 0., 1.
                if candidates:
                    loop, delay, gain = aligned(loop, candidates[0])
                candidates.append(loop)
                envelope = full_band_envelope(raw[:, 0], ref['fs'], len(loop)//240)
                full_envelopes.append(np.interp(np.arange(len(envelope))+delay*100,
                                                np.arange(len(envelope)), envelope)/gain)
            except (OSError, ValueError, EOFError):
                continue
            progress('Building loopback reference', len(candidates), min(31, len(available)))
        if len(candidates) >= 9:
            stack = np.array(candidates)
            template = np.median(stack, axis=0)
            agreement = np.array([rms(x-template)/max(rms(template), 1e-30) for x in stack])
            # Refuse a heterogeneous session rather than silently learning faults.
            if np.median(agreement) > .03 or np.mean(agreement < .05) < .7:
                template = None
                reference_error = 'Loopbacks do not form a consistent reference majority'
            else:
                _, latency, _ = aligned(template, ref['expected'])
                ref['latency'] = latency
                envelope = block_rms(template)
                baseline = np.median(np.array([block_rms(x-template) for x in stack]), axis=0)
                # Both a relative floor and a measured session residual floor.
                limits = np.maximum.reduce([envelope*.02, baseline*8,
                                             np.full(len(envelope), rms(template)*.002)])
                full_envelope = np.median(full_envelopes, axis=0)
                full_baseline = np.median(abs(np.array(full_envelopes)-full_envelope), axis=0)
                full_limits = np.maximum.reduce([full_envelope*.1, full_baseline*8,
                    np.full(len(full_envelope), rms(full_envelope)*.003)])
    for i, row in enumerate(active):
        if cancelled():
            raise InterruptedError('Scan cancelled.')
        coverage = ['Cropped IR']
        path = capture_path(folder, row)
        if path.exists():
            if not ref:
                add_issue(row, 'File/metadata', 'reference_unavailable', 'review', reference_error)
            else:
                try:
                    raw, loop = capture_audio(path, ref)
                    coverage.append('Capture')
                    for channel, category in ((0, 'Electrical/capture'), (1, 'Acoustic/microphone')):
                        if not np.any(raw[:, channel]) or np.ptp(raw[:, channel]) == 0:
                            add_issue(row, category, 'silent_channel', 'repeat', 'Capture channel is silent or constant.')
                        if np.count_nonzero(abs(raw[:, channel]) >= .999) >= 3:
                            add_issue(row, category, 'clipping', 'repeat', 'Capture reaches digital full scale.')
                    if template is not None:
                        signal, delay, gain = aligned(loop, template)
                        residual = block_rms(signal-template)
                        ratio = residual/limits
                        measured_envelope = full_band_envelope(raw[:, 0], ref['fs'], len(loop)//240)
                        measured_envelope = np.interp(np.arange(len(measured_envelope))+delay*100,
                            np.arange(len(measured_envelope)), measured_envelope)/gain
                        # Full-rate envelopes extend amplitude/dropout coverage above
                        # the 12 kHz Nyquist limit of the waveform residual test.
                        envelope_ratio = abs(measured_envelope-full_envelope)/full_limits
                        ratio = np.maximum(ratio, envelope_ratio)
                        worst = int(np.argmax(ratio))
                        row['metrics'].update(loopback_residual_score=float(ratio[worst]),
                            loopback_residual_db=db(rms(signal-template)/max(rms(template), 1e-30)),
                            loopback_event_s=worst*.01+delay,
                            loopback_delay_ms=delay*1000, loopback_gain_db=db(gain))
                        coverage.append('Loopback consensus')
                        if ratio[worst] > 1:
                            loss = (measured_envelope < full_envelope*.1) & (full_envelope > rms(full_envelope)*.05)
                            dropout = bool(np.any(loss & (ratio > 1)))
                            row['metrics']['loopback_loss_ms'] = int(np.sum(loss))*10
                            add_issue(row, 'Electrical/capture', 'loopback_dropout' if dropout else 'loopback_mismatch',
                                      'repeat' if dropout or ratio[worst] > 3 else 'review',
                                      (f'Loopback signal loss ({np.sum(loss)*10} ms in 10 ms blocks); ' if dropout else '') +
                                      f'loopback differs from reference near {worst*.01+delay:.3f} s.',
                                      score=float(ratio[worst]))
                        latency = ref['latency']+delay
                    else:
                        _, latency, _ = aligned(loop, ref['expected'])
                        coverage.append('No loopback consensus')
                        if reference_error:
                            add_issue(row, 'File/metadata', 'unstable_reference', 'review', reference_error)
                    fs = ref['fs']
                    # Discard first 50 ms of settling and leave a 20 ms marker guard.
                    stop = int((ref['marker']+latency-.02)*fs)
                    start = int((ref['start']+latency)*fs)
                    end = int((ref['end']+latency)*fs)
                    if not int(.08*fs) < stop < start < end <= len(raw):
                        raise ValueError('Aligned capture timing is outside usable recording')
                    mic = raw[:, 1]
                    level = rms(mic[start:end])
                    row['metrics'].update(mic_pre_dbfs=db(rms(mic[int(.05*fs):stop])),
                        mic_pre_relative_db=db(rms(mic[int(.05*fs):stop])/max(level, 1e-30)),
                        mic_settle_dbfs=db(rms(mic[:int(.05*fs)])))
                    if len(mic)-end >= int(.4*fs):
                        row['metrics']['mic_tail_dbfs'] = db(rms(mic[-int(.2*fs):]))
                        row['metrics']['mic_tail_relative_db'] = db(rms(mic[-int(.2*fs):])/max(level, 1e-30))
                except (OSError, ValueError, EOFError) as error:
                    add_issue(row, 'File/metadata', 'invalid_capture', 'review', str(error))
        try:
            if full_ir_metrics(folder, row):
                coverage.append('Full IR')
        except (OSError, ValueError, EOFError) as error:
            add_issue(row, 'File/metadata', 'invalid_full_ir', 'review', str(error))
        row['coverage'] = ' + '.join(coverage)
        progress('Checking capture evidence', i+1, len(active))
    compare_metrics(active)
    for row in active:
        issues = row['issues']
        # Signal loss takes precedence even when another check reports an invalid
        # IR. Preserve all secondary evidence rather than hiding other failures.
        issues.sort(key=lambda issue: issue['code'] != 'loopback_dropout')
        row['primary_issue'] = issues[0]['code'] if issues else ''
        row['category'] = '; '.join(dict.fromkeys(issue['category'] for issue in issues))
        if issues:
            severity = {'technical': 3, 'repeat': 2, 'review': 1}
            status = max((issue['severity'] for issue in issues), key=severity.get)
            row['status'] = 'repeat' if row['primary_issue'] == 'loopback_dropout' else status
            messages = [issue['message'] for issue in issues]
            row['reason'] = ' '.join(dict.fromkeys(messages))
        row['evidence'] = json.dumps(dict(metrics=row['metrics'], issues=issues), allow_nan=False)


def compare_metrics(rows):
    """Require a large absolute departure as well as robust cohort/local evidence."""
    checks = [('mic_pre_dbfs', 12., 'pre_sweep_noise', 'Elevated microphone noise before the marker.'),
              ('mic_tail_dbfs', 12., 'late_noise', 'Elevated late microphone tail; noise or room decay.'),
              ('full_ir_prefix_db', 15., 'full_ir_prefix', 'Unusual far pre-linear IR energy; inspect noise/distortion.')]
    for key, floor, code, message in checks:
        valid = [r for r in rows if key in r['metrics'] and 'xyz' in r]
        if len(valid) < 9:
            continue
        values = np.array([r['metrics'][key] for r in valid])
        median = float(np.median(values))
        scale = max(float(1.4826*np.median(abs(values-median))), 1.)
        neighbours = cKDTree([r['xyz'] for r in valid]).query(
            [r['xyz'] for r in valid], k=min(25, len(valid)))[1]
        for i, row in enumerate(valid):
            local = values[neighbours[i, 1:]]
            local_median = float(np.median(local))
            local_scale = max(float(1.4826*np.median(abs(local-local_median))), 1.)
            limit = max(median+max(floor, 6*scale), local_median+max(floor, 6*local_scale))
            # Very low absolute noise is not a meaningful corruption warning.
            relative = row['metrics'].get(key.replace('_dbfs', '_relative_db'), 0.)
            if values[i] > limit and relative > -45:
                add_issue(row, 'Acoustic/microphone', code, 'review', message,
                          value_db=float(values[i]), threshold_db=limit)
    # Constant latency is aligned out for waveform testing; report unusually large
    # latency/gain shifts separately rather than treating them as dropouts.
    for key, floor, label in [('loopback_gain_db', 1., 'level'), ('loopback_delay_ms', 2., 'latency')]:
        valid = [r for r in rows if key in r['metrics']]
        if len(valid) < 9:
            continue
        values = np.array([r['metrics'][key] for r in valid]); median = np.median(values)
        limit = max(floor, 8*1.4826*float(np.median(abs(values-median))))
        for row, value in zip(valid, values):
            if abs(value-median) > limit:
                add_issue(row, 'Electrical/capture', 'loopback_'+label, 'review',
                          f'Unusual loopback {label} relative to session.', value=float(value), threshold=limit)
