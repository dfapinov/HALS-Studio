"""Azimuth/elevation navigation for the spatial error viewer."""
import matplotlib as mpl
from mpl_toolkits.mplot3d import Axes3D


class SpatialAxes3D(Axes3D):
    def _on_move(self, event):
        # Scope the rotation style to this view; other 3D plots retain theirs.
        with mpl.rc_context({'axes3d.mouserotationstyle': 'azel'}):
            return super()._on_move(event)
