"""Cursor-centred zoom and an independently resizable phase axis."""
import numpy as np
from PySide6 import QtCore as C


def zoom_interval(current, full, anchor, step, logarithmic=False, unbounded=False):
    transform = np.log if logarithmic else np.asarray
    inverse = np.exp if logarithmic else np.asarray
    a, b = transform(current); lo, hi = transform(full)
    # Vertical axes zoom freely around the cursor, including beyond reset bounds.
    if unbounded:
        if b <= a: return current
        pivot = float(np.log(anchor) if logarithmic else anchor)
        factor = 1.25**np.clip(step, -10, 10)
        return tuple(inverse([pivot+(a-pivot)/factor, pivot+(b-pivot)/factor]))
    if hi <= lo or b <= a: return current
    if step > 0:
        pivot = float(np.log(anchor) if logarithmic else anchor)
        factor = 1.25**min(step, 10)
        left, right = pivot+(a-pivot)/factor, pivot+(b-pivot)/factor
    else:
        width = min(hi-lo, (b-a)*1.25**min(-step, 10))
        fraction = (width-(b-a))/max(hi-lo-(b-a), 1e-12)
        fraction = np.clip(fraction, 0, 1)
        if width >= (hi-lo)*(1-1e-8): return tuple(inverse([lo, hi]))
        left, right = a+fraction*(lo-a), b+fraction*(hi-b)
    return tuple(inverse([max(lo, left), min(hi, right)]))


class PlotInteraction(C.QObject):
    def __init__(self, pane):
        super().__init__(pane)
        self.pane = pane; self.axes = []; self.full = {}; self.saved = {}; self.signature = None
        self.phase_ax = self.main_ax = None; self.dragging = False; self.positioning = False
        self.pan = None
        self.globe_drag = None
        canvas = pane.chart.canvas
        canvas.mpl_connect('scroll_event', self.wheel)
        canvas.mpl_connect('button_press_event', self.press)
        canvas.mpl_connect('motion_notify_event', self.move)
        canvas.mpl_connect('button_release_event', self.release)
        canvas.mpl_connect('draw_event', self.layout_phase)

    def begin(self, signature):
        if signature != self.signature:
            self.saved = {}; self.signature = signature
        self.phase_ax = self.main_ax = None; self.axes = []; self.full = {}

    def finish(self, axes, phase_ax=None):
        self.axes = list(axes); self.main_ax = self.axes[0] if self.axes else None
        self.phase_ax = phase_ax
        for i, ax in enumerate(self.axes):
            self.full[i] = (ax.get_xlim(), ax.get_ylim())
            if i in self.saved:
                x, y = self.saved[i]
                ax.set_xlim(x); ax.set_ylim(y)
        if phase_ax:
            self.layout_phase()

    def layout_phase(self, *_):
        if self.positioning or self.phase_ax is None or self.main_ax is None: return
        self.positioning = True
        rect = self.main_ax.get_position()
        target = [rect.x0, rect.y0, rect.width, rect.height*self.pane.config['phase_height']]
        changed = not np.allclose(self.phase_ax.get_position().bounds, target, atol=1e-6)
        self.phase_ax.set_position(target)
        self.positioning = False
        if changed: C.QTimer.singleShot(0, self.pane.chart.canvas.draw_idle)

    def on_handle(self, event):
        if self.phase_ax is None or event.x is None or event.y is None: return False
        box = self.phase_ax.bbox; scale = self.pane.chart.fig.dpi/72
        return abs(event.y-(box.y1+7*scale)) < 8*scale and box.x1 < event.x < box.x1+38*scale

    def press(self, event):
        ax = self.main_ax
        if event.button == 1 and self.pane.config.get('kind', '').startswith('globe_') and ax is not None and event.x is not None and event.y is not None:
            for ax in self.axes:
                center = ax.transAxes.transform((.5, .5))
                dx, dy = event.x-center[0], event.y-center[1]
                radius = min(ax.bbox.width, ax.bbox.height)/2
                if abs(np.hypot(dx, dy)-radius) <= max(16., radius*.09):
                    self.globe_drag = (ax, center, np.arctan2(dy, dx), self.pane.config.get('globe_rotation', 0.))
                    self.pane.chart.fig.set_layout_engine('none')
                    self.pane.chart.canvas.setCursor(C.Qt.ClosedHandCursor)
                    return
        if event.button == 2 and event.inaxes in self.axes:
            ax = self.main_ax if event.inaxes is self.phase_ax else event.inaxes
            if ax.name != 'polar':
                self.pan = (ax, event.x, event.y, ax.get_xlim(), ax.get_ylim())
                self.pane.chart.fig.set_layout_engine('none')
                self.pane.chart.canvas.setCursor(C.Qt.ClosedHandCursor)
            return
        if event.button == 1 and self.on_handle(event):
            self.dragging = True
            self.drag_offset = event.y-self.phase_ax.bbox.y1

    def move(self, event):
        if self.globe_drag and event.x is not None and event.y is not None:
            ax, center, previous, rotation = self.globe_drag
            angle = np.arctan2(event.y-center[1], event.x-center[0])
            rotation += np.degrees(np.arctan2(np.sin(angle-previous), np.cos(angle-previous)))
            self.globe_drag = (ax, center, angle, rotation)
            snapped = float(10*np.round(rotation/10)) % 360
            self.pane.config['globe_rotation'] = snapped
            for axis in self.axes:
                axis.set_theta_zero_location('S', offset=snapped)
                axis.set_rlabel_position(0)
            self.pane.chart.canvas.draw_idle()
            return
        if self.pan and event.x is not None and event.y is not None:
            ax, x, y, xlim, ylim = self.pan
            full_x, _ = self.full[self.axes.index(ax)]
            def shifted(limits, fraction, logarithmic=False, full=None):
                transform, inverse = (np.log, np.exp) if logarithmic else (np.asarray, np.asarray)
                bounds = transform(limits)
                delta = -fraction*(bounds[1]-bounds[0])
                if full is not None:
                    low, high = transform(full)
                    delta = np.clip(delta, low-bounds[0], high-bounds[1])
                return inverse(bounds+delta)
            ax.set_xlim(shifted(xlim, (event.x-x)/ax.bbox.width, ax.get_xscale() == 'log', full_x))
            ax.set_ylim(shifted(ylim, (event.y-y)/ax.bbox.height))
            for j, item in enumerate(self.axes): self.saved[j] = (item.get_xlim(), item.get_ylim())
            self.pane.chart.canvas.draw_idle(); return
        if self.dragging and event.y is not None:
            rect = self.main_ax.bbox
            self.pane.config['phase_height'] = float(np.clip((event.y-self.drag_offset-rect.y0)/rect.height, .15, 1.))
            self.layout_phase(); self.pane.chart.canvas.draw_idle()
        elif self.on_handle(event): self.pane.chart.canvas.setCursor(C.Qt.SizeVerCursor)
        else: self.pane.chart.canvas.unsetCursor()

    def release(self, event):
        if self.globe_drag:
            self.globe_drag = None; self.pane.last_render = None
            self.pane.chart.canvas.unsetCursor()
        if self.pan:
            self.pan = None; self.pane.chart.canvas.unsetCursor()
        if self.dragging:
            self.dragging = False
            self.pane.last_render = None

    def wheel(self, event):
        if event.x is None or event.y is None: return
        only = None; target = event.inaxes
        if target not in self.axes:
            for candidate in self.axes:
                box = candidate.bbox
                if box.x0 <= event.x <= box.x1 and box.y0-55 <= event.y < box.y0:
                    target = candidate; only = 'x'; break
                right = candidate is self.phase_ax
                if box.y0 <= event.y <= box.y1 and ((box.x1 < event.x < box.x1+65) if right else (box.x0-65 < event.x < box.x0)):
                    target = candidate; only = 'y'; break
        if target not in self.axes: return
        # Changing tick labels must not move the axes underneath the cursor.
        self.pane.chart.fig.set_layout_engine('none')
        ax = self.main_ax if target is self.phase_ax and only != 'y' else target
        i = self.axes.index(ax)
        x, y = ax.transData.inverted().transform((event.x, event.y))
        full_x, full_y = self.full[i]
        if ax.name == 'polar':
            # A polar projection has no independent Cartesian x/y limits; zoom radius.
            ax.set_ylim(0, max(.1, zoom_interval(ax.get_ylim(), full_y, y, event.step)[1]))
        else:
            if only != 'y': ax.set_xlim(zoom_interval(ax.get_xlim(), full_x, x, event.step, ax.get_xscale() == 'log'))
            if only != 'x': ax.set_ylim(zoom_interval(ax.get_ylim(), full_y, y, event.step, unbounded=True))
        for j, item in enumerate(self.axes): self.saved[j] = (item.get_xlim(), item.get_ylim())
        self.pane.chart.canvas.draw_idle()

    def reset(self):
        self.saved.clear()
        for i, ax in enumerate(self.axes):
            ax.set_xlim(self.full[i][0]); ax.set_ylim(self.full[i][1])
        self.pane.chart.canvas.draw_idle()

    def eventFilter(self, watched, event):
        if event.type() != C.QEvent.Wheel: return False
        p = self.pane.plotter
        step = event.angleDelta().y()/120
        if not step and not event.pixelDelta().isNull(): step = event.pixelDelta().y()/30
        if not step: return False
        position, focal, up = [np.asarray(a, float) for a in p.camera_position]
        full_focal, full_distance = self.pane.home_focal, self.pane.home_distance
        distance = np.linalg.norm(position-focal)
        factor = 1.25**np.clip(step, -10, 10)
        if step > 0:
            renderer = p.renderer
            renderer.SetWorldPoint(*focal, 1); renderer.WorldToDisplay(); depth = renderer.GetDisplayPoint()[2]
            width, height = p.render_window.GetSize(); point = event.position()
            renderer.SetDisplayPoint(point.x()*width/watched.width(), (watched.height()-point.y())*height/watched.height(), depth)
            renderer.DisplayToWorld(); world = np.array(renderer.GetWorldPoint()); anchor = world[:3]/world[3]
            if distance/factor < full_distance*1e-4: return True
            position, focal = anchor+(position-anchor)/factor, anchor+(focal-anchor)/factor
        else:
            if getattr(self.pane, 'free_zoom_out', False):
                p.camera_position = [focal+(position-focal)/factor, focal, up]
                p.reset_camera_clipping_range(); p.render(); event.accept(); return True
            target = min(full_distance, distance/factor)
            if distance >= full_distance*(1-1e-8): target = full_distance
            amount = np.clip((target-distance)/max(full_distance-distance, 1e-12), 0, 1)
            new_focal = focal+amount*(full_focal-focal)
            position = new_focal+(position-focal)/distance*target; focal = new_focal
        p.camera_position = [position, focal, up]; p.reset_camera_clipping_range(); p.render()
        event.accept(); return True
