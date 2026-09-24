"""Separate the saved complex reconstruction from its WAV conversion."""
from pathlib import Path
import json
import numpy as np
import soundfile as sf
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from analyze_ir import spectrum_at, style, BLUE, ORANGE
from analyze_edited_report import metrics, delta
from reproduction.complex_to_ir_core import complex_to_ir

HERE = Path(__file__).resolve().parent
OUT = HERE / 'edited_figures'

def main():
    OUT.mkdir(exist_ok=True)
    plt.rcParams.update({'font.size': 10, 'axes.spines.top': False, 'axes.spines.right': False})
    with np.load(HERE / 'data/tweeter_stage1.npz') as z:
        sfreq, reference = z['freqs'], z['response']
    with np.load(HERE / 'data/tweeter_stage5_complex.npz') as z:
        f, reconstructed = z['freqs'], z['P']
    # The complex export omits DC; the remaining bins match Stage 1 exactly.
    np.testing.assert_array_equal(sfreq[1:], f)
    reference = reference[1:]
    wav, fs = sf.read(HERE / 'data/tweeter_stage5.wav')
    converted = complex_to_ir(reconstructed, f, target_fs=fs)
    np.testing.assert_allclose(converted, wav, atol=1e-8, rtol=1e-6)
    W = spectrum_at(wav, fs, f)
    results = {
        'tweeter_model_300_20000': metrics(f, reference, reconstructed, 300, 20000),
        'tweeter_conversion_300_20000': metrics(f, reconstructed, W, 300, 20000),
        'tweeter_conversion_20_200': metrics(f, reconstructed, W, 20, 200),
        'tweeter_wav_recreation_max_abs_sample_difference': float(max(abs(converted-wav))),
    }
    mag, phase = delta(reference, reconstructed)
    with np.load(HERE / 'data/tweeter_fit.npz') as z:
        fitf, fit = z['freqs'], 20*np.log10(np.maximum(z['pct_error']/100, 1e-30))
    fig, axs = plt.subplots(4, 1, figsize=(8, 6.9), sharex=True)
    m = (f >= 20) & (f <= 20000)
    for ax, y, label in [(axs[0], mag, 'Difference (dB)'), (axs[1], phase, 'Difference (degrees)')]:
        ax.plot(f[m], y[m], color=ORANGE, lw=.9)
        style(ax, label)
        ax.axhline(0, color='gray', ls=':', lw=.6)
    axs[0].set_title('Stage 1 minus complex reconstruction (before WAV conversion)', loc='left', fontsize=10)
    axs[1].set_ylim(-180, 180)
    axs[2].plot(fitf, fit, color=BLUE)
    style(axs[2], 'Fit residual (dB)')
    axs[2].axhline(-20, color='gray', ls=':', lw=.7)
    level_ref = max(abs(reference[(f >= 1000) & (f <= 10000)]))
    axs[3].plot(f[m], 20*np.log10(np.maximum(abs(reference[m])/level_ref, 1e-30)), color=BLUE)
    style(axs[3], 'Stage 1 level (dB)')
    axs[3].set_ylim(-100, 5)
    axs[3].set_xlabel('Frequency (Hz)')
    for ax in axs:
        ax.axvline(300, color='gray', ls='--', lw=.8)
    fig.tight_layout()
    fig.savefig(OUT / 'tweeter_complex_reconstruction.png', dpi=200)
    plt.close(fig)

    with np.load(HERE / 'data/synthetic_stage5_complex.npz') as z:
        f, C = z['freqs'], z['P']
    wav, fs = sf.read(HERE / 'data/synthetic_stage5.wav')
    W = spectrum_at(wav, fs, f)
    results['synthetic_conversion_20_200_saved_grid'] = metrics(f, C, W, 20, 200)
    # Independent known-input control: run the original through the converter,
    # without a holographic solve, then compare on a dense frequency grid.
    original, _ = sf.read(HERE / 'data/synthetic_original_windowed.wav')
    control = complex_to_ir(spectrum_at(original, fs, f), f, target_fs=fs)
    dense_f = np.fft.rfftfreq(131072, 1/fs)
    results['synthetic_conversion_only_control_20_200_dense_grid'] = metrics(
        dense_f, np.fft.rfft(original, 131072), np.fft.rfft(control, 131072), 20, 200)
    (OUT / 'pipeline_results.json').write_text(json.dumps(results, indent=2))
    print(json.dumps(results, indent=2))

if __name__ == '__main__':
    main()
