"""Analysis content renderers; pane caching and navigation remain in the host."""

import numpy as np
from hals_studio.ui.plotting.plots import draw_zoomable_polars


def _ensure_decay_view(pane):
    from hals_studio.ui.plotting.csd_plot import CSDView

    if not hasattr(pane, "csd_view"):
        pane.csd_view = CSDView()
        pane.stack.addWidget(pane.csd_view)


def _unavailable(pane, error, note):
    pane.stack.setCurrentWidget(pane.chart_frame)
    pane.chart.fig.clear()
    axis = pane.chart.fig.add_subplot()
    axis.set_axis_off()
    axis.text(0.5, 0.5, str(error), ha="center", va="center", wrap=True)
    pane.chart.done()
    pane.note.setText(note)


def render_scene(pane, s, rel, i):
    kind = pane.config["kind"]
    previous = getattr(pane, "_scene_kind", None)
    pane.ensure_3d()
    if previous != kind:
        pane.plotter.clear_sphere_widgets()
        pane.handle = None
        pane.plotter.clear()
        pane.set_lighting()
    if kind == "balloon":
        pane.probe_frequency.setText(f"{s.freqs[i]:,.0f} Hz")
        pane.probe_controls.adjustSize()
        pane.probe_controls.move(
            4, max(4, pane.plotter.interactor.height() - pane.probe_controls.height() - 6)
        )
        pane.probe_controls.show()
        pane.probe_controls.raise_()
        pane.frequency_controls.adjustSize()
        pane.frequency_controls.show()
        pane.frequency_controls.raise_()
        pane.balloon(s, rel, i)
    else:
        from hals_studio.ui.plotting.directivity_views import draw_cross_sonograms

        draw_cross_sonograms(pane, s, rel)
    if previous != kind:
        pane.camera()
    from hals_studio.ui.viewer_theme import scene_theme

    scene_theme(pane.plotter)
    pane._scene_kind = kind


def _directivity_surface(pane, s, levels, rel, i):
    c = pane.config
    kind = c["kind"]
    _ensure_decay_view(pane)
    angles, h, v = s.cuts(rel)
    data = h if kind == "map_h" else v
    pane.stack.setCurrentWidget(pane.csd_view)
    pane.csd_view.render(
        None,
        1.0,
        {
            **c,
            "csd_mode": "3D waterfall",
            "csd_span": c["span"],
            "_surface_data": (s.freqs, angles, data.T),
            "_y_label": ("Horizontal" if kind == "map_h" else "Vertical") + " angle / degrees",
        },
    )
    pane.note.setText(
        "Directivity surface - frequency / angle / relative level - drag to orbit, wheel to zoom"
    )


def _impulse(pane, s, levels, rel, i):
    o = pane.owner
    from hals_studio.ui.plotting.csd_plot import analysis_ir
    from hals_studio.ui.plotting.export_charts import ImpulsePanel

    if not hasattr(pane, "ir_panel"):
        pane.ir_panel = ImpulsePanel(show_toolbar=False)
        pane.stack.addWidget(pane.ir_panel)
    try:
        ir, fs, _ = analysis_ir(o, s)
        pane.ir_panel.update_ir(np.arange(len(ir)) / fs, ir, None, id(s))
        pane.stack.setCurrentWidget(pane.ir_panel)
        pane.note.setText(
            "HALS IR generator ? selected probe ? normalized amplitude ? time from generated IR start"
        )
    except (ValueError, OSError) as exc:
        _unavailable(pane, exc, "Impulse response unavailable for this source")


def _decay(pane, s, levels, rel, i):
    c, o = pane.config, pane.owner
    kind = c["kind"]
    from hals_studio.ui.plotting.csd_plot import analysis_ir

    _ensure_decay_view(pane)
    pane.stack.setCurrentWidget(pane.csd_view)
    try:
        ir, fs, note = analysis_ir(o, s)
        pane.csd_view.render(
            ir, fs, {**c, "csd_method": "Morlet wavelet" if kind == "wavelet" else "CSD"}
        )
        pane.note.setText(note)
    except (ValueError, OSError) as exc:
        _unavailable(pane, exc, "CSD unavailable for this source")


def _globe(pane, s, levels, rel, i):
    from hals_studio.ui.plotting.directivity_views import draw_globe

    draw_globe(pane, s, rel)


def _polar(pane, s, levels, rel, i):
    c = pane.config
    draw_zoomable_polars(pane.chart, s, rel, i, c["span"], pane=pane)
    pane.interaction.finish(pane.chart.fig.axes)


def _response(pane, s, levels, rel, i):
    pane.draw_chart(s, levels, rel, i)


RENDERERS = {
    "impulse": _impulse,
    "csd": _decay,
    "wavelet": _decay,
    "globe_hv": _globe,
    "globe_h": _globe,
    "globe_v": _globe,
    "polar": _polar,
}


def render_chart(pane, sphere, levels, relative, frequency_index):
    config = pane.config
    if config["kind"].startswith("map_") and config.get("directivity_display") in (
        "3D surface",
        "Waterfall",
    ):
        renderer = _directivity_surface
    else:
        renderer = RENDERERS.get(config["kind"], _response)
    renderer(pane, sphere, levels, relative, frequency_index)
