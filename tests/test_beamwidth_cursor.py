"""Strongest-lobe measurement and sonogram cursor readout."""
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from hals_studio.analysis.acoustics import forward_beamwidth
from hals_studio.ui.plotting.spl_cursor import SPLCursor


def test_shifted_beam_interpolates_boundaries_and_ignores_gain():
    angles = np.arange(-180., 181., 5.)
    levels = -.17 * abs(angles - 10.)
    for gain in (0., -60., 100.):
        status, left, right = forward_beamwidth(angles, levels + gain)
        assert status == 'ok'
        assert left == pytest.approx(10 - 6/.17)
        assert right == pytest.approx(10 + 6/.17)


def test_stronger_rear_peak_does_not_replace_forward_lobe():
    angles = np.arange(-180., 181., 5.)
    distance = abs((angles-180+180) % 360-180)
    levels = np.maximum(-abs(angles)/5, 20 - distance)
    assert forward_beamwidth(angles, levels) == ('ok', -30., 30.)


def test_multiple_lobes_do_not_block_width_and_missing_crossings():
    angles = np.arange(-180., 181., 5.)
    split = -np.minimum(abs(angles-30), abs(angles+30))/3
    status, left, right = forward_beamwidth(angles, split)
    assert status == 'ok'
    assert right-left == pytest.approx(36.)
    assert abs((left+right)/2) == pytest.approx(30.)
    assert forward_beamwidth(angles, np.zeros_like(angles))[0] == '>360'
    assert forward_beamwidth(angles[abs(angles) <= 45], np.zeros(np.count_nonzero(abs(angles) <= 45)))[0] == '>90'
    assert forward_beamwidth(angles[angles >= 0], -angles[angles >= 0]/5)[0] == '>30'
    assert forward_beamwidth(angles, np.full_like(angles, np.nan))[0] == 'undefined'


def test_cursor_uses_nearest_frequency_sample_and_configured_threshold(monkeypatch):
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    import hals_studio.analysis.acoustics as acoustics

    figure = Figure()
    canvas = FigureCanvasAgg(figure)
    pane = SimpleNamespace(chart=SimpleNamespace(canvas=canvas))
    label = Mock(spec=['clear', 'hide', 'show', 'setToolTip', 'setText'])
    frequency = [1000.]
    cursor = SPLCursor(pane, label, lambda: frequency[0])
    angles = np.arange(-180., 181., 5.)
    levels = np.array([-abs(angles)/5, -abs(angles-10)/10])
    measure = Mock(wraps=acoustics.forward_beamwidth)
    monkeypatch.setattr(acoustics, 'forward_beamwidth', measure)
    cursor.bind_beamwidth(figure.add_subplot(), [1000., 2000.], angles, levels, threshold=-12.)
    np.testing.assert_array_equal(measure.call_args.args[1], levels[0])
    assert measure.call_args.args[2] == -12.
    frequency[0] = 1900.
    cursor.follow_marker()
    np.testing.assert_array_equal(measure.call_args.args[1], levels[1])
    assert cursor.frequency == 2000.
    assert label.setText.call_args.args[0]
    cursor.clear()
    label.hide.assert_called()


@pytest.mark.parametrize('threshold', [-3., -6., -12.])
def test_threshold_controls_measured_width(threshold):
    angles = np.arange(-180., 181., 5.)
    levels = -.17 * abs(angles-10.)
    status, left, right = forward_beamwidth(angles, levels, threshold)
    assert status == 'ok'
    assert right-left == pytest.approx(2*abs(threshold)/.17)


@pytest.mark.parametrize('centre', [-90., -60., 0., 60., 90.])
@pytest.mark.parametrize('closed', [False, True])
def test_rotated_peak_width_is_independent_of_angle_and_seam(centre, closed):
    angles = np.arange(-180., 181. if closed else 180., 5.)
    distance = abs((angles-centre+180) % 360-180)
    levels = -distance / 5
    status, left, right = forward_beamwidth(angles, levels)
    assert status == 'ok'
    assert right-left == pytest.approx(60.)


@pytest.mark.parametrize('centre', [-90., 90.])
@pytest.mark.parametrize('closed', [False, True])
def test_broad_forward_lobe_crossings_wrap_across_full_circle_seam(centre, closed):
    angles = np.arange(-180., 181. if closed else 180., 1.)
    levels = -3 * (1-np.cos(np.deg2rad(angles-centre)))
    status, left, right = forward_beamwidth(angles, levels, threshold=-5.)
    expected_half_width = np.rad2deg(np.arccos(1-5/3))
    assert status == 'ok'
    assert (left+right)/2 == pytest.approx(centre)
    assert right-left == pytest.approx(2*expected_half_width, abs=.01)


def test_no_forward_coverage_does_not_select_an_unrelated_lobe():
    angles = np.arange(100., 151., 5.)
    assert forward_beamwidth(angles, -abs(angles-125.))[0] == 'undefined'
