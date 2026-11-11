"""Grid scan colours use evaluated residuals, excluding scan-region sentinels."""
import numpy as np
import pytest

from hals_studio.process_engine.plot_views import FrequencyBrowser3DView


def draw(view, grid):
    axis = np.arange(3, dtype=float)
    view.update_view(1016.5, grid, axis, axis, axis, [1., 1., 1.],
                     'YZ (X Depth)', 1.)


def make_view():
    return FrequencyBrowser3DView(dict(x_bounds=(0, 2), y_bounds=(0, 2),
                                       z_bounds=(0, 2)))


def test_nonfinite_points_do_not_distort_scale_or_minimum():
    view = make_view()
    grid = np.linspace(7.24, 20., 27).reshape(3, 3, 3)
    grid[1, 0, 0] = np.inf
    grid[1, 1, 0] = np.nan
    draw(view, grid)
    assert view.cbar.vmin == pytest.approx(7.24)
    assert view.cbar.vmax == pytest.approx(20.)
    assert 'Minima: 7.24%' in view.fig._suptitle.get_text()
    colors = view.ax.collections[0].get_facecolors()
    assert any(color[3] == 0 for color in colors)
    assert any(color[3] > 0 for color in colors)


@pytest.mark.parametrize('residual', [0., 7.24])
def test_constant_grid_has_nonnegative_nondegenerate_scale(residual):
    view = make_view()
    grid = np.full((3, 3, 3), residual)
    grid[0, 0, 0] = np.inf
    draw(view, grid)
    assert view.cbar.vmin >= 0
    assert view.cbar.vmax > view.cbar.vmin


def test_empty_grid_clears_scale_and_can_be_followed_by_valid_grid():
    view = make_view()
    draw(view, np.ones((3, 3, 3)))
    draw(view, np.full((3, 3, 3), np.inf))
    assert view.cbar is None
    assert not view.cbar_ax.get_visible()
    draw(view, np.full((3, 3, 3), 7.24))
    assert view.cbar_ax.get_visible()
    assert view.cbar.vmax == pytest.approx(7.24)


@pytest.mark.parametrize('minimum', [0., 2.64])
def test_prediction_landscape_caps_colours_without_changing_scores(minimum):
    view = make_view()
    axis = np.arange(3, dtype=float)
    grid = np.geomspace(2.64, 214219., 27).reshape(3, 3, 3)
    grid[0, 0, 0] = minimum
    grid[0, 0, 1] = np.inf
    view.update_view(74.8, grid, axis, axis, axis, [1., 1., 1.],
                     'XY (Z Height)', 1., metric='prediction')
    norm = view.cbar.mappable.norm
    assert norm.vmin == 0.
    assert norm.vmax == 100.
    assert float(norm(2.)) == pytest.approx(.02)
    assert float(norm(100.)) == float(norm(214219.)) == 1.
    assert grid.max() == np.inf
    assert np.max(grid[np.isfinite(grid)]) == pytest.approx(214219.)
    # Switching metrics restores the residual view's linear convention.
    draw(view, grid)
    assert float(view.cbar.mappable.norm(100.)-view.cbar.mappable.norm(10.)) < .001


@pytest.mark.parametrize('extent', [10., 30.])
def test_synthetic_physics_grid_and_all_plot_planes(extent):
    from hals_studio.process_engine import stage2_centre_origin as stage
    from hals_studio.process_engine.runtime import EngineRuntime
    from hals_studio.process_engine.she_solver_core import build_she_matrix

    # A synthetic outgoing monopole sampled on two measurement shells.
    theta, phi = np.meshgrid(np.linspace(.2, np.pi-.2, 5),
                            np.arange(8)*np.pi/4, indexing='ij')
    theta = np.tile(theta.ravel(), 2)
    phi = np.tile(phi.ravel(), 2)
    radius = np.repeat([.25, .35], 40)
    frequency = 1016.5
    k = 2*np.pi*frequency/343.
    matrix, _ = build_she_matrix((radius, theta, phi), 0, k)
    pressure = matrix[:, 0]
    cfg = dict(x_bounds=(-extent, extent), y_bounds=(-extent, extent),
               z_bounds=(-extent, extent), scan_radius_mm=10.,
               grid_res_mm=extent, use_process_pool=False, speed_of_sound=343.,
               kr_offset=0, noise_floor_start_db=-30., noise_floor_max_db=-50.,
               max_lambda=.01)
    context = ([(frequency, k, pressure)], radius, theta, phi, 0, cfg)
    x, y, z, grid = stage.generate_3d_landscape_volumetric(
        context, runtime=EngineRuntime(output=lambda _: None))
    assert grid.shape == (3, 3, 3)
    assert np.all(np.isfinite(grid))  # Including corners outside the cylinder.
    assert np.all(grid >= 0)
    assert grid[1, 1, 1] < 1e-8
    assert grid.max() > 1.
    view = FrequencyBrowser3DView(cfg)
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    canvas = FigureCanvasAgg(view.fig)
    for plane in ('YZ (X Depth)', 'XZ (Y Width)', 'XY (Z Height)'):
        view.update_view(frequency, grid, x, y, z, [0., 0., 0.], plane, 0.)
        canvas.draw()
        assert view.cbar.vmin == pytest.approx(grid.min())
        assert view.cbar.vmax == pytest.approx(grid.max())
        colors = np.asarray(view.ax.collections[0].get_facecolors())
        assert np.all(colors[:, 3] > 0)
        assert np.unique(colors[:, :3], axis=0).shape[0] > 1
