"""Project RFT import and Stage 3 reflection-free frequency boundary."""
import math


def transition_frequency_hz(rft_ms, oct_res):
    rft_ms, oct_res = float(rft_ms), float(oct_res)
    if not all(math.isfinite(v) and v > 0 for v in (rft_ms, oct_res)):
        raise ValueError('RFT and project octave resolution must be finite and positive.')
    cycles = 1.0 / math.expm1(math.log(2.0) / oct_res)
    return cycles / (rft_ms / 1000.0)


def default_lower_hz(rft_ms, oct_res):
    return float(math.ceil(transition_frequency_hz(rft_ms, oct_res) / 1000.0) * 1000)


def project_rft_ms(project):
    # Stage 3 stores the Studio override; older measurement projects use Stage 1.
    return project.get('stage3_vars', {}).get('fdw_rft_ms',
        project.get('stage1_vars', {}).get('fdw_rft_ms', '5.0'))
