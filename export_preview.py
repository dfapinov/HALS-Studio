"""Persistent, selected-point Stage 5 previews using HALS Post's preview helper."""
from collections import OrderedDict
from copy import deepcopy
from pathlib import Path
import tempfile
import numpy as np
from extract_pressures_core import PressureEvaluationSession, evaluate_she_field
from export_engine import geometry, validate, PoolAdapter
from acoustics import Cancelled


class PreviewSession(PressureEvaluationSession):
    def __init__(self, path):
        # Own only coefficient data. Reuse Atlas's warm pool, never create a second pool.
        super().__init__(path, use_process_pool=False)
        self.points = OrderedDict(); self.solves = 0

    def evaluate_field(self, coords_sph, **options):
        if self.cancelled(): raise Cancelled()
        keys = [(tuple(map(float, coord)), tuple(sorted(options.items()))) for coord in coords_sph]
        missing = list(dict.fromkeys(key for key in keys if key not in self.points))
        if missing:
            field = evaluate_she_field([key[0] for key in missing], self.data, c_sound=self.c_sound,
                       process_pool=PoolAdapter(self.viewer_pool, self.cancelled, self.progress), show_progress=False, **options)
            if self.cancelled(): raise Cancelled()
            self.solves += 1
            for i, key in enumerate(missing): self.points[key] = field['complex'][:, i].copy()
            self.field = field
        result = dict(self.field, complex=np.column_stack([self.points[key] for key in keys]))
        for key in keys: self.points.move_to_end(key)
        while len(self.points) > 128: self.points.popitem(last=False)
        return result


class PreviewCache:
    """Accessed by one preview worker at a time; invalidated when the HDF5 changes."""
    def __init__(self): self.session = None; self.source = None

    def run(self, config, index, pool, progress, cancelled):
        c = validate(config); path = Path(c['coeff_path']).resolve(); stat = path.stat()
        source = (str(path), stat.st_size, stat.st_mtime_ns)
        if source != self.source:
            self.session = PreviewSession(path); self.source = source
        session = self.session
        session.viewer_pool, session.progress, session.cancelled = pool, progress, cancelled
        layout = geometry(c); reference = layout['reference']
        options = dict(obs_mode=c['obs_mode'], use_optimized_origins=c['use_optimized_origins'],
                       ir_capture_padding_samples=c['ir_capture_padding_samples'] if c['manual_ir_capture_padding'] else None,
                       subtract_tof=c['subtract_tof'], reference_coord_sph=layout['spherical'][reference],
                       reference_distance=float(np.min(layout['base'][:, 2])), apply_mic_cal=c['apply_mic_cal'],
                       mic_cal_file=c['mic_cal_file'], mic_cal_mode=c['mic_cal_mode'],
                       mic_cal_fade_octaves=c['mic_cal_fade_octaves'], frd_db_offset=c['frd_db_offset'])
        with tempfile.TemporaryDirectory(prefix='atlas-preview-') as tmp:
            if c['apply_mic_cal'] and not Path(c['mic_cal_file']).is_file():
                fallback = Path(tmp)/'calibration.txt'; fallback.write_text(c['mic_cal_fallback'], encoding='utf-8')
                options['mic_cal_file'] = str(fallback)
            result = session.evaluate_preview_response(layout['spherical'][index], **options)
        if cancelled(): raise Cancelled()
        progress(100, 'Selected-point preview ready')
        return dict(freqs=result['freqs'], preview_point=dict(complex=result['complex_pre_tof'], mag=result['magnitude'], phase=result['phase']),
                    preview_ir=result['ir'], preview_ir_times=result['ir_times_s'], point_index=index,
                    tof_distance=result['tof_reference_distance'], tof_time=result['tof_reference_time_s'],
                    geometry=layout, config=deepcopy(c), destination=None)
