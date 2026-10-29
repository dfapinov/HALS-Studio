"""Validate a directory of filename-addressed measurements without project metadata."""
from pathlib import Path
import numpy as np
import soundfile as sf
from hals_studio.process_engine.utils import natural_keys, parse_coords_from_filename


def scan_ir_folder(folder):
    accepted, skipped, positions = [], [], set()
    sample_rate = None
    for path in sorted(Path(folder).iterdir(), key=lambda p: natural_keys(p.name)):
        if not path.is_file() or path.suffix.lower() != '.wav':
            continue
        try:
            coords = parse_coords_from_filename(path.name)
            if not np.isfinite(coords).all() or coords[0] <= 0:
                raise ValueError('Invalid coordinates')
        except (ValueError, OverflowError):
            skipped.append(path.name)
            continue
        position = tuple(np.round(coords, 10))
        if position in positions:
            raise ValueError(f'Duplicate measurement coordinates: {path.name}')
        info = sf.info(str(path))
        if not info.frames:
            raise ValueError(f'Empty IR recording: {path.name}')
        if sample_rate is not None and info.samplerate != sample_rate:
            raise ValueError('All measurement WAV files must have the same sample rate.')
        sample_rate = info.samplerate
        positions.add(position)
        accepted.append(path.name)
    if not accepted:
        raise ValueError('No WAV files with compatible HALS coordinate filenames were found.')
    return accepted, skipped


def metadata_availability(project):
    flags = project.get('measurement_metadata', {})
    grid = project.get('grid_vars', {})
    stage2 = project.get('stage2_vars', {})
    tweeter = all(grid.get('wp_tw_' + a) not in (None, '') for a in ('r', 'phi', 'z'))
    tweeter |= all(stage2.get('tweeter_' + a) not in (None, '') for a in 'xyz')
    rft = any(project.get(f'stage{s}_vars', {}).get('fdw_rft_ms') not in (None, '') for s in (1, 3))
    return bool(flags.get('tweeter_supplied', tweeter)), bool(flags.get('rft_supplied', rft))
