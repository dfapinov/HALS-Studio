"""Waypoint overlays and straight-line editing of Stage 2 validation plots."""
import numpy as np


def waypoint_color(index):
    """Stable colours shared by reference lines and their checkbox swatches."""
    return ('#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd',
            '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf')[index % 10]


def metadata_points(grid):
    """Return captured source waypoints in Cartesian millimetres."""
    points = []
    raw = [('Tweeter', {k: grid.get('wp_tw_' + k) for k in ('r', 'phi', 'z')})]
    raw.extend((p.get('name', 'User point'), p) for p in grid.get('user_positions', []))
    for name, point in raw:
        try:
            r, phi, z = (float(point[k]) for k in ('r', 'phi', 'z'))
            xyz = np.array([r * np.cos(np.deg2rad(phi)), r * np.sin(np.deg2rad(phi)), z])
            if np.all(np.isfinite(xyz)):
                points.append((name, xyz))
        except (KeyError, TypeError, ValueError):
            continue
    return points


def line_edits(rows, axis, start, end):
    """Align sampled frequencies to a straight line on a logarithmic axis."""
    if not np.all(np.isfinite([*start, *end])) or min(start[0], end[0]) <= 0:
        return []
    if start[0] == end[0]:
        return []
    left, right = sorted((start, end))
    edits = []
    for frequency, row in sorted(rows.items()):
        if left[0] <= frequency <= right[0]:
            xyz = np.array(row['final_c'], dtype=float).copy()
            xyz[axis] = np.interp(np.log(frequency), np.log([left[0], right[0]]), [left[1], right[1]])
            edits.append((frequency, xyz.tolist()))
    return edits


class OriginPointSelection:
    """Select a sampled frequency on all three graphs and report its details."""
    def __init__(self, canvas, axes, rows, on_select=None):
        self.canvas, self.axes = canvas, list(axes)
        self.frequencies = np.array(sorted(rows))
        self.coordinates = np.array([rows[f]['final_c'] for f in self.frequencies])
        self.errors = [rows[f]['error'] for f in self.frequencies]
        self.on_select = on_select
        self.pressed = None
        self.markers = []
        self.selected_frequency = None
        canvas.mpl_connect('button_press_event', self.press)
        canvas.mpl_connect('button_release_event', self.release)

    def nearest(self, event):
        if event.inaxes not in self.axes or event.x is None or event.y is None:
            return None
        axis = self.axes.index(event.inaxes)
        xy = np.column_stack((self.frequencies, self.coordinates[:, axis]))
        pixels = event.inaxes.transData.transform(xy)
        distance = np.linalg.norm(pixels - [event.x, event.y], axis=1)
        index = int(np.argmin(distance))
        return (axis, index) if distance[index] <= 6 * self.canvas.figure.dpi / 72 else None

    def press(self, event):
        self.pressed = None
        if event.button == 1 and self.nearest(event) is not None:
            self.pressed = (event.inaxes, event.x, event.y, self.nearest(event)[1])

    def release(self, event):
        pressed, self.pressed = self.pressed, None
        if (pressed is not None and event.button == 1 and event.inaxes is pressed[0]
                and event.x is not None and event.y is not None
                and np.hypot(event.x-pressed[1], event.y-pressed[2]) < 4):
            self.select(self.frequencies[pressed[3]])

    def select(self, frequency):
        matches = np.flatnonzero(self.frequencies == frequency)
        if not len(matches):return
        index = int(matches[0])
        self.selected_frequency = frequency
        if not self.markers:
            from matplotlib.lines import Line2D
            for ax in self.axes:
                marker = Line2D([], [], marker='o', markersize=11, markeredgewidth=2,
                                markerfacecolor='none', color='#ff9900', linestyle='none', zorder=10)
                ax.add_artist(marker)
                self.markers.append(marker)
        for axis, marker in enumerate(self.markers):
            marker.set_data([frequency], [self.coordinates[index, axis]])
        xyz = ' | '.join(f'{axis}: {value:.2f} mm' for axis, value in zip('XYZ', self.coordinates[index]))
        if self.on_select:
            self.on_select(f'{frequency:g} Hz | Fit error: {self.errors[index]:.2f}% | {xyz}')
        self.canvas.draw_idle()



class OriginLineEditor:
    def __init__(self, canvas, axes, workspace):
        self.canvas, self.axes, self.workspace = canvas, list(axes), workspace
        self.start = None
        self.preview = None
        self.background = None
        self.use_blit = canvas.supports_blit
        for event, handler in [('button_press_event', self.press), ('motion_notify_event', self.move),
                               ('button_release_event', self.release), ('key_press_event', self.key),
                               ('draw_event', self.on_draw), ('resize_event', self.on_resize)]:
            canvas.mpl_connect(event, handler)

    def on_draw(self, event):
        if self.start and self.use_blit:
            ax = self.start[0]
            self.background = self.canvas.copy_from_bbox(ax.bbox)
            ax.draw_artist(self.preview)

    def on_resize(self, event):
        self.background = None

    def press(self, event):
        if (event.button != 1 or event.inaxes not in self.axes or self.workspace.job
                or not self.workspace.draw_origin_line.isChecked()):
            return
        self.start = (event.inaxes, (event.xdata, event.ydata))
        from matplotlib.lines import Line2D
        self.preview = Line2D([event.xdata]*2, [event.ydata]*2, color='#d9d9d9',
                              linewidth=2, animated=self.use_blit)
        # A transient preview must not change data limits or trigger autoscaling.
        event.inaxes.add_artist(self.preview)
        self.canvas.draw()

    def move(self, event):
        if self.start and event.inaxes is self.start[0]:
            self.preview.set_data([self.start[1][0], event.xdata], [self.start[1][1], event.ydata])
            if self.use_blit and self.background is not None:
                self.canvas.restore_region(self.background)
                self.start[0].draw_artist(self.preview)
                self.canvas.blit(self.start[0].bbox)
            else:
                self.canvas.draw_idle()

    def clear(self):
        if self.preview is not None:
            self.preview.remove()
        self.start = self.preview = None
        self.background = None
        self.canvas.draw_idle()

    def key(self, event):
        if event.key == 'escape':
            self.clear()

    def release(self, event):
        if self.start is None:
            return
        ax, start = self.start
        edits = []
        if event.button == 1 and event.inaxes is ax and not self.workspace.job:
            end = (event.xdata, event.ydata)
            if np.linalg.norm(ax.transData.transform(start)-ax.transData.transform(end)) >= 4:
                edits = line_edits(self.workspace.results[2][0], self.axes.index(ax), start, end)
        self.clear()
        if edits:
            self.workspace.run('save_origins', edits)
