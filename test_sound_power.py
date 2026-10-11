import bootstrap
import numpy as np
import pytest
from sound_power import degree_power, sound_power_figure


def test_degree_power_uses_outgoing_modes_and_frequency_dependent_order():
    # Huge external coefficients and unused padding must not affect power.
    coeffs = np.full((3, 18), 1e6, dtype=complex)
    coeffs[0, :8:2] = [1, 2j, 3, 4]
    coeffs[1, :2:2] = [2]
    power = degree_power([100, 200, 0], coeffs, [1, 0, 0], 315)
    k = 2*np.pi*100/315
    np.testing.assert_allclose(power[0], np.array([1, 29])/k**2)
    np.testing.assert_allclose(power[1], [1/k**2, 0])
    assert np.isnan(power[2]).all()


def test_power_matches_integrated_far_field():
    from scipy.special import sph_harm_y
    nodes, weights = np.polynomial.legendre.leggauss(12)
    theta = np.arccos(nodes)[:, None]
    phi = np.linspace(0, 2*np.pi, 32, endpoint=False)[None, :]
    rng = np.random.default_rng(42)
    outgoing = rng.normal(size=16) + 1j*rng.normal(size=16)
    coeffs = np.zeros((1, 32), complex); coeffs[0, ::2] = outgoing
    field = np.zeros((12, 32), complex)
    for n in range(4):
        for m in range(-n, n+1):
            field += outgoing[n*n+n+m] * (1j)**(n+1) * sph_harm_y(n, m, theta, phi)
    integrated = np.sum(abs(field)**2 * weights[:, None]) * 2*np.pi/32
    k = 2*np.pi*1000/343
    np.testing.assert_allclose(degree_power([1000], coeffs, [3]).sum(), integrated/k**2)


def test_saved_stage4_plot(tmp_path):
    import h5py
    path = tmp_path/'coefficients.h5'
    with h5py.File(path, 'w') as source:
        source['freqs'] = [100., 200., 1000.]
        source['N_used'] = [0, 1, 1]
        source['coeffs'] = np.ones((3, 8), complex)
        source['speed_of_sound_mps'] = 315.
    fig = sound_power_figure(path)
    ax = fig.axes[0]
    assert ax.get_xscale() == 'log'
    assert [line.get_label() for line in ax.lines] == ['Total sound power', 'N=0', 'N=1']
    assert np.isnan(ax.lines[2].get_ydata()[0])
    degree_sum = sum(np.nan_to_num(10**(line.get_ydata()/10)) for line in ax.lines[1:])
    np.testing.assert_allclose(10**(ax.lines[0].get_ydata()/10), degree_sum)


@pytest.mark.parametrize('field, offset', [('Internal field', 0), ('External field', 1)])
def test_field_selection_and_degree_totals(field, offset):
    # Exclude the other field and unused padding, even when they contain NaNs.
    coeffs = np.full((2, 18), np.nan, complex)
    coeffs[0, offset:8:2] = [1, 2j, 3, 4]
    coeffs[1, offset] = 2
    power = degree_power([100, 200], coeffs, [1, 0], 315., field=field)
    k = 2*np.pi*100/315
    np.testing.assert_allclose(power[0], np.array([1, 29])/k**2)
    np.testing.assert_allclose(power[1], [1/k**2, 0])


def test_field_ratio_matches_stage3_coefficient_ratio():
    import bootstrap
    from process_engine.stage3_optimize_she_settings import calc_internal_external_ratio
    rng = np.random.default_rng(25)
    coeffs = rng.normal(size=(2, 32)) + 1j*rng.normal(size=(2, 32))
    internal = degree_power([100, 1000], coeffs, [3, 3], field='Internal field').sum(axis=1)
    external = degree_power([100, 1000], coeffs, [3, 3], field='External field').sum(axis=1)
    np.testing.assert_allclose(10*np.log10(internal/external),
                               [calc_internal_external_ratio(row) for row in coeffs])


def test_legend_checkboxes_toggle_isolate_and_preserve_selection():
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.backend_bases import MouseEvent
    from sound_power import PowerLegend
    def plot(hidden):
        fig = Figure(figsize=(12, 7));FigureCanvasAgg(fig)
        ax = fig.subplots()
        ax.plot([100, 1000], [10, 20], label='Total sound power')
        for n in range(13): ax.plot([100, 1000], [n, n+1], label=f'N={n}')
        ax.legend(ncol=4)
        control = PowerLegend(fig, hidden);fig.canvas.draw()
        return fig, ax, control
    hidden = set()
    fig, ax, control = plot(hidden)
    total = ax.lines[0].get_ydata().copy()
    def click(index, key=None):
        box = control.legend.texts[index].get_window_extent(fig.canvas.get_renderer())
        event = MouseEvent('button_press_event', fig.canvas, (box.x0+box.x1)/2,
                           (box.y0+box.y1)/2, button=1, key=key)
        fig.canvas.callbacks.process('button_press_event', event)
    for degree in (10, 11, 12): click(degree+1)
    assert hidden == {11, 12, 13}
    assert all(not ax.lines[i].get_visible() for i in hidden)
    assert control.legend.texts[11].get_text() == 'N=10'
    assert control.boxes[11].get_facecolor()[-1] == 0
    assert control.boxes[7].get_facecolor()[-1] == 1
    click(7, 'shift')
    assert [i for i, line in enumerate(ax.lines) if line.get_visible()] == [7]
    click(0)
    np.testing.assert_array_equal(ax.lines[0].get_ydata(), total)
    assert ax.lines[0].get_visible()
    # Rebuilding the plot for a field change retains the same selection.
    _, rebuilt, _ = plot(hidden)
    assert [i for i, line in enumerate(rebuilt.lines) if line.get_visible()] == [0, 7]
