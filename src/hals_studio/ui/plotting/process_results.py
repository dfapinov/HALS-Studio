"""Embed the shared processing plots in Qt."""
import numpy as np
import matplotlib.pyplot as pyplot
import matplotlib.ticker as ticker
from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
from PySide6 import QtWidgets as W,QtCore as C
import hals_studio.bootstrap as bootstrap


from hals_studio.process_engine import plot_views

VIEWS = {name: getattr(plot_views, name) for name in (
    'FDWView', 'ValidationView', 'SHEResultsView', 'FrequencyBrowser3DView',
    'CloudBrowser3DView', 'SpatialErrorView')}


def theme(fig):
    from hals_studio.ui.viewer_theme import NAME
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
        if not dark:
            for axis in (ax.xaxis,ax.yaxis):
                axis.set_tick_params(which='major',grid_color='#bdcde2',grid_alpha=.5)
                axis.set_tick_params(which='minor',grid_color='#dbe2ed',grid_alpha=.3)
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
        self.origin_selection=None
        if getattr(self,'interaction',None) is not None:
            self.interaction.deleteLater();self.interaction=None
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
    def enable_plot_controls(self, axes, kind, saved=None):
        from .plot_interaction import PlotInteraction
        self.chart = self
        self.config = {'kind': kind}
        self.interaction = PlotInteraction(self)
        self.interaction.begin(kind)
        self.interaction.finish(axes)
        if saved:
            # Capture all reset bounds before restoring a shared frequency axis.
            self.interaction.saved=saved
            for i,ax in enumerate(axes):
                if i in saved:
                    ax.set_xlim(saved[i][0]);ax.set_ylim(saved[i][1])
        self.canvas.setToolTip('')

    def draw(self, workspace):
        from hals_studio.ui.plotting.process_renderers import renderer_for
        kind = workspace.view.currentText()
        view = renderer_for(workspace.stage, kind)(self, workspace)
        if view is None:
            return
        if workspace.stage == 4 and kind == 'Fit error':
            for patch in list(view.ax_err.patches):
                patch.remove()
        signature=(workspace.owner.project_path, tuple(sorted(workspace.results[2][0]))) if workspace.stage==2 and kind=='Validation' else None
        saved={}
        selected=None
        if signature is not None and signature==getattr(self,'_origin_view_signature',None) and getattr(self,'interaction',None) is not None:
            saved={i:(ax.get_xlim(),ax.get_ylim()) for i,ax in enumerate(self.interaction.axes)}
            selected=getattr(getattr(self,'origin_selection',None),'selected_frequency',None)
        self._origin_view_signature=signature
        self.show_figure(view.fig)
        if workspace.stage == 2 and kind == 'Validation':
            from .origin_editing import OriginLineEditor, OriginPointSelection
            self.enable_plot_controls([view.ax_x, view.ax_y, view.ax_z], 'origin_validation', saved)
            self.config['blit_pan']=True
            self.config['idle_cursor']=C.Qt.CrossCursor if workspace.draw_origin_line.isChecked() else C.Qt.ArrowCursor
            self.origin_editor = OriginLineEditor(self.canvas, [view.ax_x, view.ax_y, view.ax_z], workspace)
            self.origin_point_details=view.fig.text(.008,.992,'Click a point for details.',
                ha='left',va='top',fontsize=8,zorder=20,
                color=view.ax_x.yaxis.label.get_color())
            self.origin_selection = OriginPointSelection(self.canvas, [view.ax_x, view.ax_y, view.ax_z], workspace.results[2][0],
                lambda text:self.origin_point_details.set_text(text.replace('% | ','%\n',1)))
            if selected is not None:self.origin_selection.select(selected)
            self.canvas.setFocusPolicy(C.Qt.StrongFocus)
            self.canvas.setCursor(C.Qt.CrossCursor if workspace.draw_origin_line.isChecked() else C.Qt.ArrowCursor)
            self.canvas.setToolTip('')
        if workspace.stage == 1:
            self.enable_plot_controls([view.ax1], 'fdw')
        if workspace.stage == 1 or (workspace.stage == 2 and kind == 'Validation'):
            from .plot_tips import PlotTips
            self.plot_tips=PlotTips(self, workspace)
