"""Independent CTA weighting checks and shared Analysis/Export contract."""
import sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parent))
import bootstrap
import numpy as np
from cta_coordinates import generate_cta2034_coords
from stage5_extract_pressures import calculate_cta2034_energy_metrics as metrics
from stage5_extract_pressures import calculate_cta2034_metrics
from analysis_metrics import cea2034


def setup():
    coords, indices, deviations = generate_cta2034_coords(1., 90., 0.)
    return np.ones((2, len(coords))), indices, deviations


def test_isotropic_and_di_scale_invariance():
    energy, indices, _ = setup()
    for name, value in metrics(energy * 100, indices).items():
        np.testing.assert_allclose(value, 0 if name.endswith(' DI') else 20, atol=1e-12)


def test_equal_reflection_groups_and_energy_domain():
    energy, indices, _ = setup()
    for key in ('V340', 'V330', 'V320'):
        energy[:, indices[key]] = 9
    result = metrics(energy, indices)
    np.testing.assert_allclose(result['Early reflections'], 10*np.log10(2.6))
    energy, indices, _ = setup()
    energy[:, indices['H10']] = 100
    np.testing.assert_allclose(metrics(energy, indices)['Listening window'], 10*np.log10(12))


def test_three_rear_directions_and_pir():
    energy, indices, _ = setup()
    energy[:, indices['H100']] = 20
    result = metrics(energy, indices)
    np.testing.assert_allclose(result['Early reflections'], 0)
    np.testing.assert_allclose(result['Horizontal reflections'], 10*np.log10(4/3))
    expected = .12*10**(result['Listening window']/10) + .44*10**(result['Early reflections']/10) + .44*10**(result['Sound power']/10)
    np.testing.assert_allclose(result['Predicted in-room'], 10*np.log10(expected))


def test_analysis_export_agree_on_directional_field():
    az = np.arange(-180., 180., 10.)
    el = np.arange(-90., 91., 10.)
    sphere = SimpleNamespace(azimuth=az, elevation=el)
    # Exact grid nodes, nonuniform levels and phases: spatial averaging must
    # discard phase, while the FRD adapter must preserve reference phase.
    def field(azimuth, elevation):
        return 2 + .6*np.cos(np.deg2rad(azimuth))*np.cos(np.deg2rad(elevation))
    energy = field(az[None, :], el[:, None])[None, ...]
    analysis = cea2034(sphere, 10*np.log10(energy))
    coords, indices, deviations = generate_cta2034_coords(1., 90., 0.)
    coords = np.asarray(coords)
    sampled = field(coords[:, 1], 90-coords[:, 0])[None, :]
    pressure = np.sqrt(sampled)*np.exp(1j*.7)
    exported = calculate_cta2034_metrics(np.array([1000.]), pressure, indices, deviations)
    for filename, name in [('Response_OnAxis', 'On axis'), ('Response_ListeningWindow', 'Listening window'),
                           ('Response_EarlyReflections', 'Early reflections'), ('Response_SoundPower', 'Sound power'),
                           ('Response_PIR', 'Predicted in-room'), ('Response_SPDI', 'Sound power DI'),
                           ('Response_ERDI', 'Early reflections DI')]:
        np.testing.assert_allclose(exported[filename][0], analysis[name], atol=1e-12)
        np.testing.assert_allclose(exported[filename][1], 0 if name.endswith(' DI') else np.rad2deg(.7))
