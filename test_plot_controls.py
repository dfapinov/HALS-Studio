"""Numerical contracts for trend fitting and Stage 5 delay compensation."""
import bootstrap
import numpy as np
import pytest
from analysis_metrics import trend_fit, contour_levels
from stage5_pressure_utils import get_min_phase_delay
from plot_interaction import zoom_interval
from response_plot import phase_values, phase_trace


def test_log_frequency_fit_and_worst_deviation():
    f = np.geomspace(100, 10000, 2001)
    x = np.log2(f/100)
    y = -70+1.5*x+.6*np.cos(8*np.pi*x/x[-1])
    fit = trend_fit(f, y)
    assert fit['slope'] == pytest.approx(1.5, abs=1e-10)
    assert fit['deviation'] == pytest.approx(.6, abs=1e-6)
    assert fit['rms'] == pytest.approx(.6/np.sqrt(2), abs=1e-5)


def test_irregular_bins_do_not_bias_a_straight_trend():
    f = np.r_[np.arange(20, 1000, 3), np.geomspace(1000, 20000, 30)]
    fit = trend_fit(f, 2*np.log2(f)-40, 100, 10000)
    assert fit['slope'] == pytest.approx(2)
    assert fit['deviation'] < 1e-10
    with pytest.raises(ValueError): trend_fit(f, f, 30000, 40000)


def test_stage5_delay_and_wrap_lines():
    f = np.arange(20., 20001., 10.)
    p = np.exp(-2j*np.pi*f*.004+1.7j)
    delay = get_min_phase_delay(p, f, 343.)/343.*1000
    assert delay == pytest.approx(4., abs=1e-9)
    phase = phase_values(f, p, 'Total phase', True, 0)
    assert np.isfinite(phase).all() and np.max(np.abs(np.diff(phase))) > 180
    x, y = phase_trace(f, phase, True)
    jumps = abs(np.diff(y)) > 180
    assert np.any(jumps)
    np.testing.assert_array_equal(np.diff(x)[jumps], 0)
    np.testing.assert_allclose(phase_values(f, p, 'Total phase', True, delay), np.degrees(1.7), atol=1e-8)


def test_cursor_zoom_and_full_view_return():
    full = (20., 20000.); anchor = 3000.
    limits = zoom_interval(full, full, anchor, 3, True)
    old_fraction = (np.log(anchor)-np.log(full[0]))/np.log(full[1]/full[0])
    fraction = (np.log(anchor)-np.log(limits[0]))/np.log(limits[1]/limits[0])
    assert fraction == pytest.approx(old_fraction)
    for _ in range(3): limits = zoom_interval(limits, full, anchor, -1, True)
    np.testing.assert_allclose(limits, full)


def test_contour_range():
    np.testing.assert_array_equal(contour_levels(-15, -6, 3), [-6, -9, -12, -15])
    with pytest.raises(ValueError): contour_levels(-96, -1, .5)
    with pytest.raises(ValueError): contour_levels(-6, -15, 3)


def test_vertical_zoom_out_exceeds_reset_bounds_and_preserves_cursor():
    full = (54., 94.)
    anchor = 84.
    limits = full
    for _ in range(4):
        limits = zoom_interval(limits, full, anchor, -1, unbounded=True)
    assert limits[1]-limits[0] == pytest.approx(40*1.25**4)
    assert limits[0] < full[0] and limits[1] > full[1]
    assert (anchor-limits[0])/(limits[1]-limits[0]) == pytest.approx(.75)
    for _ in range(4):
        limits = zoom_interval(limits, full, anchor, 1, unbounded=True)
    np.testing.assert_allclose(limits, full)
    # Panning above the reset range must not cause a snap back on zoom.
    np.testing.assert_allclose(
        zoom_interval((100., 140.), full, 120., -1, unbounded=True), (95., 145.))


def test_beam_tunnel_matches_hv_and_includes_diagonal_data():
    import acoustics as ac
    from plots import beam_tunnel_mesh
    s = ac.demo()
    xyz = ac.directions(s.elevation, s.azimuth)
    distance = np.sum((xyz-np.array([np.sqrt(.5), .5, .5]))**2, axis=-1)
    s.pressure[:] = 1+10*np.exp(-distance/.02)
    levels = s.levels()
    grid = beam_tunnel_mesh(s, levels)
    field = grid['Relative level / dB'].reshape(grid.dimensions, order='F')
    # Demo angular pitch is 5 degrees; gamma=0 is H, gamma=90 is V.
    step = min(np.diff(s.elevation)[0], np.diff(s.azimuth)[0])
    off_axis = np.linspace(0, 90, grid.dimensions[1])
    gamma90 = (grid.dimensions[2]-1)//4
    for n, angle in enumerate(off_axis):
        np.testing.assert_allclose(field[:, n, 0], levels[:, *s.index(angle, 0)], atol=1e-8)
        np.testing.assert_allclose(field[:, n, gamma90], levels[:, *s.index(0, angle)], atol=1e-8)
    alpha45 = int(np.argmin(abs(off_axis-45)))
    gamma45 = (grid.dimensions[2]-1)//8
    assert field[0, alpha45, gamma45] > max(field[0, alpha45, 0], field[0, alpha45, gamma90])+10
