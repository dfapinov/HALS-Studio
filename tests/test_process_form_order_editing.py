"""Regression coverage for manual order editing after a JSON round trip."""
import json
import os
from copy import deepcopy
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6 import QtWidgets as W
from hals_studio.ui.process_workspace import ProcessWorkspace, SCHEMA
from hals_studio.ui.process_forms import StageForms


def test_edit_orders_after_project_round_trip():
    table = json.loads(json.dumps({1000.: 4, 200.: 2, 625.5: 3}))
    captured = []
    def dialog(title, headers, rows, editable):
        captured.extend(rows)
        return [['200', '2'], ['625.5', '4'], ['1000', '5']]
    workspace = SimpleNamespace(manual_table=table, table_dialog=dialog)
    ProcessWorkspace.edit_orders(workspace)
    assert captured == [['200', 2], ['625.5', 3], ['1000', 4]]
    assert workspace.manual_table == {200.: 2, 625.5: 4, 1000.: 5}


def test_growth_modes_and_stage2_layout():
    app = W.QApplication.instance() or W.QApplication([])
    values = {int(stage): {key: deepcopy(spec['default']) for key, spec in fields.items()}
              for stage, fields in SCHEMA.items()}
    forms = StageForms(SCHEMA, values)
    manual = forms.controls[4, 'use_manual_table']
    optimizer = forms.controls[4, 'condition_preflight']
    edit = next(b for b in forms.findChildren(W.QPushButton) if b.text() == 'Edit manual order table')
    assert optimizer.isChecked() and manual.isEnabled() and not edit.isEnabled()
    manual.click()
    assert manual.isChecked() and not optimizer.isChecked() and edit.isEnabled()
    optimizer.click()
    assert optimizer.isChecked() and not manual.isChecked() and not edit.isEnabled()
    manual.click()
    assert manual.isChecked() and not optimizer.isChecked() and edit.isEnabled()
    manual.click()
    assert not manual.isChecked() and not optimizer.isChecked() and not edit.isEnabled()
    assert forms.controls[2, 'freq_end_hz'].parentWidget().title() == 'Main Settings'
    stage2_main = forms.controls[2, 'freq_end_hz'].parentWidget()
    labels = stage2_main.findChildren(W.QLabel)
    assert any(label.text() == 'Lower Frequency (Hz)' for label in labels)
    assert any(label.text() == 'Upper Frequency (Hz)' for label in labels)
    assert any("DUT's usable frequency range" in label.text() for label in labels)
    assert all('Stage 2 help:' not in label.text() for label in labels)
    assert not any('cylindrical bounds' in label.text() for label in labels)
    assert forms.controls[2, 'octave_resolution'].parentWidget().title() == 'Advanced Settings'
    stage3_main = forms.controls[3, 'freq_end_hz'].parentWidget()
    assert all('Stage 3 help:' not in label.text() for label in stage3_main.findChildren(W.QLabel))
    help_labels = {label.accessibleName(): label for label in forms.findChildren(W.QLabel)
                   if label.accessibleName().startswith('Help:')}
    assert set(help_labels) == {'Help: Stage 2 upper and lower frequency',
                                'Help: Stage 3 upper test range'}
    assert all('help_badge_small.png' in label.text() and '<img ' in label.text()
               for label in help_labels.values())
    requested = []
    forms.help_requested.connect(lambda file, heading: requested.append((file, heading)))
    help_labels['Help: Stage 2 upper and lower frequency'].linkActivated.emit('help')
    help_labels['Help: Stage 3 upper test range'].linkActivated.emit('help')
    assert requested == [('stage2_origin_help.md', 'upper-frequency'),
                         ('stage3_help.md', 'upper-test-range')]
    advanced = forms.advanced[2][1].layout()
    assert advanced.itemAt(0, W.QFormLayout.FieldRole).widget() is forms.controls[2, 'octave_resolution']
    seed = forms.controls[2, 'tweeter_x'].parentWidget()
    assert seed.title() == 'HF search seed'
    assert all(forms.controls[2, f'tweeter_{axis}'].parentWidget() is seed for axis in 'xyz')
    assert advanced.itemAt(1, W.QFormLayout.SpanningRole).widget() is seed
    bounds = forms.controls[2, 'x_bounds'].parentWidget()
    assert advanced.itemAt(advanced.rowCount()-1, W.QFormLayout.SpanningRole).widget() is bounds
    assert any(label.text() == 'Full Grid Rescan Only' for label in bounds.findChildren(W.QLabel))
    forms.close()
