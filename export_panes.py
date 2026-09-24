"""Selectable Export panes; geometry remains outside these hosts."""
from copy import deepcopy
from PySide6 import QtCore as C, QtWidgets as W
from panes import PlotPane, GROUPS, TITLES, default_config


class ExportPane(W.QWidget):
    def __init__(self, workspace, index, native, native_name):
        super().__init__()
        self.workspace = workspace
        self.index = index
        self.native = native
        self.native_name = native_name
        self.native_kind = ('response', 'csd', 'impulse')[index]
        self.native_widgets = {self.native_kind: native}
        self.mode = 'native'
        self.analysis = PlotPane(workspace.owner, index+1, 'probe')
        self.analysis.extra_menu = self.add_export_choices
        self.empty = W.QLabel('Open coefficients to preview exported data'); self.empty.setAlignment(C.Qt.AlignCenter)
        self.cli = W.QPlainTextEdit(); self.cli.setReadOnly(True)
        self.cli.setDocument(workspace.log.document())
        layout = W.QVBoxLayout(self); layout.setContentsMargins(0, 0, 0, 0)
        self.selector = W.QPushButton(native_name + '  \u25be')
        self.selector.setStyleSheet('text-align:left; padding:8px;')
        self.selector.clicked.connect(self.choose)
        layout.addWidget(self.selector)
        self.stack = W.QStackedWidget(); layout.addWidget(self.stack, 1)
        for widget in (native, self.analysis, self.cli, self.empty): self.stack.addWidget(widget)
        self.setContextMenuPolicy(C.Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(lambda _: self.choose())

    def choose(self):
        menu = W.QMenu(self)
        self.add_export_choices(menu)
        menu.addSeparator()
        for group, entries in GROUPS.items():
            sub = menu.addMenu(group)
            for kind, title in entries.items():
                sub.addAction(title, lambda checked=False, k=kind: self.select('analysis', k))
        menu.exec(self.selector.mapToGlobal(self.selector.rect().bottomLeft()))

    def add_export_choices(self, menu):
        for kind, title in [('response', 'Export SPL / phase'), ('csd', 'Export CSD / wavelet'), ('impulse', 'Export impulse response')]:
            menu.addAction(title, lambda checked=False, k=kind: self.select_native(k))
        menu.addAction('CLI output', lambda: self.select('cli'))

    def select_native(self, kind):
        if kind not in self.native_widgets:
            from export_charts import ResponsePanel, ImpulsePanel
            from csd_plot import CSDPanel
            widget = ResponsePanel(self.workspace) if kind == 'response' else ImpulsePanel() if kind == 'impulse' else CSDPanel()
            self.native_widgets[kind] = widget; self.stack.addWidget(widget)
            if kind == 'response':
                gear = W.QPushButton('Plot settings'); gear.clicked.connect(widget.settings); widget.toolbar.addWidget(gear)
        self.native_kind = kind; self.native = self.native_widgets[kind]
        self.native_name = {'response': 'Export SPL / phase', 'csd': 'Export CSD / wavelet', 'impulse': 'Export impulse response'}[kind]
        self.select('native')
        if not self.workspace.loading: self.workspace.draw_response()

    def select(self, mode, kind=None):
        self.mode = mode
        if kind is not None: self.analysis.set_kind(kind)
        self.stack.setCurrentWidget({'native': self.native, 'analysis': self.analysis, 'cli': self.cli}[mode])
        self.refresh()
        self.workspace.sync_plot_setup()

    def refresh(self):
        self.selector.setVisible(self.mode != 'analysis')
        if self.mode == 'native':
            self.stack.setCurrentWidget(self.native if self.workspace.config.get('coeff_path') else self.empty)
        if self.mode == 'analysis':
            self.analysis.render()
            self.selector.setText(TITLES.get(self.analysis.config['kind'], 'Analysis plot') + '  \u25be')
        else:
            self.selector.setText(('CLI output' if self.mode == 'cli' else self.native_name) + '  \u25be')

    def state(self):
        return dict(mode=self.mode, native_kind=self.native_kind, plot=deepcopy(self.analysis.config))

    def restore(self, state):
        native_kind = state.get('native_kind', ('response', 'csd', 'impulse')[self.index])
        if native_kind in ('response', 'csd', 'impulse'): self.select_native(native_kind)
        config = state.get('plot', {})
        kind = config.get('kind', 'probe')
        if kind in TITLES:
            self.analysis.config = dict(default_config(kind), **deepcopy(config))
            self.analysis.invalidate()
        self.mode = state.get('mode', 'native')
        if self.mode not in ('native', 'analysis', 'cli'): self.mode = 'native'
        self.stack.setCurrentWidget({'native': self.native, 'analysis': self.analysis, 'cli': self.cli}[self.mode])
        self.refresh()

    def shutdown(self):
        for widget in self.native_widgets.values():
            if widget is not self.workspace.csd_panel and hasattr(widget, 'view'): widget.view.shutdown()
        if self.analysis.plotter: self.analysis.plotter.close()
        if hasattr(self.analysis, 'csd_view'): self.analysis.csd_view.shutdown()
