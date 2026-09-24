"""Viewer analysis using HALS Stage 5's reference-axis coordinate generator.

CTA composites use energy averages, Table 7 solid-angle weights and the
12/44/44 listening-window/early-reflections/sound-power PIR weighting.
Interpolated sphere results are estimates, not a certified measurement.
"""
import json
from pathlib import Path
import bootstrap
import numpy as np
from cta_coordinates import generate_cta2034_coords
from hals_engine.stage5_extract_pressures import calculate_cta2034_energy_metrics


def reference_axis(path):
    """Read Stage 5's axis without importing the HALS GUI/configuration."""
    def find(obj):
        if isinstance(obj, dict):
            if 'zero_theta_deg' in obj and 'zero_phi_deg' in obj:
                return float(obj['zero_phi_deg']), 90 - float(obj['zero_theta_deg'])
            for value in obj.values():
                result = find(value)
                if result is not None:
                    return result
        return None
    result = find(json.loads(Path(path).read_text(encoding='utf-8-sig')))
    if result is None or not np.isfinite(result).all() or abs(result[1]) > 90:
        raise ValueError('No valid Stage 5 zero_theta_deg / zero_phi_deg reference axis found.')
    return ((result[0] + 180) % 360 - 180, result[1])


def sample_energy(sphere, energy, azimuth, elevation):
    """Periodic bilinear interpolation of energy, never coherent phase averaging."""
    az = (np.asarray(azimuth) + 180) % 360
    a = az / (360 / len(sphere.azimuth))
    e = (np.clip(elevation, -90, 90) + 90) / np.diff(sphere.elevation)[0]
    ai, ei = np.floor(a).astype(int), np.floor(e).astype(int)
    af, ef = a - ai, e - ei
    aj = (ai + 1) % len(sphere.azimuth)
    ej = np.minimum(ei + 1, len(sphere.elevation) - 1)
    return ((1-ef)*((1-af)*energy[:, ei, ai] + af*energy[:, ei, aj]) +
            ef*((1-af)*energy[:, ej, ai] + af*energy[:, ej, aj]))


def cea2034(sphere, levels, axis=(0, 0)):
    coords, indices, _ = generate_cta2034_coords(1., 90-axis[1], axis[0])
    coords = np.array(coords)
    energy = sample_energy(sphere, 10**(levels/10), coords[:, 1], 90-coords[:, 0])
    return calculate_cta2034_energy_metrics(energy, indices)


def minimum_phase(freqs, magnitude):
    """Finite-band cepstral estimate; constant endpoint magnitude extension."""
    n = 32768
    linear = np.linspace(0, freqs[-1]*2, n//2+1)
    logmag = np.interp(linear, freqs, np.log(np.maximum(magnitude, 1e-30)))
    cepstrum = np.fft.irfft(logmag, n)
    causal = np.zeros(n)
    causal[0], causal[n//2] = cepstrum[0], cepstrum[n//2]
    causal[1:n//2] = 2*cepstrum[1:n//2]
    phase = np.fft.rfft(causal).imag
    return np.interp(freqs, linear, phase) * 180/np.pi


def trend_fit(freqs, levels, low=100., high=10000.):
    """Least squares in log2(Hz), uniformly weighted per octave.

    Integrate the piecewise-linear curve exactly so native LF bin density does
    not bias a logarithmic audio plot. Deviation is worst absolute residual,
    not a confidence interval, and includes every original in-band sample.
    """
    f, y = np.asarray(freqs, float), np.asarray(levels, float)
    valid = np.isfinite(f) & np.isfinite(y) & (f > 0)
    f, y = f[valid], y[valid]
    if len(f) < 2 or low >= high: raise ValueError('Fit needs a valid range and at least two samples.')
    low, high = max(low, f[0]), min(high, f[-1])
    if low >= high: raise ValueError('Fit range does not overlap the response.')
    frequencies = np.unique(np.r_[low, f[(f > low) & (f < high)], high])
    x0, x1 = np.log2(low), np.log2(high)
    center = (x0+x1)/2
    x = np.log2(frequencies)-center
    values = np.interp(x+center, np.log2(f), y)
    dx = np.diff(x)
    mean = np.sum(dx*(values[:-1]+values[1:])/2)/(x1-x0)
    xy = np.sum(dx*((2*x[:-1]+x[1:])*values[:-1]+(x[:-1]+2*x[1:])*values[1:])/6)
    slope = xy/((x1-x0)**3/12)
    line = mean+slope*x
    residual = values-line
    return dict(freqs=frequencies, line=line, slope=float(slope), mean=float(mean),
                deviation=float(np.max(np.abs(residual))),
                rms=float(np.sqrt(np.sum(dx*(residual[:-1]**2+residual[:-1]*residual[1:]+residual[1:]**2)/3)/(x1-x0))),
                low=float(low), high=float(high))


def contour_levels(low, high, step):
    if step <= 0 or low > high or high >= 0:
        raise ValueError('Contours need a positive step and a negative level range (low <= high).')
    if (high-low)/step > 40:
        raise ValueError('Choose at most 41 contour layers for an interactive display.')
    return np.arange(high, low-1e-8, -step)
