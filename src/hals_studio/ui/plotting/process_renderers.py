"""Stage-specific result renderers; the Qt host owns canvas and interaction lifetime."""
import numpy as np
from matplotlib.figure import Figure
from PySide6 import QtWidgets as W, QtCore as C
from hals_studio import bootstrap
from hals_studio.ui.plotting.process_results import VIEWS, theme


def draw_fdw(host, workspace):
    self, p = host, workspace
    r = p.results[p.stage]
    kind = p.view.currentText()
    from hals_studio.process_engine.stage1_fdwsmooth import load_and_prep_ir
    from pathlib import Path
    f,raw,smooth,meta=r[:4];name=p.sample.currentData() or next(iter(raw));fs=float(r[4]) if len(r)>4 else 2*float(f[-1]);n_fft=round(fs/(f[1]-f[0]));data=None
    try:
        data,fs_wav=load_and_prep_ir(str(Path(p.ir_folder.text())/name),crop_samples=n_fft)
        data=np.pad(data,(0,max(0,n_fft-len(data))));fs=fs_wav
    except (OSError,RuntimeError,ValueError):
        # The NPZ is sufficient for the frequency response and smoothing curves.
        # A WAV is only needed for the optional time-domain IR panel.
        pass
    show_both=p.stage1_plot_settings()['keep_raw_and_smoothed'];primary=smooth[name] if smooth and p.stage1_plot_settings()['enable_smoothing'] and not show_both else raw[name]
    view=VIEWS['FDWView'](figsize=(12,8));view.update_view(name,p.sample.currentIndex(),f,primary,smooth.get(name) if smooth and show_both else None,meta[name],data,fs,float(meta[name].get('rft_ms',p.values[3]['fdw_rft_ms'])))
    if data is None:
        for label in view.ax2.texts:
            if label.get_text()=='Error loading wav':
                label.set_text('WAV unavailable\nShowing saved NPZ results')
    from hals_studio.process_engine.utils import _ph_pat
    match=_ph_pat.match(name)
    if match:
        decode=lambda key:float(match.group(key).replace('p','.'))
        view.ax1.set_title(f"Radius {decode('rmm'):g} mm | Phi {decode('ph'):g} deg | Height {decode('zmm'):g} mm\nFDW Magnitude", pad=24)
    view.fig.subplots_adjust(right=.79,top=.91,hspace=.5)
    from hals_studio.ui.viewer_theme import NAME
    if NAME=='Dark':
        from matplotlib.colors import LinearSegmentedColormap
        from hals_studio.ui.viewer_theme import colour
        probe=colour('#47d7ec')
        ramp=LinearSegmentedColormap.from_list('fdw',['#b49bf5','#7ebeff','#68d9ca'])
        top_frequency=fs/2
        centers=np.asarray(meta[name]['f_centers']);valid=centers[(centers>=view.ax1.get_xlim()[0]) & (centers<=top_frequency)]
        low=max(float(valid.min()) if len(valid) else 10.,1.)
        def window_color(freq):return ramp(np.clip(np.log(max(freq,low)/low)/max(np.log(top_frequency/low),1e-9),0,1))
        for i,line in enumerate(view.ax2.lines):
            if i<2:line.set_color(probe if i==0 else '#ffb56f')
            else:
                import re
                match=re.match(r'([\d.]+)Hz',line.get_label())
                if match:line.set_color(window_color(float(match.group(1))))
            line.set_alpha(1)
        for i,line in enumerate(view.ax1.lines):
            x=np.asarray(line.get_xdata())
            line.set_color(window_color(float(x[0])) if len(x)==2 and x[0]==x[1] else probe if i==0 else '#a9a1f5')
        for ax in (view.ax1,view.ax2):
            legend=ax.get_legend()
            if legend:
                handles,_=ax.get_legend_handles_labels()
                for target,source in zip(legend.legend_handles,handles):target.set_color(source.get_color())
        view.ax3.lines[0].set_color(probe)
    for patch in list(view.ax1.patches): patch.remove()
    rft_lower = float(meta[name]['f_trans'])
    rft_supplied = meta[name].get('rft_supplied', True) and getattr(p, 'rft_supplied', True)
    if NAME=='Light' and rft_supplied:
        lower = view.ax1.get_xlim()[0]
        upper = min(rft_lower, fs / 2)
        if upper > lower:
            view.ax1.axvspan(lower, upper, color='#fff2c7', alpha=1, zorder=0)
    if rft_supplied and rft_lower < fs / 2:
        view.ax1.axvspan(rft_lower, fs / 2, color='#47d7ec', alpha=0.12)
    if not rft_supplied:
        for label in list(view.ax1.texts):
            if label.get_text() == 'Reflection free range': label.remove()
    curves = [line for line in view.ax1.lines if len(line.get_xdata()) > 2]
    if smooth and p.stage1_plot_settings()['enable_smoothing']:
        smoothing_label = 'FDW + Smoothing' if meta[name].get('sliding_hf') else 'FDW + fixed smoothing'
        if show_both and len(curves)>1: curves[1].set_label(smoothing_label)
        elif curves: curves[0].set_label(smoothing_label)
        view.ax1.legend(loc='best', fontsize=8)
    fixed = meta[name].get('fixed_smoothing')
    if fixed is not None:
        view.ax1.plot(f, 20*np.log10(np.maximum(abs(fixed),1e-20)), color='#ffb56f', linewidth=1, linestyle='--', label='Fixed smoothing comparison')
        view.ax1.legend(loc='best', fontsize=8)

    return view


def draw_origin_validation(host, workspace):
    self, p = host, workspace
    r = p.results[p.stage]
    kind = p.view.currentText()
    rows=r[0];freqs=sorted(rows);current=np.array([rows[f]['final_c'] for f in freqs]).T;original=np.array([rows[f].get('original_c',rows[f]['final_c']) for f in freqs]).T
    errors=[rows[f]['error'] for f in freqs];old=[rows[f].get('original_error',rows[f]['error']) for f in freqs]
    view=VIEWS['ValidationView']();view.update_view(freqs,current,original,errors,old)
    from hals_studio.ui.viewer_theme import NAME
    if NAME=='Dark':
        from matplotlib.colors import to_hex
        from hals_studio.ui.plotting.plots import COLORS
        from hals_studio.ui.viewer_theme import colour
        for ax,color in zip(view.fig.axes,map(colour,COLORS)):
            legend=ax.get_legend()
            for item in [*ax.lines,*ax.texts,*(legend.legend_handles if legend else [])]:
                if to_hex(item.get_color())=='#0000ff':item.set_color(color);item.set_alpha(1)

    return view


def draw_origin_cloud(host, workspace):
    self, p = host, workspace
    r = p.results[p.stage]
    kind = p.view.currentText()
    camera = None
    previous = getattr(host, '_origin_cloud_figure', None)
    if (previous is not None and getattr(host, 'fig', None) is previous
            and getattr(host, '_origin_cloud_result', None) is r):
        ax = previous.axes[0]
        camera = (ax.elev, ax.azim, ax.roll, ax.get_xlim3d(), ax.get_ylim3d(), ax.get_zlim3d())
    rows=r[0];freqs=sorted(rows);xyz=np.array([rows[f]['final_c'] for f in freqs]);view=VIEWS['CloudBrowser3DView'](r[5]);view.update_view(freqs,*xyz.T,max(0,p.sample.currentIndex()))
    if camera is not None:
        elev, azim, roll, xlim, ylim, zlim = camera
        view.ax.view_init(elev=elev, azim=azim, roll=roll)
        view.ax.set_xlim3d(xlim); view.ax.set_ylim3d(ylim); view.ax.set_zlim3d(zlim)
    host._origin_cloud_figure = view.fig
    host._origin_cloud_result = r
    active=max(0,p.sample.currentIndex());point=xyz[active];view.ax.set_title('')
    view.fig.text(.035,.96,f'{freqs[active]:g} Hz\nX {point[0]:.1f} mm\nY {point[1]:.1f} mm\nZ {point[2]:.1f} mm',va='top',fontsize=11)
    from hals_studio.ui.viewer_theme import colour
    view.scatter_all.set_color(colour('#47d7ec'));view.scatter_all.set_alpha(.9);view.scatter_hi.set_color('#ffba68');view.ax.legend(loc='upper right')

    return view


def draw_origin_grid(host, workspace):
    self, p = host, workspace
    r = p.results[p.stage]
    kind = p.view.currentText()
    rows=r[0];f=p.sample.currentData() or next(iter(rows));row=rows[f];view=VIEWS['FrequencyBrowser3DView'](r[5]);plane={'XY':'XY (Z Height)','XZ':'XZ (Y Width)','YZ':'YZ (X Depth)'}[p.plane.currentText()]
    view.update_view(f,row.get('grid'),row['X_vals'],row['Y_vals'],row['Z_vals'],row['final_c'],plane,p.slice_value())

    return view


def draw_order_selection(host, workspace):
    self, p = host, workspace
    r = p.results[p.stage]
    kind = p.view.currentText()
    import sys
    from hals_studio.process_engine.stage3_optimize_she_settings import plot_internal_tail_power,highlight_stage3_choices,format_stage3_ratio_axis,format_stage3_order_axis
    from hals_studio.process_engine.stage3_spl_change import plot_spl_changes
    fig=Figure(figsize=(12,8),layout='constrained');axes=fig.subplots(2,2);ratio,spl,power,notes=axes.ravel();step=r['step1'];orders=step['orders'];options=r['options']
    ratio.plot(orders,step['ratios'],'o-',color='#599bda');ratio.axhline(r.get('sfs_ratio_rule_db',20),color='#59a14f',linestyle='--',label='20 dB quality threshold');format_stage3_ratio_axis(ratio,inspection_only=r.get('tail_only',False));format_stage3_order_axis(ratio);ratio.set_xticks(orders);ratio.set_title('Internal / External Ratio');ratio.grid(alpha=.3);highlight_stage3_choices(ratio,options);ratio.legend(fontsize=8)
    plot_internal_tail_power(power,orders,step['internal_tail_power_db'],step['tail_reference']);highlight_stage3_choices(power,options,tail=True);power.legend(fontsize=8)
    if r.get('spl_change'):plot_spl_changes(spl,dict(r['spl_change'],order_choices={k:v for k,v in options.items() if k=='spl'}))
    import textwrap
    notes.axis('off')
    ratio.set_title('Internal / External Ratio',pad=40)
    if r.get('tail_only'):
        for line in ratio.lines:line.set_alpha(.2)
        ratio.text(.5,.5,'Unavailable for order selection\nOutside the usable separation range',ha='center',va='center',transform=ratio.transAxes,bbox=dict(facecolor='#101c28',alpha=.9))
        if not step['tail_reference'].get('manual'):power.text(.5,.5,'Select a reference order manually\nto use sound power discarded',ha='center',va='center',transform=power.transAxes,bbox=dict(facecolor='#101c28',alpha=.9))
    self.show_figure(fig)
    panel=W.QScrollArea(self.canvas);panel.setWidgetResizable(True);panel.setFrameShape(W.QFrame.NoFrame);content=W.QWidget();layout=W.QVBoxLayout(content);layout.setContentsMargins(12,12,12,12);panel.setWidget(content)
    from hals_studio.ui.viewer_theme import NAME
    bg='#101c28' if NAME=='Dark' else '#ffffff'
    panel.setStyleSheet(f'QWidget {{background:{bg};font-size:14px;border:none;}} QRadioButton::indicator {{width:16px;height:16px;border:1px solid #599bda;border-radius:8px;background:{bg};}} QRadioButton::indicator:checked {{background:#599bda;border:3px solid #a9d2f7;}} QPushButton {{background:#285b85;border:1px solid #599bda;padding:7px;border-radius:4px;color:white;}}')
    radio_off=(bootstrap.RESOURCES/'assets/radio-off.svg').as_posix();radio_on=(bootstrap.RESOURCES/'assets/radio-on.svg').as_posix()
    panel.setStyleSheet(panel.styleSheet()+f' QRadioButton, QRadioButton:checked, QRadioButton:hover {{background:transparent;}} QRadioButton::indicator, QRadioButton::indicator:checked {{width:20px;height:20px;border:none;background:transparent;image:url("{radio_off}");}} QRadioButton::indicator:checked {{image:url("{radio_on}");}}')
    attention=W.QFrame(content);attention.setObjectName('stage3_recommendation')
    attention_layout=W.QVBoxLayout(attention);attention_layout.setContentsMargins(10,10,10,10);attention_layout.setSpacing(5)
    attention.setStyleSheet(f'QFrame#stage3_recommendation {{ border: 1px solid #3978a8; border-radius: 8px; background: {bg}; }}')
    layout.addWidget(attention,alignment=C.Qt.AlignHCenter)
    attention_layout.addWidget(W.QLabel('Recommended order'))
    group=W.QButtonGroup(content);self.recommendation_buttons=[]
    for key,opt in options.items():
        radio=W.QRadioButton(f"{opt.get('label',key)}: N={opt['n']}")
        radio.setText({'knee':'Internal / external ratio','tail':'Sound power discarded','spl':'Directivity change'}.get(key,key)+f" — N={opt['n']}")
        group.addButton(radio);attention_layout.addWidget(radio);self.recommendation_buttons.append(radio)
        if opt.get('reason'):
            detail=W.QLabel(opt['reason']);detail.setWordWrap(True);attention_layout.addWidget(detail)
        radio.setChecked(opt['n']==p.order_choice.currentData())
        radio.toggled.connect(lambda on,n=opt['n']:p.order_choice.setCurrentIndex(p.order_choice.findData(int(n))) if on else None)
    if not group.checkedButton() and self.recommendation_buttons:self.recommendation_buttons[0].setChecked(True)
    info=W.QLabel('Choose the recommendation to use in Stage 4. Growth optimisation runs there before the solve.')
    info.setWordWrap(True);attention_layout.addWidget(info)
    action=W.QPushButton();action.setObjectName('stage3_use_order');action.setFixedSize(184,38)
    action.clicked.connect(p.order_action);attention_layout.addWidget(action,alignment=C.Qt.AlignLeft)
    p.refresh_order_action()
    if getattr(p,'_stage3_pulse_pending',False) and not getattr(p,'_autosaving_plots',False):
        from PySide6 import QtGui as G
        effect=W.QGraphicsDropShadowEffect(attention);effect.setOffset(0,0)
        effect.setColor(G.QColor(45,155,255,220));effect.setBlurRadius(4);attention.setGraphicsEffect(effect)
        sequence=C.QSequentialAnimationGroup(attention)
        up=C.QPropertyAnimation(effect,b'blurRadius',sequence);up.setDuration(450);up.setStartValue(4);up.setEndValue(24);sequence.addAnimation(up)
        down=C.QPropertyAnimation(effect,b'blurRadius',sequence);down.setDuration(650);down.setStartValue(24);down.setEndValue(4);sequence.addAnimation(down)
        sequence.setLoopCount(4);p._stage3_attention_animation=sequence;sequence.start();p._stage3_pulse_pending=False
    layout.addStretch()
    def position(*_):
        bounds=notes.get_window_extent();scale=self.canvas.device_pixel_ratio
        available_width=max(280,min(480,round(bounds.width/scale)));available_height=round(bounds.height/scale)
        panel.setGeometry(round(bounds.x0/scale)+(round(bounds.width/scale)-available_width)//2,round(self.canvas.height()-bounds.y1/scale),available_width,available_height)
    self.canvas.mpl_connect('draw_event',position);self.canvas.mpl_connect('resize_event',position);panel.show();self.canvas.draw();position();return



def draw_spatial_error(host, workspace):
    self, p = host, workspace
    r = p.results[p.stage]
    kind = p.view.currentText()
    from hals_studio.persistence.process_cache import spatial_reconstruction
    r=p.spatial_results()
    f=r['freqs'];i=int(np.argmin(abs(f-p.frequency.value())));xyz=p.spherical_xyz(r['coords_sph']);view=VIEWS['SpatialErrorView']();view.update_view(*xyz.T,f[i],r['N_used'][i],r['P_measured'][i],spatial_reconstruction(r,i),p.threshold.value())
    self.show_figure(view.fig)
    from matplotlib.widgets import Slider
    frequency_ax=view.fig.add_axes([.11,.90,.132,.018]);floor_ax=view.fig.add_axes([.11,.815,.132,.018])
    frequency_ax.set_xscale('log')
    self.spatial_sliders=[Slider(frequency_ax,'',float(f[0]),float(f[-1]),valinit=float(f[i])),Slider(floor_ax,'',-120,0,valinit=p.threshold.value(),valstep=1)]
    freq_slider,floor_slider=self.spatial_sliders
    frequency_text=view.fig.text(.025,.923,f'Frequency\n{f[i]:,.1f} Hz',va='top',fontsize=10);floor_text=view.fig.text(.025,.838,f'Floor\n{p.threshold.value():g} dB',va='top',fontsize=10)
    freq_slider.valtext.set_visible(False);floor_slider.valtext.set_visible(False)
    log_freqs=np.log(f)
    def update(_):
        index=int(np.argmin(np.abs(log_freqs-np.log(max(float(freq_slider.val),float(f[0]))))))
        # Snap the handle to the nearest available solve bin while
        # keeping its position logarithmic in frequency.
        freq_slider.eventson=False;freq_slider.set_val(float(f[index]));freq_slider.eventson=True
        p.frequency.blockSignals(True);p.frequency.setValue(float(f[index]));p.frequency.blockSignals(False)
        p.threshold.blockSignals(True);p.threshold.setValue(floor_slider.val);p.threshold.blockSignals(False)
        angles=(view.ax.elev,view.ax.azim)
        view.update_view(*xyz.T,f[index],r['N_used'][index],r['P_measured'][index],spatial_reconstruction(r,index),floor_slider.val)
        view.ax.view_init(*angles);frequency_text.set_text(f'Frequency\n{f[index]:,.1f} Hz');floor_text.set_text(f'Floor\n{floor_slider.val:g} dB');theme(view.fig);self.canvas.draw_idle()
    for slider in self.spatial_sliders:slider.poly.set_facecolor('#599bda');slider.on_changed(update)
    theme(view.fig);self.canvas.draw_idle();return



def draw_sound_power(host, workspace):
    self, p = host, workspace
    r = p.results[p.stage]
    kind = p.view.currentText()
    from hals_studio.analysis.sound_power import sound_power_figure, PowerLegend
    self.show_figure(sound_power_figure(p.coefficient_path(),p.power_field.currentText()))
    self.enable_plot_controls(self.fig.axes, 'sound_power')
    path=str(p.coefficient_path())
    if getattr(self,'power_legend_path',None)!=path:self.power_hidden=set();self.power_legend_path=path
    self.power_legend=PowerLegend(self.fig,self.power_hidden)
    self.canvas.setToolTip('Legend checkbox: show/hide trace · Shift-click legend: show only that trace\nWheel: zoom at cursor · Wheel over an axis: zoom that axis · Middle drag: pan · Reset axes: full view')
    return



def draw_condition_number(host, workspace):
    self, p = host, workspace
    r = p.results[p.stage]
    kind = p.view.currentText()
    view=VIEWS['SHEResultsView']();f=r['freqs'];orders=r['N_used'];ticks=[0];labels=[str(orders[0])]
    ticks.extend(i for i in range(1,len(orders)) if orders[i]!=orders[i-1])
    labels.extend(str(orders[i]) for i in ticks[1:])
    view.update_cond_view(f,r['cond'],f[ticks],labels);self.show_figure(view.fig_cond);return



def draw_fit_error(host, workspace):
    self, p = host, workspace
    r = p.results[p.stage]
    kind = p.view.currentText()
    view=VIEWS['SHEResultsView']();f=r['freqs'];orders=r['N_used'];boundaries=[];start=f[0];n=orders[0]
    for i in range(1,len(f)):
        if orders[i]!=n:boundaries.append((start,f[i],n));start=f[i];n=orders[i]
    boundaries.append((start,f[-1],n));pct=r['pct_error']
    if 'P_measured' in r:
        measured=r['P_measured'];mask=abs(measured)>=abs(measured).max(axis=1,keepdims=True)*10**(-90/20)
        pct=np.linalg.norm(np.where(mask,r['residual_vector'],0),axis=1)/np.maximum(np.linalg.norm(np.where(mask,measured,0),axis=1),1e-20)*100
    view.update_view(f,pct,20*np.log10(np.maximum(pct/100,1e-12)),boundaries,[a for a,b,n in boundaries],[str(n) for a,b,n in boundaries],min(orders),max(orders),p.error_units.currentIndex()==0)

    return view


RENDERERS = {
    (1, None): draw_fdw,
    (2, 'Validation'): draw_origin_validation,
    (2, '3D coordinate cloud'): draw_origin_cloud,
    (2, None): draw_origin_grid,
    (3, None): draw_order_selection,
    (4, 'Spatial error'): draw_spatial_error,
    (4, 'Sound Power vs Harmonic Degree'): draw_sound_power,
    (4, 'Condition number'): draw_condition_number,
    (4, None): draw_fit_error,
}


def renderer_for(stage, kind):
    return RENDERERS.get((stage, kind), RENDERERS[(stage, None)])
