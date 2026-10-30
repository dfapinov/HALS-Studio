from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
from matplotlib.figure import Figure

from hals_studio.ui.plotting.process_renderers import draw_origin_cloud, VIEWS


def test_frequency_change_preserves_cloud_camera_but_new_results_reset(monkeypatch):
    class Cloud:
        def __init__(self, config):
            self.fig = Figure()
            self.ax = self.fig.add_subplot(projection='3d')
            self.ax.view_init(elev=30, azim=-45)

        def update_view(self, frequencies, x, y, z, index):
            self.scatter_all = self.ax.scatter(x, y, z, label='All')
            self.scatter_hi = self.ax.scatter([x[index]], [y[index]], [z[index]], label='Selected')

    monkeypatch.setitem(VIEWS, 'CloudBrowser3DView', Cloud)
    rows = {100: {'final_c': [0, 1, 2]}, 200: {'final_c': [3, 4, 5]}}
    result = [rows, None, None, None, None, {}]
    workspace = SimpleNamespace(stage=2, results={2: result}, view=Mock(), sample=Mock())
    workspace.sample.currentIndex.return_value = 0
    host = SimpleNamespace(fig=None)
    first = draw_origin_cloud(host, workspace)
    host.fig = first.fig
    first.ax.view_init(elev=12, azim=123, roll=7)
    first.ax.set(xlim=(-1, 2), ylim=(-2, 3), zlim=(-3, 4))
    workspace.sample.currentIndex.return_value = 1
    second = draw_origin_cloud(host, workspace)
    assert (second.ax.elev, second.ax.azim, second.ax.roll) == (12, 123, 7)
    assert second.ax.get_xlim3d() == (-1, 2)
    assert second.ax.get_ylim3d() == (-2, 3)
    assert second.ax.get_zlim3d() == (-3, 4)
    np.testing.assert_allclose(np.array(second.scatter_hi._offsets3d).ravel(), [3, 4, 5])
    host.fig = second.fig
    workspace.results[2] = list(result)
    third = draw_origin_cloud(host, workspace)
    assert (third.ax.elev, third.ax.azim, third.ax.roll) == (30, -45, 0)
