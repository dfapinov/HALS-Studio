import json

from PySide6.QtCore import QSettings

from hals_studio.persistence.preferences import JsonSettings
from hals_studio.ui.view_state import default_views, template_views


def test_json_settings_migrate_once_and_keep_templates_separate(tmp_path):
    legacy = QSettings(str(tmp_path / 'legacy.ini'), QSettings.IniFormat)
    legacy.setValue('theme', 'Light')
    custom = {'My view': default_views()['Sound field']}
    legacy.setValue('views_v2', json.dumps(custom))
    directory = tmp_path / 'settings'
    settings = JsonSettings(directory, legacy)
    assert settings.value('theme', 'Dark') == 'Light'
    assert template_views(settings.value('views_v2')) == custom
    assert json.loads((directory / 'factory-default-views.json').read_text()) == default_views()
    assert 'views_v2' not in json.loads((directory / 'preferences.json').read_text())
    settings.setValue('theme', 'Dark')
    legacy.setValue('theme', 'Light')
    assert JsonSettings(directory, legacy).value('theme') == 'Dark'


def test_json_settings_load_hand_edits_and_preserve_invalid_json(tmp_path):
    settings = JsonSettings(tmp_path)
    settings.preferences_path.write_text('{"worker_count": "invalid", "theme": "Light"}')
    settings.views_path.write_text('{broken')
    settings = JsonSettings(tmp_path)
    assert settings.value('worker_count', 0) == 0
    assert settings.value('theme') == 'Light'
    assert template_views(settings.value('views_v2')) == default_views()
    assert settings.views_path.with_suffix('.invalid.json').read_text() == '{broken'
    settings.setValue('views_v2', json.dumps(default_views()))
    assert json.loads(settings.views_path.read_text()) == default_views()


def test_missing_user_template_uses_factory_without_remigrating(tmp_path):
    settings = JsonSettings(tmp_path)
    settings.views_path.unlink()
    settings = JsonSettings(tmp_path)
    assert template_views(settings.value('views_v2')) == default_views()


def test_invalid_preferences_are_backed_up_before_save(tmp_path):
    settings = JsonSettings(tmp_path)
    settings.preferences_path.write_text('[]')
    settings = JsonSettings(tmp_path)
    settings.setValue('theme', 'Dark')
    assert settings.preferences_path.with_suffix('.invalid.json').read_text() == '[]'
    assert json.loads(settings.preferences_path.read_text()) == {'theme': 'Dark'}
