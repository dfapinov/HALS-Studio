"""Unified project/coefficient opening and explicit project persistence."""
import json
import os
from pathlib import Path
from copy import deepcopy
from hals_studio.persistence.project_repository import read_project, studio_state, write_project
from PySide6 import QtWidgets as W, QtCore as C, QtGui as G
from hals_studio.application.export_engine import DEFAULT_EXPORT
from hals_studio.persistence.project_paths import normalize_project_paths, normalize_session_paths, project_path_value


def choose_data(owner):
    path, _ = W.QFileDialog.getOpenFileName(owner, 'Open HALS data',
        str(owner.settings.value('browse_folder', '')) or (str(Path(owner.project_path).parent) if owner.project_path else str(Path.home())),
        'HALS project / recordings / coefficients / sphere (*.json *.h5 *.hdf5 *.npz *.wav);;All files (*)')
    return path or None


def ensure_export(owner):
    if owner.export_workspace is None:
        from hals_studio.ui.export_workspace import ExportWorkspace
        owner.export_workspace = ExportWorkspace(owner); owner.workspace_stack.addWidget(owner.export_workspace)
        if owner.export_setup: owner.export_workspace.apply_config(owner.export_setup)
        owner.set_theme(owner.theme_name)
    return owner.export_workspace


def open_data_path(owner, path, options=None):
    if getattr(owner,'process_workspace',None) and owner.process_workspace.job:
        owner.statusBar().showMessage('Wait for processing to finish or cancel it before opening data.');return
    if owner.worker and owner.worker.isRunning():
        owner.statusBar().showMessage('Wait for reconstruction to finish or cancel it before opening data.'); return
    pane = ensure_export(owner)
    if pane.job:
        owner.statusBar().showMessage('Wait for the current evaluation/export to finish before opening data.'); return
    path = Path(path).resolve()
    owner.analysis.available_path = None
    try:
        if path.suffix.lower() == '.wav':
            open_ir_recording(owner, path)
            return
        if path.is_dir() or path.suffix.lower() == '.json':
            from hals_studio.application.export_engine import project_files
            # Validate the selected project before applying any persisted UI state.
            candidates = project_files(path) if path.is_dir() else [path]
            if len(candidates) == 1:
                read_project(candidates[0])
            pane.open_project(path)
            project = pane.config.get('project_path')
            if not project: return
            owner.project_path = project; owner.dataset_label.setText(Path(project).stem.replace('_project','')); owner.project_path_field.setText(str(Path(project).parent))
            if getattr(owner,'process_workspace',None):owner.process_workspace.adopt_project(force=True)
            owner.pending_session = None
            owner.set_sphere(None)
            payload = read_project(project)
            saved = studio_state(payload)
            project_dir = Path(project).parent
            state = normalize_session_paths(saved.get('session'), project_dir)
            restored = {name: view for name, view in saved.get('views', {}).items()
                        if name not in ('Beam tunnel', 'Beam tube') and owner.valid_view(view)}
            if restored:
                # The project's collection is authoritative, including deletions.
                owner.views = restored
                name = saved.get('current_view')
                if name not in owner.views: name = next(iter(owner.views))
                owner.rebuild_view_buttons()
                owner.apply_view(owner.views[name]); owner.select_view_name(name)
            else:
                owner.reset_views()
            coeff = pane.config['coeff_path']
            if not coeff and state:
                coeff = project_path_value(state.get('source'), project_dir)
                pane.config['coeff_path'] = coeff
            if state and owner.valid_view(state.get('view')):
                state['source'] = coeff
                state['export_setup'] = dict(pane.config, **state.get('export_setup', {}))
                state['export_setup'].update(project_path=project, coeff_path=coeff, project_geometry=pane.config['project_geometry'])
                owner.pending_session = state
                options = options or state.get('reconstruction')
            if coeff:
                owner.analysis.open_path(coeff, options)
            elif state: owner.apply_pending_session()
            else: owner.statusBar().showMessage('Project opened; no coefficients found in outputs/coefficients.')
        else:
            owner.project_path = None; owner.project_path_field.setText(str(path))
            pane.apply_config(dict(deepcopy(DEFAULT_EXPORT), coeff_path=str(path) if path.suffix.lower() in ('.h5', '.hdf5') else '', frd_prefix=path.stem))
            owner.analysis.open_path(path, options)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc: owner.error(str(exc))


def save_project(owner):
    pane = ensure_export(owner)
    process=getattr(owner,'process_workspace',None)
    editor=getattr(process,'metadata_editor',None)
    if editor and editor.pending and not editor.apply():return
    if pane.metadata_editor.pending and not pane.metadata_editor.apply(): return
    target = owner.project_path or pane.config.get('project_path')
    if not target:
        target, _ = W.QFileDialog.getSaveFileName(owner, 'Save Project', 'project.json', 'HALS project (*.json)')
        if not target: return
    try:
        path = Path(target); payload = read_project(path) if path.exists() else {}
        payload.setdefault('project_name', path.parent.name)
        save_process = process is not None and (process.loaded is None or Path(process.loaded).resolve() == path.resolve())
        if save_process:
            for key,value in owner.process_workspace.project_payload().items():
                if isinstance(value,dict):payload.setdefault(key,{}).update(value)
                else:payload[key]=value
        payload.setdefault('grid_vars', {}).update(deepcopy(pane.config['project_geometry']))
        pane.config['project_path'] = str(path); owner.project_path = str(path)
        owner.views[owner.current_view] = owner.view_dict()
        payload.pop('hals_viewer', None)
        normalize_project_paths(payload, path.parent)
        session = normalize_session_paths(owner.session_dict(), path.parent, save=True)
        payload['hals_studio'] = dict(version=1, views=deepcopy(owner.views), current_view=getattr(owner, 'current_view', ''), session=session)
        # Existing HALS processing sections remain intact; viewer state is namespaced.
        write_project(path, payload)
        if save_process: process.loaded = str(path)
        owner.project_path_field.setText(str(path.parent)); pane.metadata_editor.reload()
        owner.statusBar().showMessage('Project saved: '+str(path))
    except (OSError, ValueError, TypeError) as exc: owner.error('Could not save project: '+str(exc))


def open_ir_recording(owner, path):
    from hals_studio.application.ir_recovery import scan_ir_folder
    from hals_studio.application.export_engine import project_files
    names, skipped = scan_ir_folder(path.parent)
    if path.name not in names:
        raise ValueError('Select a WAV with a compatible HALS coordinate filename.')
    root = path.parent.parent
    try:
        existing = project_files(root)
    except ValueError:
        existing = []
    message = (f'Opening a WAV scans its directory for all compatible measurement WAVs.\n'
               f'Found {len(names)} compatible files; skipped {len(skipped)} incompatible filenames.\n'
               f'Input: {path.parent}\nOutputs: {root / "outputs"}\n\n'
               'Opening the project JSON is preferable because it retains measurement metadata and settings.')
    if existing:
        W.QMessageBox.information(owner, 'Open measurement recordings', message +
                                 '\n\nAn existing project was found and will be used.')
        open_data_path(owner, root)
        if not owner.project_path or Path(owner.project_path).parent != root:
            return
        owner.set_workspace(2)
        process = owner.process_workspace
    else:
        W.QMessageBox.information(owner, 'Open measurement recordings', message +
            '\n\nNo RFT was supplied. Stage 1 will use 5 ms for the alpha taper without highlighting a reflection-free range. '
            'A project JSON will be created after Stage 1 succeeds.')
        owner.project_path = None
        owner.set_workspace(2)
        process = owner.process_workspace
        name = root.name
        target = root / (name + '_project.json')
        owner.project_path = str(target)
        owner.project_path_field.setText(str(root))
        pane = ensure_export(owner)
        pane.apply_config(dict(deepcopy(DEFAULT_EXPORT), project_path=str(target), project_name=name,
                               output_dir=str(root / 'outputs' / 'response_files'), frd_prefix=name))
        owner.pending_session = None
        owner.source_path = None
        owner.source_options = None
        owner.set_sphere(None)
        owner.reset_views()
        process.adopt_project(force=True, payload=dict(project_name=name,
            measurement_metadata=dict(rft_supplied=False, tweeter_supplied=False, wav_recovery=True)))
    process.ir_folder.setText(str(path.parent))
    process.filter_ir_filenames = True
    process.select_stage(1)
