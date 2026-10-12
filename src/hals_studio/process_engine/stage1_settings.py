"""Read processing provenance, including resolution recoverable from older NPZs."""
import math


def settings_from_npz(data):
    if 'stage1_settings' in data:
        return dict(data['stage1_settings'].item())
    # Old files recorded the RFT boundary, which uniquely determines FDW cycles.
    meta = data['meta'].item() if 'meta' in data else {}
    resolutions = []
    for row in meta.values():
        try:
            cycles = float(row['f_trans']) * float(row['rft_ms']) / 1000
            if math.isfinite(cycles) and cycles > 0:
                resolutions.append(1 / math.log2(1 + 1 / cycles))
        except (KeyError, ValueError, TypeError):
            pass
    if resolutions and all(math.isclose(v, resolutions[0]) for v in resolutions):
        return {'fdw_oct_res': round(resolutions[0], 10)}
    return {}


def settings_differences(recorded, visible):
    differences = {}
    for key, value in recorded.items():
        if key not in visible:
            continue
        current = visible[key]
        try:
            equal = math.isclose(float(value), float(current), rel_tol=1e-9)
        except (ValueError, TypeError):
            equal = str(value).lower() == str(current).lower()
        if not equal:
            differences[key] = (current, value)
    return differences
