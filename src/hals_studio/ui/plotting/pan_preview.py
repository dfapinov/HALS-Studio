"""Fast data-only repainting while dragging a multi-axis plot."""


class PanPreview:
    def __init__(self, canvas, axes):
        self.canvas = canvas
        self.background = None
        self.artists = [(ax, artist, artist.get_animated())
                        for ax in axes for artist in sorted([*ax.lines, *ax.texts], key=lambda a:a.get_zorder())]
        for _, artist, _ in self.artists:
            artist.set_animated(True)
        self.connection = canvas.mpl_connect('draw_event', self.on_draw)
        self.canvas.draw()

    def on_draw(self, event):
        self.background = self.canvas.copy_from_bbox(self.canvas.figure.bbox)
        self.draw_artists()

    def draw_artists(self):
        for ax, artist, _ in self.artists:
            if artist.get_visible():
                ax.draw_artist(artist)

    def paint(self):
        if self.background is None:
            self.canvas.draw_idle()
            return
        self.canvas.restore_region(self.background)
        self.draw_artists()
        self.canvas.blit(self.canvas.figure.bbox)

    def finish(self):
        self.canvas.mpl_disconnect(self.connection)
        for _, artist, animated in self.artists:
            artist.set_animated(animated)
        self.background = None
        self.canvas.draw_idle()
