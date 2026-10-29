"""Selectable Export panes; geometry remains outside these hosts."""
from copy import deepcopy
from PySide6 import QtCore as C, QtWidgets as W
from hals_studio.ui.cli_log import CliLog
from hals_studio.ui.plotting.plot_settings import GROUPS
from hals_studio.ui.plotting.export_directivity import DIRECTIVITY_TITLES


class ExportPane(W.QWidget):
    def __init__(self, workspace, index, native, native_name):
        super().__init__()
        self.workspace = workspace
        self.index = index
        self.native = native
        self.native_name = native_name
        self.native_kind = ('response', 'csd', 'impulse')[index]
        self.native_widgets = {self.native_kind: native}
        self.cta_kind = 'cea' if index == 0 else 'reflections'
        self.cta_show_info = index == 2
        self.cta_options = {}
        self.cta_panel = None
        self.directivity_panel = None
        self.directivity_kind = 'map_h'
        self.mode = 'native'
        self.empty = W.QLabel('Open coefficients to preview exported data'); self.empty.setAlignment(C.Qt.AlignCenter)
        self.cta_info = W.QLabel(
            'The 70 points in the 3D viewer are sampling positions used to calculate '
            'the CTA-2034 metrics.\n\n'
            'To inspect individual responses, select Arc Sweep mode.')
        self.cta_info.setWordWrap(True); self.cta_info.setMargin(24)
        self.cli = CliLog()
        self.cli.setDocument(workspace.log.document())
        layout = W.QVBoxLayout(self); layout.setContentsMargins(0, 0, 0, 0)
        self.selector = W.QPushButton(native_name + '  \u25be')
        self.selector.setStyleSheet('text-align:left; padding:8px;')
        self.selector.clicked.connect(self.choose)
        layout.addWidget(self.selector)
        self.stack = W.QStackedWidget(); layout.addWidget(self.stack, 1)
        for widget in (native, self.cli, self.empty, self.cta_info): self.stack.addWidget(widget)
        self.setContextMenuPolicy(C.Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(lambda _: self.choose())

    def choose(self, anchor=None):
        anchor = anchor if isinstance(anchor, W.QWidget) else self.selector
        menu = W.QMenu(self)
        self.add_export_choices(menu)
        menu.exec(anchor.mapToGlobal(anchor.rect().bottomLeft()))

    def add_export_choices(self, menu):
        if self.workspace.config['mode'] != 'CTA-2034':
            directivity = menu.addMenu('Directivity')
            for kind, title in DIRECTIVITY_TITLES.items():
                directivity.addAction(title, lambda checked=False, k=kind: self.select_directivity(k))
        if self.workspace.config['mode'] == 'CTA-2034':
            for kind, title in GROUPS['CEA2034'].items():
                menu.addAction(title, lambda checked=False, k=kind: self.select_cta(k))
            menu.addAction('About CTA-2034 sampling', self.select_cta_info)
            menu.addAction('CLI output', lambda: self.select('cli'))
            return
        for kind, title in [('response', 'SPL / phase'), ('csd', 'CSD / wavelet'), ('impulse', 'Impulse response')]:
            menu.addAction(title, lambda checked=False, k=kind: self.select_native(k))
        menu.addAction('CLI output', lambda: self.select('cli'))

    def select_directivity(self, kind):
        self.directivity_kind = kind
        self.select('directivity')

    def select_cta_info(self):
        self.cta_show_info = True
        self.select('native')

    def select_cta(self, kind):
        self.cta_show_info = False
        self.cta_kind = kind
        self.select('native')

    def select_native(self, kind):
        if kind not in self.native_widgets:
            from hals_studio.ui.plotting.export_charts import ResponsePanel, ImpulsePanel
            from hals_studio.ui.plotting.csd_plot import CSDPanel
            widget = ResponsePanel(self.workspace) if kind == 'response' else ImpulsePanel() if kind == 'impulse' else CSDPanel()
            self.native_widgets[kind] = widget; self.stack.addWidget(widget)
            if kind == 'response':
                gear = W.QPushButton('Plot settings'); gear.clicked.connect(widget.settings); widget.toolbar.addWidget(gear)
        self.native_kind = kind; self.native = self.native_widgets[kind]
        self.native_name = {'response': 'SPL / phase', 'csd': 'CSD / wavelet', 'impulse': 'Impulse response'}[kind]
        self.select('native')
        if not self.workspace.loading: self.workspace.draw_response()

    def select(self, mode):
        self.mode = mode if mode in ('native', 'cli', 'directivity') else 'native'
        self.refresh()
        self.workspace.sync_plot_setup()
        if not self.workspace.loading:
            from hals_studio.application.export_engine import needs_aggregate_preview
            result = self.workspace.result
            if needs_aggregate_preview(self.workspace.config) and result and 'preview_point' in result:
                self.workspace.changed(update_geometry=False)

    def refresh(self):
        self.selector.setVisible(True)
        if self.mode == 'directivity' and self.workspace.config['mode'] != 'CTA-2034':
            self.selector.setText(DIRECTIVITY_TITLES[self.directivity_kind] + '  \u25be')
            result = self.workspace.result
            if self.workspace.dirty or not result or 'preview_point' in result:
                self.empty.setText('Full export point preview pending' if self.workspace.config.get('coeff_path') else 'Open coefficients to preview directivity')
                self.stack.setCurrentWidget(self.empty)
                return
            if self.directivity_panel is None:
                from hals_studio.ui.plotting.export_directivity import ExportDirectivityPanel
                self.directivity_panel = ExportDirectivityPanel(); self.stack.addWidget(self.directivity_panel)
            self.directivity_panel.update_result(result, self.directivity_kind)
            self.stack.setCurrentWidget(self.directivity_panel)
            return
        if self.workspace.config['mode'] == 'CTA-2034' and self.mode != 'cli':
            if self.cta_show_info:
                self.stack.setCurrentWidget(self.cta_info)
                self.selector.setText('About CTA-2034 sampling  \u25be')
                return
            self.selector.setText(GROUPS['CEA2034'][self.cta_kind] + '  \u25be')
            result = self.workspace.result
            if self.workspace.dirty or not result or 'metrics' not in result or result['config']['mode'] != 'CTA-2034':
                self.empty.setText('CTA-2034 metrics preview pending' if self.workspace.config.get('coeff_path') else 'Open coefficients to preview CTA-2034 metrics')
                self.stack.setCurrentWidget(self.empty)
                return
            if self.cta_panel is None:
                from hals_studio.ui.plotting.export_cta import CTAPanel
                self.cta_panel = CTAPanel(self.cta_options, lambda: self.choose(self.cta_panel.header.title)); self.stack.addWidget(self.cta_panel)
            self.cta_panel.update_metrics(result, self.cta_kind)
            self.stack.setCurrentWidget(self.cta_panel)
            self.selector.hide()
            return
        self.empty.setText('Open coefficients to preview exported data')
        widget = self.cli if self.mode == 'cli' else self.native if self.workspace.config.get('coeff_path') else self.empty
        self.stack.setCurrentWidget(widget)
        self.selector.setText(('CLI output' if self.mode == 'cli' else self.native_name) + '  \u25be')

    def state(self):
        return dict(mode=self.mode, native_kind=self.native_kind, cta_kind=self.cta_kind, cta_options=deepcopy(self.cta_options), cta_show_info=self.cta_show_info, directivity_kind=self.directivity_kind)

    def restore(self, state):
        self.cta_options.clear(); self.cta_options.update(deepcopy(state.get("cta_options", {})))
        if self.cta_panel is not None:
            from hals_studio.ui.plotting.plot_settings import default_config
            for key, value in default_config("cea").items(): self.cta_options.setdefault(key, value)
            self.cta_panel.last_render = None
        self.cta_show_info = bool(state.get('cta_show_info', self.index == 2))
        kind = state.get('directivity_kind', 'map_h')
        self.directivity_kind = kind if kind in DIRECTIVITY_TITLES else 'map_h'
        kind = state.get('cta_kind', 'cea' if self.index == 0 else 'reflections')
        self.cta_kind = kind if kind in GROUPS['CEA2034'] else ('cea' if self.index == 0 else 'reflections')
        default_kind = ('response', 'csd', 'impulse')[self.index]
        # Old projects may contain an Analysis pane. Restore this slot's Export default.
        kind = default_kind if state.get('mode') == 'analysis' else state.get('native_kind', default_kind)
        self.select_native(kind if kind in ('response', 'csd', 'impulse') else default_kind)
        self.mode = state.get('mode', 'native')
        if self.mode not in ('native', 'cli', 'directivity'): self.mode = 'native'
        self.refresh()

    def invalidate(self):
        for widget in self.native_widgets.values():
            if hasattr(widget, 'key'): widget.key = None
        if self.cta_panel is not None: self.cta_panel.last_render = None
        if self.directivity_panel is not None: self.directivity_panel.result = None

    def shutdown(self):
        for widget in self.native_widgets.values():
            if widget is not self.workspace.csd_panel and hasattr(widget, 'view'): widget.view.shutdown()
