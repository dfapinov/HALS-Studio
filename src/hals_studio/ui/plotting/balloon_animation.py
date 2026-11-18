"""Rotate the balloon in world coordinates, independently of its camera."""
import os
from pathlib import Path
import tempfile
from contextlib import closing

import numpy as np
import pyvista as pv
from PIL import Image, GifImagePlugin
from PySide6 import QtCore as C, QtWidgets as W


# Change this value to set live auto-rotation speed (degrees per second).
BALLOON_ROTATION_DEGREES_PER_SECOND = 20.0


def rotate_point(point, angle):
    radians = np.deg2rad(angle)
    x, y, z = point
    return np.array((x*np.cos(radians)-y*np.sin(radians),
                     x*np.sin(radians)+y*np.cos(radians), z))


def apply_rotation(pane):
    """Keep the field, reference grid and probe in the same coordinate system."""
    angle = pane.balloon_animation.angle
    for name in ('field', 'reference', 'probe'):
        actor = pane.plotter.renderer.actors.get(name)
        if actor is not None:
            actor.SetOrientation(0, 0, angle)
    if pane.handle is not None:
        from hals_studio.analysis.acoustics import directions
        point = directions([pane.owner.elevation.value()],
                           [pane.owner.azimuth.value()])[0, 0]*1.06
        pane.handle.SetCenter(rotate_point(point, angle))


class BalloonAnimation(C.QObject):
    def __init__(self, pane):
        super().__init__(pane)
        self.pane = pane
        self.angle = 0.0
        self.elapsed = C.QElapsedTimer()
        self.timer = C.QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self.tick)

    def set_running(self, running):
        self.pane.rotate_button.setText('Stop rotation' if running else 'Rotate')
        if running:
            self.elapsed.start()
            self.timer.start()
        else:
            self.timer.stop()

    def tick(self):
        seconds = self.elapsed.restart()/1000
        pane = self.pane
        if (pane.config['kind'] != 'balloon' or pane.owner.sphere is None
                or not pane.isVisible() or pane.plotter is None):
            return
        self.angle = (self.angle + BALLOON_ROTATION_DEGREES_PER_SECOND*seconds) % 360
        apply_rotation(pane)
        pane.plotter.render()


def gif_timing(fps, seconds):
    """GIF delays use centiseconds; distribute rounding to preserve turn duration."""
    count = max(2, round(fps*seconds))
    boundaries = np.rint(np.arange(count+1)*100*seconds/count).astype(int)
    return np.arange(count)*360/count, (np.diff(boundaries)*10).tolist()


def gif_palette(samples):
    """Fit a stable palette to colours visible throughout the entire turn."""
    with Image.new('RGB', (192, 192*len(samples))) as atlas:
        for index, sample in enumerate(samples):
            with sample.resize((192, 192), Image.Resampling.LANCZOS) as thumbnail:
                atlas.paste(thumbnail, (0, 192*index))
        return atlas.quantize(colors=256, method=Image.Quantize.MEDIANCUT, kmeans=1)


def export_frames(pane, path, fps, width, height, seconds, progress):
    """Snapshot the scene and render one turn without changing the live camera."""
    angles, durations = gif_timing(fps, seconds)
    source = pane.plotter
    output = None
    stream = None
    palette = None
    try:
        with closing(pv.Plotter(off_screen=True, window_size=(width, height))) as plotter:
            plotter.render_window.SetMultiSamples(0)
            plotter.set_background(source.renderer.GetBackground(),
                                   top=source.renderer.GetBackground2())
            plotter.renderer.SetGradientBackground(source.renderer.GetGradientBackground())
            plotter.remove_all_lights()
            for light in source.renderer.lights:
                plotter.add_light(light.copy())
            actors = []
            for name in ('field', 'reference', 'probe'):
                actor = source.renderer.actors.get(name)
                if actor is not None:
                    clone = actor.copy(deep=True)
                    plotter.add_actor(clone, reset_camera=False, name=name)
                    actors.append((clone, actor.GetOrientation()[2]))
            field = plotter.renderer.actors['field']
            scalar = field.mapper.array_name
            plotter.add_scalar_bar(title=scalar, mapper=field.mapper, color='#bed0e0',
                                   vertical=True, position_x=.88, position_y=.23,
                                   height=.5, width=.04, title_font_size=9, label_font_size=9)
            if pane.handle is not None:
                marker = plotter.add_mesh(pv.Sphere(radius=.055, center=(0, 0, 0)),
                                          color='#90ffbf', reset_camera=False)
                marker_point = np.array(pane.handle.GetCenter())
            else:
                marker = None
            plotter.add_axes()
            from hals_studio.ui.viewer_theme import colour
            plotter.add_text(pane.probe_frequency.text(), position='upper_left',
                             font_size=max(10, round(min(width, height)/40)),
                             color=colour('#eef6ff'), name='frequency')
            plotter.camera.DeepCopy(source.camera)
            plotter.show(auto_close=False, interactive=False)
            def capture(angle):
                for actor, start in actors:
                    actor.SetOrientation(0, 0, start+angle)
                if marker is not None:
                    marker.position = rotate_point(marker_point, angle)
                plotter.render()
                return Image.fromarray(plotter.screenshot(return_img=True)[:, :, :3])

            # Sample the complete turn before encoding. The first view alone
            # can miss colours on the far side and flatten later highlights.
            sample_indices = np.linspace(0, len(angles), min(16, len(angles)), endpoint=False, dtype=int)
            total = len(sample_indices)+len(angles)
            samples = []
            try:
                for index, sample_index in enumerate(sample_indices):
                    if progress(index, total) is False:
                        return False
                    with capture(angles[sample_index]) as rgb:
                        samples.append(rgb.resize((192, 192), Image.Resampling.LANCZOS))
                palette = gif_palette(samples)
            finally:
                for sample in samples:
                    sample.close()
            # Stream encoded frames to disk so large exports do not accumulate
            # hundreds of full-resolution images in memory.
            stream = tempfile.NamedTemporaryFile(dir=Path(path).parent, suffix='.gif', delete=False)
            output = stream.name
            for index, angle in enumerate(angles):
                if progress(len(sample_indices)+index, total) is False:
                    return False
                with capture(angle) as rgb:
                    # Error diffusion softens shading bands while keeping one
                    # shared palette, including at the loop boundary.
                    frame = rgb.quantize(palette=palette, dither=Image.Dither.FLOYDSTEINBERG)
                if index == 0:
                    header, _ = GifImagePlugin.getheader(frame, info={'loop': 0})
                    for block in header:
                        stream.write(block)
                for block in GifImagePlugin.getdata(frame, duration=durations[index], disposal=2):
                    stream.write(block)
                frame.close()
            if progress(total, total) is False:
                return False
            # Replace the destination only after encoding completes successfully.
            stream.write(b';')
            stream.close()
            os.replace(output, path)
            output = None
            return True
    finally:
        if stream is not None:
            stream.close()
        if palette is not None:
            palette.close()
        if output is not None:
            Path(output).unlink(missing_ok=True)


def export_gif(pane):
    if pane.plotter is None or 'field' not in pane.plotter.renderer.actors:
        return
    dialog = W.QDialog(pane)
    dialog.setWindowTitle('Export animated GIF')
    form = W.QFormLayout(dialog)
    form.addRow(W.QLabel('One 360\N{DEGREE SIGN} turn about the vertical axis, using the current camera.'))
    controls = []
    for label, minimum, maximum, value in (
        ('FPS', 1, 60, 24), ('Width (px)', 128, 1920, 720),
        ('Height (px)', 128, 1920, 720), ('Seconds per turn', 1, 30, 12),
    ):
        control = W.QSpinBox()
        control.setRange(minimum, maximum)
        control.setValue(value)
        form.addRow(label, control)
        controls.append(control)
    form.addRow(W.QLabel('GIF timing is rounded to 10 ms. Higher resolution and FPS take longer to export.'))
    buttons = W.QDialogButtonBox(W.QDialogButtonBox.Save | W.QDialogButtonBox.Cancel)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    form.addRow(buttons)
    if dialog.exec() != W.QDialog.Accepted:
        return
    path, _ = W.QFileDialog.getSaveFileName(pane, 'Export animated GIF', '', 'Animated GIF (*.gif)')
    if not path:
        return
    if not path.lower().endswith('.gif'):
        path += '.gif'
    progress = W.QProgressDialog('Rendering balloon rotation\N{HORIZONTAL ELLIPSIS}', 'Cancel', 0, 100, pane)
    progress.setWindowModality(C.Qt.ApplicationModal)
    progress.setMinimumDuration(0)
    progress.setAutoClose(False)
    progress.show()
    # Freeze the displayed frequency and orientation while the scene is captured.
    rotating = pane.rotate_button.isChecked()
    sweeping = pane.owner.play.isChecked()
    pane.balloon_animation.timer.stop()
    if sweeping:
        pane.owner.play.click()
    def update(index, count):
        progress.setValue(round(100*index/count))
        if index == count:
            progress.setLabelText('Encoding GIF\N{HORIZONTAL ELLIPSIS}')
        W.QApplication.processEvents()
        return not progress.wasCanceled()
    try:
        if export_frames(pane, path, *(control.value() for control in controls), update):
            pane.owner.statusBar().showMessage(f'Saved animated GIF: {path}', 10000)
    except Exception as exc:
        W.QMessageBox.warning(pane, 'GIF export failed', str(exc))
    finally:
        progress.close()
        if rotating:
            pane.balloon_animation.set_running(True)
        if sweeping:
            pane.owner.play.click()
