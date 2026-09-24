"""CSD from HALS-generated IRs, shared by Analysis and Stage 5."""
from pathlib import Path
from copy import deepcopy
import numpy as np
import pyvista as pv
from pyvistaqt import QtInteractor
from PySide6 import QtWidgets as W, QtCore as C
from matplotlib.ticker import FuncFormatter
from plots import Chart, audio_ticks, audio_frequency
from plot_interaction import PlotInteraction

DEFAULTS = dict(csd_level_reference=False, wavelet_level_reference=False, wavelet_time_reference=False, csd_method='CSD', wavelet_units='Cycles', wavelet_cycles=12., wavelet_duration=20., wavelet_pre=1., csd_mode='3D waterfall', csd_time=20., csd_pre_time=1., csd_span=30., csd_auto_time=True, csd_fmin=100., csd_fmax=20000.)


def decay(ir, fs, duration=20., window=None, slices=160, pre_time=1.):
    """FFT of residual IR tails, with one fixed end window and a sliding soft gate.

    The gate reaches full weight at each stated time. A 0.2 ms leading shoulder
    is included identically on every slice, including time zero. No special
    first slice, circular shifts, changing end-window or synthetic floor plane.
    """
    ir = np.asarray(ir, float); peak = int(np.argmax(abs(ir)))
    shoulder = max(2, round(fs*.0002))
    end = len(ir) if window is None else min(len(ir), peak+max(16, round(window*fs/1000)))
    signal = ir[:end].copy(); n = len(signal)
    if window is not None:
        fade = min(n, max(2, round(.1*n)))
        signal[-fade:] *= np.cos(np.linspace(0, np.pi/2, fade))**2
    duration = min(max(duration, .001)/1000, max(1/fs, (end-peak-1)/fs))
    times = np.unique(np.append(np.linspace(-max(0., pre_time)/1000, duration, slices), 0.))
    samples = (np.arange(n)-peak)/fs
    gate = np.clip((samples[None,:]-times[:,None])/(shoulder/fs)+1, 0, 1)
    gate = np.sin(gate*np.pi/2)**2
    size = max(4096, 1 << max(1, n-1).bit_length())
    amplitude = abs(np.fft.rfft(gate*signal, n=size, axis=1))
    return np.fft.rfftfreq(size, 1/fs), times*1000, amplitude


def decay_map(ir, fs, config):
    window = None
    available = (len(ir)-np.argmax(abs(ir))-1)/fs*1000
    duration = (window or available) if config.get('csd_auto_time', True) else config['csd_time']
    pre_time = config.get('csd_pre_time', 1.)
    f, t, magnitude = decay(ir, fs, duration, window, pre_time=pre_time)
    low, high = max(config['csd_fmin'], f[1]), min(config['csd_fmax'], f[-1])
    if low >= high: raise ValueError('CSD frequency limits must overlap the IR frequency range.')
    frequency = np.geomspace(low, high, 320)
    amplitude = np.array([np.interp(frequency, f, row) for row in magnitude])
    reference = max(float(amplitude[0].max()), 1e-30)
    if config.get('csd_level_reference') in (True, 'IR peak slice per frequency'):
        zero_f, _, zero_magnitude = decay(ir, fs, .001, window, slices=2, pre_time=0.)
        reference = np.maximum(np.interp(frequency, zero_f, zero_magnitude[0]), reference*1e-12)
    db = 20*np.log10(np.maximum(amplitude/reference, 1e-12))
    if config.get('csd_auto_time', True):
        visible = np.flatnonzero(np.max(db, axis=1) >= -config['csd_span'])
        last = min((int(visible[-1]) if len(visible) else 0)+2, len(t)-1)
        duration = max(t[last], .1)
        # Resample the useful interval, retaining the same time-zero reference.
        f, t, magnitude = decay(ir, fs, duration, window, pre_time=pre_time)
        amplitude = np.array([np.interp(frequency, f, row) for row in magnitude])
        db = 20*np.log10(np.maximum(amplitude/reference, 1e-12))
    if config.get('wavelet_units', 'Cycles') == 'Cycles':
        end_cycles = config.get('wavelet_duration', 20.)
        if config.get('csd_auto_time', True):
            end_cycles = max(.1, max((max(t[db[:,j] >= -config['csd_span']], default=0)*frequency[j]/1000 for j in range(len(frequency)))))
        coordinate = np.unique(np.append(np.linspace(-config.get('wavelet_pre',1.),end_cycles,240),0.))
        peak = int(np.argmax(abs(ir))); shoulder = max(2, round(fs*.0002))
        end = len(ir) if window is None else min(len(ir),peak+max(16,round(window*fs/1000)))
        signal = np.asarray(ir[:end],float).copy()
        if window is not None:
            fade=min(end,max(2,round(.1*end))); signal[-fade:] *= np.cos(np.linspace(0,np.pi/2,fade))**2
        amplitude = np.zeros((len(coordinate),len(frequency)))
        for j,hz in enumerate(frequency):
            values = signal*np.exp(-2j*np.pi*hz*np.arange(end)/fs)
            tail = np.r_[np.cumsum(values[::-1])[::-1],0j]
            cuts = peak+coordinate/hz*fs
            full = np.clip(np.ceil(cuts).astype(int),0,end)
            indices = np.ceil(cuts).astype(int)[:,None]-np.arange(1,shoulder+1)[None,:]
            weights = np.sin(np.clip((indices-cuts[:,None])/shoulder+1,0,1)*np.pi/2)**2
            valid=(indices>=0)&(indices<end)
            amplitude[:,j]=abs(tail[full]+np.sum(values[np.clip(indices,0,end-1)]*weights*valid,axis=1))
        if config.get('csd_level_reference') in (True, 'IR peak slice per frequency'):
            reference=np.maximum(amplitude[coordinate==0][0],np.max(amplitude)*1e-12+1e-30)
        db=20*np.log10(np.maximum(amplitude/reference,1e-12)); t=coordinate
    return frequency, t, db


def wavelet_map(ir, fs, config):
    """Impulse-calibrated complex Morlet transform, linear convolution of the entire IR.

    Resolution is omega0 = 2*pi*f*sigma (not the display's cycle axis).
    A DC correction ensures zero mean. Zero padding prevents circular wrap.
    Cycle coordinates are resampled separately at every frequency: t = c/f.
    """
    from scipy.signal import fftconvolve
    signal = np.asarray(ir, float).copy()
    peak = int(np.argmax(abs(signal)))
    low, high = max(1., config['csd_fmin']), min(fs*.49, config['csd_fmax'])
    if low >= high: raise ValueError('Wavelet frequency limits must overlap the IR frequency range.')
    frequencies = np.geomspace(low, high, 192)
    omega = config.get('wavelet_cycles', 12.)
    cycles = config.get('wavelet_units') == 'Cycles'
    pre = config.get('wavelet_pre', 1.) if cycles else config.get('csd_pre_time', 1.)
    duration = config.get('wavelet_duration', 20.) if cycles else config['csd_time']
    envelopes = []
    reference = 1e-30
    for frequency in frequencies:
        sigma = omega/(2*np.pi*frequency)
        half = max(2, int(np.ceil(5*sigma*fs)))
        tau = np.arange(-half, half+1)/fs
        gaussian = np.exp(-.5*(tau/sigma)**2)
        kernel = gaussian*(np.exp(2j*np.pi*frequency*tau)-np.exp(-.5*omega**2))
        # Calibrate against a unit impulse at each scale. L1 normalization
        # instead gives a flat-IR spectrum an artificial +6 dB/octave tilt.
        kernel /= 1-np.exp(-.5*omega**2)
        envelope = abs(fftconvolve(signal, kernel, mode='full'))
        time = (np.arange(len(envelope))-half-peak)/fs
        reference = max(reference, float(envelope.max()))
        envelopes.append((time, envelope))
    time_reference = config.get('wavelet_time_reference', False)
    if isinstance(time_reference, bool): time_reference = 'Each frequency peak' if time_reference else 'IR peak'
    peak_times = [time[int(np.argmax(envelope))] for time, envelope in envelopes]
    if time_reference == 'Each frequency peak':
        envelopes = [(time-shift, envelope) for (time,envelope),shift in zip(envelopes,peak_times)]
    elif time_reference == 'Strongest wavelet peak':
        strongest = int(np.argmax([envelope.max() for _,envelope in envelopes]))
        envelopes = [(time-peak_times[strongest], envelope) for time,envelope in envelopes]
    references = np.full(len(envelopes), reference)
    if config.get('wavelet_level_reference') in (True, 'Each frequency peak'):
        references = np.maximum([envelope.max() for _,envelope in envelopes], reference*1e-12)
    if config.get('csd_auto_time', True):
        duration = .1
        floors = references*10**(-config['csd_span']/20)
        for frequency, (time, envelope), floor in zip(frequencies, envelopes, floors):
            indices = np.flatnonzero((envelope >= floor) & (time >= 0))
            if len(indices): duration = max(duration, time[indices[-1]]*(frequency if cycles else 1000))
        duration *= 1.03
    coordinate = np.unique(np.append(np.linspace(-pre, duration, 240), 0.))
    amplitude = np.column_stack([np.interp(coordinate/(frequency if cycles else 1000), time, envelope, left=0., right=0.)
        for frequency, (time, envelope) in zip(frequencies, envelopes)])
    db = 20*np.log10(np.maximum(amplitude/references, 1e-12))
    return frequencies, coordinate, db


def decay_setting_keys(config):
    if config.get('_all_decay_controls'):
        return ['csd_method','csd_mode','csd_level_reference','wavelet_level_reference','wavelet_time_reference','wavelet_cycles','wavelet_units','csd_auto_time','csd_time','csd_pre_time','wavelet_duration','wavelet_pre','csd_span','csd_fmin','csd_fmax']
    wavelet = config.get('csd_method') == 'Morlet wavelet' or config.get('kind') == 'wavelet'
    keys = ['csd_method','csd_mode']
    if wavelet:
        keys += ['wavelet_level_reference', 'wavelet_time_reference', 'wavelet_cycles']
    else: keys += ['csd_level_reference']
    keys += ['wavelet_units', 'csd_auto_time']
    if config.get('_all_time_controls') or config.get('wavelet_units', 'Cycles') != 'Cycles': keys += ['csd_time', 'csd_pre_time']
    if config.get('_all_time_controls') or config.get('wavelet_units', 'Cycles') == 'Cycles': keys += ['wavelet_duration', 'wavelet_pre']
    return keys + ['csd_span', 'csd_fmin', 'csd_fmax']


def analysis_ir(owner, sphere):
    """Evaluate native bins at the probe; use the unchanged HALS preview/IR core."""
    source = sphere.metadata.get('source') or owner.source_path
    if source and Path(source).suffix.lower() in ('.h5', '.hdf5') and Path(source).is_file():
        from export_preview import PreviewCache
        from export_engine import DEFAULT_EXPORT
        if not hasattr(owner, '_csd_preview'): owner._csd_preview = PreviewCache()
        az, el = np.deg2rad([owner.azimuth.value(), owner.elevation.value()])
        radius = sphere.metadata.get('radius_m', 2.)
        point = radius*np.array([np.cos(el)*np.cos(az), np.cos(el)*np.sin(az), np.sin(el)])+np.asarray(sphere.metadata.get('offset_m', [0,0,0]))
        r = np.linalg.norm(point); coord = [float(np.degrees(np.arccos(point[2]/r))), float(np.degrees(np.arctan2(point[1], point[0]))), float(r)]
        config = dict(deepcopy(DEFAULT_EXPORT), coeff_path=str(source), mode='Manual coordinates', manual_coords=[coord], subtract_tof='Off',
                      obs_mode=sphere.metadata.get('mode','Internal'), use_optimized_origins=sphere.metadata.get('optimized_origins',True),
                      manual_ir_capture_padding=True, ir_capture_padding_samples=sphere.metadata.get('padding_samples_removed',50))
        from mic_calibration import config as mic_config
        config.update(mic_config(owner))
        key = (str(source), Path(source).stat().st_mtime_ns, repr(config))
        if key != getattr(owner, '_csd_ir_key', None):
            result = owner._csd_preview.run(config, 0, owner.pool, lambda *_:None, lambda:False)
            owner._csd_ir = (result['preview_ir'], 1/np.diff(result['preview_ir_times'][:2])[0]); owner._csd_ir_key = key
        return *owner._csd_ir, 'HALS Stage 5 IR · native frequency bins · time zero at IR peak'
    # Imported full-bin sphere exports may also be used, never interpolate sparse bins.
    if not np.allclose(np.diff(sphere.freqs), np.diff(sphere.freqs)[0], rtol=.001):
        raise ValueError('Impulse-response analysis requires native frequency bins. Open the project/coefficient file to evaluate a Stage 5 IR.')
    from complex_to_ir_core import complex_to_ir
    fs = sphere.metadata.get('fs') or (44100 if sphere.freqs[-1] < 23000 else 48000)
    pressure = sphere.pressure[:, *sphere.index(owner.azimuth.value(), owner.elevation.value())]
    return complex_to_ir(pressure, sphere.freqs, target_fs=fs), fs, 'HALS Stage 5 IR · imported uniform frequency bins'


class CameraZoom(C.QObject):
    eventFilter = PlotInteraction.eventFilter
    def __init__(self, view): super().__init__(view); self.pane = view


class CSDView(W.QWidget):
    def __init__(self):
        super().__init__(); self.plotter = None; self.free_zoom_out = True; self.config = {}; self.last_render = None
        layout = W.QVBoxLayout(self); layout.setContentsMargins(0,0,0,0)
        self.stack = W.QStackedWidget(); layout.addWidget(self.stack)
        self.chart = Chart(); self.stack.addWidget(self.chart); self.interaction = PlotInteraction(self)
        self.latest = None; self._key = None; self._data = None
    def render(self, ir, fs, config):
        from viewer_theme import NAME, scene_theme
        config = {**DEFAULTS, **config}
        if config.get('_y_label') != self.config.get('_y_label'): self.initialized=False
        self.config = config; self.latest = (ir, fs, config)
        key = (id(ir), fs, tuple((k,config[k]) for k in DEFAULTS if k != 'csd_mode'))
        wavelet = config['csd_method'] == 'Morlet wavelet'
        unit = 'cycles' if config['wavelet_units'] == 'Cycles' else 'ms'
        if config.get('_surface_data') is not None:
            self._data=config['_surface_data']; self._key=None; key=(key,id(self._data))
        elif key != self._key: self._data = (wavelet_map if wavelet else decay_map)(ir,fs,config); self._key = key
        f,t,db = self._data; self.data = self._data; span = config['csd_span']
        time_reference = config['wavelet_time_reference'] if wavelet else 'IR peak'
        if isinstance(time_reference,bool): time_reference='Each frequency peak' if time_reference else 'IR peak'
        time_label = {'IR peak': 'IR peak', 'Each frequency peak': 'each frequency peak', 'Strongest wavelet peak': 'strongest wavelet peak'}[time_reference]
        y_label = config.get('_y_label',f'Time from {time_label} / {unit}')
        palette = 'PColor'
        upper = max(0., float(np.ceil(np.max(db)/5)*5))
        if config['csd_mode'] == 'Sonogram':
            self.stack.setCurrentWidget(self.chart); self.chart.fig.clear(); self.chart.fig.set_layout_engine('constrained')
            ax = self.chart.fig.add_subplot(); im = ax.pcolormesh(f,t,db,cmap=palette,vmin=-span,vmax=upper,shading='auto')
            ax.set_xscale('log'); ax.set_xticks(audio_ticks(f[0],f[-1])); ax.xaxis.set_major_formatter(FuncFormatter(lambda v,_:audio_frequency(v)))
            ax.set_xlabel('Frequency / Hz'); ax.set_ylabel(y_label); self.chart.fig.colorbar(im,ax=ax,label='Relative level / dB')
            self.interaction.begin(key); self.interaction.finish([ax]); self.chart.done(); return
        if self.plotter is None:
            self.plotter = QtInteractor(self,auto_update=False); self.plotter.render_window.SetMultiSamples(0)
            self.stack.addWidget(self.plotter.interactor); self.zoom_filter = CameraZoom(self); self.plotter.interactor.installEventFilter(self.zoom_filter)
            self.plotter.enable_terrain_style()
        self.stack.setCurrentWidget(self.plotter.interactor); p = self.plotter
        camera = p.camera_position if getattr(self,'initialized',False) else None
        p.suppress_rendering=True; p.clear()
        x,y = np.meshgrid(3*(np.log10(f)-np.log10(f[0]))/np.log10(f[-1]/f[0]), -2*(t-t[0])/max(t[-1]-t[0],.001))
        z = 1.5*(db+span)/(span+upper)
        if config.get('_surface_data') is not None: z=np.maximum(z,0.)
        grid = pv.StructuredGrid(x,y,z); grid['Level'] = db.ravel(order='F')
        surface = grid.extract_surface(algorithm='dataset_surface').clip(normal=(0,0,1),origin=(0,0,0),invert=False)
        if config.get('_surface_data') is not None:
            top=grid.extract_surface(algorithm='dataset_surface')
            bottom=pv.StructuredGrid(x,y,np.full_like(z,-.015)).extract_surface(algorithm='dataset_surface')
            bottom['Level']=np.full(bottom.n_points,-span)
            # The perimeter runs around all four sides; stitch it to a base.
            rows,cols=x.shape
            indices=[(0,j) for j in range(cols)]+[(i,cols-1) for i in range(1,rows)]+[(rows-1,j) for j in range(cols-2,-1,-1)]+[(i,0) for i in range(rows-2,0,-1)]
            rim=np.array([[x[i,j],y[i,j],z[i,j]] for i,j in indices]); n=len(rim)
            base=rim.copy(); base[:,2]=-.015
            faces=np.array([[4,i,(i+1)%n,(i+1)%n+n,i+n] for i in range(n)]).ravel()
            walls=pv.PolyData(np.vstack([rim,base]),faces)
            walls['Level']=np.r_[[db[i,j] for i,j in indices],np.full(n,-span)]
            surface=top.merge(bottom).merge(walls).clean()
        self.surface = surface
        if surface.n_points:
            p.add_mesh(surface,scalars='Level',cmap=palette,clim=(-span,upper),show_edges=False,smooth_shading=True,
                       ambient=.3,diffuse=.65,specular=.3,specular_power=24,show_scalar_bar=False)
        if config.get('_surface_data') is not None and config.get('contours',True):
            contours=grid.contour(-np.arange(config.get('directivity_contour_step',6.),span,config.get('directivity_contour_step',6.)),scalars='Level')
            if contours.n_points: p.add_mesh(contours,color='#ffffff',line_width=1.5,lighting=False)
        text = '#345574' if NAME=='Light' else '#afc6db'
        p.show_bounds(bounds=(0,3,-2,0,0,1.5),grid='back',location='outer',all_edges=False,color=text,
                      xtitle='Frequency / Hz',ytitle=y_label,ztitle='Level / dB',n_xlabels=2,show_xlabels=False,n_ylabels=2,show_ylabels=False,n_zlabels=4,
                      axes_ranges=(0,1,0,float(t[-1]),-span,upper),font_size=9)
        ticks = audio_ticks(f[0],f[-1]); tick_x=3*np.log10(ticks/f[0])/np.log10(f[-1]/f[0])
        p.add_point_labels(np.column_stack([tick_x,np.full(len(ticks),-2.06),np.full(len(ticks),-.04)]),[audio_frequency(v) for v in ticks],
                           font_size=11,text_color=text,shape=None,show_points=False,always_visible=True)
        time_ticks = np.linspace(t[0], t[-1], 5)
        if config.get('_surface_data') is not None: time_ticks=np.array([v for v in (-180,-90,0,90,180) if t[0]<=v<=t[-1]])
        p.add_point_labels(np.column_stack([np.full(len(time_ticks),3.08),-2*(time_ticks-t[0])/max(t[-1]-t[0],.001),np.full(len(time_ticks),-.04)]),[f'{v:.1f}' for v in time_ticks],
                           font_size=11,text_color=text,shape=None,show_points=False,always_visible=True)
        p.remove_all_lights()
        for elevation, azimuth, strength in [(45,-45,.8), (20,120,.35), (70,30,.4)]:
            light = pv.Light(light_type='camera light',intensity=strength); light.set_direction_angle(elevation,azimuth); p.add_light(light)
        scene_theme(p)
        if camera: p.camera_position=camera
        else: p.camera_position=[(4.5,-6,3.8),(1.5,-.9,.65),(0,0,1)]; p.reset_camera()
        p.reset_camera_clipping_range(); self.home_focal=np.asarray(p.camera.focal_point); self.home_distance=p.camera.distance
        self.initialized=True; p.suppress_rendering=False; p.render()
    def reset(self):
        self.initialized=False; self.interaction.saved.clear()
        if self.latest: self.render(*self.latest)
    def shutdown(self):
        if self.plotter: self.plotter.close()


class CSDPanel(W.QWidget):
    def __init__(self):
        super().__init__(); self.config=dict(DEFAULTS); self.latest=None
        layout=W.QVBoxLayout(self); layout.setContentsMargins(5,5,5,5)
        row=W.QHBoxLayout(); layout.addLayout(row); self.method=W.QComboBox(); self.method.addItems(['CSD','Morlet wavelet']); self.method.currentTextChanged.connect(self.set_method); row.addWidget(self.method); row.addStretch()
        self.mode=W.QComboBox(); self.mode.addItems(['3D waterfall','Sonogram']); self.mode.currentTextChanged.connect(self.set_mode); row.addWidget(self.mode)
        button=W.QPushButton('Reset axes'); button.clicked.connect(lambda:self.view.reset()); row.addWidget(button)
        gear=W.QToolButton(); gear.setText('\u2699'); gear.clicked.connect(self.settings); row.addWidget(gear)
        self.view=CSDView(); self.chart=self.view.chart; layout.addWidget(self.view,1)
        self.note=W.QLabel('HALS Stage 5 IR · time zero at the IR peak'); self.note.setWordWrap(True); layout.addWidget(self.note)
    def set_method(self,method): self.config['csd_method']=method; self.redraw()
    def set_mode(self,mode): self.config['csd_mode']=mode; self.redraw()
    def update_ir(self,ir,fs): self.latest=(ir,fs); self.redraw()
    def redraw(self):
        if self.latest:
            self.view.render(*self.latest,self.config)
            unit = 'cycles' if self.config.get('wavelet_units', 'Cycles') == 'Cycles' else 'ms'
            self.note.setText(f'HALS IR - display {self.view.data[1][0]:.2f} to {self.view.data[1][-1]:.2f} {unit}')
    def settings(self):
        from panes import SPECS,editor
        dialog=W.QDialog(self); dialog.setWindowTitle('Time / frequency decay settings'); form=W.QFormLayout(dialog); values={**DEFAULTS, **self.config}
        rows={}
        def changed(key,value):
            values[key]=value
            for name,row in rows.items():
                form.setRowVisible(row,name in decay_setting_keys(values))
        for key in decay_setting_keys({**values,'_all_decay_controls':True}):
            rows[key]=form.rowCount()
            form.addRow(SPECS[key][0],editor(key,values[key],lambda v,k=key:changed(k,v)))
        changed('wavelet_units',values['wavelet_units'])
        buttons=W.QDialogButtonBox(W.QDialogButtonBox.Ok|W.QDialogButtonBox.Cancel); form.addRow(buttons); buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject)
        if dialog.exec()==W.QDialog.Accepted:
            if values['csd_fmin']>=values['csd_fmax']: return
            self.config.update(values)
            for control,key in [(self.method,'csd_method'),(self.mode,'csd_mode')]:
                control.blockSignals(True); control.setCurrentText(values[key]); control.blockSignals(False)
            self.redraw()
