"""Numerical and end-to-end contracts for the production PRESS pipeline."""
import json
import numpy as np
import pytest
from hals_studio.process_engine.press_fitting import basis, prediction_fit
from hals_studio.process_engine.press_origins import select_local, finalize, validate_saved, plain_orders, solve_schedule, VERSION
from hals_studio.process_engine.utils import cartesian_to_spherical, grid_reference, parse_coords_from_filename
from hals_studio.process_engine.condition_preflight import optimise_transitions
from hals_studio.process_engine.runtime import EngineRuntime


def test_unscaled_qr_press_matches_explicit_deleted_she_refits():
    rng=np.random.default_rng(22);xyz=rng.normal(size=(180,3));xyz/=np.linalg.norm(xyz,axis=1)[:,None];xyz*=rng.uniform(.3,.6,(180,1))
    a=basis(xyz,np.zeros(3),5,2*np.pi*25/343);p=rng.normal(size=len(a))+1j*rng.normal(size=len(a))
    c,m=prediction_fit(a,p)
    for i in (0,45,90,179):
        keep=np.arange(len(a))!=i;deleted,_=prediction_fit(a[keep],p[keep])
        assert m['loo_residual'][i]==pytest.approx(p[i]-a[i]@deleted,rel=1e-9,abs=1e-10)
    norms=np.linalg.norm(a,axis=0);reference=np.linalg.lstsq(a/norms,p,rcond=None)[0]/norms
    np.testing.assert_allclose(a@c,a@reference,rtol=1e-9,atol=1e-10)


def test_shared_basis_preserves_harmonic_ordering_and_radial_convention():
    from scipy.special import sph_harm_y, spherical_jn, spherical_yn
    rng = np.random.default_rng(88)
    xyz = rng.normal(size=(100, 3))
    origin = np.array([.01, .02, .03])
    actual = basis(xyz, origin, 7, 2.)
    radius, theta, phi = cartesian_to_spherical(*(xyz-origin).T)
    columns = []
    for n in range(8):
        regular = spherical_jn(n, 2*radius)
        outgoing = regular-1j*spherical_yn(n, 2*radius)
        for m in range(-n, n+1):
            angular = sph_harm_y(n, m, theta, phi)
            columns.extend((outgoing*angular, regular*angular))
    np.testing.assert_allclose(actual, np.column_stack(columns), rtol=1e-12, atol=1e-10)


def test_grid_reference_is_translation_invariant():
    rng=np.random.default_rng(85);xyz=rng.normal(size=(100,3));offset=np.array([3.,-1.,2.])
    centre,r=grid_reference(*cartesian_to_spherical(*xyz.T));moved,mr=grid_reference(*cartesian_to_spherical(*(xyz+offset).T))
    np.testing.assert_allclose(moved,centre+offset);np.testing.assert_allclose(mr,r)
    np.testing.assert_array_equal(plain_orders([20,100,1000],max(r),343,13),plain_orders([20,100,1000],max(mr),343,13))


def test_local_choice_ignores_best_press_but_respects_kr_and_actual_passing_set():
    def model(n,scale,press):return dict(order=n,field=np.full(240,scale+0j),power_db=0.,press_pct=press,converged=True)
    candidates={3:model(3,1.,5.),4:model(4,1.1,1.),5:model(5,1.,2.),7:model(7,1.,.5)}
    assert select_local(candidates,3,7)==3
    assert select_local(candidates,4,7)==5  # max(3,KR4) would choose a failing order.


def test_growth_reference_is_crossover_order_and_never_queries_n4():
    f=np.arange(100.,2100.,100.);proposed=np.minimum(10,np.arange(len(f))+2);calls=[]
    def condition(n,i):calls.append((n,i));return 1e6 if n==7 else 1e8*(f[i]/f[np.flatnonzero(proposed>=n)[0]])**-4
    cross=int(np.flatnonzero(proposed>=7)[0]);result=optimise_transitions(f,proposed,condition,reference_order=7,reference_index=cross)
    assert calls[0][0]>=7 and all(n>=7 for n,i in calls)
    assert result['reference_order']==7 and result['target_condition']==1e6
    np.testing.assert_array_equal(result['adjusted_orders'][:cross],proposed[:cross])
    assert np.all(result['adjusted_orders'][cross:]>=7)


def test_local_schedule_can_fall_and_stage2_interpolates_it():
    r=np.array([.4,.4,.4,.4]);th=np.array([1.,2.,1.,2.]);ph=np.array([0.,1.,3.,4.]);f=np.array([0.,20.,40.,80.])
    rows={20.:dict(final_c=np.zeros(3),press_order=6,press_reference_settled=True,press_candidates=[]),
          80.:dict(final_c=np.zeros(3),press_order=3,press_reference_settled=True,press_candidates=[])}
    cfg=dict(grid_radius_m=.4,grid_centre_m=[0.,0.,0.],N_grid=13,press_search_cap=7,press_plan_version=VERSION,press_names=['a'],speed_of_sound=343.,kr_offset=2.,
        origin_test_range_hz=(20,80),hold_origin_lf=True,hold_origin_hf=True)
    plan,orders,origins=finalize(rows,f,(r,th,ph),cfg,EngineRuntime(output=lambda _:None))
    np.testing.assert_array_equal(orders,[0,6,5,3]);assert 'target_max' not in plan
    data=dict(freqs=f,press_lf_orders=orders,origins_mm=origins,press_origins_mm=origins.copy(),
              r_arr=r,th_arr=th,ph_arr=ph)
    np.testing.assert_array_equal(validate_saved(data,plan,343,13,False,True),orders)
    np.testing.assert_array_equal(validate_saved(data,plan,343,12,False,True),orders)
    with pytest.raises(ValueError):validate_saved(data,plan,343,3,False,True)
    data['origins_mm']=origins+1
    with pytest.raises(ValueError):validate_saved(data,plan,343,13,False,True)
    rows[20.]['final_c']=np.array([100.,0.,0.])
    edited,_,_=finalize(rows,f,(r,th,ph),cfg,EngineRuntime(output=lambda _:None))
    assert edited['anchors'][0]['manually_edited']


@pytest.mark.parametrize('prepass',[False,True])
def test_stage2_npz_to_stage4_and_change_final_cap_without_searching(tmp_path,monkeypatch,prepass):
    from hals_studio.process_engine.stage2_centre_origin import run_origin_search
    from hals_studio.process_engine.stage4_run_she_solve import run_she_solve
    from hals_studio.application.process_stages import persist_origin_result,search_origins
    from hals_studio.persistence import process_cache
    from hals_studio.process_engine import press_origins
    from hals_studio.process_engine.utils import load_and_parse_npz,spherical_to_cartesian
    import h5py
    names=[]
    for i in range(100):
        radius=300+(i%3)*80;phi=(i*137.508)%360;z=-200+(i%11)*40
        encode=lambda x:f'{x:.3f}'.replace('.','p')
        names.append(f'NA_r{encode(radius)}_ph{encode(phi)}_z{encode(z)}_ir.wav')
    xyz=np.column_stack(spherical_to_cartesian(*np.array([parse_coords_from_filename(n) for n in names]).T))
    f=np.array([0.,50.,100.,200.,400.,800.,1200.,1600.,2400.,3200.]);source=np.array([.02,.01,.015]);spectra={}
    for i,name in enumerate(names):
        distance=np.linalg.norm(xyz[i]-source);spectra[name]=np.exp(-2j*np.pi*f*distance/343)/distance
    spectra[names[0]]*=1e4
    path=tmp_path/'data.npz';np.savez_compressed(path,freqs=f,data=spectra,fs=6400.)
    blacklist=tmp_path/'blacklist.txt';blacklist.write_text(names[0]+'\n')
    runtime=EngineRuntime(output=lambda _:None)
    result=run_origin_search(str(tmp_path),path.name,path.name,tuple(source*1000),.5,
        freq_start_hz=50,freq_end_hz=3200,target_n_max_origins=3,max_iterations=150,
        press_enabled=True,press_residual_seed=prepass,press_blacklist=str(blacklist),
        optimize_speed_of_sound=False,use_process_pool=False,return_state=True,runtime=runtime)
    assert len(result[2])==99
    persist_origin_result(result,{},tmp_path,path.name,runtime)
    parsed=load_and_parse_npz(path);plan=press_origins.load_plan(parsed)
    assert plan['search_cap']==3 and 'target_max' not in plan and names[0] not in plan['names']
    modified=dict(parsed,complex_data=dict(parsed['complex_data']))
    modified['complex_data'][plan['names'][0]]=parsed['complex_data'][plan['names'][0]]+1
    with pytest.raises(ValueError):
        validate_saved(modified,plan,343,5,False,True)
    saved=parsed['press_lf_orders'].copy();assert 'growth' not in plan
    parsed['raw_data'].close()
    solved=run_she_solve(path.name,'coeff.h5',str(tmp_path),str(tmp_path),5,save_to_disk=True,
        show_plot=False,use_process_pool=False,jobs=1,condition_preflight=True,runtime=runtime)
    assert np.all(solved['N_used']>=saved[1:])
    assert solved['condition_preflight']['reference_order']==3
    np.testing.assert_array_equal(solved['N_used'],solved['press_order_schedule'])
    assert solved['P_measured'].shape[1]==99
    with h5py.File(tmp_path/'coeff.h5') as h:
        assert 'measurement_weights' not in h
        assert not plan['weighting']
        assert np.isfinite(h['coeffs'][:]).all()
        assert 'press_pilot_origins_mm' not in h
    from hals_studio.process_engine import spatial_error_viewer
    def spatial(she,measured,coords,*args,**kwargs):
        assert measured.shape[1]==99 and len(coords)==99
        return None,None,None,she['freqs'],she['N_used'],measured,measured.copy()
    monkeypatch.setattr(spatial_error_viewer,'compute_spatial_error_data',spatial)
    reopened=process_cache.hydrate_stage4(path,tmp_path/'coeff.h5')
    assert reopened['P_measured'].shape[1]==99
    cache=tmp_path/'stage2.pkl';process_cache.save(cache,2,result)
    monkeypatch.setattr(press_origins,'search_one',lambda *a,**kw:pytest.fail('Refresh must not search'))
    refreshed=run_she_solve(path.name,'coeff2.h5',str(tmp_path),str(tmp_path),6,save_to_disk=False,
        show_plot=False,use_process_pool=False,jobs=1,condition_preflight=True,runtime=runtime)
    assert max(refreshed['N_used'])==6 and refreshed['condition_preflight']['reference_order']==3
    unoptimized=run_she_solve(path.name,'unused.h5',str(tmp_path),str(tmp_path),6,save_to_disk=False,
        show_plot=False,use_process_pool=False,jobs=1,condition_preflight=False,runtime=runtime)
    assert unoptimized['condition_preflight']['status']=='disabled'
    # HF growth and final-cap changes never rewrite Stage 2's LF array.
    again=load_and_parse_npz(path);np.testing.assert_array_equal(again['press_lf_orders'],saved);again['raw_data'].close()


def test_raw_qr_handles_column_units_and_rejects_actual_dependence():
    rng=np.random.default_rng(552);a=rng.normal(size=(40,8))+1j*rng.normal(size=(40,8));p=rng.normal(size=40)+1j*rng.normal(size=40)
    reference,metric=prediction_fit(a,p);units=np.logspace(-30,30,8)
    coeff,scaled=prediction_fit(a*units,p)
    np.testing.assert_allclose((a*units)@coeff,a@reference,rtol=1e-11,atol=1e-12)
    assert scaled['press_pct']==pytest.approx(metric['press_pct'],rel=1e-11)
    a[:,-1]=a[:,0]*1e-20
    with pytest.raises(ValueError):prediction_fit(a,p)


def test_legacy_stage2_kr_is_independent_of_candidate_and_coordinate_zero(monkeypatch):
    from hals_studio.process_engine import stage2_centre_origin as stage
    rng=np.random.default_rng(71);xyz=rng.normal(size=(80,3))*.2;shift=np.array([3.,-2.,4.]);orders=[]
    def solve(**kw):orders.append(kw['order_N']);return np.zeros(1),dict(residual_norm=1.)
    monkeypatch.setattr(stage,'_solve_one_frequency',solve)
    cfg=dict(speed_of_sound=343.,kr_offset=2.,noise_floor_start_db=-12.,noise_floor_max_db=-24.,max_lambda=.01)
    for moved in (np.zeros(3),shift):
        geometry=cartesian_to_spherical(*(xyz+moved).T)
        context=([(200.,2*np.pi*200/343,np.ones(len(xyz)))],*geometry,8,cfg)
        for candidate in (np.zeros(3),np.array([.25,0,.1])):
            stage.solve_physics_3d(*((candidate+moved)*1000),context)
    assert len(set(orders))==1 and orders[0]<8


def test_full_order_search_then_lower_orders_use_original_pressures(monkeypatch):
    from hals_studio.process_engine import press_origins as engine
    rng=np.random.default_rng(67);xyz=rng.normal(size=(100,3))*.2
    geometry=cartesian_to_spherical(*xyz.T);names=[f'mic{i}' for i in range(100)]
    f=np.array([0.,50.,1000.]);spectra={name:f.astype(complex)*(i+1) for i,name in enumerate(names)}
    source=np.array([.06,.01,.03]);calls=[]
    def search(xyz,p,frequency,n,seed,cfg,hull,runtime):
        np.testing.assert_array_equal(p,frequency*np.arange(1,101))
        calls.append((frequency,n))
        return dict(order=n,origin=source.copy(),field=np.ones(240,complex),power_db=0.,
                    press_pct=1.,training_pct=1.,converged=True,evaluations=1)
    monkeypatch.setattr(engine,'search_one',search)
    cfg=dict(target_n_max_origins=3,N_grid=5,speed_of_sound=343.,grid_radius_m=.4,grid_centre_m=[0.,0.,0.],kr_offset=2.)
    rows=engine.run_search(f,[1,2],names,spectra,geometry,cfg,[100.,0.,100.],EngineRuntime(output=lambda _:None))
    assert all(n==3 for _,n in calls[:4])
    assert any(n==2 for _,n in calls)
    assert all('press_pilot_origin_mm' not in row for row in rows.values())
    assert cfg['press_plan_version']==VERSION


@pytest.mark.parametrize('version',[2,3])
def test_old_weighting_plan_is_rejected_with_rerun_instruction(version):
    from hals_studio.process_engine.press_origins import load_plan
    with pytest.raises(ValueError):
        load_plan(dict(press_plan_json=json.dumps(dict(version=version,weighting=True))))


def test_stage4_saved_schedule_requires_only_one_final_fit(monkeypatch):
    from hals_studio.process_engine import stage4_run_she_solve as stage
    from hals_studio.process_engine import press_fitting
    cfg=dict(press_order=2,speed_of_sound=343.,condition_metrics=True,
             noise_floor_start_db=-30.,noise_floor_max_db=-50.,max_lambda=0.)
    pressure=np.arange(40).astype(complex);calls=[]
    def solve(f,p,coords,n,**kwargs):
        np.testing.assert_array_equal(p,pressure)
        assert 'point_weights' not in kwargs and n==2
        calls.append(f)
        return np.zeros(18,complex),dict(residual_norm=0.,cond_post=1.,final_N=2,residual_vector=np.zeros(40,complex))
    monkeypatch.setattr(press_fitting,'prediction_fit',lambda *a,**kw:pytest.fail('Stage 4 must not do pilot/PRESS fitting'))
    monkeypatch.setattr(stage,'_solve_one_frequency',solve)
    result=stage._press_worker((0,1000.,pressure,np.full(40,.5),np.full(40,np.pi/2),np.linspace(0,2*np.pi,40),3,cfg))
    assert calls==[1000.] and len(result)==7


def test_shared_pool_search_matches_threads_and_survives_cancellation():
    import os
    from hals_studio.process_engine import press_origins
    from hals_studio.process_engine.session_pool import SessionPool, PoolView
    from hals_studio.process_engine.runtime import ProcessingCancelled

    rng = np.random.default_rng(923)
    xyz = rng.normal(size=(90, 3))
    xyz *= rng.uniform(.35, .5, (90, 1))/np.linalg.norm(xyz, axis=1)[:, None]
    geometry = cartesian_to_spherical(*xyz.T)
    frequencies = np.array([80., 300., 1500.])
    names = [f'mic{i}' for i in range(len(xyz))]
    pressure = np.array([basis(xyz, np.array([.03, .01, .02]), 2, 2*np.pi*f/343)[:, 0]
                         for f in frequencies])
    spectra = dict(zip(names, pressure.T))
    cfg = dict(target_n_max_origins=3, N_grid=3, speed_of_sound=343.,
               grid_radius_m=.5, grid_centre_m=[0., 0., 0.], kr_offset=2.,
               initial_simplex_step=15., max_iterations=40)
    def run(runtime):
        return press_origins.run_search(frequencies, [0, 1, 2], names, spectra,
                                        geometry, cfg.copy(), [30., 10., 20.], runtime)
    reference = run(EngineRuntime(output=lambda _: None))
    pool = SessionPool(2)
    try:
        pool.start()
        events = []
        runtime = EngineRuntime(output=lambda _: None, on_progress=events.append,
                                pool_factory=lambda _: PoolView(pool))
        actual = run(runtime)
        for f in frequencies:
            np.testing.assert_allclose(actual[f]['final_c'], reference[f]['final_c'], atol=1e-8)
            assert actual[f]['press_order'] == reference[f]['press_order']
            assert actual[f]['press_pct'] == pytest.approx(reference[f]['press_pct'])
        assert any(e['completed'] == e['total'] and e['total'] > 0 for e in events)
        cancelled = [False]
        def progress(event):
            if event['completed']:
                cancelled[0] = True
        with pytest.raises(ProcessingCancelled):
            run(EngineRuntime(output=lambda _: None, on_progress=progress,
                cancelled=lambda: cancelled[0], pool_factory=lambda _: PoolView(pool)))
        assert pool.executor().submit(os.getpid).result(timeout=10) > 0
    finally:
        pool.close()


def test_prediction_grid_returns_both_scores_without_kr_order_changes(monkeypatch):
    from scipy.spatial import ConvexHull
    from hals_studio.process_engine import stage2_centre_origin as stage
    rng = np.random.default_rng(912)
    xyz = rng.normal(size=(70, 3))*.3
    geometry = cartesian_to_spherical(*xyz.T)
    pressure = rng.normal(size=70)+1j*rng.normal(size=70)
    cfg = dict(origin_grid_metric='prediction', origin_grid_xyz=xyz,
               origin_grid_hull=ConvexHull(xyz).equations, use_process_pool=False,
               grid_res_mm=10., x_bounds=(-5., 5.), y_bounds=(-5., 5.), z_bounds=(-5., 5.))
    context = ([(60., 2*np.pi*60/343, pressure)], *geometry, 3, cfg)
    monkeypatch.setattr(stage, 'get_kr_limit', lambda *a, **k: pytest.fail('Grid order must stay fixed'))
    _, metrics = prediction_fit(basis(xyz, np.zeros(3), 3, 2*np.pi*60/343), pressure)
    predicted, residual = stage.prediction_grid_scores(0, 0, 0, context)
    assert predicted == pytest.approx(metrics['press_pct'])
    assert residual == pytest.approx(metrics['training_pct'])
    assert not np.isfinite(stage.prediction_grid_scores(1e6, 0, 0, context)).any()
    x, y, z, grid = stage.generate_3d_landscape_volumetric(context)
    assert grid.shape == cfg['origin_grid_residuals'].shape == (2, 2, 2)
    assert np.isfinite(grid).all()
    assert np.all(grid >= cfg['origin_grid_residuals'])


def test_rescan_score_maps_survive_viewer_cache_roundtrip(tmp_path):
    from hals_studio.persistence import process_cache
    grid = np.arange(8.).reshape(2, 2, 2)
    rows = {100.: dict(final_c=np.zeros(3), error=1., press_pct=2.,
        original_press_pct=3., grid=grid, grid_residual=grid/2, grid_metric='prediction')}
    result = (rows, None, None, None, None, {}, None)
    path = tmp_path/'origins.pkl'
    process_cache.save(path, 2, result)
    restored = process_cache.load(path, 2)[0][100.]
    np.testing.assert_array_equal(restored['grid'], grid)
    np.testing.assert_array_equal(restored['grid_residual'], grid/2)
    assert restored['grid_metric'] == 'prediction'
    assert restored['original_press_pct'] == 3.
