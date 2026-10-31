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


def analysis_delay_markers(owner):
    """Time-zero references for displayed plots that apply phase compensation."""
    from hals_studio.ui.plotting.plot_settings import GROUPS, setting_keys

    markers = []
    for plot in owner.panes:
        c = plot.config
        kind = c['kind']
        if plot.isHidden() or kind not in GROUPS['SPL & phase']:
            continue
        mode = 'Total phase' if kind == 'phase' else c['phase_mode']
        if kind == 'minimum' or mode != 'Total phase' or 'delay' not in setting_keys(kind, c):
            continue
        markers.append((plot.delay_ms() / 1000, f'Pane {plot.index + 1} t=0'))
    return tuple(markers)


def _impulse(pane, s, levels, rel, i):
    o = pane.owner
    from hals_studio.ui.plotting.csd_plot import analysis_ir
    from hals_studio.ui.plotting.export_charts import ImpulsePanel

    if not hasattr(pane, "ir_panel"):
        pane.ir_panel = ImpulsePanel(show_toolbar=False)
        pane.stack.addWidget(pane.ir_panel)
    try:
        ir, fs, _ = analysis_ir(o, s)
        pane.ir_panel.update_ir(np.arange(len(ir)) / fs, ir, None, id(s),
                                markers=analysis_delay_markers(o))
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
    renderer = RENDERERS.get(pane.config["kind"], _response)
    renderer(pane, sphere, levels, relative, frequency_index)
