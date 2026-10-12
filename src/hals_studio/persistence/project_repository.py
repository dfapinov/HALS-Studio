"""Project persistence without widgets, dialogs, or application-window state."""

import json
import os
import tempfile
from copy import deepcopy
from pathlib import Path


PROJECT_STATE_VERSION = 1
SESSION_VERSION = 2


def read_project(path):
    payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("A HALS project must contain a JSON object.")
    studio_state(payload)  # Reject unsupported versions before updating widgets.
    return payload


def studio_state(payload):
    """Read the current namespace or migrate the legacy viewer namespace in memory."""
    state = deepcopy(payload.get("hals_studio", payload.get("hals_viewer", {})))
    if not isinstance(state, dict):
        raise ValueError("HALS Studio project state must be an object.")
    version = state.get("version", PROJECT_STATE_VERSION)
    if version != PROJECT_STATE_VERSION:
        raise ValueError(f"Unsupported HALS Studio project version: {version}")
    if state.get("session") is not None:
        validate_session(state["session"])
    return state


def validate_session(state):
    if not isinstance(state, dict):
        raise ValueError("Session state must be an object.")
    # Legacy embedded sessions omitted the version; they already used this layout.
    if state.get("version", SESSION_VERSION) != SESSION_VERSION:
        raise ValueError("This workspace requires a version 2 four-pane session.")
    for key in ("view", "export_setup", "process_layout"):
        if state.get(key) is not None and not isinstance(state[key], dict):
            raise ValueError(f"Session {key} must be an object.")
    return deepcopy(state)


def write_project(path, payload):
    """Replace only a fully serialized project; preserve the prior file on failure."""
    path = Path(path)
    content = json.dumps(payload, indent=2)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, suffix=".tmp", delete=False
        ) as stream:
            temporary = stream.name
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)
