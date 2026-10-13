"""Matplotlib-only annotations shared by embedded and standalone process views."""
import numpy as np
from matplotlib.artist import Artist


class StackedWindowLabels(Artist):
    """Keep three staggered rows near the bottom, moving them away from traces."""

    def __init__(self, ax, labels):
        super().__init__()
        self.labels = labels
        self.set_zorder(19)  # Position labels immediately before their own draw.
        ax.add_artist(self)

    def draw(self, renderer):
        ax = self.axes
        lo, hi = sorted(ax.get_xlim())
        visible = []
        for index, label in enumerate(self.labels):
            show = lo <= label.get_position()[0] <= hi
            label.set_visible(show)
            if show:
                visible.append((index, label))
        paths = [line.get_transform().transform_path(line.get_path()).cleaned(simplify=True)
                 for line in ax.lines
                 if line.get_visible() and len(line.get_xdata()) > 2]
        # Size the rows in screen space so text stays separated when resized.
        height = max((label.get_window_extent(renderer).height
                      for _, label in visible), default=20) + 8
        step = min(.2, height / max(ax.bbox.height, 1))
        bottom = step / 2 + .02
        top = max(bottom, 1 - bottom - 2 * step)

        def position(base):
            for index, label in visible:
                label.set_y(base + (index % 3) * step)

        position(bottom)
        boxes = [label.get_window_extent(renderer).padded(4) for _, label in visible]
        best, best_score = bottom, float('inf')
        for base in np.linspace(bottom, top, 15):
            offset = (base - bottom) * ax.bbox.height
            score = sum(path.intersects_bbox(box.translated(0, offset), filled=False)
                        for box in boxes for path in paths)
            if score < best_score:
                best, best_score = base, score
            if score == 0:
                break
        position(best)
        self.stale = False
