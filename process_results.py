"""Embed the original HALS plotting views in Qt, without their Tk windows.

The pure view classes are compiled directly from the local, unchanged snapshot.
Only figure creation and colours are adapted; plot layout and data stay intact.
"""
import ast
import functools
import warnings
import numpy as np
import matplotlib.pyplot as pyplot
import matplotlib.ticker as ticker
from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
from PySide6 import QtWidgets as W,QtCore as C
import bootstrap


class FigureFactory:
    def figure(self, *args, **kwargs): return Figure(*args, **kwargs)
    def subplots(self, *args, **kwargs):
        size=kwargs.pop('figsize',None);fig=Figure(figsize=size)
        return fig,fig.subplots(*args,**kwargs)
    def __getattr__(self,name):return getattr(pyplot,name)


def original_views():
    path=bootstrap.HERE/'process_engine/viewers.py'
    tree=ast.parse(path.read_text(encoding='utf-8'))
    names={'silence_log_warnings','FDWView','ValidationView','SHEResultsView','FrequencyBrowser3DView','CloudBrowser3DView'}
    tree.body=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.ClassDef)) and n.name in names]
    spatial=ast.parse((bootstrap.HERE/'process_engine/spatial_error_viewer.py').read_text(encoding='utf-8'))
    tree.body.extend(n for n in spatial.body if isinstance(n,ast.ClassDef) and n.name=='SpatialErrorView')
    namespace=dict(np=np,plt=FigureFactory(),ticker=ticker,functools=functools,warnings=warnings,Poly3DCollection=Poly3DCollection)
    exec(compile(tree,str(path),'exec'),namespace)
    return namespace

VIEWS=original_views()


def theme(fig):
    from viewer_theme import NAME
    from matplotlib.colors import to_hex
    from matplotlib.text import Text
    from matplotlib.lines import Line2D
    dark=NAME=='Dark';bg='#101c28' if dark else '#ffffff';fg='#c2d1df' if dark else '#263e56'
    fig.set_facecolor(bg)
    for ax in fig.axes:
        if ax.get_legend() is not None: ax.get_legend().set_draggable(True)
        ax.set_facecolor(bg);ax.tick_params(colors=fg)
        for spine in ax.spines.values():spine.set_edgecolor('#405364' if dark else '#bdcde2')
        for line in ax.get_xgridlines()+ax.get_ygridlines():line.set_color('#405364' if dark else '#dbe2ed')
        if hasattr(ax,'zaxis'):ax.tick_params(axis='z',colors=fg)
    for item in fig.findobj():
        if isinstance(item,(Text,Line2D)):
            try:
                c=to_hex(item.get_color()).lower()
                mapping={'#000000':fg,'#333333':fg,'#0000ff':'#599bda' if dark else '#245fad','#ff0000':'#ff7777' if dark else '#c32626','#008000':'#79c995' if dark else '#008000','#006064':'#9acfe6' if dark else '#006064'}
                if isinstance(item,Text):mapping.update({'#c2d1df':fg,'#b8d6e8':fg,'#8ca4b8':fg})
                if c in mapping:item.set_color(mapping[c])
            except (ValueError,TypeError):pass
        if isinstance(item,Text):
            if item.get_text() and item.get_color() in ('black','k'):item.set_color(fg)
            if item.get_bbox_patch() is not None:item.get_bbox_patch().set_facecolor(bg)
    for ax in fig.axes:
        if hasattr(ax,'zaxis'):
            for axis in (ax.xaxis,ax.yaxis,ax.zaxis):axis.set_pane_color((.063,.11,.157,1) if dark else (1,1,1,1))


class Results(W.QWidget):
    def __init__(self):
        super().__init__();self.box=W.QVBoxLayout(self);self.box.setContentsMargins(0,0,0,0);self.canvas=None;self.fig=None;self.scroll=None
    def show_figure(self,fig):
        while self.box.count():
            widget=self.box.takeAt(0).widget();widget.setParent(None);widget.deleteLater()
        self.fig=fig;theme(fig);self.canvas=FigureCanvasQTAgg(fig);self.canvas.setMinimumHeight(720 if len(fig.axes)>=3 else 400)
        self.scroll=W.QScrollArea();self.scroll.setWidgetResizable(True);self.scroll.setFrameShape(W.QFrame.NoFrame);self.scroll.setWidget(self.canvas);self.box.addWidget(self.scroll,1)
        from matplotlib.colors import to_hex
        self.scroll.viewport().setObjectName('process_plot_background')
        self.scroll.viewport().setStyleSheet(f'QWidget#process_plot_background {{background:{to_hex(fig.get_facecolor())};}}')
        self.canvas.draw_idle()
        def zoom(event):
            ax=event.inaxes
            if ax is None or not hasattr(ax,'zaxis'):return
            factor=.85 if event.button=='up' else 1/.85
            for get,setter in ((ax.get_xlim3d,ax.set_xlim3d),(ax.get_ylim3d,ax.set_ylim3d),(ax.get_zlim3d,ax.set_zlim3d)):
                lo,hi=get();mid=(lo+hi)/2;setter(mid+(lo-mid)*factor,mid+(hi-mid)*factor)
            self.canvas.draw_idle()
        self.canvas.mpl_connect('scroll_event',zoom)
    def draw(self,p):
        r=p.results[p.stage];kind=p.view.currentText()
        if p.stage==1:
            from process_engine.stage1_fdwsmooth import load_and_prep_ir
            from pathlib import Path
            f,raw,smooth,meta=r[:4];name=p.sample.currentData() or next(iter(raw));n_fft=2*(len(f)-1);fs=float(r[4]) if len(r)>4 else 2*float(f[-1]);data=None
            try:
                data,fs_wav=load_and_prep_ir(str(Path(p.ir_folder.text())/name),crop_samples=n_fft)
                data=np.pad(data,(0,max(0,n_fft-len(data))));fs=fs_wav
            except (OSError,RuntimeError,ValueError):
                # The NPZ is sufficient for the frequency response and smoothing curves.
                # A WAV is only needed for the optional time-domain IR panel.
                pass
            show_both=p.values[1]['keep_raw_and_smoothed'];primary=smooth[name] if smooth and p.values[1]['enable_smoothing'] and not show_both else raw[name]
            view=VIEWS['FDWView'](figsize=(12,8));view.update_view(name,p.sample.currentIndex(),f,primary,smooth.get(name) if smooth and show_both else None,meta[name],data,fs,float(p.values[1]['fdw_rft_ms']))
            if data is None:
                for label in view.ax2.texts:
                    if label.get_text()=='Error loading wav':
                        label.set_text('WAV unavailable\nShowing saved NPZ results')
            from process_engine.utils import _ph_pat
            match=_ph_pat.match(name)
            if match:
                decode=lambda key:float(match.group(key).replace('p','.'))
                view.ax1.set_title(f"Radius {decode('rmm'):g} mm | Phi {decode('ph'):g} deg | Height {decode('zmm'):g} mm\nFDW Magnitude")
            view.fig.subplots_adjust(right=.79,top=.91,hspace=.5)
            from viewer_theme import NAME
            if NAME=='Dark':
                from matplotlib.colors import LinearSegmentedColormap
                from viewer_theme import colour
                probe=colour('#47d7ec')
                ramp=LinearSegmentedColormap.from_list('fdw',['#b49bf5','#7ebeff','#68d9ca'])
                transition=float(meta[name]['f_trans'])
                centers=np.asarray(meta[name]['f_centers']);valid=centers[(centers>=view.ax1.get_xlim()[0]) & (centers<=transition)]
                low=max(float(valid.min()) if len(valid) else 10.,1.)
                def window_color(freq):return ramp(np.clip(np.log(max(freq,low)/low)/max(np.log(transition/low),1e-9),0,1))
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
            curves = [line for line in view.ax1.lines if len(line.get_xdata()) > 2]
            if smooth and p.values[1]['enable_smoothing']:
                smoothing_label = 'FDW + Smoothing' if meta[name].get('sliding_hf') else 'FDW + fixed smoothing'
                if show_both and len(curves)>1: curves[1].set_label(smoothing_label)
                elif curves: curves[0].set_label(smoothing_label)
                view.ax1.legend(loc='best', fontsize=8)
            fixed = meta[name].get('fixed_smoothing')
            if fixed is not None:
                view.ax1.plot(f, 20*np.log10(np.maximum(abs(fixed),1e-20)), color='#ffb56f', linewidth=1, linestyle='--', label='Fixed smoothing comparison')
                view.ax1.legend(loc='best', fontsize=8)
        elif p.stage==2 and kind=='Validation':
            rows=r[0];freqs=sorted(rows);current=np.array([rows[f]['final_c'] for f in freqs]).T;original=np.array([rows[f].get('original_c',rows[f]['final_c']) for f in freqs]).T
            errors=[rows[f]['error'] for f in freqs];old=[rows[f].get('original_error',rows[f]['error']) for f in freqs]
            view=VIEWS['ValidationView']();view.update_view(freqs,current,original,errors,old)
            from viewer_theme import NAME
            if NAME=='Dark':
                from matplotlib.colors import to_hex
                from plots import COLORS
                from viewer_theme import colour
                for ax,color in zip(view.fig.axes,map(colour,COLORS)):
                    legend=ax.get_legend()
                    for item in [*ax.lines,*ax.texts,*(legend.legend_handles if legend else [])]:
                        if to_hex(item.get_color())=='#0000ff':item.set_color(color);item.set_alpha(1)
        elif p.stage==2 and kind=='3D coordinate cloud':
            rows=r[0];freqs=sorted(rows);xyz=np.array([rows[f]['final_c'] for f in freqs]);view=VIEWS['CloudBrowser3DView'](r[5]);view.update_view(freqs,*xyz.T,max(0,p.sample.currentIndex()))
            active=max(0,p.sample.currentIndex());point=xyz[active];view.ax.set_title('')
            view.fig.text(.035,.96,f'{freqs[active]:g} Hz\nX {point[0]:.1f} mm\nY {point[1]:.1f} mm\nZ {point[2]:.1f} mm',va='top',fontsize=11)
            from viewer_theme import colour
            view.scatter_all.set_color(colour('#47d7ec'));view.scatter_all.set_alpha(.9);view.scatter_hi.set_color('#ffba68');view.ax.legend(loc='upper right')
        elif p.stage==2:
            rows=r[0];f=p.sample.currentData() or next(iter(rows));row=rows[f];view=VIEWS['FrequencyBrowser3DView'](r[5]);plane={'XY':'XY (Z Height)','XZ':'XZ (Y Width)','YZ':'YZ (X Depth)'}[p.plane.currentText()]
            view.update_view(f,row.get('grid'),row['X_vals'],row['Y_vals'],row['Z_vals'],row['final_c'],plane,p.slice_value())
        elif p.stage==3:
            import sys
            engine_path = str(bootstrap.HERE / 'process_engine')
            if engine_path not in sys.path: sys.path.insert(0, engine_path)
            from process_engine.stage3_optimize_she_settings import plot_internal_tail_power,highlight_stage3_choices,format_stage3_ratio_axis,format_stage3_order_axis
            from process_engine.stage3_spl_change import plot_spl_changes
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
            from viewer_theme import NAME
            bg='#101c28' if NAME=='Dark' else '#ffffff'
            panel.setStyleSheet(f'QWidget {{background:{bg};font-size:14px;border:none;}} QRadioButton::indicator {{width:16px;height:16px;border:1px solid #599bda;border-radius:8px;background:{bg};}} QRadioButton::indicator:checked {{background:#599bda;border:3px solid #a9d2f7;}} QPushButton {{background:#285b85;border:1px solid #599bda;padding:7px;border-radius:4px;color:white;}}')
            radio_off=(bootstrap.HERE/'assets/radio-off.svg').as_posix();radio_on=(bootstrap.HERE/'assets/radio-on.svg').as_posix()
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
            info=W.QLabel('Choose the recommendation you want to use, then optimise growth rate:')
            info.setWordWrap(True);attention_layout.addWidget(info)
            action=W.QPushButton();action.setObjectName('stage3_growth_action');action.setFixedSize(184,38)
            action.clicked.connect(p.order_action);attention_layout.addWidget(action,alignment=C.Qt.AlignLeft)
            p.refresh_order_action()
            preflight=r.get('condition_preflight')
            attention_ready=(not preflight or r.get('selected_order_N') is None)
            if attention_ready and getattr(p,'_stage3_pulse_pending',False) and not getattr(p,'_autosaving_plots',False):
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
        elif kind=='Spatial error':
            f=r['freqs'];i=int(np.argmin(abs(f-p.frequency.value())));xyz=p.spherical_xyz(r['coords_sph']);view=VIEWS['SpatialErrorView']();view.update_view(*xyz.T,f[i],r['N_used'][i],r['P_measured'][i],r['P_measured'][i]-r['residual_vector'][i],p.threshold.value())
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
                view.update_view(*xyz.T,f[index],r['N_used'][index],r['P_measured'][index],r['P_measured'][index]-r['residual_vector'][index],floor_slider.val)
                view.ax.view_init(*angles);frequency_text.set_text(f'Frequency\n{f[index]:,.1f} Hz');floor_text.set_text(f'Floor\n{floor_slider.val:g} dB');theme(view.fig);self.canvas.draw_idle()
            for slider in self.spatial_sliders:slider.poly.set_facecolor('#599bda');slider.on_changed(update)
            theme(view.fig);self.canvas.draw_idle();return
        elif kind=='Condition number':
            view=VIEWS['SHEResultsView']();f=r['freqs'];orders=r['N_used'];ticks=[0];labels=[str(orders[0])]
            ticks.extend(i for i in range(1,len(orders)) if orders[i]!=orders[i-1])
            labels.extend(str(orders[i]) for i in ticks[1:])
            view.update_cond_view(f,r['cond'],f[ticks],labels);self.show_figure(view.fig_cond);return
        else:
            view=VIEWS['SHEResultsView']();f=r['freqs'];orders=r['N_used'];boundaries=[];start=f[0];n=orders[0]
            for i in range(1,len(f)):
                if orders[i]!=n:boundaries.append((start,f[i],n));start=f[i];n=orders[i]
            boundaries.append((start,f[-1],n));pct=r['pct_error']
            if 'P_measured' in r:
                measured=r['P_measured'];mask=abs(measured)>=abs(measured).max(axis=1,keepdims=True)*10**(-90/20)
                pct=np.linalg.norm(np.where(mask,r['residual_vector'],0),axis=1)/np.maximum(np.linalg.norm(np.where(mask,measured,0),axis=1),1e-20)*100
            view.update_view(f,pct,20*np.log10(np.maximum(pct/100,1e-12)),boundaries,[a for a,b,n in boundaries],[str(n) for a,b,n in boundaries],min(orders),max(orders),p.error_units.currentIndex()==0)
        if p.stage==4 and kind=='Fit error':
            for patch in list(view.ax_err.patches): patch.remove()
        self.show_figure(view.fig)
