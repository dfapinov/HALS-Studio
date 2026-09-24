"""Linked Qt/Matplotlib analysis panels and PyVista geometry."""
import bootstrap  # noqa: F401
import numpy as np
import pyvista as pv
from matplotlib import rcParams, colormaps, cycler
from matplotlib.ticker import FuncFormatter, LogLocator, NullFormatter
from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from PySide6.QtWidgets import QVBoxLayout, QWidget
from acoustics import directions, phase_delay, beamwidth

BG = "#101c28"
FG = "#c2d1df"
CYAN = "#47d7ec"
AMBER = "#ffba68"
COLORS = [CYAN, AMBER, "#a692ff", "#7ae2b1", "#fa7b95"]
rcParams['axes.prop_cycle'] = cycler(color=COLORS + ['#80baff', '#e5d773', '#df9dd3'])
if "PColor" not in colormaps:
    colormaps.register(colormaps["jet"].copy(), name="PColor")
FREQUENCY_STRETCH = 1.6


def audio_frequency(value):
    return f"{value/1000:g}k" if value >= 1000 else f"{value:g}"


def audio_ticks(low, high):
    return np.array([v for v in (10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000, 50000, 100000)
                     if low <= v <= high])
rcParams.update({"font.family": "DejaVu Sans", "font.size": 9, "axes.titlesize": 11,
                 "axes.labelsize": 9, "figure.facecolor": BG, "axes.facecolor": BG,
                 "axes.edgecolor": "#334555", "axes.labelcolor": FG, "text.color": FG,
                 "xtick.color": "#8ca4b8", "ytick.color": "#8ca4b8", "grid.color": "#2b3c4b",
                 "grid.alpha": .55, "savefig.facecolor": BG, "legend.frameon": False})


from matplotlib.legend import DraggableLegend


class BoundedLegend(DraggableLegend):
    """Keep the legend inside the chart canvas, including the axis margins."""
    def save_offset(self):
        super().save_offset()
        self.start_box = self.legend.get_window_extent().frozen()

    def update_offset(self, dx, dy):
        bounds = self.legend.get_figure().bbox
        box = self.start_box
        dx = np.clip(dx, bounds.x0-box.x0, max(bounds.x0-box.x0, bounds.x1-box.x1))
        dy = np.clip(dy, bounds.y0-box.y0, max(bounds.y0-box.y0, bounds.y1-box.y1))
        super().update_offset(dx, dy)


def draggable_legend(legend):
    legend.set_in_layout(False)
    if not isinstance(legend._draggable, BoundedLegend):
        legend.set_draggable(False)
        legend._draggable = BoundedLegend(legend)
    return legend._draggable


class Chart(QWidget):
    def __init__(self, toolbar=False):
        super().__init__()
        self.fig = Figure(layout="constrained")
        self.canvas = FigureCanvasQTAgg(self.fig)
        self.canvas.mpl_connect('button_press_event', self.pick_legend)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.canvas)
        if toolbar:
            layout.addWidget(NavigationToolbar2QT(self.canvas, self))

    def pick_legend(self, event):
        if event.button != 1: return
        for ax in self.fig.axes:
            legend = ax.get_legend()
            if legend is not None and legend.contains(event)[0]:
                # A transparent DI/phase axis can sit over the legend's axis.
                # Forward the pick when Matplotlib's normal axes filter skipped it.
                draggable = draggable_legend(legend)
                if not draggable.got_artist: legend.pick(event)
                return

    def done(self):
        for ax in self.fig.axes:
            legend = ax.get_legend()
            if legend is not None: draggable_legend(legend)
        from viewer_theme import chart_theme
        chart_theme(self)
        self.canvas.draw_idle()


def style(ax, title, xlabel="Frequency / Hz", ylabel="Level / dB"):
    ax.set_title(title, loc="left", pad=13, color="#eef6ff", fontweight="normal")
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.grid(True, which="both", linewidth=.5)
    ax.spines[["top", "right"]].set_visible(False)
    if xlabel == "Frequency / Hz":
        ax.set_xscale("log")
        lo, hi = ax.get_xlim()
        ticks = audio_ticks(lo, hi)
        ax.set_xticks(ticks)
        ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: audio_frequency(v)))
        ax.xaxis.set_minor_formatter(NullFormatter())
        ax.xaxis.set_minor_locator(LogLocator(base=10, subs=range(2, 10)))
    ax.ticklabel_format(axis="y", style="plain", useOffset=False) if ax.get_yscale() == "linear" else None


def balloon_mesh(sphere, values, display_range=36, mapping="dB radius"):
    closed = np.column_stack((values, values[:, :1]))
    a = np.r_[sphere.azimuth, sphere.azimuth[0] + 360]
    radius = np.clip((closed + display_range) / display_range, .015, 1.3)
    if mapping == "Pressure radius":
        radius = np.clip(10 ** (closed / 20), .008, 2.)
    if mapping in ("Unit sphere", "Colour sphere (no deformation)"):
        radius = np.ones_like(closed)
    xyz = directions(sphere.elevation, a) * radius[..., None]
    mesh = pv.StructuredGrid(xyz[..., 0], xyz[..., 1], xyz[..., 2])
    mesh["Relative level / dB"] = closed.ravel(order="F")
    return mesh


def volume_mesh(sphere, relative, full_azimuth=False):
    mask = np.ones(len(sphere.azimuth), bool) if full_azimuth else (sphere.azimuth >= -90) & (sphere.azimuth <= 90)
    azimuth, values = sphere.azimuth[mask], relative[:, :, mask]
    if full_azimuth:
        azimuth = np.r_[azimuth, 180.]; values = np.concatenate((values, values[:, :, :1]), axis=2)
    # VTK x is log10(f), y is horizontal angle, z is elevation.
    # Angle scales compress degrees to keep the visual aspect navigable.
    x, y, z = np.meshgrid(FREQUENCY_STRETCH * np.log10(sphere.freqs), azimuth / 90,
                          sphere.elevation / 90, indexing="ij")
    mesh = pv.StructuredGrid(x, y, z)
    mesh["Relative level / dB"] = values.transpose(0, 2, 1).ravel(order="F")
    return mesh


def beam_tunnel_mesh(sphere, relative, extent=90.):
    """Frequency extrusion of an azimuthal-equidistant directional projection.

    Disk radius is off-axis angle from +X; its polar angle rotates the cut
    from horizontal toward vertical. Every ray through its centre is a real
    great-circle directivity cut, not an interpolation between H/V cuts.
    """
    from analysis_metrics import sample_energy
    step = min(np.diff(sphere.elevation)[0], np.diff(sphere.azimuth)[0])
    off_axis = np.linspace(0., extent, max(3, int(np.ceil(extent/step))+1))
    rotation = np.linspace(0., 360., max(24, int(np.ceil(360/step)))+1)
    alpha, gamma = np.meshgrid(np.deg2rad(off_axis), np.deg2rad(rotation), indexing='ij')
    dx, dy, dz = np.cos(alpha), np.sin(alpha)*np.cos(gamma), np.sin(alpha)*np.sin(gamma)
    azimuth = np.rad2deg(np.arctan2(dy, dx)); elevation = np.rad2deg(np.arcsin(np.clip(dz, -1, 1)))
    energy = sample_energy(sphere, 10**(relative/10), azimuth.ravel(), elevation.ravel())
    levels = 10*np.log10(np.maximum(energy, 1e-60)).reshape((len(sphere.freqs), *alpha.shape))
    x = np.broadcast_to(FREQUENCY_STRETCH*np.log10(sphere.freqs)[:, None, None], levels.shape)
    y = np.broadcast_to(np.rad2deg(alpha)*np.cos(gamma)/90, levels.shape)
    z = np.broadcast_to(np.rad2deg(alpha)*np.sin(gamma)/90, levels.shape)
    mesh = pv.StructuredGrid(x.copy(), y.copy(), z.copy())
    mesh['Relative level / dB'] = levels.ravel(order='F')
    return mesh


def coverage_surface(mesh, threshold, closed=True):
    """The boundary of the sampled region at or above the selected level.

    Contours alone omit broad low-frequency fields. Boundary caps mark where
    above-threshold coverage reaches the angular/frequency domain boundary.
    """
    scalar = "Relative level / dB"
    surface = mesh.contour([threshold], scalars=scalar)
    if closed:
        caps = mesh.extract_surface(algorithm="dataset_surface").clip_scalar(scalars=scalar, value=threshold, invert=False)
        surface = surface.merge(caps) if surface.n_points else caps
    return surface


def response_directions(sphere, plane, extent, step, symmetric=False, direction=None):
    angles = np.arange(0, extent + .00001, step)
    if direction == '-':
        angles = -angles
    elif direction == '+/-' or (direction is None and symmetric):
        angles = np.r_[-angles[:0:-1], angles]
    result, used = [], set()
    for angle in angles:
        if plane == "Horizontal":
            az, el = angle, 0
        else:
            el = np.degrees(np.arcsin(np.sin(np.deg2rad(angle))))
            az = 0 if np.cos(np.deg2rad(angle)) >= -1e-12 else -180
        idx = sphere.index(az, el)
        if idx in used:
            continue
        used.add(idx)
        if plane == "Horizontal":
            actual = sphere.azimuth[idx[1]]
        else:
            actual = sphere.elevation[idx[0]]
            if abs(sphere.azimuth[idx[1]]) > 90:
                actual = np.sign(angle) * (180-abs(actual))
        result.append((idx, "On axis" if actual == 0 else f"{actual:+g}°"))
    return result


def draw_polars(chart, sphere, rel, i, dynamic_range):
    chart.fig.clear()
    chart.fig.get_layout_engine().set(rect=(0, 0, 1, 1))
    angles, h, v = sphere.cuts(rel)
    theta = np.deg2rad(np.r_[angles, angles[0] + 360])
    side_by_side = chart.width() > chart.height() * 1.6
    compact = chart.height() < 320 and not side_by_side
    shared = chart.fig.add_subplot(111, projection="polar") if compact else None
    for j, (values, title, color) in enumerate(((h, "HORIZONTAL  /  XY", CYAN), (v, "VERTICAL  /  XZ", AMBER))):
        ax = shared if compact else chart.fig.add_subplot(1 if side_by_side else 2, 2 if side_by_side else 1, j + 1, projection="polar")
        r = np.clip(np.r_[values[i], values[i, 0]], -dynamic_range, 6) + dynamic_range
        ax.plot(theta, r, color=color, lw=1.6, label="H" if j == 0 else "V")
        ax.fill(theta, r, color=color, alpha=.10)
        ax.set_theta_zero_location("N")
        ax.set_theta_direction(-1)
        ax.set_ylim(0, dynamic_range + 3)
        ticks = np.arange(0, dynamic_range + .1, 12)
        ax.set_yticks(ticks, [f"{t-dynamic_range:g}" for t in ticks], fontsize=7)
        ax.set_xticks(np.deg2rad([0, 90, 180, 270]), ["0°", "+90°", "180°", "−90°"], fontsize=8)
        ax.grid(alpha=.6, linewidth=.5)
        ax.set_title("POLAR CUTS" if compact else title, fontsize=9, color=FG if compact else color, pad=16)
    if compact:
        shared.legend(loc="upper right", fontsize=7, ncol=2, bbox_to_anchor=(1.3, 1.25))
    chart.done()


def draw_zoomable_polars(chart, sphere, rel, i, dynamic_range):
    """Polar cuts on Cartesian axes so cursor-centred zoom also pans correctly."""
    from matplotlib.patches import Circle
    chart.fig.clear(); chart.fig.set_layout_engine('constrained'); chart.fig.get_layout_engine().set(rect=(0, 0, 1, 1))
    angles, h, v = sphere.cuts(rel)
    theta = np.deg2rad(np.r_[angles, angles[0]+360])
    horizontal = chart.width() > chart.height()*1.3
    for j, (values, title, color) in enumerate(((h, 'HORIZONTAL / XY', CYAN), (v, 'VERTICAL / XZ', AMBER))):
        ax = chart.fig.add_subplot(1 if horizontal else 2, 2 if horizontal else 1, j+1)
        radius = np.clip(np.r_[values[i], values[i, 0]], -dynamic_range, 6)+dynamic_range
        ax.plot(radius*np.sin(theta), radius*np.cos(theta), color=color, lw=1.5)
        ax.fill(radius*np.sin(theta), radius*np.cos(theta), color=color, alpha=.1)
        for level in np.arange(0, dynamic_range+.01, 12):
            r = dynamic_range-level
            if r > 0:
                ax.add_patch(Circle((0, 0), r, facecolor='none', edgecolor='#385061', lw=.5))
                ax.text(.7, r, f'{-level:g}', color='#8ca4b8', fontsize=7, va='top', clip_on=True)
        for angle, text in [(0, '0°'), (90, '+90°'), (180, '180°'), (270, '−90°')]:
            rad = np.deg2rad(angle)
            ax.plot([0, dynamic_range*np.sin(rad)], [0, dynamic_range*np.cos(rad)], color='#385061', lw=.5)
            ax.text((dynamic_range+4)*np.sin(rad), (dynamic_range+4)*np.cos(rad), text,
                    ha='center', va='center', color='#8ca4b8', fontsize=8, clip_on=True)
        ax.set_xlim(-dynamic_range-9, dynamic_range+9); ax.set_ylim(-dynamic_range-9, dynamic_range+9)
        ax.set_aspect('equal', adjustable='box'); ax.set_axis_off(); ax.set_title(title, color=color, fontsize=9)
    chart.done()


def draw_response(chart, sphere, levels, i, selected, offset=0, comparison=None,
                  mode="Overview", extent=90, step=10, symmetric=False, dynamic_range=36):
    chart.fig.clear()
    if "polar" in mode.lower():
        angles, h, v = sphere.cuts(sphere.relative(levels, "On axis"))
        ax = chart.fig.add_subplot(111, projection="polar")
        cut = h if mode.startswith("Horizontal") else v
        theta = np.deg2rad(np.r_[angles, angles[0]+360])
        values = np.maximum(np.r_[cut[i], cut[i, 0]], -dynamic_range) + dynamic_range
        ax.plot(theta, values, color=CYAN, lw=1.5)
        ax.fill(theta, values, color=CYAN, alpha=.15)
        ax.set_theta_zero_location("N")
        ax.set_theta_direction(-1)
        ax.set_ylim(0, dynamic_range+3)
        ax.set_thetamin(-extent)
        ax.set_thetamax(extent)
        ax.set_yticks(np.linspace(0, dynamic_range, 4), [f"{v:g}" for v in np.linspace(-dynamic_range, 0, 4)])
        ax.set_title(f"{mode.upper()} · {audio_frequency(sphere.freqs[i])} Hz · on-axis reference", fontsize=9)
        chart.done()
        return
    ax = chart.fig.add_subplot(111)
    if mode == "Overview":
        curves = [(sphere.index(az, el), title, color) for az, el, title, color in
                  [(0, 0, "On axis", CYAN), (30, 0, "H +30°", AMBER), (60, 0, "H +60°", "#a692ff"),
                   (*selected, "Probe", "#7ae2b1")]]
    else:
        family = response_directions(sphere, mode.split()[0], extent, step, symmetric)
        curves = [(idx, title, colormaps["turbo"](n/max(1, len(family)-1))) for n, (idx, title) in enumerate(family)]
    for idx, title, color in curves:
        ax.semilogx(sphere.freqs, levels[:, *idx] + offset, color=CYAN if title == "On axis" else color,
                    lw=1.8 if title == "On axis" else 1.2, label=title)
    if comparison:
        ax.semilogx(comparison.freqs, comparison.levels()[:, *comparison.index()] + offset,
                    color="#fa7b95", ls="--", lw=1, label="Reference on axis")
    ax.axvline(sphere.freqs[i], color="white", alpha=.45, lw=.7)
    style(ax, "RESPONSE TRACES" if mode == "Overview" else mode.upper(), ylabel="Level / dB")
    top = max(np.max(levels), np.max(comparison.levels()) if comparison else -np.inf) + offset
    ax.set_ylim(top - 65, top + 5)
    ax.legend(loc="lower left", ncol=min(8, len(curves)+bool(comparison)), fontsize=7)
    ax.margins(x=.01)
    chart.done()


def draw_maps(chart, sphere, levels, relative, i, display_range, cmap):
    chart.fig.clear()
    angles, h, v = sphere.cuts(relative)
    for n, (cut, name) in enumerate(((h, "HORIZONTAL DIRECTIVITY"), (v, "VERTICAL DIRECTIVITY"))):
        ax = chart.fig.add_subplot(2, 2, n + 1)
        im = ax.pcolormesh(sphere.freqs, angles, cut.T, shading="auto", cmap=cmap, vmin=-display_range, vmax=0, rasterized=True)
        ax.contour(sphere.freqs, angles, cut.T, levels=[-12, -6], colors=["#ffffff70", "#ffffff"], linewidths=.55)
        ax.axvline(sphere.freqs[i], color=CYAN, lw=1, ls="--")
        ax.set_ylim(-180, 180)
        ax.set_yticks([-180, -90, 0, 90, 180])
        style(ax, name, ylabel="Angle / degrees")
        chart.fig.colorbar(im, ax=ax, label="Relative dB", pad=.025, shrink=.85)
    angles, h, v = sphere.cuts(levels)
    ax = chart.fig.add_subplot(2, 2, 3)
    ax.semilogx(sphere.freqs, beamwidth(angles, h), color=CYAN, label="Horizontal")
    ax.semilogx(sphere.freqs, beamwidth(angles, v), color=AMBER, label="Vertical")
    ax.set_ylim(0, 360)
    style(ax, "−6 dB BEAMWIDTH  /  FRONT LOBE", ylabel="Coverage / degrees")
    ax.legend()
    ax = chart.fig.add_subplot(2, 2, 4)
    im = ax.pcolormesh(sphere.azimuth, sphere.elevation, relative[i], shading="auto", cmap=cmap,
                       vmin=-display_range, vmax=0)
    ax.set_xticks([-180, -90, 0, 90, 180])
    ax.set_yticks([-90, -45, 0, 45, 90])
    style(ax, f"SPHERICAL MAP  /  {sphere.freqs[i]:,.0f} Hz", "Azimuth / degrees", "Elevation / degrees")
    chart.fig.colorbar(im, ax=ax, label="Relative dB", pad=.025, shrink=.85)
    chart.done()


def draw_analysis(chart, sphere, levels, selected, remove_ms, offset, comparison=None):
    chart.fig.clear()
    chart.fig.get_layout_engine().set(rect=(0, .035, 1, .965))
    idx = sphere.index(*selected)
    metrics = sphere.metrics(levels)
    f = sphere.freqs
    ax = chart.fig.add_subplot(221)
    for name, label, color in (("on_axis", "On axis", CYAN), ("sphere_average", "Sphere energy average", AMBER)):
        ax.semilogx(f, metrics[name] + offset, color=color, label=label)
    ax.semilogx(f, levels[:, *idx] + offset, color=COLORS[3], label="Probe")
    if comparison:
        ax.semilogx(comparison.freqs, comparison.levels()[:, *comparison.index()] + offset, "--", color=COLORS[4], label="Reference axis")
    style(ax, "MAGNITUDE & RADIATED ENERGY", ylabel="dB re HALS unit + offset")
    ax.legend(fontsize=8)
    phase, delay = phase_delay(f, sphere.pressure[:, *idx], remove_ms)
    ax = chart.fig.add_subplot(222)
    ax.semilogx(f, phase, color=COLORS[2], lw=1.2)
    style(ax, "PROBE PHASE  /  UNWRAPPED", ylabel="Phase / degrees")
    ax = chart.fig.add_subplot(223)
    ax.semilogx(f, delay, color=COLORS[3], lw=1.2)
    style(ax, "PROBE GROUP DELAY", ylabel="Delay / ms")
    ax = chart.fig.add_subplot(224)
    ax.semilogx(f, metrics["directivity_index"], color=AMBER, label="On-axis DI")
    ax.axhline(0, color=FG, lw=.5)
    style(ax, "DIRECTIVITY INDEX  /  FULL SPHERE", ylabel="DI / dB")
    chart.fig.text(.5, .005, "Phase / delay use native complex bins. Sparse frequency sampling can alias phase; reconstruct all bins for delay work.",
                   color="#91a8bb", ha="center", fontsize=8)
    chart.done()
