"""Schema-driven Process stage forms and their local control dependencies."""

from PySide6 import QtCore as C, QtWidgets as W

from hals_studio import bootstrap

MAIN = {
    1: ["fdw_oct_res", "fdw_max_cap_ms"],
    2: ["freq_start_hz", "freq_end_hz"],
    3: ["freq_end_hz", "freq_start_hz"],
    4: ["target_n_max"],
}


class StageForms(W.QStackedWidget):
    rft_reset_requested = C.Signal()
    edit_orders_requested = C.Signal()
    help_requested = C.Signal(str, str)

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
                seed_group = W.QGroupBox("HF search seed")
                seedform = W.QFormLayout(seed_group)
                grid_group = W.QGroupBox()
                gridform = W.QFormLayout(grid_group)
                gridform.addRow(W.QLabel("Full Grid Rescan Only"))
                grid_note = W.QLabel("XYZ bounds default to the measurement extents. Edit them to scan a smaller or larger volume.")
                grid_note.setWordWrap(True)
                gridform.addRow(grid_note)
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
                    if stage == 2 and key == "tweeter_x":
                        advancedform.addRow(seed_group)
                    if stage == 2 and key in ("tweeter_x", "tweeter_y", "tweeter_z"):
                        target = seedform
                    if stage == 2 and key in ("x_bounds", "y_bounds", "z_bounds", "grid_res_mm"):
                        target = gridform
                        if key.endswith("_bounds"):
                            control.textChanged.connect(lambda _, k=key: self._scan_bound_edited(k))
                        control.setToolTip("Full grid re-scan only. " + spec["help"])
                    target.addRow(caption, field)
                self.controls[stage, key] = control
            if stage == 2:
                mainform.addRow(self._help_note(
                    "Set the lower and upper frequencies to the DUT's usable frequency range.",
                    "stage2_origin_help.md", "upper-frequency",
                    "Help: Stage 2 upper and lower frequency",
                ))
                holds = W.QWidget()
                holdrow = W.QHBoxLayout(holds)
                holdrow.setContentsMargins(0, 0, 0, 0)
                for key in ("hold_origin_lf", "hold_origin_hf"):
                    control = self.controls[2, key]
                    control.setText(schema["2"][key]["label"])
                    holdrow.addWidget(control)
                holdrow.addStretch()
                advancedform.addRow("Hold coordinate outside test range", holds)
                advancedform.addRow(grid_group)
            if stage == 3:
                mainform.addRow(self._help_note(
                    "The reflection-free range is where Stage 1 windowing has removed room "
                    "reflections. It is distinct from the DUT's usable frequency range.",
                    "stage3_help.md", "upper-test-range",
                    "Help: Stage 3 upper test range",
                ))
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
                def select_manual(checked, optimizer=optimizer, button=edit):
                    if checked:
                        optimizer.setChecked(False)
                    button.setEnabled(checked)

                def select_optimizer(checked, manual=control):
                    if checked:
                        manual.setChecked(False)

                control.toggled.connect(select_manual)
                optimizer.toggled.connect(select_optimizer)
                select_manual(control.isChecked())
        for key in ("noise_floor_start_db", "noise_floor_max_db", "max_lambda"):
            control = self.controls[4, key]
            form = control.parentWidget().layout()
            caption = form.labelForField(control)

            def show_regularization(on, c=control, label=caption):
                c.setVisible(on)
                label.setVisible(on)

            self.controls[4, "enable_regularization"].toggled.connect(show_regularization)
            show_regularization(self.controls[4, "enable_regularization"].isChecked())

    def _help_note(self, message, filename, heading, accessible_name):
        badge_url = C.QUrl.fromLocalFile(str(bootstrap.RESOURCES / "assets" / "help_badge_small.png"))
        note = W.QLabel(
            f'{message} <a href="help"><img src="{badge_url.toString()}" '
            'width="20" height="20" style="vertical-align:middle"></a>'
        )
        note.setWordWrap(True)
        note.setAccessibleName(accessible_name)
        note.setToolTip(accessible_name)
        note.linkActivated.connect(lambda _: self.help_requested.emit(filename, heading))
        return note

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
