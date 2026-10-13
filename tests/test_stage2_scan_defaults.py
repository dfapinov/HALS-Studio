"""Measurement defaults populate full grid bounds without losing manual edits."""
from copy import deepcopy
from types import SimpleNamespace
import pytest
from PySide6.QtWidgets import QApplication
from hals_studio.ui.process_forms import StageForms
from hals_studio.ui.process_workspace import ProcessWorkspace, SCHEMA


@pytest.fixture
def forms():
    app = QApplication.instance() or QApplication([])
    values = {int(stage): {k: deepcopy(s['default']) for k,s in fields.items()}
              for stage, fields in SCHEMA.items()}
    widget = StageForms(SCHEMA, values)
    yield widget
    widget.close()


def populate(forms, radius=250, low=-100, high=350):
    names = {f'mic_r{radius}_ph0_z{low}.wav': [],
             f'mic_r{radius}_ph180_z{high}.wav': []}
    workspace = SimpleNamespace(results={1: (None, names)}, pages=forms)
    ProcessWorkspace.refresh_scan_bounds(workspace)


def test_npz_filename_bounds_populate_before_stage2_and_follow_new_measurements(forms):
    populate(forms)
    assert forms.values[2]['x_bounds'] == '-250, 250'
    assert forms.values[2]['y_bounds'] == '-250, 250'
    assert forms.values[2]['z_bounds'] == '-100, 350'
    assert not forms.manual_scan_bounds
    populate(forms, 300, -150, 400)
    assert forms.values[2]['x_bounds'] == '-300, 300'
    assert forms.values[2]['z_bounds'] == '-150, 400'


def test_manual_bounds_survive_updates_and_saved_state(forms):
    populate(forms)
    forms.controls[2, 'x_bounds'].setText('-500, 500')
    forms.controls[2, 'z_bounds'].setText('0, 100')
    saved_manual = sorted(forms.manual_scan_bounds)
    populate(forms, 300, -150, 400)
    assert forms.values[2]['x_bounds'] == '-500, 500'
    assert forms.values[2]['y_bounds'] == '-300, 300'
    assert forms.values[2]['z_bounds'] == '0, 100'
    forms.restore_scan_bounds_state(saved_manual)
    populate(forms, 400)
    assert forms.values[2]['x_bounds'] == '-500, 500'
    assert forms.values[2]['y_bounds'] == '-400, 400'
    assert forms.values[2]['z_bounds'] == '0, 100'


def test_older_project_defaults_are_replaced_but_custom_bounds_are_preserved(forms):
    forms.controls[2, 'y_bounds'].setText('-20, 30')
    forms.restore_scan_bounds_state()
    populate(forms)
    assert forms.values[2]['x_bounds'] == '-250, 250'
    assert forms.values[2]['y_bounds'] == '-20, 30'
    assert forms.values[2]['z_bounds'] == '-100, 350'


def test_cached_cylinder_can_supply_defaults_without_stage1_results(forms):
    cfg = dict(scan_radius_mm=123.5, x_bounds=(-123.5, 123.5),
               y_bounds=(-123.5, 123.5), z_bounds=(20, 220))
    workspace = SimpleNamespace(results={2: (None, None, None, None, None, cfg)}, pages=forms)
    ProcessWorkspace.refresh_scan_bounds(workspace)
    assert forms.values[2]['x_bounds'] == '-123.5, 123.5'
    assert forms.values[2]['z_bounds'] == '20, 220'
