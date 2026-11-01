import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import hals_studio.bootstrap as bootstrap
import io
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from types import SimpleNamespace
import numpy as np
import pytest
from hals_studio.process_engine.process_progress import Progress, collect_tasks


class RecordedOutput(io.StringIO):
    def __init__(self):
        super().__init__();self.events=[]
    def progress(self,event):self.events.append(event)


def test_progress_initial_first_returns_eta_and_completion(monkeypatch):
    import hals_studio.process_engine.process_progress as process_progress
    now=[0.]
    monkeypatch.setattr(process_progress.time,'monotonic',lambda:now[0])
    stream=RecordedOutput()
    with redirect_stdout(stream):
        progress=Progress('Work',10)
        for _ in range(3):
            now[0]+=2;progress.advance()
        now[0]=20;progress.advance(7)
    assert [e['completed'] for e in stream.events]==[0,1,2,3,10]
    assert stream.events[2]['eta'] is None
    assert stream.events[3]['eta']==14
    assert stream.events[-1]['eta']==0
    assert '7 remaining' in stream.getvalue()


@pytest.mark.parametrize('shared', [False,True])
def test_reports_actual_completions_while_returning_input_order(shared):
    from hals_studio.process_engine.session_pool import PoolView
    release=threading.Event()
    stream=RecordedOutput()
    def emit(event):
        stream.events.append(event)
        if event['completed']==1:release.set()
    stream.progress=emit
    def task(i):
        if i==0:assert release.wait(3), 'Progress waited for the first submitted task'
        return i*10
    with ThreadPoolExecutor(max_workers=2) as executor, redirect_stdout(stream):
        pool=PoolView(SimpleNamespace(executor=lambda:executor,workers=2)) if shared else executor
        results=collect_tasks(pool,task,[0,1,2,3],'Tasks')
    assert results==[0,10,20,30]
    assert stream.events[1]['completed']==1
    assert stream.events[-1]['completed']==4


def test_indexed_collection_runs_in_spawn_workers():
    import multiprocessing
    from concurrent.futures import ProcessPoolExecutor
    from hals_studio.process_engine.session_pool import PoolView
    with ProcessPoolExecutor(max_workers=2,mp_context=multiprocessing.get_context('spawn')) as executor:
        pool=PoolView(SimpleNamespace(workers=2,executor=lambda:executor))
        assert collect_tasks(pool,abs,[-4,-2,-3],'Spawn tasks')==[4,2,3]


def test_speed_candidate_batch_counts_probe_fits(monkeypatch):
    import hals_studio.process_engine.stage2_centre_origin as stage
    def fake(args):
        speed,probes,*_=args
        results=[dict(freq=f,error=speed+f,origin=np.zeros(3)) for f,p in probes]
        return speed,np.mean([r['error'] for r in results]),results
    monkeypatch.setattr(stage,'_worker_speed_of_sound_candidate',fake)
    stream=RecordedOutput()
    with redirect_stdout(stream):
        result=stage.run_speed_of_sound_candidate_batch('Fine pass',[342.,343.],
            [(5000.,[1]),(6000.,[1]),(7000.,[1])],(0,0,0),[],[],[],{},use_process_pool=False)
    assert [r[0] for r in result]==[342.,343.]
    assert all(len(r[2])==3 for r in result)
    assert result[0][1]==6342.
    assert stream.events[-1]['total']==6 and stream.events[-1]['completed']==6


def test_grid_results_keep_their_coordinates(monkeypatch):
    import hals_studio.process_engine.stage2_centre_origin as stage
    monkeypatch.setattr(stage,'solve_physics_3d',lambda x,y,z,context:x+2*y+3*z)
    config=dict(grid_res_mm=1.,x_bounds=(-1,1),y_bounds=(-1,1),z_bounds=(-1,1),use_process_pool=False)
    stream=RecordedOutput()
    with redirect_stdout(stream):
        x,y,z,grid=stage.generate_3d_landscape_volumetric((config,))
    expected=x[:,None,None]+2*y[None,:,None]+3*z[None,None,:]
    np.testing.assert_array_equal(grid,expected)
    assert stream.events[-1]['completed']==27


def test_progress_crosses_processing_job_signal(monkeypatch):
    from PySide6 import QtWidgets as W
    import hals_studio.infrastructure.process_job as process_job, hals_studio.process_engine.session_pool as session_pool
    app=W.QApplication.instance() or W.QApplication([])
    def fake_run(request, *, runtime):
        progress=runtime.progress('Stage 1 test',3)
        for _ in range(3):progress.advance()
        return 'cache'
    monkeypatch.setattr(process_job.process_service,'run',fake_run)
    monkeypatch.setattr(session_pool,'install_session_pool',lambda pool:None)
    job=process_job.ProcessJob({'stage':1},SimpleNamespace(workers=2,state='ready'))
    events=[];finished=[]
    job.progress.connect(events.append);job.completed.connect(finished.append)
    job.start();assert job.wait(5000);app.processEvents()
    assert [event['completed'] for event in events]==[0,1,2,3]
    assert finished[0]['ok']


def test_cpu_percentage_uses_deltas(monkeypatch):
    from hals_studio.ui.cpu_usage import CpuSampler
    sampler=CpuSampler()
    samples=iter([(100,200),(110,300),(110,400)])
    monkeypatch.setattr(sampler,'counters',lambda:next(samples))
    assert sampler.sample() is None
    assert sampler.sample()==pytest.approx(90.)
    assert sampler.sample()==pytest.approx(100.)


def test_processing_progress_updates_and_clears_status_bar(tmp_path):
    from PySide6 import QtCore as C, QtWidgets as W
    from hals_studio.ui.process_workspace import ProcessWorkspace
    app=W.QApplication.instance() or W.QApplication([])
    owner=W.QMainWindow();owner.project_path=None
    owner.show_documentation=lambda *args: None
    owner.settings=C.QSettings(str(tmp_path/'settings.ini'),C.QSettings.IniFormat)
    owner.progress=W.QProgressBar();owner.statusBar().addPermanentWidget(owner.progress)
    pane=ProcessWorkspace(owner)
    try:
        pane.job=True
        pane.processing_progress(dict(label='Stage 2 test',completed=3,total=10,remaining=7,eta=14))
        assert owner.progress.maximum()==10 and owner.progress.value()==3
        pane.end_processing_progress('Complete');pane.job=False
        assert owner.progress.isHidden()
    finally:pane.close();owner.close();app.processEvents()
