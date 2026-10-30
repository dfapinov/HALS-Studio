"""Readable per-user JSON settings, with one-time migration from QSettings."""
import json
import os
from pathlib import Path
import shutil

from PySide6.QtCore import QSettings

from hals_studio.bootstrap import RESOURCES
from hals_studio.persistence.project_repository import write_project


class JsonSettings:
    """The small QSettings interface used by the UI, backed by JSON files.

    Edit these files with the application closed. Factory defaults are refreshed
    from the bundled copy on startup; user defaults survive application updates.
    """

    def __init__(self, directory, legacy=None):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.preferences_path = self.directory / 'preferences.json'
        self.views_path = self.directory / 'user-default-views.json'
        factory = json.loads((RESOURCES / 'default_views.json').read_text(encoding='utf-8'))
        write_project(self.directory / 'factory-default-views.json', factory)
        first_run = not self.preferences_path.exists()
        self._values = self._read(self.preferences_path)
        if first_run:
            if legacy is not None:
                self._values = {key: legacy.value(key) for key in legacy.allKeys() if key != 'views_v2'}
            if not self.views_path.exists():
                from hals_studio.ui.view_state import template_views
                saved = legacy.value('views_v2', '{}') if legacy is not None else '{}'
                write_project(self.views_path, template_views(saved))
            self.sync()

    @staticmethod
    def _read(path):
        try:
            value = json.loads(path.read_text(encoding='utf-8'))
            if isinstance(value, dict):
                return value
        except FileNotFoundError:
            return {}
        except (ValueError, UnicodeError):
            pass
        # Preserve an invalid hand edit before any later save replaces it.
        shutil.copy2(path, path.with_suffix('.invalid.json'))
        return {}

    def value(self, key, default=None):
        if key == 'views_v2':
            return json.dumps(self._read(self.views_path))
        value = self._values.get(key, default)
        if default is not None:
            try:
                return type(default)(value)
            except (TypeError, ValueError, OverflowError):
                return default
        return value

    def setValue(self, key, value):
        if key == 'views_v2':
            write_project(self.views_path, json.loads(value))
        else:
            self._values[key] = value
            self.sync()

    def sync(self):
        write_project(self.preferences_path, self._values)


def studio_settings():
    directory = Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'HALS Studio' / 'settings'
    return JsonSettings(directory, legacy=QSettings('HALS', 'Studio'))
