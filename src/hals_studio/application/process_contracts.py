"""Validated application requests and named results at the engine boundary."""

from copy import deepcopy
from dataclasses import dataclass
from enum import IntEnum
from functools import lru_cache
import json
import math
from pathlib import Path
from typing import Any, NamedTuple, TypedDict


class Stage(IntEnum):
    FDW = 1
    ORIGINS = 2
    ORDER = 3
    SOLVE = 4


@lru_cache(maxsize=1)
def _settings_schema():
    import hals_studio.bootstrap as bootstrap

    return json.loads((bootstrap.RESOURCES / "process_schema.json").read_text(encoding="utf-8"))


def validated_settings(stage, supplied):
    schema = _settings_schema()[str(int(stage))]
    settings = {key: deepcopy(field["default"]) for key, field in schema.items()}
    settings.update(deepcopy(supplied))
    integers = {
        "fdw_windows_per_oct",
        "target_n_max_origins",
        "max_iterations",
        "spl_sphere_points",
        "target_n_max",
    }
    positive = {
        "fdw_oct_res",
        "fdw_windows_per_oct",
        "octave_resolution",
        "initial_simplex_step",
        "max_iterations",
        "grid_res_mm",
        "spl_sphere_points",
        "spl_radius_m",
        "fdw_rft_ms",
    }
    for key, field in schema.items():
        value = settings[key]
        if isinstance(field["default"], bool):
            if not isinstance(value, bool):
                raise ValueError(f"{field['label']} must be enabled or disabled.")
            continue
        if key == "smoothing_oct_res" and str(value).lower() == "auto":
            continue
        try:
            values = [float(part.strip()) for part in str(value).split(",")]
        except (TypeError, ValueError):
            raise ValueError(f"{field['label']} requires a numeric value.") from None
        if not all(math.isfinite(number) for number in values):
            raise ValueError(f"{field['label']} must be finite.")
        if key.endswith("_bounds") or key == "test_order_range":
            if len(values) != 2 or values[0] > values[1]:
                raise ValueError(f"{field['label']} requires an ordered pair.")
            if key == "test_order_range" and any(n < 0 or n != int(n) for n in values):
                raise ValueError("Order range requires nonnegative integers.")
        elif len(values) != 1:
            raise ValueError(f"{field['label']} requires one number.")
        elif key in integers and values[0] != int(values[0]):
            raise ValueError(f"{field['label']} requires an integer.")
        elif key in positive and values[0] <= 0:
            raise ValueError(f"{field['label']} must be positive.")
    return settings


class JobResult(TypedDict, total=False):
    ok: bool
    stage: int
    cache: str
    cancelled: bool
    error: str


class OriginResult(NamedTuple):
    """Named fields while retaining legacy tuple indexing and unpacking."""

    rows: dict
    frequencies: Any
    filenames: Any
    spectra: Any
    geometry: Any
    config: dict
    data: Any


@dataclass(frozen=True)
class ProcessRequest:
    stage: Stage
    settings: dict
    folder: Path
    name: str
    cache: Path
    options: dict

    @classmethod
    def from_mapping(cls, value):
        if not isinstance(value, dict):
            raise ValueError("Processing request must be an object.")
        try:
            stage = Stage(int(value["stage"]))
        except (KeyError, TypeError, ValueError):
            raise ValueError("Choose a processing stage from 1 to 4.") from None
        if isinstance(value["stage"], bool) or str(value["stage"]) != str(int(stage)):
            raise ValueError("Processing stage must be an integer from 1 to 4.")
        settings = value.get("settings")
        if not isinstance(settings, dict):
            raise ValueError("Processing settings must be an object.")
        name = value.get("name", "")
        if (
            not isinstance(name, str)
            or not name.strip()
            or name in (".", "..")
            or any(c in name for c in '<>:"/\\|?*')
            or any(ord(c) < 32 for c in name)
        ):
            raise ValueError("Use a project name without path separators or reserved characters.")
        action = value.get("action", "run")
        allowed = {
            Stage.FDW: {"run"},
            Stage.ORIGINS: {"run", "rescan", "save_origins", "load_origins"},
            Stage.ORDER: {"run", "reference"},
            Stage.SOLVE: {"run"},
        }
        if action not in allowed[stage]:
            raise ValueError(f"Unsupported action for Stage {stage}: {action}")
        for key in ("folder", "cache"):
            if not isinstance(value.get(key), (str, Path)) or not str(value[key]).strip():
                raise ValueError(f"Processing request requires {key}.")
        options = deepcopy(value)
        for key in ("ir_folder", "origin_cache"):
            if options.get(key):
                options[key] = str(Path(options[key]).resolve())
        return cls(
            stage,
            validated_settings(stage, settings),
            Path(value["folder"]).resolve(),
            name,
            Path(value["cache"]).resolve(),
            options,
        )

    def to_mapping(self):
        return dict(
            deepcopy(self.options),
            stage=int(self.stage),
            settings=deepcopy(self.settings),
            folder=str(self.folder),
            name=self.name,
            cache=str(self.cache),
        )
