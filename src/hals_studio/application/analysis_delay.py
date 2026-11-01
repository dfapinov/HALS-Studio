"""Estimate Analysis timing from the same native response used by export."""
from hals_studio.application.analysis_native import native_response
from hals_studio.process_engine.stage5_pressure_utils import get_min_phase_delay


def estimated_delay_ms(owner, *, reference=False):
    sphere = owner.sphere
    if sphere is None:
        return 0.
    result = native_response(owner, sphere, reference=reference)
    speed = float(sphere.metadata.get('speed_of_sound', 343.))
    if result is not None:
        if 'estimated_delay_ms' not in result:
            result['estimated_delay_ms'] = get_min_phase_delay(
                result['preview_point']['complex'], result['freqs'], speed) / speed * 1000
        return result['estimated_delay_ms']
    azimuth, elevation = owner.axis if reference else (owner.azimuth.value(), owner.elevation.value())
    pressure = sphere.pressure[:, *sphere.index(azimuth, elevation)]
    return get_min_phase_delay(pressure, sphere.freqs, speed) / speed * 1000
