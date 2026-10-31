"""Qt Process workspace backed exclusively by the viewer's processing snapshot."""
import json
from pathlib import Path
from copy import deepcopy
import numpy as np
from PySide6 import QtCore as C,QtGui as G,QtWidgets as W
import hals_studio.bootstrap as bootstrap
import hals_studio.persistence.process_cache as process_cache
from hals_studio.ui.cli_log import CliLog
from hals_studio.persistence.project_paths import project_path_value
from hals_studio.ui.plotting.plots import Chart
from pyvistaqt import QtInteractor
import pyvista as pv

SCHEMA=json.loads((bootstrap.RESOURCES/'process_schema.json').read_text(encoding='utf-8'))
VIEWS={1:['FDW results'],2:['Validation','3D coordinate cloud','3D grid scan'],3:['Order recommendations'],4:['Fit error','Condition number','Spatial error','Sound Power vs Harmonic Degree']}

class ProcessWorkspace(W.QWidget):
    def __init__(self,owner):
        super().__init__();self.owner=owner;self.stage=1;self.job=False;self.results={};self.loaded=None;self.host=None;self.buffer='';self.plotter=None;self.stage1_settings={}
        self.rft_supplied=True;self.tweeter_supplied=True;self.filter_ir_filenames=False;self.wav_recovery=False
        self.origin_edits_pending=False
        self.values={int(i):{k:deepcopy(s['default']) for k,s in fields.items()} for i,fields in SCHEMA.items()}
        self.manual_table={350.:3,500.:4,625.:5,750.:6,875.:7,1500.:8,2100.:9,2800.:10,3500.:11,4100.:12,4600.:13,5000.:14,6000.:15}
        self.toolbar=W.QWidget();row=W.QHBoxLayout(self.toolbar);row.setContentsMargins(0,0,0,0);self.stage_buttons=[]
        self.metadata_button=W.QPushButton('Project metadata');self.metadata_button.setCheckable(True);self.metadata_button.clicked.connect(lambda:self.select_stage(0));row.addWidget(self.metadata_button)
        for stage,title in enumerate(['Stage 1 - FDW','Stage 2 - Origins','Stage 3 - Order','Stage 4 - Solve'],1):
            b=W.QPushButton(title);b.setCheckable(True);b.clicked.connect(lambda _,s=stage:self.select_stage(s));row.addWidget(b);self.stage_buttons.append(b)
        row.addStretch();layout=W.QVBoxLayout(self);layout.setContentsMargins(0,0,0,0)
        self.split=W.QSplitter();layout.addWidget(self.split)
        left=W.QWidget();box=W.QVBoxLayout(left);box.setContentsMargins(5,5,5,5)
        self.left_box=box
        self.project_name=W.QLineEdit(self);self.project_name.hide()
        self.ir_folder=W.QLineEdit(self);self.ir_folder.hide()
        self.speed_settings=W.QWidget();speedrow=W.QHBoxLayout(self.speed_settings);self.manual_speed=W.QCheckBox('Manual sound speed');speedrow.addWidget(self.manual_speed);self.speed=W.QDoubleSpinBox();self.speed.setRange(250,450);self.speed.setValue(343);self.speed.setSuffix(' m/s');self.speed.setFixedWidth(120);speedrow.addWidget(self.speed);box.addWidget(self.speed_settings);self.manual_speed.toggled.connect(self.speed.setEnabled);self.speed.setEnabled(False)
        from hals_studio.ui.process_forms import StageForms
        self.pages = StageForms(SCHEMA, self.values)
        box.addWidget(self.pages, 1)
        self.controls = self.pages.controls
        self.advanced = self.pages.advanced
        self.rft_reset_button = self.pages.rft_reset_button
        self.pages.rft_reset_requested.connect(self.set_range_from_rft)
        self.pages.edit_orders_requested.connect(self.edit_orders)
        self.pages.help_requested.connect(self.owner.show_documentation)
        self.order_choice=W.QComboBox();self.order_choice.setSizeAdjustPolicy(W.QComboBox.AdjustToContents);self.order_choice.currentIndexChanged.connect(self.refresh_order_action)
        self.reference_order=W.QComboBox();self.reference_order.setSizeAdjustPolicy(W.QComboBox.AdjustToContents);self.reference_order.currentIndexChanged.connect(self.change_reference)
        actions=W.QHBoxLayout();box.addLayout(actions);self.run_button=W.QPushButton('Run Stage 1');self.run_button.setObjectName('primary');self.run_button.clicked.connect(lambda:self.run());actions.addWidget(self.run_button)
        self.cancel_button=W.QPushButton('Cancel');self.cancel_button.setEnabled(False);self.cancel_button.clicked.connect(lambda:self.cancel());actions.addWidget(self.cancel_button)
        self.left_panel=left;left.setMinimumWidth(0);left.setSizePolicy(W.QSizePolicy.Ignored,W.QSizePolicy.Expanding)
        self.sidebar_split=W.QSplitter(C.Qt.Vertical);self.sidebar_split.setChildrenCollapsible(False);self.sidebar_split.addWidget(left);self.split.addWidget(self.sidebar_split)
        result=W.QWidget();resultbox=W.QVBoxLayout(result);resultbox.setContentsMargins(5,5,5,5);bar=W.QHBoxLayout();bar.setContentsMargins(0,0,0,0)
        self.result_bar=W.QWidget();self.result_bar.setLayout(bar);resultbox.addWidget(self.result_bar);self.main_result_bar=bar
        self.plot_label=W.QLabel('Plot type');bar.addWidget(self.plot_label);self.view=W.QComboBox();self.view.setSizeAdjustPolicy(W.QComboBox.AdjustToContents);self.view.setMaximumWidth(240);self.view.currentTextChanged.connect(self.draw);bar.addWidget(self.view)
        self.sample_label=W.QLabel('File');bar.addWidget(self.sample_label);self.sample=W.QComboBox();self.sample.setFixedWidth(210);self.sample.currentIndexChanged.connect(self.draw);bar.addWidget(self.sample)
        self.frequency_label=W.QLabel('Frequency');bar.addWidget(self.frequency_label)
        self.frequency=W.QDoubleSpinBox();self.frequency.setRange(.1,100000);self.frequency.setValue(1000);self.frequency.setSuffix(' Hz');self.frequency.setKeyboardTracking(False);self.frequency.valueChanged.connect(self.draw);bar.addWidget(self.frequency)
        self.plane=W.QComboBox();self.plane.addItems(['XY','XZ','YZ']);self.plane.currentTextChanged.connect(self.draw);bar.addWidget(self.plane)
        self.slice_position=W.QSlider(C.Qt.Horizontal);self.slice_position.setFixedWidth(130);self.slice_position.valueChanged.connect(self.draw);bar.addWidget(self.slice_position);self.slice_label=W.QLabel();self.slice_label.setMinimumWidth(85);bar.addWidget(self.slice_label)
        self.error_units=W.QComboBox();self.error_units.addItems(['Error / dB','Error / percent']);self.error_units.currentTextChanged.connect(self.draw);bar.addWidget(self.error_units)
        self.power_tools=W.QWidget();powerbar=W.QHBoxLayout(self.power_tools);powerbar.setContentsMargins(0,0,0,0)
        self.power_field=W.QComboBox();self.power_field.addItems(['Internal field','External field']);self.power_field.setAccessibleName('Sound power field');self.power_field.currentTextChanged.connect(self.draw);powerbar.addWidget(self.power_field)
        bar.addWidget(self.power_tools)
        self.threshold=W.QDoubleSpinBox();self.threshold.setRange(-120,0);self.threshold.setValue(-30);self.threshold.setPrefix('Floor ');self.threshold.setSuffix(' dB');self.threshold.setToolTip('Exclude measurement points below this level relative to the strongest point at this frequency.');self.threshold.valueChanged.connect(self.draw);bar.addWidget(self.threshold)
        self.previous=W.QPushButton('< Previous');self.previous.clicked.connect(lambda:self.sample.setCurrentIndex((self.sample.currentIndex()-1)%max(1,self.sample.count())));bar.addWidget(self.previous)
        self.next=W.QPushButton('Next >');self.next.clicked.connect(lambda:self.sample.setCurrentIndex((self.sample.currentIndex()+1)%max(1,self.sample.count())));bar.addWidget(self.next)

        bar.addStretch();self.power_reset=W.QPushButton('Reset axes');self.power_reset.setFixedHeight(32);self.power_reset.clicked.connect(self.reset);bar.addWidget(self.power_reset)
        self.ir_export=W.QToolButton();self.ir_export.setText('Export IR...');self.ir_export.setPopupMode(W.QToolButton.MenuButtonPopup)
        self.ir_export.clicked.connect(lambda:self.export_stage1_ir(False));menu=W.QMenu(self.ir_export)
        menu.addAction('Export All...',lambda:self.export_stage1_ir(True));self.ir_export.setMenu(menu);bar.addWidget(self.ir_export)
        bar.removeWidget(self.power_reset);bar.addWidget(self.power_reset)
        self.save_image_button=W.QPushButton('Save image');self.save_image_button.setFixedHeight(32);self.save_image_button.clicked.connect(self.save_image);bar.addWidget(self.save_image_button)
        self.stage2_tools=W.QWidget();s2=W.QHBoxLayout(self.stage2_tools);s2.setContentsMargins(0,0,0,0);rescan=W.QPushButton('Full grid rescan of selected frequency');rescan.clicked.connect(lambda:self.run('rescan'));s2.addWidget(rescan);s2.addWidget(W.QLabel('Frequency'));self.rescan_frequency=W.QComboBox();self.rescan_frequency.setFixedWidth(145);self.rescan_frequency.currentIndexChanged.connect(self.sample.setCurrentIndex);self.sample.currentIndexChanged.connect(self.rescan_frequency.setCurrentIndex);s2.addWidget(self.rescan_frequency);edit=W.QPushButton('Edit coordinate table');edit.clicked.connect(self.edit_origins);s2.addWidget(edit);s2.addStretch();bar.insertWidget(2,self.stage2_tools)
        self.stage3_tools=W.QWidget();s3=W.QHBoxLayout(self.stage3_tools);s3.setContentsMargins(0,0,0,0);s3.addWidget(W.QLabel('Sound power reference'));self.reference_order.setMaximumWidth(200);s3.addWidget(self.reference_order);s3.addStretch();bar.insertWidget(0,self.stage3_tools)
        self.order_choice.hide()

        self.origin_plot_tools=W.QWidget();origin_tools=W.QHBoxLayout(self.origin_plot_tools);origin_tools.setContentsMargins(0,0,0,0)
        self.origin_waypoint_box=W.QWidget();self.origin_waypoint_layout=W.QHBoxLayout(self.origin_waypoint_box);self.origin_waypoint_layout.setContentsMargins(0,0,0,0)
        self.origin_waypoint_checks={};self._origin_waypoint_project=None;origin_tools.addWidget(self.origin_waypoint_box)
        origin_tools.addSpacing(12)
        self.draw_origin_line=W.QToolButton();self.draw_origin_line.setText('Draw');self.draw_origin_line.setCheckable(True)
        self.draw_origin_line.setFixedHeight(32)
        self.draw_origin_line.setIcon(G.QIcon(str(bootstrap.RESOURCES/'assets'/'draw-pen.svg')));self.draw_origin_line.setToolButtonStyle(C.Qt.ToolButtonTextBesideIcon)
        self.draw_origin_line.setToolTip('Enable Draw: left-drag a straight line on X, Y or Z. Release to preview coordinates and fit errors. Save Project to apply. Esc cancels.')
        self.draw_origin_line.toggled.connect(self.draw);origin_tools.addWidget(self.draw_origin_line)
        self.origin_edit_note=W.QLabel('Manual coordinate edits need Save Project to apply.');origin_tools.addWidget(self.origin_edit_note)
        origin_tools.addStretch();resultbox.addWidget(self.origin_plot_tools)
        self.stack=W.QStackedWidget();resultbox.addWidget(self.stack,1);self.chart=Chart(toolbar=False);self.stack.addWidget(self.chart)
        from hals_studio.ui.plotting.process_results import Results
        self.original_results=Results();self.stack.addWidget(self.original_results)
        self.stage4_navigation=W.QWidget();navigation=W.QHBoxLayout(self.stage4_navigation);navigation.setContentsMargins(0,0,0,0)
        navigation.addStretch()
        self.analysis_button=W.QPushButton('Analysis');self.analysis_button.clicked.connect(lambda:self.publish(0));navigation.addWidget(self.analysis_button)
        self.export_button=W.QPushButton('Export');self.export_button.clicked.connect(lambda:self.publish(1));navigation.addWidget(self.export_button)
        resultbox.addWidget(self.stage4_navigation)
        result.setMinimumWidth(0);result.setSizePolicy(W.QSizePolicy.Ignored,W.QSizePolicy.Expanding);self.split.addWidget(result)
        cli=W.QFrame();cli.setFrameShape(W.QFrame.StyledPanel);cl=W.QVBoxLayout(cli);cl.setContentsMargins(5,5,5,5);cr=W.QHBoxLayout();cr.addWidget(W.QLabel('CLI OUTPUT'));cr.addStretch();b=W.QPushButton('Clear');b.clicked.connect(lambda:self.log.clear());cr.addWidget(b);b=W.QPushButton('Save log');b.clicked.connect(self.save_log);cr.addWidget(b);cl.addLayout(cr)
        self.log=CliLog();self.log.setMaximumBlockCount(30000);cl.addWidget(self.log);self.sidebar_split.addWidget(cli)
        self._sidebar_width=int(owner.settings.value('process_sidebar_width',420))
        self.split.setSizes([self._sidebar_width,980]);self.split.splitterMoved.connect(lambda *_: owner.settings.setValue('process_sidebar_width',self.split.sizes()[0]))
        cli_fraction=float(owner.settings.value('process_cli_height_fraction',.3))
        cli_fraction=max(.05,min(.95,cli_fraction))
        self.sidebar_split.setSizes([round(1000*(1-cli_fraction)),round(1000*cli_fraction)])
        self.sidebar_split.splitterMoved.connect(self.save_cli_split)
        self._rft_default=None
        self.refresh_rft_range()
        self.controls[3,'fdw_rft_ms'].textChanged.connect(self.refresh_rft_range)
        self.controls[1,'fdw_oct_res'].textChanged.connect(self.refresh_rft_range)
        self.controls[3,'fdw_rft_ms'].textEdited.connect(self.rft_edited)
        for axis in 'xyz':self.controls[2,'tweeter_'+axis].textEdited.connect(self.tweeter_edited)
        self.select_stage(1)
        C.QTimer.singleShot(0,self.restore_sidebar_width)
    def restore_sidebar_width(self):
        if self.split.width() > 0:
            width=int(self.owner.settings.value('process_sidebar_width',self._sidebar_width))
            self.split.setSizes([width,max(0,self.split.width()-width)])
    def save_cli_split(self,*_):
        sizes=self.sidebar_split.sizes();total=sum(sizes)
        if total:self.owner.settings.setValue('process_cli_height_fraction',sizes[1]/total)
    def select_stage(self,stage):
        coeff_path=self.coefficient_path()
        self.stage4_navigation.setVisible(stage==4 and coeff_path is not None and coeff_path.is_file())
        self.metadata_button.setChecked(stage==0);self.speed_settings.setVisible(stage==0);self.pages.setVisible(stage!=0);self.run_button.setVisible(stage!=0);self.cancel_button.setVisible(stage!=0)
        self.result_bar.setVisible(stage!=0);self.stage2_tools.setVisible(stage==2);self.stage3_tools.setVisible(stage==3)
        if stage==0:
            self.stage=0
            for b in self.stage_buttons:b.setChecked(False)
            if not hasattr(self,'metadata_editor'):
                from hals_studio.ui.project_ui import ensure_export
                from hals_studio.ui.project_metadata import MetadataEditor
                self.metadata_editor=MetadataEditor(ensure_export(self.owner));self.metadata_editor.save_button.clicked.disconnect();self.metadata_editor.save_button.clicked.connect(self.owner.save_project);self.metadata_editor.table.itemChanged.connect(self.metadata_changed);self.left_box.insertWidget(1,self.metadata_editor,1);self.metadata_editor.save_button.hide()
            self.metadata_editor.reload();self.metadata_editor.show();self.show_splash();return
        if hasattr(self,'metadata_editor'):self.metadata_editor.hide()
        self.stage=stage;self.pages.setCurrentIndex(stage-1)
        if stage==4 and self.results.get(4) is None and coeff_path is not None and coeff_path.is_file():
            try:self.results[4]=process_cache.load_stage4_summary(coeff_path)
            except (OSError,KeyError):pass
        for i,b in enumerate(self.stage_buttons,1):b.setChecked(i==stage)
        self.run_button.setText(f'Run Stage {stage}');self.view.blockSignals(True);self.view.clear();self.view.addItems(VIEWS[stage]);self.view.blockSignals(False);self.update_selectors();self.draw()
    def show_splash(self):
        if not hasattr(self,'splash'):
            self.splash=W.QLabel();self.splash.setAlignment(C.Qt.AlignCenter);self.splash.setMinimumSize(1,1);self.stack.addWidget(self.splash)
        pix=G.QPixmap(str(bootstrap.RESOURCES/'assets/hals_splash.png'))
        self.splash.setPixmap(pix.scaled(max(100,self.stack.width()-30),max(100,self.stack.height()-30),C.Qt.KeepAspectRatio,C.Qt.SmoothTransformation));self.stack.setCurrentWidget(self.splash)
    def metadata_changed(self,*_):
        if self.metadata_editor.filling or self.metadata_editor.pending:return
        self.owner.export_workspace.metadata_editor.reload()
        from hals_studio.application.export_engine import waypoint
        try:
            xyz=waypoint(self.owner.export_workspace.config['project_geometry'],'tw')*1000
            for axis,value in zip('xyz',xyz):self.set_value(2,'tweeter_'+axis,round(float(value),3))
            self.tweeter_supplied=True
        except (KeyError,ValueError,TypeError):self.tweeter_supplied=False
    def rft_edited(self,*_):
        self.rft_supplied=True
    def tweeter_edited(self,*_):
        self.tweeter_supplied=True
    def set_value(self,stage,key,value):
        control=self.controls[stage,key]
        if isinstance(control,W.QCheckBox):control.setChecked(bool(value))
        else:control.setText(str(value))
    def adopt_project(self,force=False,payload=None):
        path=self.owner.project_path
        if not path or (self.loaded==path and not force):return
        data=payload if payload is not None else json.loads(Path(path).read_text(encoding='utf-8-sig'))
        from hals_studio.application.ir_recovery import metadata_availability
        self.tweeter_supplied,self.rft_supplied=metadata_availability(data)
        self.wav_recovery=data.get('measurement_metadata',{}).get('wav_recovery',False)
        self.filter_ir_filenames=data.get('measurement_metadata',{}).get('filter_ir_filenames',self.wav_recovery)
        self.loaded=path;self.results={};self.stage1_settings={};self.origin_edits_pending=False
        self.project_name.setText(data.get('project_name',Path(path).stem.replace('_project','')));self.owner.dataset_label.setText(self.project_name.text())
        self._loading_rft=True
        for stage in range(1,5):
            for key,spec in SCHEMA[str(stage)].items():self.set_value(stage,key,data.get(f'stage{stage}_vars',{}).get(key,spec['default']))
        if 'condition_preflight' not in data.get('stage4_vars',{}):
            self.set_value(4,'condition_preflight',data.get('stage3_vars',{}).get('condition_preflight',True))
        from hals_studio.process_engine.rft_range import project_rft_ms
        self.set_value(3,'fdw_rft_ms',project_rft_ms(data) if self.rft_supplied else 5.0)
        self._loading_rft=False
        self.refresh_rft_range()
        if 'freq_start_hz' not in data.get('stage3_vars',{}):self.set_range_from_rft()
        self.manual_table=data.get('stage4_manual_table',self.manual_table)
        glob=data.get('global_vars',{});self.manual_speed.setChecked(bool(glob.get('enable_manual_speed_of_sound',False)));self.speed.setValue(float(glob.get('speed_of_sound',343)))
        folder=Path(path).parent;choices=[folder/n for n in ('recordings','Recordings','measurement_set','input_irs','input_irs_synth')]+[folder]
        self.ir_folder.setText(str(next((p for p in choices if p.is_dir() and next(p.glob('*.wav'),None)),folder)))
        grid=data.get('grid_vars',{})
        if all(grid.get('wp_tw_'+k) not in (None,'') for k in ('r','phi','z')):
            r,phi,z=[float(grid['wp_tw_'+k]) for k in ('r','phi','z')]
            for key,val in zip('xyz',(r*np.cos(np.deg2rad(phi)),r*np.sin(np.deg2rad(phi)),z)):self.set_value(2,'tweeter_'+key,round(val,3))
        saved_folder=project_path_value(data.get('input_ir_folder'),folder)
        if saved_folder:self.ir_folder.setText(saved_folder)
        self.cache(1).unlink(missing_ok=True)
        npz=folder/'outputs'/f'{self.project_name.text()}_complex_data.npz'
        if npz.is_file():
            self.stage1_settings=process_cache.load_stage1_settings(npz)
            self.reconcile_stage1_settings()
            self.refresh_rft_range()
            try:self.results[1]=process_cache.load_stage1(npz,self.stage1_plot_settings())
            except FileNotFoundError:pass
        for stage in range(2,5):
            if self.cache(stage).exists():
                self.results[stage]=process_cache.load(self.cache(stage),stage)
        state=data.get('hals_studio', data.get('hals_viewer',{})).get('session',{}).get('process_layout') or {}
        self.pages.restore_scan_bounds_state(state.get('manual_scan_bounds'))
        self.refresh_scan_bounds()
        saved_ir_folder=project_path_value(state.get('input_ir_folder'),folder)
        if saved_ir_folder:self.ir_folder.setText(saved_ir_folder)
        self.select_stage(state.get('stage',1));self.start_host()
    def layout_state(self):
        return dict(stage=self.stage,input_ir_folder=self.ir_folder.text(),
                    manual_scan_bounds=sorted(self.pages.manual_scan_bounds))
    def project_payload(self):
        return dict(input_ir_folder=self.ir_folder.text(),measurement_metadata=dict(rft_supplied=self.rft_supplied,tweeter_supplied=self.tweeter_supplied,wav_recovery=self.wav_recovery,filter_ir_filenames=self.filter_ir_filenames),project_name=self.project_name.text().strip(),**{f'stage{s}_vars':deepcopy(v) for s,v in self.values.items()},stage4_manual_table=self.manual_table,
            global_vars=dict(enable_manual_speed_of_sound=self.manual_speed.isChecked(),speed_of_sound=str(self.speed.value())))
    def save_pending_origins(self):
        if not self.origin_edits_pending:return
        if self.job:raise ValueError('Wait for coordinate fitting errors to finish before saving the project.')
        from hals_studio.application.process_stages import persist_origin_result
        output=self.measurement_path()
        result=process_cache.hydrate_stage2(self.results[2],output)
        result=persist_origin_result(result,self.values[2],output.parent,output.name)
        process_cache.save(self.cache(2),2,result)
        self.results[2]=process_cache.compact(2,result);self.origin_edits_pending=False
        self.origin_edit_note.setText('Manual coordinate edits need Save Project to apply.')
    def cache(self,stage):
        project=Path(self.owner.project_path)
        return project.parent/'process_cache'/project.stem/f'stage{stage}.pkl'
    def new_project(self):
        if self.job:return
        path,_=W.QFileDialog.getSaveFileName(self,'New HALS project','project.json','HALS project (*.json)')
        if not path:return
        self.rft_supplied=False;self.tweeter_supplied=False;self.wav_recovery=False;self.filter_ir_filenames=False
        from hals_studio.ui.project_ui import ensure_export
        from hals_studio.application.export_engine import DEFAULT_EXPORT
        ensure_export(self.owner).apply_config(deepcopy(DEFAULT_EXPORT))
        self.owner.source_path=None;self.owner.source_options=None
        self.owner.project_path=path;self.owner.project_path_field.setText(str(Path(path).parent));self.loaded=path;self.results={};self.stage1_settings={};self.origin_edits_pending=False;self.project_name.setText(Path(path).stem.replace('_project',''));self.ir_folder.setText(str(Path(path).parent));self.owner.save_project();self.start_host();self.select_stage(1)
    def browse_ir(self):
        path=W.QFileDialog.getExistingDirectory(self,'Input IR recordings',self.ir_folder.text())
        if path:self.ir_folder.setText(path)
    def start_host(self):
        self.owner.pool.start()
    def run(self,action='run',edits=None):
        from hals_studio.application.job_coordinator import jobs_for
        jobs = jobs_for(self.owner)
        if self.stage==0:return
        if self.job or jobs.busy():return
        if not self.owner.project_path:W.QMessageBox.information(self,'Project required','Open or create a project first.');return
        if self.owner.worker and self.owner.worker.isRunning():W.QMessageBox.information(self,'Busy','Wait for Analysis reconstruction to finish.');return
        if self.owner.export_workspace and self.owner.export_workspace.job:W.QMessageBox.information(self,'Busy','Wait for Export evaluation to finish.');return
        name=self.project_name.text().strip()
        if self.stage==4 and self.values[4]['use_manual_table'] and not self.manual_table:
            W.QMessageBox.warning(self,'Order table','Enter a manual order table or uncheck Use manual order table.');return
        if self.stage==4 and not self.values[4]['use_manual_table']:
            try:
                if int(self.values[4]['target_n_max'])<2:raise ValueError()
            except ValueError:W.QMessageBox.warning(self,'Harmonic order','The solver requires a maximum order of at least 2 without a manual order table.');return
        if not name or Path(name).name!=name or any(c in name for c in '<>:"/\\|?*'):W.QMessageBox.warning(self,'Project name','Use a valid filename without path separators.');return
        request=dict(stage=self.stage,settings=deepcopy(self.values[self.stage]),folder=str(Path(self.owner.project_path).parent),name=name,ir_folder=self.ir_folder.text(),cache=str(self.cache(self.stage)),manual_table=self.manual_table,speed=self.speed.value(),manual_speed=self.manual_speed.isChecked(),action=action)
        request['rft_ms']=self.values[3]['fdw_rft_ms'] if self.rft_supplied else 5.0
        if self.stage==3 and not self.rft_supplied:request['settings']['fdw_rft_ms']=5.0
        request['rft_supplied']=self.rft_supplied
        request['tweeter_supplied']=self.tweeter_supplied
        if self.stage==1 and self.filter_ir_filenames:
            from hals_studio.application.ir_recovery import scan_ir_folder
            try:request['input_filenames'],_=scan_ir_folder(self.ir_folder.text())
            except (OSError,ValueError,RuntimeError) as exc:
                W.QMessageBox.warning(self,'IR recordings',str(exc));return
        if action=='run' and self.stage==2 and not self.tweeter_supplied:
            W.QMessageBox.information(self,'Automatic tweeter seed',
                'No tweeter coordinate was supplied. A 20 mm grid scan inside the measurement cylinder, '
                'at or below the end frequency (capped at 20 kHz), followed by simplex refinement, '
                'will estimate the HF seed. The LF search starts at (0, 0, 0). '
                'The estimated tweeter coordinate will be saved to the project.')
        if action=='run' and self.stage==3 and not self.rft_supplied:
            W.QMessageBox.information(self,'RFT unavailable',
                'No measured RFT was supplied. The suggested lower test frequency uses a 5 ms fallback. '
                'The current lower test frequency is retained, including any value you entered.')
        request['project_oct_res']=self.stage1_resolution()
        if self.stage==2 and (action=='save_origins' or (action=='rescan' and self.origin_edits_pending)):
            request['preview_only']=True;request['origin_result']=self.results[2]
        if edits:request['edits']=edits
        if action=='reference':request['reference']=self.reference_order.currentData()['n']
        if action=='load_origins':request['origin_cache']=self.origin_cache_path
        if action=='rescan':
            if 2 not in self.results:return
            request['rescan']=[float(self.sample.currentData())]
        self.active_request=request;self._cli_line='';self.start_host();self.job=True;self.active_stage=self.stage;self.run_button.setEnabled(False);self.cancel_button.setEnabled(True)
        self.refresh_order_action()
        self.log.appendPlainText(f'\nStage {self.stage} - {action} - {name}\n')
        from hals_studio.infrastructure.process_job import ProcessJob
        self.host=ProcessJob(request,self.owner.pool,self)
        self._host_outcome = None
        jobs.track('process', self.host, self.cancel)
        self.host.message.connect(self.append_output)
        self.host.progress.connect(self.processing_progress)
        self.host.completed.connect(self._receive_completion)
        self.host.finished.connect(self._host_completed)
        if hasattr(self.owner,'progress'):
            self.owner.progress.setRange(0,0);self.owner.progress.show();self.owner.statusBar().showMessage(f'Stage {self.stage}: preparing… | ETA estimating…')
        self.host.start()
    def processing_progress(self,event):
        if not self.job or not hasattr(self.owner,'progress'):return
        self.display_processing_progress(event)
    def display_processing_progress(self,event):
        if not hasattr(self.owner,'progress'):return
        from hals_studio.process_engine.process_progress import duration
        total=event['total'];done=event['completed']
        self.owner.progress.setRange(0,total);self.owner.progress.setValue(done)
        self.owner.progress.show()
        message=(f"{event['label']}: {done}/{total} complete · {event['remaining']} remaining · ETA {duration(event['eta'])}" if total else f"{event['label']} · ETA estimating…")
        self.owner.statusBar().showMessage(message)
    def end_processing_progress(self,message):
        if hasattr(self.owner,'progress'):
            self.owner.progress.setRange(0,100);self.owner.progress.hide();self.owner.statusBar().showMessage(message)
    def append_output(self,text):
        import re
        text=re.sub(r'\x1b\[[0-9;]*[A-Za-z]','',text)
        with self.log.output_update():
            cursor=G.QTextCursor(self.log.document());cursor.movePosition(G.QTextCursor.End)
            for token in re.split(r'([\r\n])',text):
                if token=='\r':self._cli_line=''
                elif token=='\n':cursor.insertBlock();self._cli_line=''
                elif token:
                    self._cli_line=getattr(self,'_cli_line','')+token
                    cursor.movePosition(G.QTextCursor.StartOfBlock,G.QTextCursor.KeepAnchor);cursor.insertText(self._cli_line)
    def prepare_slice(self):
        r=self.results.get(2)
        if r is None:return
        f=self.sample.currentData()
        if f is None:return
        row=r[0][f];axis={'XY':2,'XZ':1,'YZ':0}[self.plane.currentText()];raw=row[('X_vals','Y_vals','Z_vals')[axis]];coords=np.asarray(raw) if raw is not None else np.array([])
        self.slice_position.setEnabled(row.get('grid') is not None)
        key=(f,self.plane.currentText(),id(row.get('grid')))
        if key!=getattr(self,'_slice_key',None):
            self._slice_key=key;self.slice_position.blockSignals(True);self.slice_position.setRange(0,max(0,len(coords)-1));self.slice_position.setValue(int(np.argmin(abs(coords-row['final_c'][axis]))) if len(coords) else 0);self.slice_position.blockSignals(False)
        self.slice_label.setText(f'{self.slice_value():.1f} mm')
    def slice_value(self):
        r=self.results.get(2);f=self.sample.currentData()
        if r is None or f is None:return 0.
        axis={'XY':2,'XZ':1,'YZ':0}[self.plane.currentText()];coords=r[0][f][('X_vals','Y_vals','Z_vals')[axis]]
        return float(coords[min(self.slice_position.value(),len(coords)-1)]) if coords is not None and len(coords) else 0.
    @C.Slot(dict)
    def _receive_completion(self, event):
        self._host_outcome = event

    @C.Slot()
    def _host_completed(self):
        self.finished(self._host_outcome or dict(ok=False, error='Processing stopped without a result.'))

    def finished(self,event):
        self.job=False;self.run_button.setEnabled(True);self.cancel_button.setEnabled(False)
        self.end_processing_progress('Processing complete' if event['ok'] else 'Processing failed — see CLI output')
        self.refresh_order_action()
        if not event['ok']:return
        stage=int(event['stage'])
        if event.get('preview_only'):
            self.results[2]=event['result'];self.origin_edits_pending=True
            self.origin_edit_note.setText('Unsaved manual coordinate edits — Save Project to apply.')
            self.draw()
            return
        if stage==1:
            self.stage1_settings=process_cache.load_stage1_settings(event['cache'])
            self.results[1]=process_cache.load_stage1(event['cache'],self.stage1_plot_settings())
            self.refresh_rft_range()
            if self.wav_recovery and not Path(self.owner.project_path).exists():
                self.owner.save_project()
        else:self.results[stage]=process_cache.load(event['cache'],stage)
        if stage in (1,2):self.origin_edits_pending=False
        if stage==2:self.save_estimated_tweeter()
        if stage in (1, 2):self.refresh_scan_bounds()
        if stage==3 and self.results[3].get('below_rft'):self.set_value(3,'freq_start_hz',self.results[3]['test_band_hz'][0])
        self.select_stage(stage)
        if getattr(self,'active_request',{}).get('action')=='rescan':
            index=self.sample.findData(self.active_request['rescan'][0]);self.sample.setCurrentIndex(index);self.view.setCurrentText('3D grid scan')
        reference_change=stage==3 and getattr(self,'active_request',{}).get('action')=='reference'
        if not reference_change:self.autosave_plots()
        if stage==3 and not reference_change:
            self._stage3_pulse_pending=True
            self.draw()
        self._cli_line='';self.log.appendPlainText(f'Stage {stage} complete. Results saved.')
        if stage==4:self.reload_coefficients(force=True)
    def cancel(self, restart=True):
        from hals_studio.application.job_coordinator import jobs_for
        jobs = jobs_for(self.owner)
        if self.host and self.host.isRunning():
            self.host.requestInterruption()
            self.cancel_button.setEnabled(False)
            self.end_processing_progress('Cancelling processing...')
            pool = self.owner.pool
            def stopped():
                if restart and not jobs.closing and self.owner.pool is pool:
                    from hals_studio.infrastructure.worker_pool import WarmPool
                    self.owner.pool = WarmPool(int(self.owner.settings.value('worker_count', 0)) or None)
                    self.owner.pool.start()
                self.run_button.setEnabled(not self.job and not jobs.closing)
            jobs.stop_pool(pool, stopped)
        self.refresh_order_action()

    def shutdown(self):
        self.cancel(restart=False)
        for job in getattr(self, '_spatial_jobs', []):
            job.requestInterruption()

    def load_existing(self):
        if not self.owner.project_path:return
        root=Path(self.owner.project_path).parent;name=self.project_name.text()
        try:
            if self.stage==1:
                self.results.pop(1,None)
                self.results[1]=process_cache.load_stage1(root/'outputs'/f'{name}_complex_data.npz',self.values[1])
            elif self.cache(self.stage).exists():
                self.results[self.stage]=process_cache.load(self.cache(self.stage),self.stage)
            elif self.stage==2:
                path,_=W.QFileDialog.getOpenFileName(self,'Open HALS origin cache',str(root/'outputs'),'HALS origin cache (*.pkl)')
                if path:self.origin_cache_path=path;self.run('load_origins')
                return
            elif self.stage==4:
                self.results[4]=process_cache.load_stage4_summary(self.coefficient_path())
            else:raise ValueError('Run this stage to obtain its full diagnostics.')
            if self.stage in (1, 2):self.refresh_scan_bounds()
            self.update_selectors();self.draw()
        except Exception as e:W.QMessageBox.warning(self,'Results',str(e))
    def refresh_scan_bounds(self):
        from hals_studio.process_engine.origin_scan_region import measurement_cylinder
        from hals_studio.process_engine.utils import parse_coords_from_filename
        measurement = self.results.get(1)
        coordinates = []
        if measurement is not None:
            for name in measurement[1]:
                try:coordinates.append(parse_coords_from_filename(name))
                except ValueError:continue
        if coordinates:
            radii, angles, _ = np.asarray(coordinates).T
            bounds = measurement_cylinder(radii, angles)
        else:
            result = self.results.get(2)
            if result is None or 'scan_radius_mm' not in result[5]:return
            bounds = result[5]
        self.pages.apply_scan_bounds(bounds)

    def update_selectors(self):
        self.ir_export.setVisible(self.stage==1)
        self.ir_export.setEnabled(1 in self.results and not self.job)
        self.rescan_frequency.blockSignals(True);self.rescan_frequency.clear()
        self.sample.blockSignals(True);self.sample.clear();r=self.results.get(self.stage)
        if self.stage==4:
            power_index=self.view.findText('Sound Power vs Harmonic Degree')
            if power_index>=0:
                coeff=self.coefficient_path();available=coeff is not None and coeff.is_file()
                self.view.model().item(power_index).setEnabled(available)
                self.view.setItemData(power_index,'' if available else 'Sound power needs the saved coefficient file.',C.Qt.ToolTipRole)
                if not available and self.view.currentIndex()==power_index:self.view.setCurrentIndex(0)
            index=self.view.findText('Spatial error')
            if index>=0:
                coeff=self.coefficient_path();npz=self.measurement_path()
                available=coeff is not None and coeff.is_file() and npz is not None and npz.is_file()
                self.view.model().item(index).setEnabled(available)
                self.view.setItemData(index,'' if available else 'Spatial error needs the measurement NPZ and coefficient file.',C.Qt.ToolTipRole)
                if not available and self.view.currentIndex()==index:self.view.setCurrentIndex(0)
        if r is not None:
            if self.stage==1:
                pane=self.owner.export_workspace
                grid=pane.config.get('project_geometry',{}) if pane is not None else {}
                names=sorted(r[1]);preferred=process_cache.closest_tweeter_ir(names,grid)
                if preferred is not None:names.remove(preferred);names.insert(0,preferred)
                for name in names:
                    self.sample.addItem(name+' — Closest to tweeter' if name==preferred else name,name)
                    index=self.sample.count()-1
                    self.sample.setItemData(index,name,C.Qt.ToolTipRole)
                    if name==preferred:
                        font=G.QFont(self.sample.font());font.setBold(True);self.sample.setItemData(index,font,C.Qt.FontRole)
                        self.sample.setItemData(index,f'{name}\nClosest to tweeter: nearest Z height, then nearest phi angle (ignoring radius).',C.Qt.ToolTipRole)
                self.sample.setCurrentIndex(0)
            elif self.stage==2:
                for f in sorted(r[0]):self.sample.addItem(f'{f:,.1f} Hz',float(f))
            elif self.stage==3:
                self.order_choice.clear();self.reference_order.blockSignals(True);self.reference_order.clear()
                for key,opt in r.get('options',{}).items():
                    title={'knee':'Internal / external ratio','tail':'Sound power discarded','spl':'Directivity change'}.get(key,opt.get('label',key));self.order_choice.addItem(f"{title} - N={opt['n']}",int(opt['n']));self.order_choice.setItemData(self.order_choice.count()-1,opt.get('reason',opt.get('label','')),C.Qt.ToolTipRole)
                for n,ref in r.get('step1',{}).get('tail_by_reference',{}).items():self.reference_order.addItem(f'N={n}',ref)
                reference=r.get('step1',{}).get('tail_reference',{}).get('n')
                for i in range(self.reference_order.count()):
                    if self.reference_order.itemData(i).get('n')==reference:self.reference_order.setCurrentIndex(i)
                recommended=r.get('selected_order_N',r.get('options',{}).get(r.get('recommended_key'),{}).get('n'))
                index=self.order_choice.findData(recommended)
                if index>=0:self.order_choice.setCurrentIndex(index)
                self.reference_order.blockSignals(False)
            elif self.stage==4:
                for i in range(len(r.get('coords_sph',[]))):self.sample.addItem(f'Point {i+1}',i)
        if self.stage==2:
            for i in range(self.sample.count()):self.rescan_frequency.addItem(self.sample.itemText(i),self.sample.itemData(i))
        self.rescan_frequency.blockSignals(False);self.sample.blockSignals(False)
    def selected_origin_waypoints(self):
        from hals_studio.ui.plotting.origin_editing import metadata_points, waypoint_color
        pane=self.owner.export_workspace
        points=metadata_points(pane.config.get('project_geometry',{}) if pane is not None else {})
        keys=[(index,name) for index,(name,xyz) in enumerate(points)]
        project=self.owner.project_path
        if list(self.origin_waypoint_checks)!=keys or project!=self._origin_waypoint_project:
            previous={key:check.isChecked() for key,check in self.origin_waypoint_checks.items()} if project==self._origin_waypoint_project else {}
            while self.origin_waypoint_layout.count():
                self.origin_waypoint_layout.takeAt(0).widget().deleteLater()
            self.origin_waypoint_checks={};self._origin_waypoint_project=project
            for key in keys:
                check=W.QCheckBox(key[1]);check.setChecked(previous.get(key,False))
                check.setToolTip('Show this metadata waypoint on the X, Y and Z graphs.')
                item=W.QWidget();row=W.QHBoxLayout(item);row.setContentsMargins(0,0,0,0);row.setSpacing(4)
                dash=W.QLabel(f'<span style="color:{waypoint_color(key[0])}">━━</span>');dash.setFixedWidth(22)
                row.addWidget(check);row.addWidget(dash)
                check.toggled.connect(self.draw);self.origin_waypoint_layout.addWidget(item);self.origin_waypoint_checks[key]=check
        return [(index,name,xyz) for index,(name,xyz) in enumerate(points) if self.origin_waypoint_checks[index,name].isChecked()]

    def draw(self,*_):
        self.origin_plot_tools.setVisible(self.stage==2 and self.view.currentText()=='Validation')
        self.origin_edit_note.setVisible(self.stage==2)
        if self.stage==0:return
        self.last_plot_error=None
        view=self.view.currentText()
        self.power_tools.setVisible(self.stage==4 and view=='Sound Power vs Harmonic Degree')
        self.power_reset.setVisible(self.stage in (1,2) or (self.stage==4 and view=='Sound Power vs Harmonic Degree'))
        if view!=getattr(self,'_last_view_kind',None):
            self._last_view_kind=view
            if view in ('Fit error','Spatial error'):
                self.threshold.blockSignals(True);self.threshold.setValue(-90 if view=='Fit error' else -30);self.threshold.blockSignals(False)
        for control in (self.previous,self.next):control.setVisible(self.stage==1)
        self.sample.setVisible(self.stage==1);self.sample_label.setVisible(self.stage==1);self.frequency_label.hide()
        self.frequency.hide();self.plane.setVisible(view=='Search landscape')
        self.plane.setVisible(view=='3D grid scan');self.slice_position.setVisible(view=='3D grid scan');self.slice_label.setVisible(view=='3D grid scan')
        self.plot_label.setVisible(len(VIEWS[self.stage])>1);self.view.setVisible(len(VIEWS[self.stage])>1)
        if view=='3D grid scan':self.prepare_slice()
        self.error_units.setVisible(view=='Fit error');self.threshold.hide()
        r=self.results.get(self.stage);self.chart.fig.clear();ax=self.chart.fig.add_subplot();self.stack.setCurrentWidget(self.chart)
        if r is None:ax.set_axis_off();ax.text(.5,.5,'Run this stage or load its saved results.',ha='center',va='center');self.chart.done();return
        if self.stage==4 and view=='Spatial error' and 'spatial_data' not in r:
            if not r.get('spatial_pending') and not r.get('spatial_error'):self.start_spatial_compute(r)
            ax.set_axis_off();ax.text(.5,.5,r.get('spatial_error','Calculating spatial error at 1/96-octave spacing...'),ha='center',va='center',wrap=True);self.chart.done();return
        try:
            view=self.view.currentText()
            self.original_results.draw(self);self.stack.setCurrentWidget(self.original_results);return
        except Exception as e:self.last_plot_error=str(e);ax.clear();ax.set_axis_off();ax.text(.02,.8,str(e),wrap=True,transform=ax.transAxes);self.chart.done()
    @staticmethod
    def spherical_xyz(coords,radians=False):
        coords=np.asarray(coords);theta,phi=(coords[:,:2].T if radians else np.deg2rad(coords[:,:2]).T);r=coords[:,2];return np.column_stack([r*np.sin(theta)*np.cos(phi),r*np.sin(theta)*np.sin(phi),r*np.cos(theta)])
    def cloud(self,xyz,scalars=None,title=''):
        if self.plotter is None:self.plotter=QtInteractor(self,auto_update=False);self.stack.addWidget(self.plotter.interactor);self.plotter.enable_terrain_style()
        self.stack.setCurrentWidget(self.plotter.interactor);self.plotter.clear()
        from hals_studio.ui.viewer_theme import colour
        if scalars is None:self.plotter.add_points(xyz,color='#599bda',point_size=10,render_points_as_spheres=True)
        else:self.plotter.add_mesh(pv.PolyData(xyz),scalars=np.asarray(scalars),cmap='PColor',point_size=10,render_points_as_spheres=True,scalar_bar_args={'title':title,'color':colour('#b8d6e8'),'title_font_size':12,'label_font_size':10})
        from hals_studio.ui.viewer_theme import scene_theme
        scene_theme(self.plotter);self.plotter.add_axes();self.scene_bounds();self.plotter.view_isometric();self.plotter.reset_camera();self.plotter.render()
    def scene_bounds(self,bounds=None):
        from hals_studio.ui.viewer_theme import colour
        unit='mm' if self.stage==2 or self.view.currentText()=='Origins / 3D' else 'm'
        self.plotter.show_bounds(bounds=bounds,grid='back',location='outer',all_edges=False,color=colour('#b8d6e8'),font_size=10,xtitle='X / '+unit,ytitle='Y / '+unit,ztitle='Z / '+unit)
    def reset(self):
        if self.stack.currentWidget() is self.original_results and getattr(self.original_results,'interaction',None) is not None:self.original_results.interaction.reset()
        elif self.plotter and self.stack.currentWidget() is self.plotter.interactor:self.plotter.reset_camera();self.plotter.render()
        else:self.draw()
    def image_path(self):
        import re
        name=self.project_name.text().strip() or 'HALS'
        kind=self.view.currentText()
        suffix={
            'Validation':'complex_data_origins',
            'Order recommendations':'complex_data_stage3_order_sweep',
            'Fit error':'coefficients_residual_error',
            'Condition number':'coefficients_condition_number',
        }.get(kind)
        if suffix is None:
            suffix=f'stage{self.stage}_'+re.sub(r'[^a-z0-9]+','_',kind.lower()).strip('_')
            if kind=='Sound Power vs Harmonic Degree':suffix+='_'+self.power_field.currentText().lower().replace(' ','_')
            if self.stage==1:suffix+='_'+Path(str(self.sample.currentData() or 'response')).stem
            elif self.stage==2:suffix+=f'_{float(self.sample.currentData() or 0):.1f}Hz'
            elif kind=='Spatial error':suffix+=f'_{self.frequency.value():.1f}Hz'
            if kind=='3D grid scan':suffix+=f'_{self.plane.currentText()}_{self.slice_value():.1f}mm'
        folder=Path(self.owner.project_path).parent/'outputs' if self.owner.project_path else Path.home()
        return folder/(re.sub(r'[<>:"/\\|?*]','_',f'{name}_{suffix}')+'.png')
    def write_image(self,path):
        if self.stack.currentWidget() is self.original_results:
            self.original_results.canvas.draw()
            if self.stage==3:self.original_results.canvas.grab().save(str(path))
            else:self.original_results.fig.savefig(path,dpi=180,facecolor=self.original_results.fig.get_facecolor(),edgecolor=self.original_results.fig.get_edgecolor())
        elif self.plotter and self.stack.currentWidget() is self.plotter.interactor:self.plotter.screenshot(str(path))
        else:self.chart.fig.savefig(path,dpi=180,facecolor=self.chart.fig.get_facecolor(),edgecolor=self.chart.fig.get_edgecolor())
    def save_image(self):
        path,_=W.QFileDialog.getSaveFileName(self,'Save result image',str(self.image_path()),'PNG (*.png)')
        if path:
            if not Path(path).suffix:path+='.png'
            self.write_image(path)
    def autosave_plots(self):
        # The Tk result windows performed these saves; the Qt workspace owns them now.
        kinds={1:['FDW results'],2:['Validation'],3:['Order recommendations'],4:['Fit error','Condition number']}[self.stage]
        selected=self.view.currentText()
        self._autosaving_plots=True
        try:
            self.view.blockSignals(True)
            for kind in kinds:
                self.view.setCurrentText(kind);self.draw()
                if self.last_plot_error:raise RuntimeError(self.last_plot_error)
                path=self.image_path();path.parent.mkdir(parents=True,exist_ok=True);self.write_image(path)
                self.log.appendPlainText(f'Saved plot: {path}')
        except Exception as exc:
            self.log.appendPlainText(f'Could not save result plot: {exc}')
        finally:
            self.view.setCurrentText(selected);self.view.blockSignals(False);self.draw();self._autosaving_plots=False
    def save_log(self):
        path,_=W.QFileDialog.getSaveFileName(self,'Save processing log','','Text (*.txt)')
        if path:Path(path).write_text(self.log.toPlainText(),encoding='utf-8')
    def refresh_order_action(self,*_):
        results=getattr(self,'original_results',None)
        if results is None:return
        button=results.findChild(W.QPushButton,'stage3_use_order')
        if button is None:return
        n=self.order_choice.currentData()
        button.setText('Use in Stage 4');button.setFixedSize(184,38);button.setEnabled(not self.job and n is not None)
        button.setStyleSheet('QPushButton { background:#24824b; border:1px solid #59d98b; color:white; font-weight:bold; border-radius:5px; } QPushButton:hover { background:#2b9959; }')
        for radio in results.findChildren(W.QRadioButton):radio.setEnabled(not self.job)
    def order_action(self):
        if self.job or self.order_choice.currentData() is None:return
        self.set_value(4,'target_n_max',self.order_choice.currentData())
        self.select_stage(4)
    def change_reference(self):
        if self.stage!=3 or self.reference_order.currentData() is None:return
        self.run('reference')
    def edit_orders(self):
        rows=self.table_dialog('Manual harmonic order table',['Upper frequency / Hz','Order N'],[[f'{f:g}',n] for f,n in sorted((float(f),n) for f,n in self.manual_table.items())],True)
        if rows is not None:
            try:self.manual_table={float(f):int(n) for f,n in rows}
            except ValueError:W.QMessageBox.warning(self,'Order table','Enter numeric frequencies and integer orders.')
    def edit_origins(self):
        if 2 not in self.results:return
        rows=self.table_dialog('Edit acoustic origins - Save Project to apply',['Frequency / Hz','X / mm','Y / mm','Z / mm'],[[f'{f:.2f}',*[f'{x:.2f}' for x in v['final_c']]] for f,v in sorted(self.results[2][0].items())],False)
        if rows is not None:
            try:self.run('save_origins',[(f,[float(old) if text==f'{old:.2f}' else float(text) for old,text in zip(self.results[2][0][f]['final_c'],row[1:])]) for f,row in zip(sorted(self.results[2][0]),rows)])
            except ValueError:W.QMessageBox.warning(self,'Origins','Enter numeric coordinates.')
    def table_dialog(self,title,headers,rows,add):
        d=W.QDialog(self);d.setWindowTitle(title);box=W.QVBoxLayout(d);table=W.QTableWidget(len(rows),len(headers));table.setHorizontalHeaderLabels(headers);box.addWidget(table)
        table.horizontalHeader().setSectionResizeMode(W.QHeaderView.ResizeToContents)
        for i,row in enumerate(rows):
            for j,v in enumerate(row):table.setItem(i,j,W.QTableWidgetItem(str(v)))
        if add:
            b=W.QPushButton('Add row');b.clicked.connect(lambda:table.insertRow(table.rowCount()));box.addWidget(b);b=W.QPushButton('Remove row');b.clicked.connect(lambda:table.removeRow(table.currentRow()));box.addWidget(b)
        else:
            for i in range(table.rowCount()):table.item(i,0).setFlags(table.item(i,0).flags() & ~C.Qt.ItemIsEditable)
        buttons=W.QDialogButtonBox(W.QDialogButtonBox.Save|W.QDialogButtonBox.Cancel);buttons.accepted.connect(d.accept);buttons.rejected.connect(d.reject);box.addWidget(buttons);d.resize(520,420)
        if d.exec()==W.QDialog.Accepted:return [[table.item(i,j).text() if table.item(i,j) else '' for j in range(len(headers))] for i in range(table.rowCount())]
    def stage1_resolution(self):
        return self.stage1_settings.get('fdw_oct_res',self.values[1]['fdw_oct_res'])
    def stage1_plot_settings(self):
        return dict(self.values[1],**self.stage1_settings)
    def reconcile_stage1_settings(self):
        from hals_studio.process_engine.stage1_settings import settings_differences
        visible=dict(self.values[1],fdw_rft_ms=self.values[3]['fdw_rft_ms'])
        differences=settings_differences(self.stage1_settings,visible)
        if not differences:return
        if self.choose_stage1_settings(differences):
            self._loading_rft=True
            for key,value in self.stage1_settings.items():
                stage=3 if key=='fdw_rft_ms' else 1
                if (stage,key) in self.controls:self.set_value(stage,key,value)
            self._loading_rft=False
    def choose_stage1_settings(self,differences):
        dialog=W.QMessageBox(self);dialog.setWindowTitle('Stage 1 settings differ')
        dialog.setText('The Stage 1 NPZ was processed with different settings from this project. Which settings should populate the visible fields?')
        dialog.setInformativeText('Stage 3 will use the octave resolution recorded in the NPZ whichever fields you choose. Rerun Stage 1 to apply a different resolution to the data.')
        details=[]
        for key,(project,recorded) in differences.items():
            stage=3 if key=='fdw_rft_ms' else 1
            details.append(f"{SCHEMA[str(stage)][key]['label']}: project {project}; NPZ {recorded}")
        dialog.setDetailedText('\n'.join(details))
        use_npz=dialog.addButton('Use NPZ settings',W.QMessageBox.AcceptRole)
        keep=dialog.addButton('Keep project settings',W.QMessageBox.RejectRole)
        dialog.setDefaultButton(use_npz);dialog.setEscapeButton(keep);dialog.exec()
        return dialog.clickedButton()==use_npz
    def refresh_rft_range(self,*_):
        from hals_studio.process_engine.rft_range import default_lower_hz
        previous=self._rft_default
        try:
            lower=default_lower_hz(self.values[3]['fdw_rft_ms'],self.stage1_resolution())
        except (ValueError,TypeError,OverflowError):
            self.rft_reset_button.setEnabled(False);return
        self.rft_reset_button.setEnabled(True)
        self._rft_default=lower
        if not getattr(self,'_loading_rft',False) and (previous is None or self.values[3]['freq_start_hz']==str(previous)):
            self.set_value(3,'freq_start_hz',lower)
    def set_range_from_rft(self):
        from hals_studio.process_engine.rft_range import default_lower_hz
        self.set_value(3,'freq_start_hz',default_lower_hz(self.values[3]['fdw_rft_ms'],self.stage1_resolution()))
    def coefficient_path(self):
        if not self.owner.project_path:return None
        return Path(self.owner.project_path).parent/'outputs'/'coefficients'/(self.project_name.text().strip()+'_coefficients.h5')

    def measurement_path(self):
        if not self.owner.project_path:return None
        return Path(self.owner.project_path).parent/'outputs'/(self.project_name.text().strip()+'_complex_data.npz')

    def spatial_results(self):
        return self.results[4]['spatial_data']

    def start_spatial_compute(self,result):
        from hals_studio.application.job_coordinator import jobs_for
        if jobs_for(self.owner).closing:
            return
        from hals_studio.infrastructure.process_job import SpatialErrorJob
        result['spatial_pending']=True
        job=SpatialErrorJob(self.measurement_path(),self.coefficient_path(),self.owner.pool,self)
        if not hasattr(self,'_spatial_jobs'):self._spatial_jobs=[]
        self._spatial_jobs.append(job)
        def owns_progress():
            worker=getattr(self.owner,'worker',None)
            return not self.job and not (worker and worker.isRunning()) and self.results.get(4) is result
        def progress(event):
            if owns_progress():self.display_processing_progress(event)
        job.progress.connect(progress)
        progress(dict(label='Spatial error: loading data',completed=0,total=0,remaining=0,eta=None))
        def completed(event):
            if owns_progress():self.end_processing_progress('Spatial error ready' if event['ok'] else 'Spatial error failed ? see CLI output')
            result.pop('spatial_pending',None)
            if self.results.get(4) is not result:return
            if event['ok']:result['spatial_data']=event['result']
            else:
                result['spatial_error']=event['error'];self.log.appendPlainText('Spatial error: '+event['error'])
            if self.stage==4 and self.view.currentText()=='Spatial error':self.draw()
        def cleanup():
            self._spatial_jobs.remove(job);job.deleteLater()
        job.completed.connect(completed);job.finished.connect(cleanup)
        from hals_studio.application.job_coordinator import jobs_for
        jobs_for(self.owner).track(f'spatial:{id(job)}', job)
        job.start()

    def reload_coefficients(self, force=False):
        """Make completed coefficients available; Analysis is evaluated on demand."""
        path = self.coefficient_path()
        if self.job or path is None or not path.is_file(): return False
        stamp = self.owner.analysis.coefficient_stamp(path)
        if not force and getattr(self, '_published_coeff_stamp', None) == stamp: return True
        from hals_studio.ui.project_ui import ensure_export
        from hals_studio.application.export_preview import PreviewCache
        try:
            pane = ensure_export(self.owner)
            pane.timer.stop(); pane.preview_cache = PreviewCache(); pane.result = None
            for plot in pane.custom_panes: plot.invalidate()
            self.owner.pending_session = None
            self.owner.analysis.prepare_coefficients(path)
            pane.apply_config(dict(pane.config, coeff_path=str(path)), refresh_metadata=False)
            self._published_coeff_stamp = stamp
            return True
        except Exception as exc:
            self.log.appendPlainText('Could not prepare coefficients: '+str(exc))
            return False

    def publish(self, workspace=0):
        if self.job:return
        path=self.coefficient_path()
        if path is None or not path.is_file():
            W.QMessageBox.information(self,'Coefficients','Run Stage 4 first.');return
        if self.reload_coefficients():
            if workspace == 0 and self.owner.workspace_mode.currentData() == 0:
                self.owner.analysis.activate_coefficients(path)
            else: self.owner.set_workspace(workspace)


    def save_estimated_tweeter(self):
        cfg=self.results[2][5]
        if self.tweeter_supplied or 'estimated_tweeter_mm' not in cfg:return
        x,y,z=map(float,cfg['estimated_tweeter_mm'])
        pane=self.owner.export_workspace
        grid=dict(pane.config['project_geometry'],wp_tw_r=float(np.hypot(x,y)),
                  wp_tw_phi=float(np.degrees(np.arctan2(y,x))),wp_tw_z=z)
        grid['tweeter_coordinate_source']='Stage 2 automatic grid scan and simplex'
        pane.apply_config(dict(pane.config,project_geometry=grid))
        for axis,value in zip('xyz',(x,y,z)):self.set_value(2,'tweeter_'+axis,value)
        self.tweeter_supplied=True
        if hasattr(self,'metadata_editor'):self.metadata_editor.reload()
        self.owner.save_project()

    def export_stage1_ir(self, all_files=False):
        if self.job or 1 not in self.results:return
        from hals_studio.application.stage1_export import export_ir
        f,raw,smooth,meta,fs=self.results[1]
        spectra=smooth if smooth and self.stage1_plot_settings().get('enable_smoothing') else raw
        variant='smoothed' if self.stage1_plot_settings().get('enable_smoothing') else 'fdw'
        if smooth and self.stage1_plot_settings().get('keep_raw_and_smoothed'):
            choice,ok=W.QInputDialog.getItem(self,'Export Stage 1 IR','Both curves are displayed. Choose the data to export:',
                                            ['FDW + smoothing','FDW only'],0,False)
            if not ok:return
            if choice=='FDW only':spectra=raw;variant='fdw'
        root=Path(self.owner.project_path).parent/'outputs'/'stage1_ir'
        try:
            if all_files:
                root.mkdir(parents=True,exist_ok=True)
                folder=W.QFileDialog.getExistingDirectory(self,'Export all Stage 1 IRs ('+variant+')',str(root))
                if not folder:return
                paths=[(Path(folder)/(Path(name).stem+'_'+variant+'.wav'),name) for name in spectra]
                if any(path.exists() for path,_ in paths):
                    if W.QMessageBox.question(self,'Replace exported IRs','Some exported WAV files already exist. Replace them?')!=W.QMessageBox.Yes:return
            else:
                name=self.sample.currentData()
                if name not in spectra:return
                root.mkdir(parents=True,exist_ok=True)
                filename,_=W.QFileDialog.getSaveFileName(self,'Export Stage 1 IR ('+variant+')',str(root/(Path(name).stem+'_'+variant+'.wav')),'WAV (*.wav)')
                if not filename:return
                paths=[(Path(filename),name)]
            source=Path(self.ir_folder.text()).resolve()
            if any(path.resolve() in {source/name for name in raw} for path,_ in paths):
                raise ValueError('Choose an output filename that does not overwrite an input recording.')
            for path,name in paths:export_ir(path,f,spectra[name],fs)
            self.log.appendPlainText(f'Exported {len(paths)} Stage 1 {variant} IR WAV file(s).')
        except (OSError,ValueError,RuntimeError) as exc:
            W.QMessageBox.warning(self,'Stage 1 IR export',str(exc))
