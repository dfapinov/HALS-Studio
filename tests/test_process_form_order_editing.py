"""Regression coverage for manual order editing after a JSON round trip."""
import json
from types import SimpleNamespace

from hals_studio.ui.process_workspace import ProcessWorkspace


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
