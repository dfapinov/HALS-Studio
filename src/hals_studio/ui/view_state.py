"""Saved analysis view defaults and migrations, without Qt dependencies."""

from copy import deepcopy
import json
from hals_studio.ui.plotting.plot_settings import default_config, TITLES


class ViewCollection:
    """Project-local named views, independent of menus and pane widgets."""

    def __init__(self, views):
        self.views = deepcopy(views)
        self.current = None

    def remember(self, snapshot):
        if self.current in self.views:
            self.views[self.current] = deepcopy(snapshot)

    def add(self, name, snapshot):
        if name in self.views:
            raise ValueError("Choose a different view name.")
        self.remember(snapshot)
        self.views[name] = deepcopy(snapshot)
        self.current = name

    def rename(self, original, name):
        if name == original:
            return
        if name in self.views:
            raise ValueError("Choose a different view name.")
        self.views[name] = self.views.pop(original)
        if self.current == original:
            self.current = name

    def remove(self, name):
        if len(self.views) <= 1:
            return self.current
        self.views.pop(name)
        # Leave the deleted name current until the UI has switched panes.
        # Remembering the outgoing pane state must not overwrite its successor.
        return next(iter(self.views)) if self.current == name else self.current

    def reorder(self, names):
        self.views = {
            name: self.views[name]
            for name in dict.fromkeys([*names, *self.views])
            if name in self.views
        }


def default_views():
    result = {}
    for name, kinds in {
        "Sound field": ["balloon", "probe", "polar", "map_h"],
        "Directivity": ["cross_sonograms", "map_h", "map_v", "di"],
        "Globes": ["globe_hv", "cross_sonograms", "polar", "probe"],
        "CEA2034": ["cea", "reflections", "cea_Sound power DI", "cea_Early reflections DI"],
    }.items():
        configs = [default_config(k) for k in kinds]
        for config in configs:
            if config["kind"] != "probe":
                config["phase_mode"] = "None"
        if name == "Sound field":
            configs[0]["pins"] = ["normalization", "span", "geometry"]
        result[name] = dict(
            version=2, panes=configs, outer=[600, 380], rows=[[700, 800], [700, 800]]
        )
    return result


def valid_view(view):
    if not isinstance(view, dict):
        return False
    panes = view.get("panes")
    return (
        isinstance(panes, list)
        and len(panes) == 4
        and all(
            isinstance(pane, dict) and pane.get("kind") in (*TITLES, "volume", "globe_h", "globe_v")
            for pane in panes
        )
    )


def restore_pane(config):
    result = dict(default_config(config["kind"]), **deepcopy(config))
    if "sweep_direction" not in config:
        result["sweep_direction"] = "+/-" if config.get("symmetric", True) else "+"
    result["pins"] = ["sweep_direction" if key == "symmetric" else key for key in result["pins"]]
    # Older templates/projects captured the former 1/12 default.
    # Migrate once; newly saved explicit smoothing choices still persist.
    if config.get("energy_smoothing_version", 0) < 1:
        result["smoothing"] = "None"
        result["energy_smoothing_version"] = 1
    if result["kind"] in ("globe_h", "globe_v"):
        result["kind"] = "globe_hv"
    if result["kind"] == "volume":
        result["kind"] = "cross_sonograms"
    if "phase_mode" not in config:
        result["phase_mode"] = (
            "Minimum phase"
            if config["kind"] == "minimum"
            else "Total phase"
            if config["kind"] in ("probe", "phase") and config.get("phase", True)
            else "None"
        )
    if result["volume_mode"] == "Coverage envelopes":
        result["volume_mode"] = "Closed contour surfaces"
    return result


def restore_view(view):
    """Validate the complete snapshot before the UI applies any of its panes."""
    if not valid_view(view):
        raise ValueError("A view must contain four recognized plot panes.")
    restored = deepcopy(view)
    restored["panes"] = [restore_pane(config) for config in view["panes"]]
    return restored


def template_views(saved):
    try:
        saved = json.loads(saved)
        if isinstance(saved, dict):
            views = {
                name: view
                for name, view in saved.items()
                if name not in ("Beam tunnel", "Beam tube") and valid_view(view)
            }
            if views:
                return views
    except (ValueError, TypeError):
        pass
    return default_views()
