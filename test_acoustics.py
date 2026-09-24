import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import bootstrap
import numpy as np
import pytest
import acoustics as ac


def constant_sphere():
    e, a = ac.grid(5)
    return ac.Sphere(np.array([100., 200., 400.]), e, a, np.ones((3, len(e), len(a)), complex))


def test_isotropic_energy_and_di():
    s = constant_sphere()
    assert s.weights().sum() == pytest.approx(1)
    m = s.metrics(s.levels())
    np.testing.assert_allclose(m["sphere_average"], 0, atol=1e-12)
    np.testing.assert_allclose(m["directivity_index"], 0, atol=1e-12)
    angles, h, _ = s.cuts(s.levels())
    assert np.isnan(ac.beamwidth(angles, h)).all()


def test_dipole_di_and_beamwidth():
    s = constant_sphere()
    x = ac.directions(s.elevation, s.azimuth)[..., 0]
    s.pressure[:] = x
    m = s.metrics(s.levels())
    np.testing.assert_allclose(m["directivity_index"], 10*np.log10(3), atol=.02)
    angles, h, v = s.cuts(s.levels())
    np.testing.assert_allclose(ac.beamwidth(angles, h), 120, atol=.5)
    np.testing.assert_allclose(ac.beamwidth(angles, v), 120, atol=.5)


def test_phase_and_delay_sign():
    f = np.arange(10., 10000., 10.)
    p = np.exp(-2j*np.pi*f*.003)
    phase, gd = ac.phase_delay(f, p)
    np.testing.assert_allclose(gd, 3, atol=1e-10)
    _, gd = ac.phase_delay(f, p, remove_ms=3)
    np.testing.assert_allclose(gd, 0, atol=1e-10)


def test_smoothing_preserves_constant_energy_and_raw_phase():
    s = ac.demo()
    original = s.pressure.copy()
    levels = s.levels(3)
    assert np.isfinite(levels).all()
    np.testing.assert_array_equal(s.pressure, original)
    c = constant_sphere()
    np.testing.assert_allclose(c.levels(3), 0)


def test_sphere_roundtrip_and_metrics_export(tmp_path):
    s = ac.demo()
    path = tmp_path / "sphere.npz"
    ac.save_sphere(s, path)
    loaded = ac.load_sphere(path)
    np.testing.assert_array_equal(s.pressure, loaded.pressure)
    assert loaded.metadata == s.metadata
    path = tmp_path / "metrics.csv"
    ac.export_metrics(s, path, s.levels(), 30, 15)
    data = np.loadtxt(path, delimiter=",", skiprows=1)
    assert data.shape == (len(s.freqs), 9)


def test_invalid_sphere_rejected():
    s = constant_sphere()
    with pytest.raises(ValueError, match="increasing"):
        ac.Sphere([100, 100], s.elevation, s.azimuth, s.pressure[:2])
    with pytest.raises(ValueError, match="NaN"):
        ac.Sphere(s.freqs, s.elevation, s.azimuth, s.pressure*np.nan)


def test_coordinate_conventions_and_seam():
    s = constant_sphere()
    xyz = ac.directions(s.elevation, s.azimuth)
    np.testing.assert_allclose(xyz[s.index(0, 0)], [1, 0, 0], atol=1e-12)
    np.testing.assert_allclose(xyz[s.index(90, 0)], [0, 1, 0], atol=1e-12)
    np.testing.assert_allclose(xyz[s.index(0, 90)], [0, 0, 1], atol=1e-12)
    assert s.index(180, 0) == s.index(-180, 0)


def test_reconstruction_against_hals_evaluator(tmp_path):
    import h5py
    from extract_pressures_core import evaluate_she_field
    path = tmp_path / "monopole.h5"
    with h5py.File(path, "w") as h:
        h["freqs"] = [100., 1000., 10000.]
        h["N_used"] = np.zeros(3, int)
        h["coeffs"] = np.tile([1.+.5j, .1+.2j], (3, 1))
        h["origins_mm"] = np.tile([10., 20., 30.], (3, 1))
        h["fs"] = 48000.
        h["speed_of_sound_mps"] = 345.
    s = ac.reconstruct(path, step=15, bins=0, radius=2, padding=50)
    expected = evaluate_she_field([[90, 0, 2]], path, c_sound=345., use_process_pool=False, show_progress=False)
    np.testing.assert_allclose(s.pressure[:, *s.index()], expected["complex"][:, 0], rtol=1e-12)
    with pytest.raises(ac.Cancelled):
        ac.reconstruct(path, step=15, cancelled=lambda: True)


def test_export_folder_incomplete_and_full(tmp_path):
    folder = tmp_path / "exports"
    folder.mkdir()
    f = np.array([100., 1000.])
    np.savez(folder / "first_complex.npz", freqs=f, P=np.ones(2), theta_in=90, phi_in=0, r_in=2)
    with pytest.raises(ValueError, match="complete sphere"):
        ac.import_exports(folder)
    (folder / "first_complex.npz").unlink()
    for i, el in enumerate([-90, 0, 90]):
        for j, az in enumerate([-180, -90, 0, 90]):
            np.savez(folder / f"p{i}_{j}_complex.npz", freqs=f, P=np.ones(2), theta_in=90-el, phi_in=az, r_in=2)
    s = ac.import_exports(folder)
    assert s.pressure.shape == (2, 3, 4)


def test_geometry_preserves_scalar_ordering():
    from plots import balloon_mesh, volume_mesh
    s = ac.demo()
    relative = s.relative(s.levels())
    b = balloon_mesh(s, relative[20])
    expected = np.column_stack((relative[20], relative[20, :, :1])).ravel(order="F")
    np.testing.assert_allclose(b["Relative level / dB"], expected)
    v = volume_mesh(s, relative)
    assert v.contour([-6]).n_points > 0


def test_native_frequency_selection_reports_duplicates_and_finer_hf():
    f = np.arange(5, 24001) * (24000/4860)
    old = ac.select_frequencies(f, 120)
    fine = ac.select_frequencies(f, 480)
    assert len(old) < 120
    assert len(fine) > len(old)
    assert np.all(np.diff(old) > 0)
    h_old = f[old][f[old] > 3000]
    h_fine = f[fine][f[fine] > 3000]
    assert np.max(np.diff(h_fine)) < np.max(np.diff(h_old)) / 3
    np.testing.assert_array_equal(ac.select_frequencies(f, 0), np.flatnonzero((f>=20)&(f<=20000)))


def test_omnidirectional_volume_has_coverage_even_without_crossings():
    from plots import volume_mesh, coverage_surface
    s = constant_sphere()
    mesh = volume_mesh(s, s.relative(s.levels()))
    assert coverage_surface(mesh, -6, closed=False).n_points == 0
    surface = coverage_surface(mesh, -6, closed=True)
    assert surface.n_points > 0
    np.testing.assert_allclose(surface.bounds, mesh.bounds)


def test_unit_sphere_and_response_families():
    from plots import balloon_mesh, response_directions
    s = ac.demo()
    mesh = balloon_mesh(s, s.relative(s.levels())[30], mapping="Colour sphere (no deformation)")
    np.testing.assert_allclose(np.linalg.norm(mesh.points, axis=1), 1, atol=1e-12)
    horizontal = response_directions(s, "Horizontal", 90, 10)
    vertical = response_directions(s, "Vertical", 90, 10)
    assert len(horizontal) == len(vertical) == 10
    assert horizontal[0][1] == "On axis"
    assert horizontal[3][0] == s.index(30, 0)
    assert vertical[3][0] == s.index(0, 30)
    assert len(response_directions(s, "Horizontal", 30, 10, True)) == 7
    # Fine requested steps never produce duplicated native traces.
    family = response_directions(s, "Horizontal", 20, 1)
    assert len({idx for idx, _ in family}) == len(family)
