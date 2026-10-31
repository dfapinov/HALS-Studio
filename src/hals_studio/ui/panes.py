"""Independent plot panes, contextual setup, and pinnable settings."""
import numpy as np
import pyvista as pv
from pyvistaqt import QtInteractor
from PySide6 import QtCore as C, QtGui as G, QtWidgets as W
from hals_studio.analysis.analysis_metrics import contour_levels
from hals_studio.process_engine.stage5_pressure_utils import get_min_phase_delay
from hals_studio.ui.plotting.plot_interaction import PlotInteraction
from hals_studio.ui.plotting.plots import Chart

from hals_studio.ui.plotting.plot_settings import (
    GROUPS, TITLES, MAGNITUDE_KINDS, default_config,
    selected_magnitudes,
)
from hals_studio.ui.pane_setup import Setup


class PlotMenu(W.QMenu):
    """Keep checkboxes open so several responses can be selected in one visit."""
    def addMenu(self, title):
        child = PlotMenu(title, self); super().addMenu(child); return child

    def mouseReleaseEvent(self, event):
        action = self.actionAt(event.pos())
        if event.button() == C.Qt.LeftButton and action and action.isEnabled() and action.isCheckable():
            action.trigger(); event.accept(); return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        action = self.activeAction()
        if event.key() == C.Qt.Key_Space and action and action.isEnabled() and action.isCheckable():
            action.trigger(); event.accept(); return
        super().keyPressEvent(event)


class PlotPane(W.QFrame):
    def __init__(self, owner, index, kind):
        super().__init__()
        self.owner, self.index = owner, index
        self.config = default_config(kind)
        self.plotter = self.handle = None
        self.last_render = None
        self.setMinimumSize(230, 180)
        layout = W.QVBoxLayout(self); layout.setContentsMargins(5, 5, 5, 5); layout.setSpacing(4)
        from hals_studio.ui.plot_header import PlotHeader
        self.header = PlotHeader(
            lambda: self.menu(self.title.mapToGlobal(self.title.rect().bottomLeft())),
            self.reset_zoom, self.setup)
        self.title, self.cursor_label, self.gear = self.header.title, self.header.readout, self.header.gear
        layout.addWidget(self.header)
        self.stack = W.QStackedWidget(); layout.addWidget(self.stack)
        self.chart = Chart(); self.chart_frame = W.QWidget(); chart_row = W.QHBoxLayout(self.chart_frame)
        chart_row.setContentsMargins(0, 0, 0, 0); chart_row.setSpacing(0); chart_row.addWidget(self.chart, 1)
        self.stack.addWidget(self.chart_frame)
        self.probe_controls = W.QWidget(); self.probe_controls.setObjectName('probeOverlay'); self.probe_controls.setStyleSheet('QWidget#probeOverlay, QWidget#probeOverlay QLabel { background:transparent; }'); probe_row = W.QHBoxLayout(self.probe_controls)
        probe_row.setContentsMargins(6, 3, 6, 3); probe_row.setSpacing(6)
        self.probe_frequency = W.QLabel(); self.probe_frequency.setObjectName('hero'); self.probe_frequency.setStyleSheet('font-size:24px;font-weight:600;background:transparent;')
        self.frequency_controls=W.QWidget(); self.frequency_controls.setObjectName('frequencyOverlay')
        self.frequency_controls.setStyleSheet('QWidget#frequencyOverlay, QWidget#frequencyOverlay QLabel { background:transparent; }')
        frequency_row=W.QHBoxLayout(self.frequency_controls); frequency_row.setContentsMargins(6,3,6,3); frequency_row.setSpacing(6)
        frequency_row.addWidget(self.probe_frequency)
        previous=W.QPushButton('\u2039'); previous.setFixedWidth(54); previous.clicked.connect(lambda:owner.frequency.setValue(max(0,owner.frequency.value()-1))); frequency_row.addWidget(previous)
        self.sweep_button=W.QPushButton('\u25b8 Sweep'); self.sweep_button.setCheckable(True); self.sweep_button.setFixedWidth(70)
        self.sweep_button.clicked.connect(lambda:owner.play.click()); owner.play.toggled.connect(self.sweep_button.setChecked); owner.play.toggled.connect(lambda active:self.sweep_button.setText('\u2161 Pause' if active else '\u25b8 Sweep')); frequency_row.addWidget(self.sweep_button)
        next_button=W.QPushButton('\u203a'); next_button.setFixedWidth(54); next_button.clicked.connect(owner.advance); frequency_row.addWidget(next_button)
        self.frequency_controls.hide()

        self.probe_editors = []
        for name, source in [('Probe azimuth', owner.azimuth), ('Elevation', owner.elevation)]:
            probe_row.addWidget(W.QLabel(name))
            control = W.QDoubleSpinBox(); control.setRange(source.minimum(), source.maximum())
            control.setFixedWidth(90); control.setDecimals(1); control.setSuffix('°'); control.setValue(source.value())
            control.valueChanged.connect(source.setValue)
            def sync(value, target=control):
                target.blockSignals(True); target.setValue(value); target.blockSignals(False)
            source.valueChanged.connect(sync)
            probe_row.addWidget(control); self.probe_editors.append(control)
        self.probe_controls.hide()
        from hals_studio.ui.plotting.spl_cursor import SPLCursor
        self.cursor = SPLCursor(self, self.cursor_label)
        self.interaction = PlotInteraction(self)
        self.chart.canvas.mpl_connect('button_press_event', self.chart_click)
        self.note = W.QLabel(); self.note.setWordWrap(True); self.note.setStyleSheet('font-size:10px;color:#849eb1;padding:3px;')
        layout.addWidget(self.note)
        for widget in (self, self.chart.canvas, self.title):
            widget.setContextMenuPolicy(C.Qt.CustomContextMenu)
            widget.customContextMenuRequested.connect(lambda p, w=widget: self.menu(w.mapToGlobal(p)))

    def chart_click(self, event):
        self.owner.active_plot = self
        if any(ax.get_legend() is not None and ax.get_legend().contains(event)[0] for ax in self.chart.fig.axes): return
        if self.interaction.on_handle(event): return
        if event.button == 1 and event.xdata and event.inaxes and self.config['kind'] not in ('polar', 'globe_hv', 'globe_h', 'globe_v'):
            self.owner.jump_frequency(event.xdata)

    def menu(self, position):
        self.owner.active_plot = self
        menu = PlotMenu(self)
        self._magnitude_actions = {}
        exclusive = G.QActionGroup(menu); exclusive.setExclusive(True)
        for category, items in GROUPS.items():
            sub = menu.addMenu('SPL / Phase' if category == 'SPL & phase' else category)
            if category == 'SPL & phase':
                sub.addSection('Magnitude')
                selected = selected_magnitudes(self.config)
                for key, title in items.items():
                    if key in ('phase', 'minimum'): continue
                    action = sub.addAction(title); action.setCheckable(True)
                    self._magnitude_actions.setdefault(key, []).append(action)
                    action.setChecked(key in selected)
                    action.triggered.connect(lambda checked=False, k=key: self.toggle_magnitude(k))
                sub.addAction('Clear magnitudes', self.clear_magnitudes)
                sub.addSection('Phase')
                phases = G.QActionGroup(sub); phases.setExclusive(True)
                for mode in ('None', 'Total phase', 'Minimum phase'):
                    action = sub.addAction(mode if mode != 'None' else 'No phase'); action.setCheckable(True); phases.addAction(action)
                    action.setChecked(self.config['phase_mode'] == mode)
                    action.triggered.connect(lambda checked=False, m=mode: self.select_phase(m))
                sub.addSection('Phase display')
                wraps = G.QActionGroup(sub); wraps.setExclusive(True)
                for title, value in [('Wrapped', True), ('Unwrapped', False)]:
                    action = sub.addAction(title); action.setCheckable(True); wraps.addAction(action)
                    action.setChecked(self.config['wrapped'] == value)
                    action.triggered.connect(lambda checked=False, v=value: self.change('wrapped', v))
                continue
            for key, title in items.items():
                action = sub.addAction(title); action.setCheckable(True)
                if category == 'CEA2034': self._magnitude_actions.setdefault(key, []).append(action)
                action.setChecked(key in selected_magnitudes(self.config) if category == 'CEA2034' else key == self.config['kind'])
                if category == 'CEA2034': action.triggered.connect(lambda checked=False, k=key: self.toggle_magnitude(k))
                else:
                    exclusive.addAction(action)
                    action.triggered.connect(lambda checked=False, k=key: self.set_kind(k))
            if category == 'CEA2034': sub.addSeparator(); sub.addAction('Clear magnitudes', self.clear_magnitudes)
        menu.addSeparator(); menu.addAction('Plot setup / pin settings…', self.setup)
        menu.addAction('Add overlay…', lambda: self.owner.capture_overlay(self))
        menu.addAction('Reset zoom', self.reset_zoom)
        if self.config['kind'] in ('balloon', 'cross_sonograms'):
            camera = menu.addMenu('Camera')
            for name in ('Front', 'Side', 'Top', 'Isometric'):
                camera.addAction(name, lambda n=name: self.camera(n))
        menu.addAction('Export plot image…', self.export)
        if self.config['kind'] == 'balloon':
            menu.addAction('Export displayed mesh…', self.export_mesh)
        elif self.config['kind'] not in ('polar', 'globe_hv', 'globe_h', 'globe_v'):
            menu.addAction('Export plotted data CSV…', self.export_csv)
        menu.exec(position)
        self._magnitude_actions = {}; menu.deleteLater()

    def export_mesh(self):
        path, _ = W.QFileDialog.getSaveFileName(self, 'Export VTK structured grid', '', 'VTK grid (*.vts)')
        if path:
            if not path.lower().endswith('.vts'): path += '.vts'
            self.mesh.save(path)

    def export_csv(self):
        import csv
        path, _ = W.QFileDialog.getSaveFileName(self, 'Export plotted data', '', 'CSV (*.csv)')
        if not path: return
        if not path.lower().endswith('.csv'): path += '.csv'
        with open(path, 'w', newline='', encoding='utf-8') as stream:
            writer = csv.writer(stream)
            if self.config['kind'].startswith(('map_', 'globe_')):
                s = self.owner.sphere; levels = self.owner.get_levels(self.config['smoothing'])
                angles, h, v = s.cuts(s.relative(levels, 'On axis' if self.config.get('directivity_on_axis',False) else 'Peak'))
                data = h if self.config['kind'] in ('map_h', 'globe_h') else v
                writer.writerow(['Frequency Hz', 'Angle degrees', 'Relative level dB'])
                for j, freq in enumerate(s.freqs):
                    writer.writerows((freq, angle, value) for angle, value in zip(angles, data[j]))
            else:
                writer.writerow(['Curve', 'Frequency Hz', 'Value', 'Axis units'])
                for ax in self.chart.fig.axes:
                    for line in ax.lines:
                        name = line.get_label()
                        if name.startswith('_'): continue
                        writer.writerows((name, f, value, ax.get_ylabel()) for f, value in zip(line.get_xdata(), line.get_ydata()))

    def export(self):
        path, _ = W.QFileDialog.getSaveFileName(self, 'Export plot', '', 'PNG image (*.png)')
        if path:
            if not path.lower().endswith('.png'): path += '.png'
            if self.config['kind'] in ('csd','wavelet') or (self.config['kind'].startswith('map_') and self.config.get('directivity_display')in ('3D surface','Waterfall')):
                view=self.csd_view
                if view.stack.currentWidget() is view.chart: view.chart.fig.savefig(path,dpi=180)
                else: view.plotter.screenshot(path)
            elif self.config['kind'] == 'impulse' and hasattr(self, 'ir_panel'): self.ir_panel.chart.fig.savefig(path, dpi=180)
            elif self.config['kind'] in ('balloon', 'cross_sonograms'): self.plotter.screenshot(path)
            else: self.chart.fig.savefig(path, dpi=180)

    def setup(self):
        if self.config['kind'] == 'impulse':
            if hasattr(self, 'ir_panel'): self.ir_panel.settings()
            return
        dialog = Setup(self)
        if dialog.exec() == W.QDialog.Accepted:
            self.config = dialog.values; self.invalidate(); self.owner.rebuild_pins(); self.owner.schedule()

    def set_kind(self, kind):
        if kind in MAGNITUDE_KINDS and self.config['kind'] not in MAGNITUDE_KINDS:
            self.config['smoothing'] = 'None'
        self.config['kind'] = kind
        self.config['magnitude_selection'] = None
        if kind in GROUPS['CEA2034']: self.config['phase_mode'] = 'None'
        if kind in ('phase', 'minimum'): self.config['phase_mode'] = 'Minimum phase' if kind == 'minimum' else 'Total phase'
        self.invalidate(); self.owner.rebuild_pins(); self.owner.schedule()

    def toggle_magnitude(self, kind):
        if self.config['kind'] not in MAGNITUDE_KINDS:
            self.config['smoothing'] = 'None'
        selected = [key for key in selected_magnitudes(self.config)
                    if (key in GROUPS['CEA2034']) == (kind in GROUPS['CEA2034'])]
        if kind in GROUPS['CEA2034']: self.config['phase_mode'] = 'None'
        if kind in selected: selected.remove(kind)
        else:
            selected.append(kind)
            if kind == 'di' or kind.endswith(' DI'): self.config['phase_mode'] = 'None'
        self.config['magnitude_selection'] = selected
        self.config['kind'] = selected[0] if selected else 'probe'
        self.sync_magnitude_actions()
        self.invalidate(); self.owner.rebuild_pins(); self.owner.schedule()

    def clear_magnitudes(self):
        self.config['magnitude_selection'] = []; self.config['kind'] = 'probe'
        self.sync_magnitude_actions()
        self.invalidate(); self.owner.rebuild_pins(); self.owner.schedule()

    def sync_magnitude_actions(self):
        selected = selected_magnitudes(self.config)
        for kind, actions in getattr(self, '_magnitude_actions', {}).items():
            for action in actions: action.setChecked(kind in selected)

    def select_phase(self, mode):
        if mode != 'None' and self.config['kind'] in GROUPS['CEA2034']:
            self.config['kind'] = 'probe'; self.config['magnitude_selection'] = ['probe']
        self.config['phase_mode'] = mode
        if self.config['kind'] in MAGNITUDE_KINDS:
            self.config['magnitude_selection'] = selected_magnitudes(self.config)
        elif self.config['kind'] not in ('phase', 'minimum'):
            self.config['kind'] = 'probe'; self.config['magnitude_selection'] = ['probe']
        if self.config['kind'] in ('phase', 'minimum'):
            self.config['kind'] = 'probe' if mode == 'None' else ('minimum' if mode == 'Minimum phase' else 'phase')
        if mode != 'None':
            selected = [k for k in selected_magnitudes(self.config) if k != 'di' and not k.endswith(' DI')]
            self.config['magnitude_selection'] = selected
            if self.config['kind'] == 'di' or self.config['kind'].endswith(' DI'): self.config['kind'] = selected[0] if selected else 'probe'
            self.sync_magnitude_actions()
        self.config['phase'] = mode != 'None'
        self.invalidate(); self.owner.rebuild_pins(); self.owner.schedule()

    def fit_names(self, config=None):
        from hals_studio.ui.plotting.response_plot import magnitude_curves
        if self.owner.sphere is None: return ['First curve']
        config = self.config if config is None else config
        if config['kind'] in ('balloon', 'volume', 'map_h', 'map_v', 'polar'): return ['First curve']
        curves, _, _ = magnitude_curves(self, self.owner.sphere, self.owner.get_levels(config['smoothing']), config)
        return ['First curve', *curves]

    def estimated_delay_ms(self):
        o = self.owner
        if o.sphere is None: return 0.
        pressure = o.sphere.pressure[:, *o.sphere.index(*o.axis)]
        speed = float(o.sphere.metadata.get('speed_of_sound', 343.))
        return get_min_phase_delay(pressure, o.sphere.freqs, speed)/speed*1000

    def fill_estimated_delay(self, field, values):
        try: delay = self.estimated_delay_ms()
        except ValueError as exc:
            W.QMessageBox.warning(self, 'Delay estimate', str(exc)); return
        values['min_phase_delay'] = False
        field.setValue(delay)
        values['delay'] = field.value()
        if values is self.config:
            self.invalidate(); self.owner.schedule()

    def delay_ms(self):
        self.delay_note = ''
        # Convert legacy automatic estimate + trim into one explicit value.
        if self.config.get('min_phase_delay'):
            try: self.config['delay'] += self.estimated_delay_ms()
            except ValueError as exc:
                self.delay_note = f'Delay estimate unavailable: {exc}'
                return self.config['delay']
            self.config['min_phase_delay'] = False
        return self.config['delay']

    def reset_zoom(self):
        if self.config['kind'] == 'impulse':
            if hasattr(self, 'ir_panel'): self.ir_panel.interaction.reset()
            return
        if self.config['kind'] in ('csd', 'wavelet') or (self.config['kind'].startswith('map_') and self.config.get('directivity_display') in ('3D surface','Waterfall')):
            if hasattr(self, 'csd_view'): self.csd_view.reset()
            return
        if self.config['kind'] in ('balloon', 'cross_sonograms'): self.camera()
        else: self.interaction.reset()

    def invalidate(self):
        self.last_render = None

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.invalidate()
        self.owner.schedule()

    def change(self, key, value):
        if key == 'phase_mode':
            self.select_phase(value); return
        previous = self.config[key]; self.config[key] = value
        manual = 'auto_axes' if key in ('fmin', 'fmax', 'ymin', 'ymax') else 'phase_auto' if key in ('phase_min', 'phase_max') else 'di_auto' if key in ('di_min', 'di_max') else None
        if manual:
            self.config[manual] = False
            self.owner.rebuild_pins()
        if key=='csd_method': self.config['kind']='wavelet' if value=='Morlet wavelet' else 'csd'
        if key.startswith('contour_'):
            try: contour_levels(self.config['contour_low'], self.config['contour_high'], self.config['contour_step'])
            except ValueError as exc:
                self.config[key] = previous; self.owner.statusBar().showMessage(str(exc)); self.owner.rebuild_pins(); return
        self.invalidate(); self.owner.schedule()
        if key in ('breakout', 'extent', 'step', 'symmetric', 'sweep_direction', 'wavelet_units', 'csd_method'): self.owner.rebuild_pins()

    def ensure_3d(self):
        if self.plotter is None:
            self.plotter = QtInteractor(self, auto_update=False)
            # Qt's FBO multisampling conflicts with VTK depth peeling and can
            # make every translucent surface disappear on some OpenGL drivers.
            self.plotter.render_window.SetMultiSamples(0)
            self.stack.addWidget(self.plotter.interactor)
            self.probe_controls.setParent(self.plotter.interactor)
            self.frequency_controls.setParent(self.plotter.interactor)
            self.frequency_controls.move(4,4)
            self.plotter.set_background('#09151f', top='#1b3040')
            self.set_lighting()
            self.plotter.add_axes()
            self.plotter.interactor.setContextMenuPolicy(C.Qt.CustomContextMenu)
            self.plotter.interactor.customContextMenuRequested.connect(lambda p: self.menu(self.plotter.interactor.mapToGlobal(p)))
            self.plotter.interactor.installEventFilter(self.interaction)
        self.stack.setCurrentWidget(self.plotter.interactor)
        if self.config['orbit'].startswith('Az'):
            self.plotter.enable_terrain_style(); self.plotter.camera.up = (0, 0, 1)
        else: self.plotter.enable_trackball_style()

    def set_lighting(self):
        # Plotter.clear() removes lights as well as actors. Reinstall after
        # each scene rebuild, otherwise material settings produce a flat fill.
        self.plotter.remove_all_lights()
        for elevation, azimuth, intensity, color in ((30, -40, .95, '#fff2df'), (-20, 45, .3, '#bfdcff'), (55, 145, .6, '#ffffff')):
            light = pv.Light(light_type='camera light', intensity=intensity, color=color)
            light.set_direction_angle(elevation, azimuth)
            self.plotter.add_light(light)

    def camera(self, name='Isometric'):
        if not self.plotter: return
        if name == 'Front': self.plotter.view_yz()
        elif name == 'Top': self.plotter.view_xy()
        elif name == 'Side': self.plotter.view_xz()
        else:
            center = np.asarray(self.plotter.bounds).reshape(3, 2).mean(axis=1)
            self.plotter.camera_position = [center + (3.5, -5, 2.8), center, (0, 0, 1)]
        self.plotter.reset_camera()
        if self.config['kind'] == 'balloon': self.plotter.camera.zoom(1.35)
        self.home_focal = np.asarray(self.plotter.camera.focal_point)
        self.home_distance = np.linalg.norm(np.asarray(self.plotter.camera.position)-self.home_focal)
        self.plotter.render()

    def drag(self, point, widget):
        norm = np.linalg.norm(point)
        if norm < 1e-8: return
        d = np.asarray(point)/norm; widget.SetCenter(d*1.06)
        self.owner.azimuth.setValue(float(np.degrees(np.arctan2(d[1], d[0]))))
        self.owner.elevation.setValue(float(np.degrees(np.arcsin(np.clip(d[2], -1, 1)))))

    def render(self):
        o, c = self.owner, self.config
        if o.sphere is None:
            self.cursor.clear()
            self.interaction.begin(None)
            self.chart.fig.clear(); self.chart.canvas.draw_idle()
            self.stack.setCurrentWidget(self.chart_frame)
            self.probe_controls.hide(); self.frequency_controls.hide()
            self.note.setText('Open coefficients to view analysis plots')
            self.last_render = None
            return
        from hals_studio.ui.plotting.analysis_renderers import analysis_delay_markers
        markers = analysis_delay_markers(o) if c['kind'] == 'impulse' else ()
        key = (id(o.sphere), o.frequency.value(), o.azimuth.value(), o.elevation.value(),
               repr(c), o.overlay_revision, o.axis, markers)
        if self.last_render == key: return
        response_plot = c['kind'] in MAGNITUDE_KINDS or c['kind'] in ('phase', 'minimum')
        if (response_plot and self.last_render is not None and
                self.last_render[:1] + self.last_render[2:] == key[:1] + key[2:] and
                hasattr(self, 'frequency_marker')):
            frequency = o.sphere.freqs[o.frequency.value()]
            self.frequency_marker.set_xdata([frequency, frequency])
            self.cursor.follow_marker()
            self.chart.canvas.draw_idle()
            self.last_render = key
            return
        self.cursor.clear()
        title = TITLES[c['kind']]
        selected = selected_magnitudes(c)
        if c['magnitude_selection'] is not None:
            title = ' + '.join(TITLES[k] for k in selected) if len(selected) <= 2 else f'Magnitude responses ({len(selected)} selections)'
            if not selected: title = 'No magnitudes'
        if (c['kind'] in GROUPS['SPL & phase'] or c['magnitude_selection'] is not None) and c['kind'] not in ('phase', 'minimum') and c['phase_mode'] != 'None':
            title += ' / '+c['phase_mode']
        self.title.setText(f'{title.upper()}     ▾')
        self.title.setToolTip(title)
        self.note.setText('Right-click to choose plot or configure settings')
        s, i = o.sphere, o.frequency.value()
        levels = o.get_levels(c['smoothing']); rel = s.relative(levels, ('On axis' if c.get('directivity_on_axis',False) else 'Peak') if c['kind'].startswith(('map_', 'globe_')) or c['kind']=='cross_sonograms' else c['normalization'])
        kind = c['kind']
        self.probe_controls.setVisible(kind == 'balloon')
        self.frequency_controls.setVisible(kind == 'balloon')
        if kind in ('balloon', 'cross_sonograms'):
            from hals_studio.ui.plotting.analysis_renderers import render_scene
            render_scene(self, s, rel, i)
        else:
            self.stack.setCurrentWidget(self.chart_frame)
            if c['auto_axes'] and (kind in GROUPS['SPL & phase'] or c['magnitude_selection'] is not None):
                probe_key = (o.azimuth.value(), o.elevation.value(), o.overlay_revision, o.axis)
                if probe_key != getattr(self, '_range_probe', None): self.interaction.saved.clear()
                self._range_probe = probe_key
            self.interaction.begin((id(s), kind, c['auto_axes'], c['fmin'], c['fmax'], c['ymin'], c['ymax'], c['wrapped'], c['phase_mode'], c['phase_auto'], c['phase_min'], c['phase_max'], c['di_auto'], c['di_min'], c['di_max'], tuple(selected_magnitudes(c))))
            from hals_studio.ui.plotting.analysis_renderers import render_chart
            render_chart(self, s, levels, rel, i)
        self.last_render = (id(o.sphere), o.frequency.value(), o.azimuth.value(), o.elevation.value(),
                            repr(c), o.overlay_revision, o.axis, markers)

    def balloon(self, s, rel, i):
        from hals_studio.ui.plotting.scene_renderers import balloon
        return balloon(self, s, rel, i)

    def material(self):
        specular, power = {'Matte': (.05, 8), 'Satin': (.4, 18), 'Glossy': (.85, 35)}[self.config['surface_finish']]
        return dict(lighting=True, ambient=.12, diffuse=.8, specular=specular, specular_power=power)

    def volume(self, s, rel, i):
        from hals_studio.ui.plotting.scene_renderers import volume
        return volume(self, s, rel, i)

    def draw_chart(self, s, levels, rel, i):
        from hals_studio.ui.plotting.response_plot import draw_chart
        draw_chart(self, s, levels, rel, i)
