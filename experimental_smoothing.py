"""Cycle-based HF smoothing schedule used by viewer Stage 1.

The module name is retained for compatibility with the comparison scripts.
Use the existing cycles/octave estimate to release HF smoothing from 1/24
to 1/12 octave. This is an anchored bandwidth policy, not an exact inverse
of the asymmetric time window's complex convolution kernel.
"""
import numpy as np
from scipy.sparse import csr_matrix
from process_engine.fdw_smoothing_core import calculate_cycles_from_oct_res


def fractional_bandwidth(resolution):
    return 2.0 ** (.5 / np.asarray(resolution)) - 2.0 ** (-.5 / np.asarray(resolution))


def sliding_resolution(freqs, rft_ms, fdw_resolution=12., base_resolution=24.,
                       target_resolution=12., onset_octaves=0.):
    """Hold base below C/T; approach target above it; optionally ease onset.

    C = f*T; estimated octave resolution = log(2)/log(1+1/C).
    Its symmetric fractional bandwidth is 1/sqrt(C*(C+1)).
    Release = 1 - (estimated window BW / FDW BW)^2.
    Added BW^2 = base BW^2 + Release*(target BW^2 - base BW^2).
    A smoothstep multiplier over onset_octaves removes the slope corner.
    """
    f = np.asarray(freqs, dtype=float)
    if (rft_ms <= 0 or min(fdw_resolution, base_resolution, target_resolution) <= 0
            or target_resolution > base_resolution or onset_octaves < 0
            or np.any(~np.isfinite(f)) or np.any(f < 0)):
        raise ValueError('Invalid smoothing schedule parameters.')
    transition = calculate_cycles_from_oct_res(fdw_resolution) / (rft_ms / 1000)
    cycles = np.maximum(f * rft_ms / 1000, np.finfo(float).tiny)
    ratio = np.ones_like(f)
    high = f > transition
    ratio[high] = 1 / np.sqrt(cycles[high] * (cycles[high]+1)) / fractional_bandwidth(fdw_resolution)
    release = np.clip(1-ratio**2, 0, 1)
    if onset_octaves:
        u = np.clip(np.log2(np.maximum(f, transition)/transition)/onset_octaves, 0, 1)
        release *= u*u*(3-2*u)
    bandwidth = np.sqrt(fractional_bandwidth(base_resolution)**2 + release *
                        (fractional_bandwidth(target_resolution)**2-fractional_bandwidth(base_resolution)**2))
    result = np.log(2) / (2*np.arcsinh(bandwidth/2))
    result[~high] = base_resolution
    return result


def smoothing_matrix(freqs, resolution, truncate=3.):
    """Same normalized, finite Gaussian weights and bin bypass as Stage 1.

    A reusable sparse operator permits repeatable dataset-wide comparisons.
    Rotation/removal of the IR peak delay is applied separately.
    """
    f = np.asarray(freqs, dtype=float)
    n = len(f)
    if n < 2 or not np.allclose(np.diff(f), f[1]-f[0]) or f[1] <= f[0]:
        raise ValueError('An increasing uniform frequency grid is required.')
    resolutions = np.broadcast_to(np.asarray(resolution, dtype=float), f.shape)
    if np.any(~np.isfinite(resolutions)) or np.any(resolutions <= 0) or truncate <= 0:
        raise ValueError('Resolution and truncation must be finite and positive.')
    sigma = f*fractional_bandwidth(resolutions)/2.355/(f[1]-f[0])
    indices, values, indptr = [], [], [0]
    for i, width in enumerate(sigma):
        if f[i] <= 1e-6 or width < .5:
            ix, weights = np.array([i]), np.ones(1)
        else:
            radius = int(truncate*width)
            ix = np.arange(max(0, i-radius), min(n, i+radius+1))
            weights = np.exp(-.5*((ix-i)/width)**2); weights /= weights.sum()
        indices.extend(ix); values.extend(weights); indptr.append(len(indices))
    return csr_matrix((values, indices, indptr), shape=(n, n))


def apply_operator(operator, freqs, response, peak_seconds):
    rotation = np.exp(2j*np.pi*np.asarray(freqs)*peak_seconds)
    return (operator @ (response*rotation))*rotation.conj()


def frozen_neighbours(freqs, aligned_response, resolution):
    """Evaluate i-1 and i+1 holding fractional resolution at its value at i.

    Comparing this phase slope with the actual sliding-output phase slope
    isolates the schedule derivative, beyond constant-octave smoothing.
    """
    f = np.asarray(freqs); df = f[1]-f[0]; n = len(f)
    result = []
    for delta in (-1, 1):
        out = np.empty(n, dtype=complex)
        for i, res in enumerate(resolution):
            j = min(n-1, max(0, i+delta))
            sigma = f[j]*fractional_bandwidth(res)/2.355/df
            if f[j] <= 1e-6 or sigma < .5: out[i] = aligned_response[j]; continue
            radius = int(3*sigma); ix = np.arange(max(0,j-radius), min(n,j+radius+1))
            weights = np.exp(-.5*((ix-j)/sigma)**2); weights /= weights.sum()
            out[i] = np.dot(weights, aligned_response[ix])
        result.append(out)
    return result
