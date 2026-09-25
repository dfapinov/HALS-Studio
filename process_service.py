"""Isolated, persistent processing host. Only the copied process_engine is imported."""
import os,sys,json,pickle,traceback,multiprocessing
from pathlib import Path
import bootstrap
sys.path.insert(0,str(bootstrap.HERE/'process_engine'))
os.environ['MPLBACKEND']='Agg'
import numpy as np
import process_cache

class FileMapping(dict):
    @property
    def files(self):return list(self)

def run(request):
    stage=int(request['stage']); v=request['settings']; root=Path(request['folder']); name=request['name']
    out=root/'outputs';out.mkdir(exist_ok=True);os.chdir(out);filename=name+'_complex_data.npz'
    input_name=name+'_complex_data_centered.npz' if stage==3 and (out/(name+'_complex_data_centered.npz')).exists() else filename
    if stage>1 and not (out/input_name).is_file(): raise ValueError('Run Stage 1 first: '+str(out/input_name))
    if stage==1:
        from stage1_fdwsmooth import fdwsmooth
        smooth=v['smoothing_oct_res'];smooth=float(v['fdw_oct_res'])*2 if str(smooth).lower()=='auto' else float(smooth)
        result=fdwsmooth(input_dir=request['ir_folder'],out_dir=str(out),output_filename=filename,
            fdw_rft_ms=float(v['fdw_rft_ms']),fdw_oct_res=float(v['fdw_oct_res']),fdw_max_cap_ms=float(v['fdw_max_cap_ms']),
            enable_smoothing=v['enable_smoothing'],smoothing_oct_res=smooth,show_plot=False,save_to_disk=True,
            fdw_alpha_hf=float(v['fdw_alpha_hf']),fdw_alpha_lf=float(v['fdw_alpha_lf']),fdw_windows_per_oct=int(v['fdw_windows_per_oct']),
            peak_detect_threshold_db=float(v['peak_detect_threshold_db']),enable_auto_gain=v['enable_auto_gain'],target_peak_db=float(v['target_peak_db']),
            keep_raw_and_smoothed=v['keep_raw_and_smoothed'],use_process_pool=True,
            sliding_hf=True, compare_smoothing=False, workers=request.get('workers'))
    elif stage==2:
        from stage2_centre_origin import run_origin_search,export_interpolated_origins
        if request.get('action') in ('save_origins','rescan'):
            result=process_cache.hydrate_stage2(process_cache.load(request['cache'],2),out/filename)
            for row in result[0].values():
                row.setdefault('original_c',np.array(row['final_c']).copy());row.setdefault('original_error',row['error'])
            for freq,xyz in request.get('edits',[]):result[0][float(freq)]['final_c']=np.asarray(xyz)
            if request['action']=='rescan':
                from stage2_centre_origin import get_order_for_frequency,generate_3d_landscape_volumetric,run_simplex_descent_3d
                rows,freqs,keys,d,geom,cfg,data=result
                for f in request['rescan']:
                    i=np.argmin(abs(freqs-f));N=get_order_for_frequency(f,cfg.get('manual_order_table',{}),cfg.get('target_n_max_origins',4),cfg.get('N_grid',999))
                    pc=([(float(f),float(2*np.pi*f/cfg['speed_of_sound']),np.array([d[k][i] for k in keys]))],*geom,N,cfg)
                    import stage2_centre_origin as origins
                    from session_pool import borrow_pool
                    original_borrow=origins.borrow_pool
                    try:
                        origins.borrow_pool=lambda workers=None:borrow_pool(request.get('workers',workers))
                        x,y,z,grid=generate_3d_landscape_volumetric(pc)
                    finally:origins.borrow_pool=original_borrow
                    idx=np.unravel_index(np.argmin(grid),grid.shape);seed=(x[idx[0]],y[idx[1]],z[idx[2]])
                    centre,path=run_simplex_descent_3d(seed,pc);rows[f].update(grid=grid,X_vals=x,Y_vals=y,Z_vals=z,final_c=centre,path=path)
        else:
            bounds=lambda k:tuple(float(x.strip()) for x in v[k].split(','))
            result=run_origin_search(input_dir_origins=str(out),input_filename_origins=filename,output_filename_origins=filename,
                tweeter_coords_mm=tuple(float(v['tweeter_'+k]) for k in 'xyz'),octave_resolution=1/float(v['octave_resolution']),
                freq_start_hz=float(v['freq_start_hz']),freq_end_hz=float(v['freq_end_hz']),initial_simplex_step=float(v['initial_simplex_step']),
                max_iterations=int(v['max_iterations']),x_bounds=bounds('x_bounds'),y_bounds=bounds('y_bounds'),z_bounds=bounds('z_bounds'),grid_res_mm=float(v['grid_res_mm']),
                target_n_max_origins=int(v['target_n_max_origins']),manual_order_table=None,save_to_disk=False,plot_results_origins=False,
                speed_of_sound=float(request.get('speed',343)),optimize_speed_of_sound=not request.get('manual_speed',False),use_process_pool=True,return_state=True,
                use_cache=request.get('action')=='load_origins',read_cache_file=request.get('origin_cache',''))
        if result is None: raise ValueError('Origin search returned no results')
        rows,freqs,keys,d,geom,cfg,data=result
        if request.get('action') in ('rescan','save_origins'):
            from stage2_centre_origin import solve_physics_3d,get_order_for_frequency
            for f,row in rows.items():
                i=np.argmin(abs(freqs-f));N=get_order_for_frequency(f,cfg.get('manual_order_table',{}),cfg.get('target_n_max_origins',4),cfg.get('N_grid',999))
                pc=([(float(f),float(2*np.pi*f/cfg['speed_of_sound']),np.array([d[k][i] for k in keys]))],*geom,N,cfg)
                row['error']=solve_physics_3d(*row['final_c'],pc)
        source=data;data=FileMapping(source)
        if hasattr(source,'close'):source.close()
        usable=[(f,r['final_c']) for f,r in sorted(rows.items()) if r['final_c'] is not None]
        if not usable:raise ValueError('No valid acoustic origins')
        xyz=np.array([p for f,p in usable]);export_interpolated_origins([f for f,p in usable],*xyz.T,freqs,data,str(out),filename,True,speed_of_sound=cfg.get('speed_of_sound',343))
        result=(rows,freqs,keys,d,geom,cfg,dict(data))
    elif stage==3:
        from stage3_optimize_she_settings import run_open_branch_optimizer
        from session_pool import borrow_pool
        orders=tuple(int(x.strip()) for x in v['test_order_range'].split(','))
        action=request.get('action')
        if action=='growth':
            from condition_preflight import run_condition_preflight
            from utils import load_and_parse_npz
            with open(request['cache'],'rb') as stream:result=pickle.load(stream)
            selected_n=int(request['selected_order_N'])
            settings=request.get('preflight_settings',{})
            cfg=dict(target_n_max=selected_n,
                     kr_offset=float(settings.get('kr_offset',2.)),
                     use_optimized_origins=settings.get('use_optimized_origins',True),
                     use_manual_table=False,manual_order_table={})
            result['selected_order_N']=selected_n
            result['condition_preflight']=run_condition_preflight(load_and_parse_npz(str(out/filename)),cfg)
        elif action=='reference':
            from stage3_optimize_she_settings import stage3_order_choices,recommended_stage3_choice
            with open(request['cache'],'rb') as stream:result=pickle.load(stream)
            result.pop('condition_preflight',None);result.pop('selected_order_N',None)
            step=result['step1'];selected=step['tail_by_reference'][str(request['reference'])];tail_only=result.get('tail_only',False)
            step['internal_tail_power_db']=selected['power_db'];step['tail_reference'].update(selected,manual=True)
            updated=stage3_order_choices(step['orders'],step['ratios'],step['residuals'],step.get('rolloff_knee'),selected['power_db'],selected['n'],tail_only=tail_only,manual_reference=tail_only)
            for key in ('knee','tail'):result['options'].pop(key,None)
            result['options'].update(updated);result['recommended_key']=recommended_stage3_choice(result['options'])
        else:
            result=run_open_branch_optimizer(input_dir_opti=str(out),input_filename_opti=input_name,test_order_range=orders,
                octave_resolution=int(v['octave_resolution']),spl_change_enabled=True,spl_sphere_points=int(v['spl_sphere_points']),spl_radius_m=float(v['spl_radius_m']),spl_floor_db=-40.,
                freq_start_hz=float(v['freq_start_hz']),freq_end_hz=float(v['freq_end_hz']),use_optimized_origins=True,speed_of_sound=343.,kr_offset=2.,use_process_pool=True,process_pool=borrow_pool(6))
    else:
        from stage4_run_she_solve import run_she_solve
        result=run_she_solve(input_filename_she=filename,output_filename_she=name+'_coefficients.h5',input_dir_she=str(out),output_dir_she=str(out/'coefficients'),
            target_n_max=int(v['target_n_max']),kr_offset=float(v['kr_offset']),use_manual_table=v['use_manual_table'],manual_order_table={float(k):int(n) for k,n in request['manual_table'].items()},
            noise_floor_start_db=float(v['noise_floor_start_db']),noise_floor_max_db=float(v['noise_floor_max_db']),max_lambda=float(v['max_lambda']) if v['enable_regularization'] else 0.,
            condition_metrics=True,use_optimized_origins=v['use_optimized_origins'],save_to_disk=True,speed_of_sound=343.,jobs=None,show_plot=False,use_process_pool=True)
    if result is None:raise ValueError('Processing returned no results; inspect the CLI output')
    cache=Path(request['cache'])
    if stage==1:
        cache.unlink(missing_ok=True)
        return str(out/filename)
    process_cache.save(cache,stage,result)
    return str(cache)

def main():
    from session_pool import SessionPool,install_session_pool
    pool=SessionPool();install_session_pool(pool);pool.start()
    print('HALS Process worker pool warming',flush=True)
    try:
        for line in sys.stdin:
            try:
                request=json.loads(line);result=run(request);print('\n@@HALS@@'+json.dumps({'ok':True,'stage':request['stage'],'cache':result}),flush=True)
            except Exception:
                traceback.print_exc();print('\n@@HALS@@'+json.dumps({'ok':False}),flush=True)
    finally:pool.close()
if __name__=='__main__':
    multiprocessing.freeze_support();main()
