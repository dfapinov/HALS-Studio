"""Lossless-level time-domain exports of the Stage 1 complex spectra."""
import numpy as np
from hals_studio.process_engine.complex_to_ir_core import complex_to_ir
from hals_studio.process_engine.utils import write_wav


def export_ir(path, freqs, spectrum, sample_rate):
    freqs = np.asarray(freqs, dtype=float)
    spectrum = np.asarray(spectrum)
    if len(freqs) < 2 or spectrum.shape != freqs.shape or sample_rate <= 0:
        raise ValueError('Stage 1 export needs a complete, uniformly spaced FFT spectrum.')
    if not np.isfinite(spectrum).all() or not np.isfinite(freqs).all() or freqs[1] <= freqs[0]:
        raise ValueError('Stage 1 spectrum contains non-finite values.')
    ir = complex_to_ir(spectrum, freqs, sample_rate, preserve_spectrum=True)
    write_wav(ir, round(sample_rate), str(path), normalize=False)
