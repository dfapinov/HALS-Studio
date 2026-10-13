"""Editors and setup dialog for independent plot panes."""

from copy import deepcopy
from PySide6 import QtCore as C, QtWidgets as W
from hals_studio.analysis.analysis_metrics import contour_levels
from hals_studio.ui.plotting.plot_settings import (
    SPECS,
    TITLES,
    setting_keys,
    selected_magnitudes,
    decay_setting_keys,
)


def editor(key, value, callback, options=None):
    spec = options if options is not None else SPECS[key][1]
    if key == "opacity_low":
        w = W.QSlider(C.Qt.Horizontal)
        w.setRange(0, 95)
        w.setValue(round(value * 100))
        w.setToolTip("Lowest-level surface opacity; highest-level surface stays at 95%.")
        w.valueChanged.connect(lambda v: callback(v / 100))
        return w
    if spec is bool:
        w = W.QCheckBox()
        w.setChecked(
            value
            if isinstance(value, bool)
            else value in ("Each frequency peak", "IR peak slice per frequency")
        )
        w.toggled.connect(callback)
    elif isinstance(spec, list):
        w = W.QComboBox()
        w.setSizeAdjustPolicy(W.QComboBox.AdjustToMinimumContentsLengthWithIcon)
        w.setMinimumContentsLength(1)
        w.addItems(spec)
        w.setCurrentText(
            "Waterfall" if key == "directivity_display" and value == "3D surface" else value
        )
        w.currentTextChanged.connect(callback)
    else:
        w = W.QDoubleSpinBox()
        w.setRange(*spec)
        w.setDecimals(3 if key == "delay" else 1)
        if key == "phase_height":
            w.setDecimals(2)
            w.setSingleStep(0.05)
        w.setValue(value)
        w.setKeyboardTracking(False)
        w.valueChanged.connect(callback)
    return w


class Setup(W.QDialog):
    def __init__(self, pane):
        super().__init__(pane)
        self.setWindowTitle(f"Pane {pane.index + 1} - {TITLES[pane.config['kind']]} setup")
        if pane.config.get("min_phase_delay"):
            pane.delay_ms()
        self.values = deepcopy(pane.config)
        if pane.config["kind"] in ("csd", "wavelet"):
            self.values["csd_method"] = (
                "Morlet wavelet" if pane.config["kind"] == "wavelet" else "CSD"
            )
        layout = W.QVBoxLayout(self)
        note = W.QLabel(
            "Pin selected settings to the left sidebar. Each pane keeps its own settings."
        )
        note.setWordWrap(True)
        note.setSizePolicy(W.QSizePolicy.Ignored, W.QSizePolicy.Preferred)
        layout.addWidget(note)
        self.size_note = note
        pin_mode = W.QCheckBox("Pin settings - show pin checkboxes")
        layout.addWidget(pin_mode)
        scroll = W.QScrollArea()
        scroll.setWidgetResizable(True)
        layout.addWidget(scroll)
        body = W.QWidget()
        form = W.QGridLayout(body)
        form.setAlignment(C.Qt.AlignTop)
        scroll.setWidget(body)
        self.size_scroll = scroll
        self.size_body = body
        self.size_pin_mode = pin_mode
        scroll.setHorizontalScrollBarPolicy(C.Qt.ScrollBarAsNeeded)
        self.pin_checks = {}
        self.controls = {}
        self.pane = pane
        self.time_rows = {}
        for row, key in enumerate(
            setting_keys(
                pane.config["kind"],
                {**self.values, "_all_time_controls": True, "_all_decay_controls": True},
            )
        ):
            check = W.QCheckBox("Pin")
            check.setChecked(key in self.values["pins"])
            check.setVisible(False)
            self.pin_checks[key] = check
            pin_mode.toggled.connect(
                lambda enabled, w=check, k=key: w.setVisible(
                    enabled
                    and (
                        k not in ("csd_time", "csd_pre_time", "wavelet_duration", "wavelet_pre")
                        or k.startswith("wavelet_")
                        == (self.values.get("wavelet_units", "Cycles") == "Cycles")
                    )
                )
            )
            form.addWidget(check, row, 0)
            caption = W.QLabel(SPECS[key][0])
            form.addWidget(caption, row, 1)
            control = editor(
                key,
                self.values[key],
                lambda v, k=key: self.changed(k, v),
                pane.fit_names() if key == "fit_curve" else None,
            )
            self.controls[key] = control
            if key == "delay":
                group = W.QWidget()
                row_layout = W.QHBoxLayout(group)
                row_layout.setContentsMargins(0, 0, 0, 0)
                row_layout.addWidget(control)
                estimate = W.QPushButton("Estimate")
                estimate.setToolTip(
                    "Estimate propagation delay from reference-axis excess group delay and fill the delay value."
                )
                estimate.clicked.connect(
                    lambda checked=False, field=control: pane.fill_estimated_delay(
                        field, self.values
                    )
                )
                row_layout.addWidget(estimate)
                control = group
            form.addWidget(control, row, 2)
            if pane.config["kind"] in ("csd", "wavelet"):
                self.time_rows[key] = (caption, control, check)
        self.sync_time_rows()
        buttons = W.QDialogButtonBox(W.QDialogButtonBox.Ok | W.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.size_buttons = buttons
        pin_mode.toggled.connect(lambda _: C.QTimer.singleShot(0, self.fit_contents))

    def showEvent(self, event):
        super().showEvent(event)
        self.fit_contents()

    def fit_contents(self):
        self.size_body.layout().activate()
        content = self.size_body.sizeHint()
        area = self.screen().availableGeometry()
        margins = self.layout().contentsMargins()
        spacing = self.layout().spacing()
        width = min(
            max(340, content.width() + margins.left() + margins.right() + 26),
            int(area.width() * 0.9),
        )
        note_height = self.size_note.heightForWidth(width - margins.left() - margins.right())
        height = (
            content.height()
            + max(0, note_height)
            + self.size_pin_mode.sizeHint().height()
            + self.size_buttons.sizeHint().height()
            + margins.top()
            + margins.bottom()
            + 3 * spacing
            + 6
        )
        self.resize(width, min(height, int(area.height() * 0.85)))

    def sync_time_rows(self):
        for key, (caption, control, check) in self.time_rows.items():
            visible = key in decay_setting_keys(self.values)
            caption.setVisible(visible)
            control.setVisible(visible)
            if not visible:
                check.hide()

    def changed(self, key, value):
        self.values[key] = value
        if key == "phase_mode" and value != "None":
            selected = [
                k for k in selected_magnitudes(self.values) if k != "di" and not k.endswith(" DI")
            ]
            self.values["magnitude_selection"] = selected
            if self.values["kind"] == "di" or self.values["kind"].endswith(" DI"):
                self.values["kind"] = selected[0] if selected else "probe"
        manual = (
            "auto_axes"
            if key in ("fmin", "fmax", "ymin", "ymax")
            else "phase_auto"
            if key in ("phase_min", "phase_max")
            else "di_auto"
            if key in ("di_min", "di_max")
            else None
        )
        if manual:
            self.values[manual] = False
            if manual in self.controls:
                self.controls[manual].setChecked(False)
        if key == "csd_method":
            self.values["kind"] = "wavelet" if value == "Morlet wavelet" else "csd"
        if key in ("wavelet_units", "csd_method"):
            self.sync_time_rows()
            C.QTimer.singleShot(0, self.fit_contents)
        if (
            key in ("breakout", "extent", "step", "symmetric", "sweep_direction")
            and "fit_curve" in self.controls
        ):
            options = self.pane.fit_names(self.values)
            control = self.controls["fit_curve"]
            selected = (
                self.values["fit_curve"] if self.values["fit_curve"] in options else "First curve"
            )
            control.blockSignals(True)
            control.clear()
            control.addItems(options)
            control.setCurrentText(selected)
            control.blockSignals(False)
            self.values["fit_curve"] = selected

    def accept(self):
        if self.values["di_min"] >= self.values["di_max"]:
            W.QMessageBox.warning(self, "DI limits", "DI minimum must be smaller than maximum.")
            return
        if self.values["fmin"] >= self.values["fmax"] or self.values["ymin"] >= self.values["ymax"]:
            W.QMessageBox.warning(
                self, "Axis limits", "Minimum limits must be smaller than maximum limits."
            )
            return
        if self.values["fit_low"] >= self.values["fit_high"]:
            W.QMessageBox.warning(
                self, "Fit range", "Fit minimum must be smaller than fit maximum."
            )
            return
        try:
            contour_levels(
                self.values["contour_low"], self.values["contour_high"], self.values["contour_step"]
            )
        except ValueError as exc:
            W.QMessageBox.warning(self, "Contours", str(exc))
            return
        self.values["pins"] = [key for key, w in self.pin_checks.items() if w.isChecked()]
        super().accept()
