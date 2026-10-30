"""Shared plot defaults and setting visibility, independent of widgets."""

from copy import deepcopy

GROUPS = {
    "3D field": {
        "balloon": "Balloon / colour sphere",
        "cross_sonograms": "Intersecting H/V sonograms",
    },
    "Time / decay": {
        "impulse": "Impulse response",
        "csd": "Cumulative spectral decay",
        "wavelet": "Morlet wavelet",
    },
    "Directivity": {
        "map_h": "Horizontal spectrogram",
        "map_v": "Vertical spectrogram",
        "polar": "Horizontal + vertical polars",
        "globe_hv": "Horizontal + vertical globes",
    },
    "SPL & phase": {
        "di": "Sound power directivity index",
        "probe": "Probe SPL",
        "reference": "Reference axis SPL",
        "phase": "Total phase",
        "minimum": "Minimum phase estimate",
        "sweep_h": "Horizontal SPL sweep",
        "sweep_v": "Vertical SPL sweep",
    },
    "CEA2034": {
        "cea": "Spinorama overview",
        "cea_On axis": "On axis",
        "cea_Listening window": "Listening window",
        "cea_Early reflections": "Early reflections",
        "cea_Sound power": "Sound power",
        "cea_Predicted in-room": "Predicted in-room",
        "cea_Sound power DI": "Sound power DI",
        "cea_Early reflections DI": "Early reflections DI",
        "reflections": "Reflection breakouts",
        "cea_Floor": "Floor",
        "cea_Ceiling": "Ceiling",
        "cea_Front wall": "Front wall",
        "cea_Side walls": "Side walls",
        "cea_Rear wall": "Rear wall",
    },
}
TITLES = {k: v for group in GROUPS.values() for k, v in group.items()}
MAGNITUDE_KINDS = {
    k: v
    for category in ("SPL & phase", "CEA2034")
    for k, v in GROUPS[category].items()
    if k not in ("phase", "minimum")
}


def selected_magnitudes(config):
    selected = config.get("magnitude_selection")
    if selected is None:
        return [config["kind"]] if config["kind"] in MAGNITUDE_KINDS else []
    cta = config['kind'] in GROUPS['CEA2034']
    return [key for key in selected if key in MAGNITUDE_KINDS
            and (key in GROUPS['CEA2034']) == cta]


DECAY_DEFAULTS = dict(
    csd_level_reference=False,
    wavelet_level_reference=False,
    wavelet_time_reference=False,
    csd_method="CSD",
    wavelet_units="Cycles",
    wavelet_cycles=12.0,
    wavelet_duration=20.0,
    wavelet_pre=1.0,
    csd_mode="3D waterfall",
    csd_time=20.0,
    csd_pre_time=1.0,
    csd_span=30.0,
    csd_auto_time=True,
    csd_fmin=100.0,
    csd_fmax=20000.0,
)

DEFAULT = dict(
    **DECAY_DEFAULTS,
    directivity_display="Sonogram",
    directivity_on_axis=False,
    directivity_contour_step=6.0,
    kind="probe",
    normalization="Peak",
    smoothing="None",
    globe_rotation={"horizontal": 180.0, "vertical": 90.0},
    polar_rotation={"horizontal": 0.0, "vertical": 270.0},
    polar_sample_points=False,
    span=36.0,
    palette="PColor",
    geometry="dB radius",
    reference_sphere=True,
    edges=False,
    phase_colour=False,
    orbit="Az / El - no roll",
    contours=True,
    extent=90.0,
    step=10.0,
    symmetric=True,
    sweep_direction="+/-",
    delay=0.0,
    offset=0.0,
    wrapped=True,
    di_auto=True,
    di_min=-5.0,
    di_max=20.0,
    phase_auto=True,
    phase_min=-180.0,
    phase_max=180.0,
    phase=True,
    phase_mode="Total phase",
    magnitude_selection=None,
    phase_height=0.45,
    min_phase_delay=False,
    overlays=True,
    fmin=20.0,
    fmax=20000.0,
    ymin=-100.0,
    ymax=10.0,
    auto_axes=True,
    fit=False,
    fit_low=100.0,
    fit_high=10000.0,
    fit_curve="First curve",
    volume_mode="Closed contour surfaces",
    volume_coordinates="Beam tunnel",
    beam_extent=90.0,
    threshold=-6.0,
    contour_low=-18.0,
    contour_high=-6.0,
    contour_step=3.0,
    opacity_low=0.12,
    contour_colours="Red shades",
    surface_finish="Glossy",
    breakout="All",
    pins=[],
)


def default_config(kind):
    config = dict(deepcopy(DEFAULT), kind=kind)
    config["energy_smoothing_version"] = 1
    if kind in MAGNITUDE_KINDS or kind in ("phase", "minimum"):
        config["smoothing"] = "None"
    return config


# key: label, type/options, range. A single schema drives both setup and sidebar.
SPECS = {
    "csd_method": ("Analysis", ["CSD", "Morlet wavelet"]),
    "directivity_on_axis": ("SPL - normalize on axis", bool),
    "directivity_contour_step": ("Contours Step / dB", (0.5, 60.0)),
    "directivity_display": ("Display", ["Sonogram", "Waterfall"]),
    "csd_level_reference": ("SPL - normalize", bool),
    "wavelet_level_reference": ("SPL - normalize", bool),
    "wavelet_time_reference": ("Time - normalize to peak arrival", bool),
    "wavelet_units": ("Time axis", ["Milliseconds", "Cycles"]),
    "wavelet_cycles": ("Resolution (higher = narrower bands)", (3.0, 20.0)),
    "wavelet_duration": ("Decay duration / cycles", (0.1, 500.0)),
    "wavelet_pre": ("Pre allowance / cycles", (0.0, 100.0)),
    "csd_pre_time": ("Pre allowance / milliseconds", (0.0, 100.0)),
    "csd_auto_time": ("Auto time to dB floor", bool),
    "csd_mode": ("Decay display", ["3D waterfall", "Sonogram"]),
    "csd_time": ("Decay duration / milliseconds", (0.1, 500.0)),
    "csd_span": ("Decay range / dB", (10.0, 120.0)),
    "csd_fmin": ("Frequency minimum / Hz", (1.0, 100000.0)),
    "csd_fmax": ("Frequency maximum / Hz", (2.0, 100000.0)),
    "normalization": ("Normalize to", ["Peak", "On axis"]),
    "smoothing": (
        "Energy smoothing",
        ["None", "1/24 octave", "1/12 octave", "1/6 octave", "1/3 octave"],
    ),
    "span": ("Colour / polar range (dB)", (6.0, 120.0)),
    "palette": ("Palette", ["PColor"]),
    "geometry": ("Geometry", ["dB radius", "Pressure radius", "Colour sphere (no deformation)"]),
    "surface_finish": ("Surface finish", ["Matte", "Satin", "Glossy"]),
    "reference_sphere": ("Reference sphere", bool),
    "edges": ("Mesh edges", bool),
    "phase_colour": ("Colour by phase", bool),
    "orbit": ("Orbit mode", ["Az / El - no roll", "Trackball"]),
    "contours": ("Show Contours", bool),
    "polar_sample_points": ("Show sampled-angle dots", bool),
    "extent": ("Sweep extent (degrees)", (0.0, 180.0)),
    "sweep_direction": ("Direction", ["+/-", "+", "-"]),
    "step": ("Sweep increment (degrees)", (1.0, 90.0)),
    "symmetric": ("Include negative angles", bool),
    "delay": ("Delay compensation (ms)", (-10000.0, 10000.0)),
    "offset": ("Level offset (dB)", (-200.0, 200.0)),
    "min_phase_delay": ("Min phase (Stage 5 reference delay)", bool),
    "phase_mode": ("Phase response", ["None", "Total phase", "Minimum phase"]),
    "phase_height": ("Phase axis height (fraction)", (0.15, 1.0)),
    "fit": ("Fit line", bool),
    "fit_low": ("Fit range from (Hz)", (0.1, 1000000.0)),
    "fit_high": ("Fit range to (Hz)", (0.1, 1000000.0)),
    "fit_curve": ("Fit response", ["First curve"]),
    "wrapped": ("Wrap phase at +/-180 degrees", bool),
    "phase": ("Show probe phase", bool),
    "overlays": ("Show saved probe overlays", bool),
    "auto_axes": ("Automatic axes", bool),
    "fmin": ("Frequency minimum (Hz)", (0.1, 1000000.0)),
    "fmax": ("Frequency maximum (Hz)", (0.1, 1000000.0)),
    "di_auto": ("Automatic DI limits", bool),
    "di_min": ("DI minimum (dB)", (-100000.0, 100000.0)),
    "di_max": ("DI maximum (dB)", (-100000.0, 100000.0)),
    "phase_auto": ("Automatic phase limits", bool),
    "phase_min": ("Phase minimum (degrees)", (-100000.0, 100000.0)),
    "phase_max": ("Phase maximum (degrees)", (-100000.0, 100000.0)),
    "ymin": ("Magnitude minimum (dB)", (-100000.0, 100000.0)),
    "ymax": ("Magnitude maximum (dB)", (-100000.0, 100000.0)),
    "volume_mode": (
        "Volume display",
        ["Closed contour surfaces", "Level crossings", "H/V colour slices"],
    ),
    "volume_coordinates": ("Directional layout", ["Beam tunnel", "Azimuth / elevation"]),
    "beam_extent": ("Maximum off-axis angle (degrees)", (15.0, 180.0)),
    "threshold": ("Volume threshold (dB)", (-96.0, -0.1)),
    "contour_low": ("Lowest contour (dB)", (-96.0, -0.1)),
    "contour_high": ("Highest contour (dB)", (-96.0, -0.1)),
    "contour_step": ("Contour increment (dB)", (0.5, 24.0)),
    "opacity_low": ("Lowest contour opacity", (0.0, 0.95)),
    "contour_colours": ("Contour colours", ["Red shades", "Single red", "Palette colours"]),
    "breakout": ("Breakout curves", ["All", "Horizontal", "Vertical"]),
}


def setting_keys(kind, config=None):
    if kind == "impulse":
        return []
    if kind in ("csd", "wavelet"):
        return decay_setting_keys({**DEFAULT, **(config or {}), "kind": kind})
    if kind == "cross_sonograms":
        return [
            "directivity_on_axis",
            "smoothing",
            "span",
            "contours",
            "directivity_contour_step",
            "fmin",
            "fmax",
        ]
    if kind.startswith("globe_"):
        return [
            "directivity_on_axis",
            "smoothing",
            "span",
            "contours",
            "directivity_contour_step",
            "fmin",
            "fmax",
        ]
    if kind.startswith("map_"):
        return [
            "directivity_display",
            "directivity_on_axis",
            "smoothing",
            "span",
            "contours",
            "directivity_contour_step",
        ]
    common = ["smoothing"]
    if kind in ("balloon", "volume", "map_h", "map_v", "polar"):
        common += ["normalization", "span"]
    if kind == "balloon":
        return common + [
            "geometry",
            "surface_finish",
            "reference_sphere",
            "edges",
            "phase_colour",
            "delay",
            "orbit",
        ]
    if kind == "volume":
        return common + [
            "volume_coordinates",
            "beam_extent",
            "volume_mode",
            "contour_low",
            "contour_high",
            "contour_step",
            "contour_colours",
            "opacity_low",
            "surface_finish",
            "orbit",
        ]
    if kind.startswith("map_"):
        common += ["directivity_display", "contours"]
    if kind == "polar":
        common += ["polar_sample_points"]
    if kind.startswith("sweep_"):
        common += ["extent", "step", "sweep_direction"]
    if kind in GROUPS["SPL & phase"]:
        common += ["phase_mode", "wrapped", "delay", "phase_height", "overlays"]
    if kind not in ("phase", "minimum", "polar", "map_h", "map_v"):
        common += ["fit", "fit_low", "fit_high", "fit_curve"]
    if kind in ("reflections", "cea_Sound power"):
        common += ["breakout"]
    if kind != "polar":
        common += ["offset", "auto_axes", "fmin", "fmax", "ymin", "ymax"]
    if config is not None and config.get("magnitude_selection") is not None:
        selected = selected_magnitudes(config)
        if any(k.startswith("sweep_") for k in selected):
            common += ["extent", "step", "sweep_direction"]
        if any(k in ("reflections", "cea_Sound power") for k in selected):
            common += ["breakout"]
        common += ["phase_mode", "wrapped", "delay", "phase_height", "overlays"]
        if selected:
            common += ["fit", "fit_low", "fit_high", "fit_curve"]
    if kind in GROUPS["SPL & phase"] or (config and config.get("magnitude_selection") is not None):
        common += ["phase_auto", "phase_min", "phase_max"]
        if kind in ("phase", "minimum"):
            common = [key for key in common if key not in ("ymin", "ymax")]
    if config and any(k == "di" or k.endswith(" DI") for k in selected_magnitudes(config)):
        common = [
            k
            for k in common
            if k not in ("phase_auto", "phase_min", "phase_max", "wrapped", "delay")
        ]
        common += ["di_auto", "di_min", "di_max"]
    if kind in GROUPS['CEA2034']:
        common = [key for key in common if key not in ('phase_mode', 'wrapped', 'delay', 'phase_auto', 'phase_min', 'phase_max')]
    common = list(dict.fromkeys(common))
    return common


def decay_setting_keys(config):
    if config.get("_all_decay_controls"):
        return [
            "csd_method",
            "csd_mode",
            "csd_level_reference",
            "wavelet_level_reference",
            "wavelet_time_reference",
            "wavelet_cycles",
            "wavelet_units",
            "csd_auto_time",
            "csd_time",
            "csd_pre_time",
            "wavelet_duration",
            "wavelet_pre",
            "csd_span",
            "csd_fmin",
            "csd_fmax",
        ]
    wavelet = config.get("csd_method") == "Morlet wavelet" or config.get("kind") == "wavelet"
    keys = ["csd_method", "csd_mode"]
    if wavelet:
        keys += ["wavelet_level_reference", "wavelet_time_reference", "wavelet_cycles"]
    else:
        keys += ["csd_level_reference"]
    keys += ["wavelet_units", "csd_auto_time"]
    if config.get("_all_time_controls") or config.get("wavelet_units", "Cycles") != "Cycles":
        keys += ["csd_time", "csd_pre_time"]
    if config.get("_all_time_controls") or config.get("wavelet_units", "Cycles") == "Cycles":
        keys += ["wavelet_duration", "wavelet_pre"]
    return keys + ["csd_span", "csd_fmin", "csd_fmax"]


def cta_curve_names(kind, breakout='All'):
    """Shared metric selections for Analysis and exact Export results."""
    if kind == 'cea':
        return ['On axis', 'Listening window', 'Early reflections', 'Sound power',
                'Sound power DI', 'Early reflections DI']
    if kind == 'reflections':
        return {'All': ['Floor', 'Ceiling', 'Front wall', 'Side walls', 'Rear wall'],
                'Horizontal': ['Front wall', 'Side walls', 'Rear wall', 'Horizontal reflections'],
                'Vertical': ['Floor', 'Ceiling', 'Vertical reflections']}[breakout]
    names = [kind[4:]]
    if kind == 'cea_Sound power' and breakout != 'All': names += [breakout+' sound power']
    return names
