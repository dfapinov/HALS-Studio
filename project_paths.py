"""Portable file paths embedded in HALS Studio project JSON files."""
from copy import deepcopy
from pathlib import Path


def project_path_value(value, project_dir, *, save=False, require_exists=True):
    """Convert project-owned paths between folder-relative JSON and runtime paths.

    Paths outside the project are intentionally not persisted in a project JSON;
    that prevents a backup copy from accidentally loading files from its source.
    """
    if not value:
        return ''
    root = Path(project_dir).resolve()
    candidate = Path(value)
    if save:
        candidate = (root / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
        try:
            return candidate.relative_to(root).as_posix()
        except ValueError:
            return ''
    candidate = (root / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return ''
    return str(candidate) if not require_exists or candidate.exists() else ''


def normalize_session_paths(state, project_dir, *, save=False):
    """Normalize the paths in a saved HALS Studio viewer/export session."""
    if not state:
        return state
    state = deepcopy(state)
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
                      'origin_cache', 'project_path'}


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
