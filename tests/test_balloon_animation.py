"""Object rotation must preserve camera control and export complete, loopable turns."""
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
from PIL import Image
import pyvista as pv
import pytest

from hals_studio.ui.plotting.balloon_animation import (
    BalloonAnimation, apply_rotation, export_frames, gif_palette, gif_timing, rotate_point,
)
from hals_studio.ui.panes import PlotPane


@pytest.fixture
def scene():
    plotter = pv.Plotter(off_screen=True, window_size=(256, 192))
    mesh = pv.Cube(x_length=1.8, y_length=.7)
    mesh['Level'] = np.arange(mesh.n_points, dtype=float)
    plotter.add_mesh(mesh, name='field', scalars='Level', clim=(0, 7))
    plotter.add_mesh(pv.Line((0, 0, 0), (1.06, 0, 0)), name='probe')
    plotter.set_background('#09151f', top='#1b3040')
    plotter.camera_position = [(3, -4, 2), (0, 0, 0), (0, 0, 1)]
    plotter.show(auto_close=False, interactive=False)
    pane = SimpleNamespace(
        plotter=plotter, mesh=mesh, handle=Mock(),
        probe_frequency=SimpleNamespace(text=lambda: '180 Hz'),
        balloon_animation=SimpleNamespace(angle=45.),
        owner=SimpleNamespace(azimuth=Mock(value=lambda: 0.),
                              elevation=Mock(value=lambda: 0.), sphere=object()),
        config={'kind': 'balloon'}, isVisible=lambda: True,
    )
    pane.handle.GetCenter.return_value = rotate_point((1.06, 0, 0), 45.)
    yield pane
    plotter.close()


def test_rotation_preserves_camera_and_rotated_probe_drag(scene, monkeypatch):
    monkeypatch.setattr('hals_studio.ui.plotting.balloon_animation.BALLOON_ROTATION_DEGREES_PER_SECOND', 30.)
    camera = tuple(scene.plotter.camera_position)
    animation = SimpleNamespace(pane=scene, angle=45., elapsed=Mock(restart=lambda: 1000))
    scene.balloon_animation = animation
    BalloonAnimation.tick(animation)
    assert animation.angle == pytest.approx(75.)
    assert tuple(scene.plotter.camera_position) == camera
    # Camera changes made by the user survive subsequent animation ticks.
    scene.plotter.camera.azimuth += 19
    camera = tuple(scene.plotter.camera_position)
    BalloonAnimation.tick(animation)
    assert tuple(scene.plotter.camera_position) == camera
    assert scene.plotter.renderer.actors['field'].GetOrientation()[2] == pytest.approx(105.)
    PlotPane.drag(scene, rotate_point((1.06, 0, 0), animation.angle), scene.handle)
    assert scene.owner.azimuth.setValue.call_args.args[0] == pytest.approx(0., abs=1e-10)
    assert scene.owner.elevation.setValue.call_args.args[0] == pytest.approx(0., abs=1e-10)


@pytest.mark.parametrize('fps', [1, 24, 30, 60])
def test_seam_and_timing(fps):
    angles, durations = gif_timing(fps, 3)
    assert len(angles) == fps*3
    np.testing.assert_allclose(np.diff(np.r_[angles, 360]), 360/len(angles))
    assert sum(durations) == 3000
    assert min(durations) >= 10


def test_gif_dimensions_frames_loop_camera_and_cancellation(scene, tmp_path):
    apply_rotation(scene)
    camera = tuple(scene.plotter.camera_position)
    orientation = scene.plotter.renderer.actors['field'].GetOrientation()
    path = tmp_path/'turn.gif'
    assert export_frames(scene, path, 4, 256, 192, 1, lambda i, n: True)
    with Image.open(path) as gif:
        assert gif.size == (256, 192)
        assert gif.n_frames == 4
        assert gif.info['loop'] == 0
        frames, durations = [], []
        for index in range(gif.n_frames):
            gif.seek(index)
            frames.append(np.array(gif.convert('RGB')))
            durations.append(gif.info['duration'])
        assert sum(durations) == 1000
        assert not np.array_equal(frames[0], frames[1])
    assert tuple(scene.plotter.camera_position) == camera
    assert scene.plotter.renderer.actors['field'].GetOrientation() == orientation
    saved = path.read_bytes()
    assert not export_frames(scene, path, 4, 256, 192, 1, lambda i, n: i < 6)
    assert path.read_bytes() == saved
    assert list(tmp_path.iterdir()) == [path]


def test_export_failure_removes_partial_file(scene, tmp_path):
    path = tmp_path/'turn.gif'
    def fail(index, count):
        if index == 5:
            raise RuntimeError('capture failed')
        return True
    with pytest.raises(RuntimeError, match='capture failed'):
        export_frames(scene, path, 4, 256, 192, 1, fail)
    assert not list(tmp_path.iterdir())


def test_palette_preserves_colours_that_appear_later_in_rotation():
    ramp = np.tile(np.arange(256, dtype=np.uint8), (64, 1))
    red = np.zeros((64, 256, 3), dtype=np.uint8)
    red[:, :, 0] = ramp
    green = np.zeros_like(red)
    green[:, :, 1] = ramp
    with Image.fromarray(red) as first, Image.fromarray(green) as later:
        with first.quantize(colors=256) as old_palette, gif_palette([first, later]) as palette:
            with later.quantize(palette=old_palette) as old, later.quantize(
                palette=palette, dither=Image.Dither.FLOYDSTEINBERG,
            ) as improved:
                old_error = np.mean(abs(np.array(old.convert('RGB'), dtype=float)-green))
                new_error = np.mean(abs(np.array(improved.convert('RGB'), dtype=float)-green))
                assert new_error < old_error/10


def test_balloon_button_and_redraw_preserve_rotation_and_camera():
    import hals_studio.bootstrap as bootstrap  # Registers the application colour maps.
    from PySide6 import QtWidgets as W
    from hals_studio.analysis.acoustics import demo

    app = W.QApplication.instance() or W.QApplication([])
    sphere = demo()
    azimuth, elevation = W.QDoubleSpinBox(), W.QDoubleSpinBox()
    azimuth.setRange(-180, 180)
    elevation.setRange(-90, 90)
    frequency = W.QSlider()
    frequency.setRange(0, len(sphere.freqs)-1)
    play = W.QPushButton(); play.setCheckable(True)
    owner = SimpleNamespace(
        sphere=sphere, azimuth=azimuth, elevation=elevation, frequency=frequency,
        play=play, advance=Mock(), schedule=Mock(), overlay_revision=0, axis='X',
        get_levels=lambda _: sphere.levels(),
    )
    pane = PlotPane(owner, 0, 'balloon')
    pane.resize(800, 650)
    try:
        pane.render()
        pane.rotate_button.click()
        assert pane.balloon_animation.timer.isActive()
        pane.balloon_animation.angle = 87.
        apply_rotation(pane)
        pane.plotter.camera.azimuth += 17
        camera = tuple(pane.plotter.camera_position)
        frequency.setValue(1)
        pane.render()
        assert tuple(pane.plotter.camera_position) == camera
        assert pane.plotter.renderer.actors['field'].GetOrientation()[2] == pytest.approx(87.)
        np.testing.assert_allclose(pane.handle.GetCenter(), rotate_point((1.06, 0, 0), 87.))
        pane.rotate_button.click()
        assert not pane.balloon_animation.timer.isActive()
    finally:
        pane.balloon_animation.timer.stop()
        if pane.plotter:
            pane.plotter.close()
        pane.close()
        pane.deleteLater()
        app.processEvents()
