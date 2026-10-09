"""Portable file paths embedded in HALS Studio project JSON files."""
from copy import deepcopy
from pathlib import Path, PureWindowsPath


def project_path_value(value, project_dir, *, save=False, require_exists=True):
    """Convert project-owned paths between folder-relative JSON and runtime paths.

    Legacy absolute paths can be recovered from an existing suffix inside the
    current project. Never follow paths belonging to another project copy.
    """
    if not value:
        return ''
    root = Path(project_dir).resolve()
    candidate = Path(value)
    legacy = PureWindowsPath(value) if PureWindowsPath(value).is_absolute() else candidate
    absolute = legacy.is_absolute()
    candidate = (root / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
    try:
        if absolute and not Path(value).is_absolute():
            raise ValueError()
        candidate.relative_to(root)
    except ValueError:
        if not absolute:
            return ''
        parts = legacy.parts[1:]
        for start in range(len(parts)):
            recovered = root.joinpath(*parts[start:]).resolve()
            if recovered.is_relative_to(root) and recovered.exists():
                candidate = recovered
                break
        else:
            return ''
    if save:
        return candidate.relative_to(root).as_posix()
    return str(candidate) if not require_exists or candidate.exists() else ''


def normalize_session_paths(state, project_dir, *, save=False):
    """Normalize the paths in a saved HALS Studio viewer/export session."""
    if not state:
        return state
    state = deepcopy(state)
    layout = state.get('process_layout')
    if layout and layout.get('input_ir_folder'):
        layout['input_ir_folder'] = project_path_value(
            layout['input_ir_folder'], project_dir, save=save)
    state['source'] = project_path_value(state.get('source'), project_dir, save=save) or None
    setup = state.get('export_setup')
    if setup:
        setup = dict(setup)
        for key in ('coeff_path', 'output_dir', 'mic_cal_file', 'mic_cal_fallback', 'project_path'):
            if setup.get(key):
                if key == 'project_path' and not save:
                    setup[key] = str(Path(project_dir).resolve() / Path(setup[key]).name)
                else:
                    setup[key] = project_path_value(setup[key], project_dir, save=save,
                                                    require_exists=key in ('coeff_path', 'mic_cal_file', 'mic_cal_fallback'))
                    if key == 'output_dir' and not save and not setup[key]:
                        setup[key] = str(Path(project_dir).resolve() / 'outputs' / 'response_files')
        state['export_setup'] = setup
    if state.get('axis_source'):
        state['axis_source'] = project_path_value(state['axis_source'], project_dir, save=save) or None
    return state


_PROJECT_FILE_KEYS = {'coeff_path', 'source', 'mic_cal_file', 'mic_cal_fallback',
                      'output_dir', 'input_dir', 'ir_folder', 'axis_source', 'cache',
                      'origin_cache', 'project_path', 'input_ir_folder'}


def normalize_project_paths(value, project_dir):
    """Store project-owned paths in legacy HALS sections relative to the folder."""
    if isinstance(value, dict):
        for key, item in list(value.items()):
            if key in _PROJECT_FILE_KEYS and isinstance(item, str) and item:
                value[key] = project_path_value(item, project_dir, save=True)
            else:
                normalize_project_paths(item, project_dir)
    elif isinstance(value, list):
        for item in value:
            normalize_project_paths(item, project_dir)
    return value
