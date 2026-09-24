"""GUI regression: no demo fallback and persisted selectable Export panes."""
import bootstrap
import json
from copy import deepcopy
from unittest.mock import patch
from PySide6 import QtWidgets as W, QtCore as C
from workspace import Workspace
from project_ui import ensure_export
import acoustics as ac

app = W.QApplication([])
settings = C.QSettings(str(bootstrap.HERE/'artifacts'/'empty-export-panes.ini'), C.QSettings.IniFormat)
settings.clear()
w = Workspace(start_pool=False, settings=settings)
try:
    assert w.sphere is None
    export = ensure_export(w)
    geometry = export.rows[0].widget(0)
    for pane in export.custom_panes:
        pane.select('cli')
        assert pane.stack.currentWidget() is pane.cli
        pane.select('analysis', 'probe')
    for pane in export.custom_panes:
        for kind in ('response', 'csd', 'impulse'): pane.select_native(kind)
        pane.select('analysis', 'probe')
    export.log.appendPlainText('Shared CLI output')
    assert all('Shared CLI output' in pane.cli.toPlainText() for pane in export.custom_panes)
    w.set_sphere(ac.demo()); w.refresh()
    saved = deepcopy(w.session_dict()['export_setup'])
    assert all(s['mode'] == 'analysis' for s in saved['plot_panes'])
    for pane in export.custom_panes: pane.select('native')
    export.apply_config(saved)
    assert all(p.mode == 'analysis' for p in export.custom_panes)
    assert export.rows[0].widget(0) is geometry
    # Real project opening path, with no coefficients on disk.
    project = bootstrap.HERE/'artifacts'/'empty-coefficient-project.json'
    project.write_text(json.dumps({'project_name': 'Empty', 'hals_viewer': {'session': w.session_dict()}}))
    def open_empty(path):
        export.config.update(project_path=str(path), coeff_path='')
    with patch.object(export, 'open_project', side_effect=open_empty): w.open_path(project)
    assert w.sphere is None and w.source_path is None
    assert not w.play.isEnabled()
    assert all(not pane.chart.fig.axes for pane in w.panes)
    for pane in export.custom_panes:
        pane.select('native'); assert pane.stack.currentWidget() is pane.empty
    print('PASS: empty project clears loaded data; fixed geometry, configurable panes, shared CLI, settings restore')
finally:
    w.close()
