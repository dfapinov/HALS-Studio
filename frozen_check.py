"""Exercise the compiled app without showing a window or changing user settings."""
import json
import traceback
from pathlib import Path


def run(output):
    report = Path(output).resolve()
    report.parent.mkdir(parents=True, exist_ok=True)
    result = {'ok': False}
    window = None
    try:
        import bootstrap
        from PySide6 import QtWidgets as W, QtCore as C
        from workspace import Workspace
        import process_service
        from hals_engine.stage5_extract_pressures import calculate_cta2034_energy_metrics
        from cta_coordinates import generate_cta2034_coords
        import numpy as np
        for path in ('studio.ico', 'assets/speaker.svg', 'process_schema.json', 'process_engine/session_pool.py'):
            assert (bootstrap.HERE/path).is_file(), 'Missing packaged resource: '+path
        app = W.QApplication.instance() or W.QApplication([])
        window = Workspace(start_pool=False, settings=C.QSettings(str(report.with_suffix('.ini')), C.QSettings.IniFormat))
        assert window.sphere is None
        coords, indices, _ = generate_cta2034_coords(1., 90., 0.)
        metrics = calculate_cta2034_energy_metrics(np.ones((2, len(coords))), indices)
        assert all(np.allclose(value, 0) for value in metrics.values())
        # A real spawned worker imports the dynamically loaded Stage 1-4 engines.
        from worker_pool import WarmPool
        pool = WarmPool(1)
        try:
            pool.start()
            assert pool._ready.wait(60), 'Worker initialization timed out'
            assert pool.state == 'ready', pool.error
        finally:
            pool.close()
        result = {'ok': True, 'checks': ['resources', 'Qt workspace', 'CTA metrics', 'spawned processing worker']}
    except Exception:
        result['error'] = traceback.format_exc()
    finally:
        if window is not None: window.close()
        report.write_text(json.dumps(result, indent=2), encoding='utf-8')
    return 0 if result['ok'] else 1
