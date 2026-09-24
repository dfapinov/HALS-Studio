"""Studio preferences, with a one-time import from the earlier Viewer app."""
from PySide6.QtCore import QSettings


def studio_settings():
    settings = QSettings('HALS', 'Studio')
    if not settings.contains('viewer_preferences_migrated'):
        legacy = QSettings('HALS', 'Atlas')
        for key in legacy.allKeys():
            if not settings.contains(key): settings.setValue(key, legacy.value(key))
        settings.setValue('viewer_preferences_migrated', True)
        settings.sync()
    return settings
