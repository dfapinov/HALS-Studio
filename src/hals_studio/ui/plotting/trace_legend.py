"""Automatic response legends that avoid visible SPL/phase/DI traces and notes."""
import numpy as np
from matplotlib.legend import Legend
from matplotlib.transforms import Bbox


class TraceLegend(Legend):
    """Find empty space using both axes, independent of trace sampling density."""

    def __init__(self, ax, handles, labels, extra_axes=(), **kwargs):
        self._draw_positions = None
        self._previous_positions = {}
        self._previous_geometry = None
        self._reuse_next_draw = False
        self.extra_axes = tuple(extra_axes)
        super().__init__(ax, handles, labels, loc='best', **kwargs)

    def draw(self, renderer):
        # Reuse placement for one frame while the traces continue redrawing.
        # Geometry changes invalidate it immediately (including export DPI).
        geometry = self._geometry()
        reuse = self._reuse_next_draw and geometry == self._previous_geometry
        self._draw_positions = dict(self._previous_positions) if reuse else {}
        try:
            super().draw(renderer)
            self._previous_positions = self._draw_positions
            self._previous_geometry = geometry
            self._reuse_next_draw = not reuse
        finally:
            self._draw_positions = None

    def _geometry(self):
        return (self.figure.dpi, tuple(self.figure.bbox.bounds),
                tuple(self.get_bbox_to_anchor().bounds),
                *((ax.get_visible(), tuple(ax.bbox.bounds))
                  for ax in (self.axes, *self.extra_axes)))

    def _obstacles(self, renderer):
        notes, traces = [], []
        for ax in (self.axes, *self.extra_axes):
            if not ax.get_visible():
                continue
            texts = list(ax.texts)
            # Protect the scale when using space outside the main axes.
            for axis in (ax.xaxis, ax.yaxis):
                if axis.get_visible():
                    texts.extend(axis.get_ticklabels())
                    texts.extend([axis.label, axis.get_offset_text()])
            for text in texts:
                if not text.get_visible() or not text.get_text():
                    continue
                text.update_bbox_position_size(renderer)
                patch = text.get_bbox_patch()
                notes.append(patch.get_window_extent(renderer) if patch is not None
                             else text.get_window_extent(renderer))
            for line in ax.lines:
                if (not line.get_visible() or line.get_alpha() == 0
                        or line.get_gid() == 'frequency-cursor'):
                    continue
                path = line.get_transform().transform_path(line.get_path())
                # Use a coarse three-pixel approximation for collision checks.
                # The plotted data and the two-pixel safety margin are unchanged.
                path.simplify_threshold = 3.0
                path = path.cleaned(simplify=True)
                clip = line.get_clip_box() if line.get_clip_on() else None
                padding = renderer.points_to_pixels(line.get_linewidth()) / 2 + 2
                traces.append((path, clip, padding))
        return notes, traces

    def _positions(self, width, height, renderer, notes):
        anchor = self.get_bbox_to_anchor()
        pad = renderer.points_to_pixels(self._fontsize * self.borderaxespad)
        left, bottom = anchor.x0 + pad, anchor.y0 + pad
        right, top = anchor.x1 - width - pad, anchor.y1 - height - pad
        if any(ax.get_visible() and ax.bbox.height < self.axes.bbox.height - 1
               for ax in self.extra_axes):
            # Space above the shortened DI/phase scale is available. Remain
            # inside the canvas and check its tick labels/annotations as well.
            right = max(right, min(self.figure.bbox.x1 - width - pad,
                                   anchor.x1 - width / 2))
        right, top = max(left, right), max(bottom, top)
        ys = np.linspace(bottom, top, 6)
        # Keep the four corners. Offset the four interior rows by half a
        # column so the fixed 36 samples can find gaps between grid columns.
        # The frequency axis may be logarithmic, but these are screen pixels.
        step = (right - left) / 5
        corners = list(dict.fromkeys(((right, top), (left, top),
                                     (right, bottom), (left, bottom))))
        yield from corners
        for row, y in enumerate(reversed(ys)):
            xs = (np.linspace(left, right, 6) if row in (0, 5) else
                  [left, *(left + (i + .5) * step for i in range(1, 5)), right])
            # When there is no clear corner, equal scores favour the left gap.
            for x in xs:
                if (x, y) not in corners:
                    yield x, y

    def _find_best_position(self, width, height, renderer):
        key = (width, height)
        if self._draw_positions is not None and key in self._draw_positions:
            return self._draw_positions[key]
        result = self._search_position(width, height, renderer)
        if self._draw_positions is not None:
            self._draw_positions[key] = result
        return result

    @staticmethod
    def _trace_hits(box, traces):
        for path, clip, padding in traces:
            hitbox = box.padded(padding)
            if clip is not None:
                hitbox = Bbox.intersection(hitbox, clip)
            if hitbox is not None:
                yield path.intersects_bbox(hitbox, filled=False)

    def _has_clearance(self, box, margin, notes, traces):
        expanded = box.padded(margin)
        return (not any(expanded.overlaps(note) for note in notes)
                and not any(self._trace_hits(expanded, traces)))

    def _clearance(self, box, notes, traces, renderer):
        # Five bisections distinguish gaps to about three screen pixels,
        # avoiding the broad score ties that favoured positions near traces.
        low, high = 0., 96.
        for _ in range(5):
            middle = (low + high) / 2
            if self._has_clearance(box, middle, notes, traces):
                low = middle
            else:
                high = middle
        return low

    def _intrusion(self, box, traces):
        """Count how deeply traces enter a legend when overlap is unavoidable."""
        edge = min(box.width, box.height)
        # The same transformed paths serve both checks. This does not add
        # candidate positions or alter the displayed response curves.
        return tuple(sum(self._trace_hits(box.padded(-edge * fraction), traces))
                     for fraction in (.4, .25, .1))

    def _search_position(self, width, height, renderer):
        notes, traces = self._obstacles(renderer)
        positions = np.asarray(list(self._positions(width, height, renderer, notes)))
        previous = self._previous_positions.get((width, height))
        same_geometry = self._geometry() == self._previous_geometry
        # Corners outrank the stay-put margin. Retain the current corner if it
        # remains clear so switching between clear corners does not flicker.
        clear_corners = []
        for x, y in positions[:4]:
            corner = Bbox.from_bounds(x, y, width, height)
            if self._has_clearance(corner, 0., notes, traces):
                clear_corners.append((x, y))
        if clear_corners:
            if same_geometry and previous in clear_corners:
                return previous
            return clear_corners[0]
        if previous is not None and same_geometry:
            box = Bbox.from_bounds(*previous, width, height)
            if self._has_clearance(box, 12., notes, traces):
                return previous
        overlaps = np.zeros(len(positions))
        # Calculate note overlap in one batch instead of constructing thousands
        # of Bbox intersections in the inner candidate loop.
        for note in notes:
            widths = np.maximum(0, np.minimum(positions[:, 0] + width, note.x1)
                                - np.maximum(positions[:, 0], note.x0))
            heights = np.maximum(0, np.minimum(positions[:, 1] + height, note.y1)
                                 - np.maximum(positions[:, 1], note.y0))
            overlaps += widths * heights
        best = None
        # Notes have priority. Within equal overlap, preserve corner-first then left-first order.
        for index in np.argsort(overlaps, kind='stable'):
            overlap = overlaps[index]
            if best is not None and overlap > best[0]:
                break
            x, y = positions[index]
            box = Bbox.from_bounds(x, y, width, height)
            collisions = 0
            for hit in self._trace_hits(box, traces):
                collisions += hit
                if best is not None and collisions > best[1]:
                    break
            if best is not None and (overlap, collisions) > best[:2]:
                continue
            intrusion = self._intrusion(box, traces) if collisions else (0, 0, 0)
            clearance = self._clearance(box, notes, traces, renderer) if collisions == 0 else 0
            candidate = (overlap, collisions, *intrusion, -clearance,
                         int(index), (x, y))
            if best is None or candidate[:-1] < best[:-1]:
                best = candidate
        return best[-1]


def trace_legend(ax, extra_axes=()):
    """Build one combined legend, avoiding traces and fit annotations on redraw."""
    extra_axes = tuple(other for other in extra_axes if other is not ax)
    handles, labels = ax.get_legend_handles_labels()
    for other in extra_axes:
        extra_handles, extra_labels = other.get_legend_handles_labels()
        handles.extend(extra_handles)
        labels.extend(extra_labels)
    if not handles:
        return None
    legend = TraceLegend(ax, handles, labels, extra_axes, fontsize=7,
                         ncol=2 if len(handles) > 5 else 1)
    # Placement already stays inside the canvas. Reserving layout space for it
    # would shrink the axes on each redraw when it uses the DI/phase margin.
    legend.set_in_layout(False)
    ax.legend_ = legend
    legend._remove_method = ax._remove_legend
    return legend
