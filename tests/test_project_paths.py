from hals_studio.persistence.project_paths import normalize_project_paths, normalize_session_paths, project_path_value


def test_process_input_folder_moves_with_project(tmp_path):
    original = tmp_path / 'original'
    backup = tmp_path / 'backup'
    for root in (original, backup):
        (root / 'measurement_set').mkdir(parents=True)
    state = {'process_layout': {'stage': 2, 'input_ir_folder': str(original / 'measurement_set')}}

    saved = normalize_session_paths(state, original, save=True)
    assert saved['process_layout']['input_ir_folder'] == 'measurement_set'
    assert state['process_layout']['input_ir_folder'] == str(original / 'measurement_set')
    restored = normalize_session_paths(saved, backup)
    assert restored['process_layout']['input_ir_folder'] == str(backup / 'measurement_set')
    assert restored['process_layout']['stage'] == 2
    assert normalize_session_paths(state, backup)['process_layout']['input_ir_folder'] == str(backup / 'measurement_set')
    assert normalize_project_paths(state, original)['process_layout']['input_ir_folder'] == 'measurement_set'


def test_legacy_windows_paths_recover_existing_project_suffix(tmp_path):
    root = tmp_path / 'moved'
    asset = root / 'outputs' / 'coefficients' / 'speaker.h5'
    asset.parent.mkdir(parents=True)
    asset.touch()
    old = r'D:\Jans Measurments\ELAC-Debut2.0\outputs\coefficients\speaker.h5'
    assert project_path_value(old, root) == str(asset)
    assert project_path_value(old, root, save=True) == 'outputs/coefficients/speaker.h5'
    assert project_path_value(r'D:\old\missing.h5', root, save=True) == ''
    assert project_path_value('../outside.h5', root, save=True) == ''


def test_project_paths_are_relative_and_bound_to_project_copy(tmp_path):
    original = tmp_path / 'original'
    backup = tmp_path / 'backup'
    external = original / 'outputs' / 'coefficients' / 'speaker_coefficients.h5'
    external.parent.mkdir(parents=True)
    external.touch()
    (backup / 'outputs' / 'coefficients').mkdir(parents=True)

    assert project_path_value(external, original, save=True) == 'outputs/coefficients/speaker_coefficients.h5'
    assert project_path_value('outputs/coefficients/speaker_coefficients.h5', backup) == ''
    assert project_path_value(external, backup) == ''

    local = backup / 'outputs' / 'coefficients' / external.name
    local.touch()
    assert project_path_value('outputs/coefficients/speaker_coefficients.h5', backup) == str(local)


def test_project_session_saves_assets_relatively_and_drops_external_paths(tmp_path):
    root = tmp_path / 'project'
    mic_cal = root / 'mic_cal.txt'
    root.mkdir()
    mic_cal.touch()
    external = tmp_path / 'other-copy' / 'coefficients.h5'
    external.parent.mkdir()
    external.touch()
    state = {
        'source': str(external),
        'axis_source': str(root / 'speaker_project.json'),
        'export_setup': {
            'coeff_path': str(external),
            'mic_cal_file': str(mic_cal),
            'output_dir': str(root / 'outputs' / 'response_files'),
            'project_path': str(root / 'speaker_project.json'),
        },
    }

    saved = normalize_session_paths(state, root, save=True)
    assert saved['source'] is None
    assert saved['axis_source'] == 'speaker_project.json'
    assert saved['export_setup'] == {
        'coeff_path': '', 'mic_cal_file': 'mic_cal.txt',
        'output_dir': 'outputs/response_files', 'project_path': 'speaker_project.json',
    }
    assert state['export_setup']['coeff_path'] == str(external)

    restored = normalize_session_paths(saved, root)
    assert restored['source'] is None
    assert restored['export_setup']['mic_cal_file'] == str(mic_cal)
    assert restored['export_setup']['output_dir'] == str(root / 'outputs' / 'response_files')


def test_legacy_project_settings_keep_relative_asset_paths(tmp_path):
    root = tmp_path / 'project'
    root.mkdir()
    payload = {'stage5_vars': {'output_dir': 'outputs/response_files', 'mic_cal_file': 'mic_cal.txt'},
               'mic_cal_fallback': 'mic_cal.txt'}

    result = normalize_project_paths(payload, root)
    assert result['stage5_vars'] == {'output_dir': 'outputs/response_files', 'mic_cal_file': 'mic_cal.txt'}
    assert result['mic_cal_fallback'] == 'mic_cal.txt'
