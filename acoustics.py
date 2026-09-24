"""Complex sphere I/O and acoustic calculations, independent of the GUI.

Axes follow HALS: +X front, +Y left, +Z up. Elevation is 90-theta.
Pressure axes are (frequency, elevation, azimuth); angles are degrees.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import bootstrap  # noqa: F401
import h5py
import numpy as np


class Cancelled(Exception):
    pass


def db(p):
    return 20 * np.log10(np.maximum(np.abs(p), 1e-30))


def directions(elevation, azimuth):
    e, a = np.deg2rad(np.meshgrid(elevation, azimuth, indexing="ij"))
    return np.stack((np.cos(e) * np.cos(a), np.cos(e) * np.sin(a), np.sin(e)), -1)


@dataclass
class Sphere:
    freqs: np.ndarray
    elevation: np.ndarray
    azimuth: np.ndarray
    pressure: np.ndarray
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        self.freqs = np.asarray(self.freqs, float)
        self.elevation = np.asarray(self.elevation, float)
        self.azimuth = np.asarray(self.azimuth, float)
        self.pressure = np.asarray(self.pressure, complex)
        for name in ("freqs", "elevation", "azimuth"):
            a = getattr(self, name)
            if a.ndim != 1 or len(a) < 2 or not np.isfinite(a).all() or np.any(np.diff(a) <= 0):
                raise ValueError(f"{name} must be finite, increasing, unique, and contain at least two values.")
        if self.freqs[0] <= 0:
            raise ValueError("Frequencies must be positive.")
        if self.pressure.shape != (len(self.freqs), len(self.elevation), len(self.azimuth)):
            raise ValueError("Pressure shape must be (frequency, elevation, azimuth).")
        if not np.isfinite(self.pressure).all():
            raise ValueError("Complex pressures contain NaN or infinity; check the reconstruction radius and coefficients.")
        if not np.allclose(self.elevation[[0, -1]], [-90, 90]) or not np.isclose(self.azimuth[0], -180):
            raise ValueError("A full sphere is required: elevation -90…90 and azimuth -180…<180.")
        if not np.allclose(np.diff(self.elevation), np.diff(self.elevation)[0]) or not np.allclose(np.diff(self.azimuth), 360 / len(self.azimuth)):
            raise ValueError("The sphere must have uniform angular spacing and no duplicate azimuth seam.")

    @property
    def name(self):
        return self.metadata.get("name", "Untitled sphere")

    def index(self, az=0, el=0):
        a = (float(az) + 180) % 360 - 180
        ia = np.argmin(np.abs((self.azimuth - a + 180) % 360 - 180))
        return int(np.argmin(np.abs(self.elevation - el))), int(ia)

    def weights(self):
        edges = np.r_[-90, (self.elevation[:-1] + self.elevation[1:]) / 2, 90]
        rings = np.diff(np.sin(np.deg2rad(edges))) / 2
        return np.broadcast_to(rings[:, None] / len(self.azimuth), self.pressure.shape[1:])

    def levels(self, octave=0):
        energy = np.abs(self.pressure) ** 2
        if octave:
            # Energy average in a centred fractional-octave band; phase is untouched.
            half = 1 / (2 * octave)
            logf = np.log2(self.freqs)
            bounds = np.searchsorted(logf, np.column_stack((logf - half, logf + half)))
            summed = np.concatenate((np.zeros_like(energy[:1]), np.cumsum(energy, axis=0)))
            energy = np.stack([(summed[max(b, a + 1)] - summed[a]) / (max(b, a + 1) - a) for a, b in bounds])
        return 10 * np.log10(np.maximum(energy, 1e-60))

    def relative(self, levels, normalization="Peak"):
        reference = levels.max(axis=(1, 2)) if normalization == "Peak" else levels[:, *self.index()]
        return levels - reference[:, None, None]

    def metrics(self, levels):
        power = 10 * np.log10(np.maximum(np.sum(10 ** (levels / 10) * self.weights(), axis=(1, 2)), 1e-60))
        axis = levels[:, *self.index()]
        return {"on_axis": axis, "sphere_average": power, "directivity_index": axis - power}

    def cuts(self, levels):
        # Signed great-circle angles: 0 front, +/-90 side/up/down, +/-180 rear.
        angles = self.azimuth
        e0, _ = self.index()
        horizontal = levels[:, e0, :]
        vertical = []
        for angle in angles:
            rad = np.deg2rad(angle)
            el = np.degrees(np.arcsin(np.sin(rad)))
            az = 0 if np.cos(rad) >= -1e-12 else -180
            vertical.append(levels[:, *self.index(az, el)])
        return angles, horizontal, np.stack(vertical, axis=1)


def beamwidth(angles, cut, threshold=-6):
    """Width of the front-connected lobe, linearly interpolating its crossings.

    NaN means the lobe never crosses the threshold in a complete revolution.
    """
    out = []
    zero = int(np.argmin(np.abs(angles)))
    for row in cut:
        row = row - row[zero]
        crossings = []
        for sign in (-1, 1):
            prev_a, prev_v = 0., 0.
            crossing = None
            for step in range(1, len(angles) // 2 + 1):
                i = (zero + sign * step) % len(angles)
                a = step * (360 / len(angles))
                v = row[i]
                if v <= threshold:
                    crossing = prev_a + (a - prev_a) * (threshold - prev_v) / (v - prev_v)
                    break
                prev_a, prev_v = a, v
            crossings.append(crossing)
        out.append(sum(crossings) if all(c is not None for c in crossings) else np.nan)
    return np.asarray(out)


def phase_delay(freqs, pressure, remove_ms=0):
    corrected = pressure * np.exp(2j * np.pi * freqs * remove_ms / 1000)
    phase = np.unwrap(np.angle(corrected))
    delay = -np.gradient(phase, 2 * np.pi * freqs) * 1000
    return np.rad2deg(phase), delay


def grid(step=5):
    if step not in (2, 3, 5, 6, 10, 15):
        raise ValueError("Angular step must divide both 90 and 360.")
    return np.arange(-90, 90 + step / 2, step), np.arange(-180, 180, step)


def demo():
    f = np.geomspace(30, 20000, 181)
    e, a = grid(5)
    xyz = directions(e, a)
    x, y, z = np.moveaxis(xyz, -1, 0)
    k = 2 * np.pi * f[:, None, None] / 343
    # An explicitly synthetic, complex three-radiator illustration.
    woofer = (1 / (1 + (f[:, None, None] / 1250) ** 4)) * (.57 + .43 * x) ** 2
    tweeter = (1 - 1 / (1 + (f[:, None, None] / 1250) ** 4))
    horn = np.exp(-(.018 * k * y) ** 2 - (.031 * k * z) ** 2) * (.12 + .88 * np.maximum(x, 0))
    p = woofer * (np.exp(-1j * k * z * .09) + .85 * np.exp(1j * k * z * .09)) / 1.85
    p = (p + tweeter * horn * np.exp(-1j * k * .012)) * np.exp(-1j * k * 2)
    return Sphere(f, e, a, p, {"name": "ATLAS / virtual two-way", "source": "Synthetic demonstration", "demo": True,
                                      "radius_m": 2., "mode": "Internal", "phase_note": "Synthetic physical propagation delay retained"})


def save_sphere(sphere, path):
    np.savez_compressed(path, format_version=np.array(1), freqs=sphere.freqs, elevation=sphere.elevation,
                        azimuth=sphere.azimuth, pressure=sphere.pressure,
                        metadata=np.array(json.dumps(sphere.metadata)))


def load_sphere(path):
    with np.load(path, allow_pickle=False) as d:
        required = {"freqs", "elevation", "azimuth", "pressure"}
        if not required.issubset(d.files):
            raise ValueError("This is not a full-sphere cache. For Stage 5 point files, use Import export folder; for reconstruction, open the Stage 4 .h5 file.")
        meta = json.loads(str(d["metadata"])) if "metadata" in d else {}
        return Sphere(d["freqs"], d["elevation"], d["azimuth"], d["pressure"], meta)


def select_frequencies(freqs, bins=480, fmin=20., fmax=20000.):
    """Snap log targets to native bins, explicitly retaining unique samples only."""
    freqs = np.asarray(freqs, float)
    good = np.flatnonzero((freqs >= fmin) & (freqs <= fmax) & (freqs > 0))
    if len(good) < 2 or bins < 0 or bins == 1:
        raise ValueError("Choose at least two native bins and a valid frequency range.")
    if not bins:
        return good
    targets = np.geomspace(freqs[good[0]], freqs[good[-1]], bins)
    logf = np.log(freqs[good])
    right = np.clip(np.searchsorted(logf, np.log(targets)), 1, len(good)-1)
    left = right - 1
    nearest = np.where(abs(logf[left]-np.log(targets)) <= abs(logf[right]-np.log(targets)), left, right)
    return np.unique(good[nearest])


def reconstruct(path, step=5, bins=480, radius=2., mode="Internal", fmin=20., fmax=20000.,
                padding=50, origins=True, offset=(0., 0., 0.), progress: Callable = lambda *_: None,
                cancelled: Callable = lambda: False, pool=None):
    """Evaluate native frequency batches through the local HALS Stage 5 snapshot.

    The GUI supplies a warm process pool; callers without one run serially.
    The engine bounds temporary mode-by-point arrays. No complex interpolation.
    """
    from utils import load_she_h5, cartesian_to_spherical
    from worker_pool import evaluate_task
    from stage5_pressure_utils import apply_ir_padding_phase
    import schema
    data = load_she_h5(path)
    all_f = np.asarray(data[schema.FREQS])
    good = np.flatnonzero((all_f >= fmin) & (all_f <= fmax) & (all_f > 0))
    if len(good) < 2:
        raise ValueError("The requested frequency range contains fewer than two coefficient bins.")
    if radius <= 0 or not np.isfinite(radius):
        raise ValueError("Observation radius must be positive.")
    indices = select_frequencies(all_f, bins, fmin, fmax)
    e, a = grid(step)
    xyz = directions(e, a).reshape(-1, 3) * radius + np.asarray(offset)
    r, th, ph = cartesian_to_spherical(*xyz.T)
    if np.any(r <= 1e-9):
        raise ValueError("The observation sphere passes through the origin.")
    coords = np.column_stack((np.rad2deg(th), np.rad2deg(ph), r))
    p = np.empty((len(indices), len(e), len(a)), complex)
    speed = data.get(schema.SPEED_OF_SOUND_MPS)
    speed = float(speed) if speed is not None else 343.
    origin_data = data.get(schema.ORIGINS_MM)
    if not origins or origin_data is None:
        origin_data = np.zeros((len(all_f), 3))
    def tasks():
        for start in range(0, len(indices), 4):
            if cancelled():
                raise Cancelled()
            local = np.arange(start, min(start+4, len(indices)))
            source = indices[local]
            yield (local, all_f[source], data[schema.COEFFS][source], data[schema.N_USED][source],
                   r, th, ph, origin_data[source], mode, speed)
    progress(0, f"Reconstructing {len(indices)} unique native bins ({bins or len(indices)} requested)")
    results = pool.map(tasks(), cancelled) if pool else map(evaluate_task, tasks())
    done = 0
    try:
        for local, pressures in results:
            if cancelled():
                raise Cancelled()
            p[local] = pressures.reshape(len(local), len(e), len(a))
            done += len(local)
            progress(int(done / len(indices) * 100), f"Reconstructing sphere · {done}/{len(indices)} native bins")
    finally:
        if hasattr(results, "close"):
            results.close()
    if padding < 0:
        raise ValueError("Capture padding must be nonnegative.")
    fs = data.get(schema.FS)
    fs = float(fs) if fs is not None else (44100. if all_f[-1] < 23000 else 48000.)
    p = apply_ir_padding_phase(p.reshape(len(indices), -1), all_f[indices], padding, fs).reshape(p.shape)
    return Sphere(all_f[indices], e, a, p, {"name": Path(path).stem.replace("_coefficients", ""),
        "source": str(Path(path).resolve()), "radius_m": radius, "mode": mode, "angular_step": step,
        "speed_of_sound": speed, "padding_samples_removed": padding, "optimized_origins": origins,
        "offset_m": list(offset), "source_frequency_bins": len(good), "sampled_frequency_bins": len(indices),
        "requested_frequency_targets": bins, "engine": "Viewer-local HALS Stage 5 snapshot",
        "workers": pool.workers if pool else 1,
        "phase_note": "HALS capture padding removed; physical propagation delay retained; no mic calibration or FRD offset applied"})


def import_exports(folder, progress=lambda *_: None, cancelled=lambda: False):
    """Read Stage 5 complex files only if they form a complete angular grid.

    Never invent a sphere from a pair of polar arcs or mix radii/exports.
    """
    files = sorted(Path(folder).rglob("*_complex.npz"))
    if not files:
        raise ValueError("No Stage 5 *_complex.npz files found in this folder.")
    points, pressures, radii = [], [], []
    freqs = None
    for n, path in enumerate(files):
        if cancelled():
            raise Cancelled()
        with np.load(path, allow_pickle=False) as d:
            if not {"freqs", "P", "theta_in", "phi_in", "r_in"}.issubset(d.files):
                raise ValueError(f"Missing Stage 5 coordinates in {path.name}.")
            if freqs is None:
                freqs = d["freqs"].copy()
            if not np.array_equal(freqs, d["freqs"]):
                raise ValueError("Export frequency grids differ. Select one coherent export folder.")
            points.append((round(90 - float(d["theta_in"]), 5), round((float(d["phi_in"]) + 180) % 360 - 180, 5)))
            radii.append(float(d["r_in"]))
            pressures.append(d["P"].reshape(-1))
        progress(int((n + 1) / len(files) * 100), f"Reading {n + 1}/{len(files)} complex responses")
    if not np.allclose(radii, radii[0], atol=1e-6, rtol=1e-5):
        raise ValueError("Multiple observation radii found. Select a single full-sphere export.")
    e, a = (np.unique(np.asarray(points)[:, i]) for i in (0, 1))
    lookup = {}
    for point, pressure in zip(points, pressures):
        if point in lookup:
            raise ValueError("Duplicate directions found; choose a folder containing just one sphere export.")
        lookup[point] = pressure
    if len(points) != len(e) * len(a) or len(e) < 3 or len(a) < 4:
        raise ValueError("These exports do not cover a complete sphere. Open the Stage 4 coefficients to reconstruct all directions.")
    p = np.stack([lookup[(el, az)] for el in e for az in a], axis=-1).reshape(len(freqs), len(e), len(a))
    keep = freqs > 0
    return Sphere(freqs[keep], e, a, p[keep], {"name": Path(folder).name, "source": str(Path(folder).resolve()),
                  "radius_m": radii[0], "phase_note": "Original Stage 5 complex export phase; no additional correction"})


def export_metrics(sphere, path, levels, az=0, el=0, remove_ms=0, offset_db=0):
    idx = sphere.index(az, el)
    phase, delay = phase_delay(sphere.freqs, sphere.pressure[:, *idx], remove_ms)
    metrics = sphere.metrics(levels)
    angles, h, v = sphere.cuts(levels)
    table = np.column_stack((sphere.freqs, levels[:, *idx] + offset_db, phase, delay,
                             metrics["on_axis"] + offset_db, metrics["sphere_average"] + offset_db,
                             metrics["directivity_index"], beamwidth(angles, h), beamwidth(angles, v)))
    np.savetxt(path, table, delimiter=",", header="frequency_Hz,selected_dB,phase_deg,group_delay_ms,on_axis_dB,sphere_average_dB,on_axis_DI_dB,horizontal_beamwidth_deg,vertical_beamwidth_deg", comments="")
