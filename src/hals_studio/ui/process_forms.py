"""Schema-driven Process stage forms and their local control dependencies."""

from PySide6 import QtCore as C, QtWidgets as W

MAIN = {
    1: ["fdw_oct_res", "fdw_max_cap_ms"],
    2: ["octave_resolution", "freq_start_hz"],
    3: ["freq_end_hz", "freq_start_hz"],
    4: ["target_n_max"],
}


class StageForms(W.QStackedWidget):
    rft_reset_requested = C.Signal()
    edit_orders_requested = C.Signal()

    def __init__(self, schema, values, parent=None):
        super().__init__(parent)
        self.values = values
        self.manual_scan_bounds = set()
        self._setting_scan_bounds = False
        self._default_scan_bounds = {key: schema["2"][key]["default"]
                                     for key in ("x_bounds", "y_bounds", "z_bounds")}
        self.controls = {}
        self.advanced = {}
        for stage in range(1, 5):
            scroll = W.QScrollArea()
            scroll.setWidgetResizable(True)
            page = W.QWidget()
            pagebox = W.QVBoxLayout(page)
            main = W.QGroupBox("Main Settings")
            mainform = W.QFormLayout(main)
            pagebox.addWidget(main)
            toggle = W.QToolButton()
            toggle.setText("Show Advanced Settings")
            toggle.setCheckable(True)
            toggle.setToolButtonStyle(C.Qt.ToolButtonTextBesideIcon)
            toggle.setArrowType(C.Qt.RightArrow)
            pagebox.addWidget(toggle)
            advanced = W.QGroupBox("Advanced Settings")
            advancedform = W.QFormLayout(advanced)
            pagebox.addWidget(advanced)
            if stage == 2:
                note = W.QLabel("Main scan: cylindrical bounds are calculated automatically from the measurement filename coordinates.")
                note.setWordWrap(True)
                mainform.addRow(note)
                grid_group = W.QGroupBox("Full grid re-scan only")
                gridform = W.QFormLayout(grid_group)
                grid_note = W.QLabel("XYZ bounds default to the measurement extents. Edit them to scan a smaller or larger volume.")
                grid_note.setWordWrap(True)
                gridform.addRow(grid_note)
                advancedform.addRow(grid_group)
            advanced.hide()
            self.advanced[stage] = (toggle, advanced)

            def expand(checked, b=toggle, g=advanced):
                g.setVisible(checked)
                b.setText("Hide Advanced Settings" if checked else "Show Advanced Settings")
                b.setArrowType(C.Qt.DownArrow if checked else C.Qt.RightArrow)

            toggle.toggled.connect(expand)
            form = W.QFormLayout()
            pagebox.addLayout(form)
            pagebox.addStretch()
            scroll.setWidget(page)
            self.addWidget(scroll)
            for key, spec in schema[str(stage)].items():
                value = self.values[stage][key]
                if isinstance(value, bool):
                    control = W.QCheckBox()
                    control.setChecked(value)
                    control.toggled.connect(lambda v, s=stage, k=key: self.values[s].update({k: v}))
                else:
                    control = W.QLineEdit(str(value))
                    control.textChanged.connect(
                        lambda v, s=stage, k=key: self.values[s].update({k: v})
                    )
                control.setToolTip(spec["help"])
                caption = W.QLabel(spec["label"])
                caption.setWordWrap(False)
                if isinstance(control, W.QLineEdit):
                    control.setFixedWidth(
                        145 if key.endswith("bounds") or key == "test_order_range" else 105
                    )
                field = control
                if stage == 3 and key == "freq_start_hz":
                    field = W.QWidget()
                    row = W.QHBoxLayout(field)
                    row.setContentsMargins(0, 0, 0, 0)
                    row.addWidget(control)
                    self.rft_reset_button = W.QPushButton("Set from RFT")
                    self.rft_reset_button.clicked.connect(self.rft_reset_requested)
                    row.addWidget(self.rft_reset_button)
                    row.addStretch()
                if not (stage == 2 and key in ("hold_origin_lf", "hold_origin_hf")):
                    target = mainform if key in MAIN[stage] else advancedform
                    if stage == 2 and key in ("x_bounds", "y_bounds", "z_bounds", "grid_res_mm"):
                        target = gridform
                        if key.endswith("_bounds"):
                            control.textChanged.connect(lambda _, k=key: self._scan_bound_edited(k))
                        control.setToolTip("Full grid re-scan only. " + spec["help"])
                    target.addRow(caption, field)
                self.controls[stage, key] = control
            if stage == 2:
                holds = W.QWidget()
                holdrow = W.QHBoxLayout(holds)
                holdrow.setContentsMargins(0, 0, 0, 0)
                for key in ("hold_origin_lf", "hold_origin_hf"):
                    control = self.controls[2, key]
                    control.setText(schema["2"][key]["label"])
                    holdrow.addWidget(control)
                holdrow.addStretch()
                advancedform.addRow("Hold coordinate outside test range", holds)
            if stage == 4:
                control = self.controls[4, "use_manual_table"]
                caption = advancedform.labelForField(control)
                advancedform.removeWidget(control)
                advancedform.removeWidget(caption)
                caption.deleteLater()
                control.setText(schema["4"]["use_manual_table"]["label"])
                advancedform.addRow(control)
                edit = W.QPushButton("Edit manual order table")
                edit.setSizePolicy(W.QSizePolicy.Fixed, W.QSizePolicy.Fixed)
                edit.clicked.connect(self.edit_orders_requested)
                advancedform.addRow(edit)
                optimizer = self.controls[4, "condition_preflight"]
                optimizer_label = advancedform.labelForField(optimizer)

                def growth_controls(
                    manual, optimizer=optimizer, label=optimizer_label, button=edit
                ):
                    optimizer.setEnabled(not manual)
                    label.setEnabled(not manual)
                    button.setEnabled(manual)

                control.toggled.connect(growth_controls)
                growth_controls(control.isChecked())
        for key in ("noise_floor_start_db", "noise_floor_max_db", "max_lambda"):
            control = self.controls[4, key]
            form = control.parentWidget().layout()
            caption = form.labelForField(control)

            def show_regularization(on, c=control, label=caption):
                c.setVisible(on)
                label.setVisible(on)

            self.controls[4, "enable_regularization"].toggled.connect(show_regularization)
            show_regularization(self.controls[4, "enable_regularization"].isChecked())

    def _scan_bound_edited(self, key):
        if not self._setting_scan_bounds:
            self.manual_scan_bounds.add(key)

    def restore_scan_bounds_state(self, manual=None):
        """Keep saved edits; older projects adopt defaults only for unchanged bounds."""
        if manual is not None:
            self.manual_scan_bounds = set(manual) & self._default_scan_bounds.keys()
            return
        self.manual_scan_bounds = set()
        for key, default in self._default_scan_bounds.items():
            try:
                current = tuple(float(v) for v in self.controls[2, key].text().split(','))
                original = tuple(float(v) for v in str(default).split(','))
            except ValueError:
                self.manual_scan_bounds.add(key)
                continue
            if current != original:
                self.manual_scan_bounds.add(key)

    def apply_scan_bounds(self, bounds):
        """Update automatically managed fields without replacing manual overrides."""
        self._setting_scan_bounds = True
        try:
            for key in self._default_scan_bounds:
                if key not in self.manual_scan_bounds:
                    self.controls[2, key].setText(', '.join(f'{v:g}' for v in bounds[key]))
        finally:
            self._setting_scan_bounds = False
