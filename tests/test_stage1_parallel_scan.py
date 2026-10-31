"""Parallel peak scan preserves full-capture sizing, gain and processing output."""
import multiprocessing
from concurrent.futures import ProcessPoolExecutor
from types import SimpleNamespace
import numpy as np
import pytest
import soundfile as sf
from scipy.fft import next_fast_len
from hals_studio.process_engine import stage1_fdwsmooth as stage
from hals_studio.process_engine.runtime import EngineRuntime
from hals_studio.process_engine.session_pool import PoolView


def write_inputs(root):
    names = ['point1.wav', 'point2.wav', 'silent.wav']
    for index, name in enumerate(names):
        ir = np.zeros((8192, 2))
        if index < 2:
            ir[96+index*48, 0] = .5
            ir[7000, 0] = 1.  # Outside the crop: must still set auto gain.
        ir[20, 1] = 10.  # The first channel is used, as in the existing pipeline.
        sf.write(root/name, ir, 48000, subtype='FLOAT')
    return names


def run(root, runtime, **kwargs):
    return stage.fdwsmooth(str(root), str(root), 'unused.npz', 5, 12, 50, True, 24,
        save_to_disk=False, enable_auto_gain=True, runtime=runtime, **kwargs)


def test_spawn_scan_and_processing_match_serial_reference(tmp_path):
    names = write_inputs(tmp_path)
    records = {}
    for name in names:
        data, fs = stage.load_and_prep_ir(tmp_path/name)
        records[name] = (fs, stage.get_earliest_significant_peak(data, fs, -12.),
                         float(np.max(np.abs(data))))
    class SerialRuntime(EngineRuntime):
        def completed(self, executor, function, items, chunksize=1):
            # Reverse the scan completion order to exercise order independence.
            items = list(items)
            if function.func is stage.scan_file_worker:
                return iter([(name, *records[name]) for name in reversed(items)])
            return map(function, items)
    expected = run(tmp_path, SerialRuntime(output=lambda text: None), use_process_pool=False, workers=1)
    requests = []; events = []
    with ProcessPoolExecutor(max_workers=2, mp_context=multiprocessing.get_context('spawn')) as executor:
        pool = PoolView(SimpleNamespace(workers=2, executor=lambda: executor))
        runtime = EngineRuntime(output=lambda text: None, on_progress=events.append,
            pool_factory=lambda workers=None: (requests.append(workers) or pool))
        actual = run(tmp_path, runtime)
    assert requests == [None]  # Both passes reuse a single borrowed pool.
    np.testing.assert_array_equal(actual[0], expected[0])
    crop = next_fast_len(max(row[1] for row in records.values())+2400)
    assert len(actual[0]) == crop//2+1
    for output in (1, 2):
        assert actual[output].keys() == expected[output].keys()
        for name in names:
            np.testing.assert_array_equal(actual[output][name], expected[output][name])
    for name in names:
        assert actual[3][name]['t_peak'] == records[name][1]/48000
    scanned = [event for event in events if event['label'] == 'Stage 1 peak scan']
    assert scanned[0]['completed'] == 0
    assert scanned[-1]['completed'] == len(names)


def test_parallel_scan_rejects_mixed_sample_rates_before_fdw(tmp_path, monkeypatch):
    sf.write(tmp_path/'a.wav', np.zeros(256), 48000)
    sf.write(tmp_path/'b.wav', np.zeros(256), 44100)
    def unexpected(*args, **kwargs):
        pytest.fail('FDW started before scan validation finished')
    monkeypatch.setattr(stage, 'process_file_worker', unexpected)
    with pytest.raises(ValueError, match='same sample rate'):
        run(tmp_path, EngineRuntime(output=lambda text: None), use_process_pool=False, workers=2)
