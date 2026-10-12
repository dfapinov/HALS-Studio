"""Preferences for HALS Studio."""
from PySide6.QtCore import QSettings


def studio_settings():
    return QSettings('HALS', 'Studio')
