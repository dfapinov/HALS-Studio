"""Shared automatic legend placement for response plots with optional extra axes."""
from matplotlib.legend import Legend
from matplotlib.transforms import Bbox


class TraceLegend(Legend):
    """Include phase/DI traces in Matplotlib's draw-time overlap calculation."""

    def __init__(self, ax, handles, labels, extra_axes=(), **kwargs):
        self.extra_axes = tuple(extra_axes)
        super().__init__(ax, handles, labels, loc='best', **kwargs)

    def _auto_legend_data(self, renderer):
        # Matplotlib's default only considers artists on the legend's own axis.
        bboxes, lines, offsets = super()._auto_legend_data(renderer)
        for ax in self.extra_axes:
            if not ax.get_visible(): continue
            lines.extend(line.get_transform().transform_path(line.get_path())
                         for line in ax.lines if line.get_visible())
            bboxes.extend(text.get_window_extent(renderer)
                          for text in ax.texts if text.get_visible())
        return bboxes, lines, offsets

    def _find_best_position(self, width, height, renderer):
        # Fit information has priority over trace avoidance. Counting a text box
        # as one collision otherwise lets a dense trace push the legend over it.
        notes = []
        for ax in (self.axes, *self.extra_axes):
            for text in ax.texts:
                if not text.get_visible() or not text.get_text(): continue
                text.update_bbox_position_size(renderer)
                patch = text.get_bbox_patch()
                notes.append(patch.get_window_extent(renderer) if patch is not None
                             else text.get_window_extent(renderer))
        bboxes, lines, offsets = self._auto_legend_data(renderer)
        size = Bbox.from_bounds(0, 0, width, height)
        candidates = []
        for index in range(1, len(self.codes)):
            x, y = self._get_anchored_bbox(index, size, self.get_bbox_to_anchor(), renderer)
            box = Bbox.from_bounds(x, y, width, height)
            overlap = sum((intersection.width * intersection.height)
                          for note in notes
                          if (intersection := Bbox.intersection(box, note)) is not None)
            badness = (sum(box.count_contains(line.vertices) +
                           line.intersects_bbox(box, filled=False) for line in lines)
                       + box.count_contains(offsets) + box.count_overlaps(bboxes))
            candidates.append((overlap, badness, index, (x, y)))
        return min(candidates)[-1]


def trace_legend(ax, extra_axes=()):
    """Build one combined legend, avoiding traces and fit annotations on redraw."""
    extra_axes = tuple(other for other in extra_axes if other is not ax)
    handles, labels = ax.get_legend_handles_labels()
    for other in extra_axes:
        extra_handles, extra_labels = other.get_legend_handles_labels()
        handles.extend(extra_handles)
        labels.extend(extra_labels)
    if not handles: return None
    legend = TraceLegend(ax, handles, labels, extra_axes, fontsize=7,
                         ncol=2 if len(handles) > 5 else 1)
    ax.legend_ = legend
    legend._remove_method = ax._remove_legend
    return legend
