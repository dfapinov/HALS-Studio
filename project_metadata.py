"""Double-click waypoint editing; project writes happen only on Save."""
from copy import deepcopy
from pathlib import Path
import json
import tempfile
import os
import numpy as np
from PySide6 import QtCore as C, QtWidgets as W
from export_engine import waypoint, cabinet_geometry

WAYPOINTS = [('Top critical', 'top'), ('Bottom critical', 'bot'), ('Tweeter', 'tw'),
             ('Reference origin', 'ref_origin'), ('Baffle bottom left', 'baffle_bl'),
             ('Baffle top left', 'baffle_tl'), ('Baffle top right', 'baffle_tr')]


def save_project_metadata(path, grid):
    path = Path(path)
    project = json.loads(path.read_text(encoding='utf-8-sig'))
    target = project.setdefault('grid_vars', {})
    for _, prefix in WAYPOINTS:
        for axis in ('r', 'phi', 'z'): target[f'wp_{prefix}_{axis}'] = grid.get(f'wp_{prefix}_{axis}', '')
    target['user_positions'] = deepcopy(grid.get('user_positions', []))
    temporary = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent, prefix='.atlas-metadata-', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name); json.dump(project, stream, indent=2); stream.write('\n')
        os.replace(temporary, path)
    finally:
        if temporary and temporary.exists(): temporary.unlink()


class MetadataEditor(W.QWidget):
    def __init__(self, workspace):
        super().__init__(); self.workspace = workspace; self.filling = False; self.pending = False
        box = W.QVBoxLayout(self); box.setContentsMargins(5, 5, 5, 5)
        help_text = W.QLabel('HALS cylindrical coordinates\nR: radius / mm · φ: azimuth / degrees · Z: height / mm')
        help_text.setWordWrap(True); box.addWidget(help_text)
        self.table = W.QTableWidget(0, 4); self.table.setHorizontalHeaderLabels(['Position', 'R / mm', 'φ / °', 'Z / mm'])
        self.table.verticalHeader().hide(); self.table.horizontalHeader().setSectionResizeMode(0, W.QHeaderView.Stretch)
        for col in (1, 2, 3): self.table.setColumnWidth(col, 65)
        self.table.setEditTriggers(W.QAbstractItemView.DoubleClicked)
        self.table.itemChanged.connect(self.edited); box.addWidget(self.table, 1)
        row = W.QHBoxLayout(); box.addLayout(row)
        self.add_button = W.QPushButton('Add driver'); self.add_button.clicked.connect(self.add_driver); row.addWidget(self.add_button)
        self.remove_button = W.QPushButton('Remove'); self.remove_button.clicked.connect(self.remove_driver); row.addWidget(self.remove_button)
        self.save_button = W.QPushButton('Save'); self.save_button.clicked.connect(self.save); box.addWidget(self.save_button)
        self.note = W.QLabel(); self.note.setWordWrap(True); box.addWidget(self.note)
        self.reload()

    def reload(self):
        self.filling = True; grid = self.workspace.config['project_geometry']; self.table.setRowCount(0)
        for name, prefix in WAYPOINTS: self.add_row(name, [grid.get(f'wp_{prefix}_{axis}', '') for axis in ('r', 'phi', 'z')], fixed=True)
        for entry in grid.get('user_positions', []): self.add_row(entry.get('name', 'Driver'), [entry.get(axis, '') for axis in ('r', 'phi', 'z')])
        self.filling = False; self.pending = False
        self.save_button.setEnabled(bool(self.workspace.config['project_path']))
        self.note.setText('Double-click a field to edit. Save writes to the project JSON.')

    def add_row(self, name, values, fixed=False):
        index = self.table.rowCount(); self.table.insertRow(index)
        for col, value in enumerate([name, *values]):
            item = W.QTableWidgetItem(str(value)); item.setToolTip(str(value))
            if fixed and col == 0: item.setFlags(item.flags() & ~C.Qt.ItemIsEditable)
            self.table.setItem(index, col, item)

    def edited(self, *_):
        if not self.filling:
            self.pending = True; self.apply()

    def add_driver(self):
        self.filling = True; self.add_row('Driver', [0, 0, 0]); self.filling = False; self.edited()
    def remove_driver(self):
        for index in sorted({item.row() for item in self.table.selectedItems()}, reverse=True):
            if index >= len(WAYPOINTS): self.table.removeRow(index); self.edited()

    def read_grid(self):
        grid = deepcopy(self.workspace.config['project_geometry']); grid['user_positions'] = []
        for row in range(self.table.rowCount()):
            name = self.table.item(row, 0).text().strip()
            values = [self.table.item(row, col).text().strip() for col in (1, 2, 3)]
            if any(values):
                if not all(values): raise ValueError(f'{name}: enter all three coordinates, or leave all three blank.')
                numbers = list(map(float, values))
                if not np.isfinite(numbers).all() or numbers[0] < 0: raise ValueError(f'{name}: use finite coordinates and a nonnegative radius.')
            if row < len(WAYPOINTS):
                prefix = WAYPOINTS[row][1]
                for axis, value in zip(('r', 'phi', 'z'), values): grid[f'wp_{prefix}_{axis}'] = value
            elif any(values):
                if not name: raise ValueError('Give each driver/user position a name.')
                grid['user_positions'].append(dict(name=name, **dict(zip(('r', 'phi', 'z'), numbers))))
        return grid

    def apply(self):
        try:
            config = deepcopy(self.workspace.config); config['project_geometry'] = self.read_grid()
            for prefix in ('ref_origin', 'tw'):
                try:
                    xyz = waypoint(config['project_geometry'], prefix)*1000
                    config.update(dict(zip(('offset_x', 'offset_y', 'offset_z'), np.round(xyz, 3).tolist())))
                    break
                except (KeyError, ValueError, TypeError): pass
            if config['dut_depth_x'] <= 0:
                vertices, _, valid = cabinet_geometry(config)
                if valid: config['dut_depth_x'] = float(np.linalg.norm(vertices[2]-vertices[1])*1000)
            self.workspace.apply_config(config, refresh_metadata=False)
            self.pending = False; self.note.setText('Updated in viewer · not saved to project.'); return True
        except (ValueError, TypeError) as exc: self.note.setText(str(exc)); return False

    def save(self):
        if self.pending and not self.apply(): return
        try:
            save_project_metadata(self.workspace.config['project_path'], self.workspace.config['project_geometry'])
            self.note.setText('Saved project metadata.')
            self.workspace.log.appendPlainText('Metadata saved to '+self.workspace.config['project_path'])
        except (OSError, ValueError, TypeError) as exc: self.note.setText('Could not save: '+str(exc))
