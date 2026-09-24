"""Qt Process workspace backed exclusively by the viewer's processing snapshot."""
import json,os,pickle,sys,hashlib,subprocess
from pathlib import Path
from copy import deepcopy
import numpy as np
from PySide6 import QtCore as C,QtGui as G,QtWidgets as W
import bootstrap
from plots import Chart,style
from pyvistaqt import QtInteractor
import pyvista as pv

SCHEMA=json.loads((bootstrap.HERE/'process_schema.json').read_text(encoding='utf-8'))
VIEWS={1:['FDW results'],2:['Validation','3D coordinate cloud','3D grid scan'],3:['Order recommendations'],4:['Fit error','Condition number','Spatial error']}
MAIN={1:['fdw_rft_ms','fdw_oct_res','fdw_max_cap_ms','enable_auto_gain','target_peak_db','enable_smoothing','smoothing_oct_res'],2:['octave_resolution','tweeter_x','tweeter_y','tweeter_z'],3:['freq_end_hz'],4:['target_n_max']}

class ProcessWorkspace(W.QWidget):
    def __init__(self,owner):
        super().__init__();self.owner=owner;self.stage=1;self.job=False;self.results={};self.loaded=None;self.host=None;self.buffer='';self.plotter=None
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
        self.pages=W.QStackedWidget();box.addWidget(self.pages,1);self.controls={};self.advanced={}
        for stage in range(1,5):
            scroll=W.QScrollArea();scroll.setWidgetResizable(True);page=W.QWidget();pagebox=W.QVBoxLayout(page);main=W.QGroupBox('Main Settings');mainform=W.QFormLayout(main);pagebox.addWidget(main)
            toggle=W.QToolButton();toggle.setText('Show Advanced Settings');toggle.setCheckable(True);toggle.setToolButtonStyle(C.Qt.ToolButtonTextBesideIcon);toggle.setArrowType(C.Qt.RightArrow);pagebox.addWidget(toggle)
            advanced=W.QGroupBox('Advanced Settings');advancedform=W.QFormLayout(advanced);pagebox.addWidget(advanced);advanced.hide();self.advanced[stage]=(toggle,advanced)
            def expand(checked,b=toggle,g=advanced):g.setVisible(checked);b.setText('Hide Advanced Settings' if checked else 'Show Advanced Settings');b.setArrowType(C.Qt.DownArrow if checked else C.Qt.RightArrow)
            toggle.toggled.connect(expand);form=W.QFormLayout();pagebox.addLayout(form);pagebox.addStretch();scroll.setWidget(page);self.pages.addWidget(scroll)
            for key,spec in SCHEMA[str(stage)].items():
                value=self.values[stage][key]
                if isinstance(value,bool):control=W.QCheckBox();control.setChecked(value);control.toggled.connect(lambda v,s=stage,k=key:self.values[s].update({k:v}))
                else:control=W.QLineEdit(str(value));control.textChanged.connect(lambda v,s=stage,k=key:self.values[s].update({k:v}))
                control.setToolTip(spec['help']);caption=W.QLabel(spec['label']);caption.setWordWrap(False)
                if isinstance(control,W.QLineEdit):control.setFixedWidth(145 if key.endswith('bounds') or key=='test_order_range' else 105)
                (mainform if key in MAIN[stage] else advancedform).addRow(caption,control);self.controls[stage,key]=control
            if stage==1:self.form_button(form,'Reflection-free time calculator',self.rft_calculator)
            if stage==3:
                self.order_choice=W.QComboBox();self.order_choice.setSizeAdjustPolicy(W.QComboBox.AdjustToContents)
                self.reference_order=W.QComboBox();self.reference_order.setSizeAdjustPolicy(W.QComboBox.AdjustToContents);self.reference_order.currentIndexChanged.connect(self.change_reference)
            if stage==4:
                control=self.controls[4,'use_manual_table'];caption=advancedform.labelForField(control);advancedform.removeWidget(control);advancedform.removeWidget(caption);caption.deleteLater();control.setText('Use manual order table');advancedform.addRow(control)
                edit=W.QPushButton('Edit manual order table');edit.setSizePolicy(W.QSizePolicy.Fixed,W.QSizePolicy.Fixed);edit.clicked.connect(self.edit_orders);advancedform.addRow(edit)
        actions=W.QHBoxLayout();box.addLayout(actions);self.run_button=W.QPushButton('Run Stage 1');self.run_button.setObjectName('primary');self.run_button.clicked.connect(lambda:self.run());actions.addWidget(self.run_button)
        self.cancel_button=W.QPushButton('Cancel');self.cancel_button.setEnabled(False);self.cancel_button.clicked.connect(lambda:self.cancel());actions.addWidget(self.cancel_button)
        self.split.addWidget(left);self.right=W.QSplitter(C.Qt.Vertical);self.split.addWidget(self.right)
        result=W.QWidget();resultbox=W.QVBoxLayout(result);resultbox.setContentsMargins(5,5,5,5);bar=W.QHBoxLayout();bar.setContentsMargins(0,0,0,0)
        self.result_bar=W.QWidget();self.result_bar.setLayout(bar);resultbox.addWidget(self.result_bar);self.main_result_bar=bar
        self.plot_label=W.QLabel('Plot type');bar.addWidget(self.plot_label);self.view=W.QComboBox();self.view.setSizeAdjustPolicy(W.QComboBox.AdjustToContents);self.view.setMaximumWidth(240);self.view.currentTextChanged.connect(self.draw);bar.addWidget(self.view)
        self.sample_label=W.QLabel('File');bar.addWidget(self.sample_label);self.sample=W.QComboBox();self.sample.setFixedWidth(210);self.sample.currentIndexChanged.connect(self.draw);bar.addWidget(self.sample)
        self.frequency_label=W.QLabel('Frequency');bar.addWidget(self.frequency_label)
        self.frequency=W.QDoubleSpinBox();self.frequency.setRange(.1,100000);self.frequency.setValue(1000);self.frequency.setSuffix(' Hz');self.frequency.setKeyboardTracking(False);self.frequency.valueChanged.connect(self.draw);bar.addWidget(self.frequency)
        self.plane=W.QComboBox();self.plane.addItems(['XY','XZ','YZ']);self.plane.currentTextChanged.connect(self.draw);bar.addWidget(self.plane)
        self.slice_position=W.QSlider(C.Qt.Horizontal);self.slice_position.setFixedWidth(130);self.slice_position.valueChanged.connect(self.draw);bar.addWidget(self.slice_position);self.slice_label=W.QLabel();self.slice_label.setMinimumWidth(85);bar.addWidget(self.slice_label)
        self.error_units=W.QComboBox();self.error_units.addItems(['Error / dB','Error / percent']);self.error_units.currentTextChanged.connect(self.draw);bar.addWidget(self.error_units)
        self.threshold=W.QDoubleSpinBox();self.threshold.setRange(-120,0);self.threshold.setValue(-30);self.threshold.setPrefix('Floor ');self.threshold.setSuffix(' dB');self.threshold.setToolTip('Exclude measurement points below this level relative to the strongest point at this frequency.');self.threshold.valueChanged.connect(self.draw);bar.addWidget(self.threshold)
        self.previous=W.QPushButton('< Previous');self.previous.clicked.connect(lambda:self.sample.setCurrentIndex((self.sample.currentIndex()-1)%max(1,self.sample.count())));bar.addWidget(self.previous)
        self.next=W.QPushButton('Next >');self.next.clicked.connect(lambda:self.sample.setCurrentIndex((self.sample.currentIndex()+1)%max(1,self.sample.count())));bar.addWidget(self.next)

        bar.addStretch();self.save_image_button=W.QPushButton('Save image');self.save_image_button.clicked.connect(self.save_image);bar.addWidget(self.save_image_button)
        self.stage2_tools=W.QWidget();s2=W.QHBoxLayout(self.stage2_tools);s2.setContentsMargins(0,0,0,0);rescan=W.QPushButton('Full grid rescan of selected frequency');rescan.clicked.connect(lambda:self.run('rescan'));s2.addWidget(rescan);s2.addWidget(W.QLabel('Frequency'));self.rescan_frequency=W.QComboBox();self.rescan_frequency.setFixedWidth(145);self.rescan_frequency.currentIndexChanged.connect(self.sample.setCurrentIndex);self.sample.currentIndexChanged.connect(self.rescan_frequency.setCurrentIndex);s2.addWidget(self.rescan_frequency);edit=W.QPushButton('Edit coordinate table');edit.clicked.connect(self.edit_origins);s2.addWidget(edit);s2.addStretch();bar.insertWidget(2,self.stage2_tools)
        self.stage3_tools=W.QWidget();s3=W.QHBoxLayout(self.stage3_tools);s3.setContentsMargins(0,0,0,0);s3.addWidget(W.QLabel('Sound power reference'));self.reference_order.setMaximumWidth(200);s3.addWidget(self.reference_order);s3.addStretch();bar.insertWidget(0,self.stage3_tools)
        self.order_choice.hide()

        self.stack=W.QStackedWidget();resultbox.addWidget(self.stack,1);self.chart=Chart(toolbar=False);self.stack.addWidget(self.chart)
        from process_results import Results
        self.original_results=Results();self.stack.addWidget(self.original_results)
        self.stage4_navigation=W.QWidget();navigation=W.QHBoxLayout(self.stage4_navigation);navigation.setContentsMargins(0,0,0,0)
        navigation.addStretch()
        self.analysis_button=W.QPushButton('Analysis');self.analysis_button.clicked.connect(lambda:self.publish(0));navigation.addWidget(self.analysis_button)
        self.export_button=W.QPushButton('Export');self.export_button.clicked.connect(lambda:self.publish(1));navigation.addWidget(self.export_button)
        resultbox.addWidget(self.stage4_navigation)
        self.summary=W.QLabel('Open a HALS project or create one to begin.');self.summary.setWordWrap(True);resultbox.addWidget(self.summary);self.right.addWidget(result)
        cli=W.QWidget();cl=W.QVBoxLayout(cli);cl.setContentsMargins(5,5,5,5);cr=W.QHBoxLayout();cr.addWidget(W.QLabel('CLI OUTPUT'));cr.addStretch();b=W.QPushButton('Clear');b.clicked.connect(lambda:self.log.clear());cr.addWidget(b);b=W.QPushButton('Save log');b.clicked.connect(self.save_log);cr.addWidget(b);cl.addLayout(cr)
        self.log=W.QPlainTextEdit();self.log.setReadOnly(True);self.log.setMaximumBlockCount(30000);cl.addWidget(self.log);self.right.addWidget(cli)
        self.split.setSizes([420,980]);self.right.setSizes([650,280]);self.select_stage(1)
        self.controls[1,'enable_auto_gain'].toggled.connect(self.controls[1,'target_peak_db'].setEnabled);self.controls[1,'target_peak_db'].setEnabled(self.controls[1,'enable_auto_gain'].isChecked())
        for key in ('noise_floor_start_db','noise_floor_max_db','max_lambda'):
            control=self.controls[4,key];form=control.parentWidget().layout();caption=form.labelForField(control)
            def show_regularization(on,c=control,label=caption):c.setVisible(on);label.setVisible(on)
            self.controls[4,'enable_regularization'].toggled.connect(show_regularization);show_regularization(self.controls[4,'enable_regularization'].isChecked())
    @staticmethod
    def form_button(form,title,callback):
        b=W.QPushButton(title);b.clicked.connect(callback);form.addRow(b)
    def select_stage(self,stage):
        self.stage4_navigation.setVisible(stage==4)
        self.metadata_button.setChecked(stage==0);self.speed_settings.setVisible(stage==0);self.pages.setVisible(stage!=0);self.run_button.setVisible(stage!=0);self.cancel_button.setVisible(stage!=0)
        self.result_bar.setVisible(stage!=0);self.stage2_tools.setVisible(stage==2);self.stage3_tools.setVisible(stage==3)
        if stage==0:
            self.stage=0
            for b in self.stage_buttons:b.setChecked(False)
            if not hasattr(self,'metadata_editor'):
                from project_ui import ensure_export
                from project_metadata import MetadataEditor
                self.metadata_editor=MetadataEditor(ensure_export(self.owner));self.metadata_editor.save_button.clicked.disconnect();self.metadata_editor.save_button.clicked.connect(self.owner.save_project);self.metadata_editor.table.itemChanged.connect(self.metadata_changed);self.left_box.insertWidget(1,self.metadata_editor,1);self.metadata_editor.save_button.hide()
            self.metadata_editor.reload();self.metadata_editor.show();self.show_splash();self.summary.setText('Double-click coordinates to edit. Save Project writes your changes.');return
        if hasattr(self,'metadata_editor'):self.metadata_editor.hide()
        self.stage=stage;self.pages.setCurrentIndex(stage-1)
        for i,b in enumerate(self.stage_buttons,1):b.setChecked(i==stage)
        self.run_button.setText(f'Run Stage {stage}');self.view.blockSignals(True);self.view.clear();self.view.addItems(VIEWS[stage]);self.view.blockSignals(False);self.update_selectors();self.draw()
    def show_splash(self):
        if not hasattr(self,'splash'):
            self.splash=W.QLabel();self.splash.setAlignment(C.Qt.AlignCenter);self.splash.setMinimumSize(1,1);self.stack.addWidget(self.splash)
        pix=G.QPixmap(str(bootstrap.HERE/'assets/hals_splash.png'))
        self.splash.setPixmap(pix.scaled(max(100,self.stack.width()-30),max(100,self.stack.height()-30),C.Qt.KeepAspectRatio,C.Qt.SmoothTransformation));self.stack.setCurrentWidget(self.splash)
    def metadata_changed(self,*_):
        if self.metadata_editor.filling or self.metadata_editor.pending:return
        self.owner.export_workspace.metadata_editor.reload()
        from export_engine import waypoint
        try:
            xyz=waypoint(self.owner.export_workspace.config['project_geometry'],'tw')*1000
            for axis,value in zip('xyz',xyz):self.set_value(2,'tweeter_'+axis,round(float(value),3))
        except (KeyError,ValueError,TypeError):pass
    def set_value(self,stage,key,value):
        control=self.controls[stage,key]
        if isinstance(control,W.QCheckBox):control.setChecked(bool(value))
        else:control.setText(str(value))
    def adopt_project(self,force=False):
        path=self.owner.project_path
        if not path or (self.loaded==path and not force):return
        data=json.loads(Path(path).read_text(encoding='utf-8-sig'));self.loaded=path;self.results={}
        self.project_name.setText(data.get('project_name',Path(path).stem.replace('_project','')));self.owner.dataset_label.setText(self.project_name.text())
        for stage in range(1,5):
            for key,spec in SCHEMA[str(stage)].items():self.set_value(stage,key,data.get(f'stage{stage}_vars',{}).get(key,spec['default']))
        self.manual_table=data.get('stage4_manual_table',self.manual_table)
        glob=data.get('global_vars',{});self.manual_speed.setChecked(bool(glob.get('enable_manual_speed_of_sound',False)));self.speed.setValue(float(glob.get('speed_of_sound',343)))
        folder=Path(path).parent;choices=[folder/n for n in ('recordings','Recordings','measurement_set','input_irs','input_irs_synth')]+[folder]
        self.ir_folder.setText(str(next((p for p in choices if p.is_dir() and next(p.glob('*.wav'),None)),folder)))
        grid=data.get('grid_vars',{})
        if all(grid.get('wp_tw_'+k) not in (None,'') for k in ('r','phi','z')):
            r,phi,z=[float(grid['wp_tw_'+k]) for k in ('r','phi','z')]
            for key,val in zip('xyz',(r*np.cos(np.deg2rad(phi)),r*np.sin(np.deg2rad(phi)),z)):self.set_value(2,'tweeter_'+key,round(val,3))
        for stage in range(1,5):
            if self.cache(stage).exists():
                with open(self.cache(stage),'rb') as stream:self.results[stage]=pickle.load(stream)
        state=data.get('hals_studio', data.get('hals_viewer',{})).get('session',{}).get('process_layout') or {}
        if state.get('input_ir_folder'):self.ir_folder.setText(state['input_ir_folder'])
        self.split.setSizes(state.get('split',[420,980]));self.right.setSizes(state.get('right',[650,280]));self.select_stage(state.get('stage',1));self.start_host()
    def layout_state(self):
        return dict(stage=self.stage,split=self.split.sizes(),right=self.right.sizes(),input_ir_folder=self.ir_folder.text())
    def project_payload(self):
        return dict(project_name=self.project_name.text().strip(),**{f'stage{s}_vars':deepcopy(v) for s,v in self.values.items()},stage4_manual_table=self.manual_table,
            global_vars=dict(enable_manual_speed_of_sound=self.manual_speed.isChecked(),speed_of_sound=str(self.speed.value())))
    def cache(self,stage):
        digest=hashlib.sha256(str(self.owner.project_path).encode()).hexdigest()[:20]
        return bootstrap.CACHE_ROOT/digest/f'stage{stage}.pkl'
    def new_project(self):
        if self.job:return
        path,_=W.QFileDialog.getSaveFileName(self,'New HALS project','project.json','HALS project (*.json)')
        if not path:return
        from project_ui import ensure_export
        from export_engine import DEFAULT_EXPORT
        ensure_export(self.owner).apply_config(deepcopy(DEFAULT_EXPORT))
        self.owner.source_path=None;self.owner.source_options=None
        self.owner.project_path=path;self.owner.project_path_field.setText(str(Path(path).parent));self.loaded=path;self.results={};self.project_name.setText(Path(path).stem.replace('_project',''));self.ir_folder.setText(str(Path(path).parent));self.owner.save_project();self.start_host();self.select_stage(1)
    def browse_ir(self):
        path=W.QFileDialog.getExistingDirectory(self,'Input IR recordings',self.ir_folder.text())
        if path:self.ir_folder.setText(path)
    def start_host(self):
        self.owner.pool.start()
    def run(self,action='run',edits=None):
        if self.stage==0:return
        if self.job:return
        if not self.owner.project_path:W.QMessageBox.information(self,'Project required','Open or create a project first.');return
        if self.owner.worker and self.owner.worker.isRunning():W.QMessageBox.information(self,'Busy','Wait for Analysis reconstruction to finish.');return
        if self.owner.export_workspace and self.owner.export_workspace.job:W.QMessageBox.information(self,'Busy','Wait for Export evaluation to finish.');return
        name=self.project_name.text().strip()
        if self.stage==4 and not self.values[4]['use_manual_table']:
            try:
                if int(self.values[4]['target_n_max'])<2:raise ValueError()
            except ValueError:W.QMessageBox.warning(self,'Harmonic order','The solver requires a maximum order of at least 2 without a manual order table.');return
        if not name or Path(name).name!=name or any(c in name for c in '<>:"/\\|?*'):W.QMessageBox.warning(self,'Project name','Use a valid filename without path separators.');return
        request=dict(stage=self.stage,settings=deepcopy(self.values[self.stage]),folder=str(Path(self.owner.project_path).parent),name=name,ir_folder=self.ir_folder.text(),cache=str(self.cache(self.stage)),manual_table=self.manual_table,speed=self.speed.value(),manual_speed=self.manual_speed.isChecked(),action=action)
        if edits:request['edits']=edits
        if action=='reference':request['reference']=self.reference_order.currentData()['n']
        if action=='load_origins':request['origin_cache']=self.origin_cache_path
        if action=='rescan':
            if 2 not in self.results:return
            request['rescan']=[float(self.sample.currentData())]
        self.active_request=request;self._cli_line='';self.start_host();self.job=True;self.active_stage=self.stage;self.run_button.setEnabled(False);self.cancel_button.setEnabled(True)
        self.log.appendPlainText(f'\nStage {self.stage} - {action} - {name}\n')
        from process_job import ProcessJob
        self.host=ProcessJob(request,self.owner.pool,self);self.host.message.connect(self.append_output);self.host.completed.connect(self.finished);self.host.start();self.summary.setText(f'Stage {self.stage} running - inspect CLI output below')
    def append_output(self,text):
        import re
        text=re.sub(r'\x1b\[[0-9;]*[A-Za-z]','',text)
        cursor=self.log.textCursor();cursor.movePosition(G.QTextCursor.End)
        for token in re.split(r'([\r\n])',text):
            if token=='\r':self._cli_line=''
            elif token=='\n':cursor.insertBlock();self._cli_line=''
            elif token:
                self._cli_line=getattr(self,'_cli_line','')+token
                cursor.movePosition(G.QTextCursor.StartOfBlock,G.QTextCursor.KeepAnchor);cursor.insertText(self._cli_line)
        self.log.setTextCursor(cursor);self.log.ensureCursorVisible()
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
    def read_output(self):
        text=bytes(self.host.readAllStandardOutput()).decode('utf-8',errors='replace');self.buffer+=text
        while '\n' in self.buffer:
            line,self.buffer=self.buffer.split('\n',1)
            if line.startswith('@@HALS@@'):self.finished(json.loads(line[8:]))
            else:
                import re
                self.log.appendPlainText(re.sub(r'\x1b\[[0-9;]*[A-Za-z]','',line.rstrip('\r').replace('\r','\n')))
    def finished(self,event):
        if self.host:self.host.wait()
        self.job=False;self.run_button.setEnabled(True);self.cancel_button.setEnabled(False)
        if not event['ok']:self.summary.setText('Processing failed - see CLI output');return
        stage=int(event['stage'])
        with open(event['cache'],'rb') as stream:self.results[stage]=pickle.load(stream)
        if stage==1:
            meta=self.results[1][3];transition=max((float(v.get('f_trans',0)) for v in meta.values()),default=0)
            if transition:self.set_value(3,'freq_start_hz',np.ceil(transition/1000)*1000)
        if stage==3 and self.results[3].get('below_rft'):self.set_value(3,'freq_start_hz',self.results[3]['test_band_hz'][0])
        self.select_stage(stage)
        if getattr(self,'active_request',{}).get('action')=='rescan':
            index=self.sample.findData(self.active_request['rescan'][0]);self.sample.setCurrentIndex(index);self.view.setCurrentText('3D grid scan')
        self.autosave_plots();self._cli_line='';self.log.appendPlainText(f'Stage {stage} complete. Results saved.');self.summary.setText(f'Stage {stage} completed - {Path(self.owner.project_path).parent / "outputs"}')
        if stage==4:self.reload_coefficients(force=True)
    def host_finished(self,*_):
        if self.job:self.job=False;self.run_button.setEnabled(True);self.cancel_button.setEnabled(False);self.summary.setText('Processing stopped. See CLI output.')
    def cancel(self,restart=True):
        if self.host and self.host.isRunning():
            self.owner.pool.close();self.host.wait()
            from worker_pool import WarmPool
            if restart:self.owner.pool=WarmPool(int(self.owner.settings.value('worker_count',0)) or None);self.owner.pool.start()
        self.job=False;self.run_button.setEnabled(True);self.cancel_button.setEnabled(False)
    def shutdown(self):self.cancel(restart=False)
    def load_existing(self):
        if not self.owner.project_path:return
        root=Path(self.owner.project_path).parent;name=self.project_name.text()
        try:
            if self.cache(self.stage).exists():
                with open(self.cache(self.stage),'rb') as stream:self.results[self.stage]=pickle.load(stream)
            elif self.stage==1:
                with np.load(root/'outputs'/f'{name}_complex_data.npz',allow_pickle=True) as d:self.results[1]=(d['freqs'],d['data'].item(),None,d['meta'].item() if 'meta' in d else {})
            elif self.stage==2:
                path,_=W.QFileDialog.getOpenFileName(self,'Open HALS origin cache',str(root/'outputs'),'HALS origin cache (*.pkl)')
                if path:self.origin_cache_path=path;self.run('load_origins')
                return
            elif self.stage==4:
                import h5py
                with h5py.File(root/'outputs'/'coefficients'/f'{name}_coefficients.h5') as f:self.results[4]={k:f[k][()] for k in f}
            else:raise ValueError('Run this stage to obtain its full diagnostics.')
            self.update_selectors();self.draw()
        except Exception as e:W.QMessageBox.warning(self,'Results',str(e))
    def update_selectors(self):
        self.rescan_frequency.blockSignals(True);self.rescan_frequency.clear()
        self.sample.blockSignals(True);self.sample.clear();r=self.results.get(self.stage)
        if r is not None:
            if self.stage==1:
                for name in sorted(r[1]):self.sample.addItem(name,name)
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
                recommended=r.get('options',{}).get(r.get('recommended_key'),{}).get('n')
                index=self.order_choice.findData(recommended)
                if index>=0:self.order_choice.setCurrentIndex(index)
                self.reference_order.blockSignals(False)
            elif self.stage==4:
                for i in range(len(r.get('coords_sph',[]))):self.sample.addItem(f'Point {i+1}',i)
        if self.stage==2:
            for i in range(self.sample.count()):self.rescan_frequency.addItem(self.sample.itemText(i),self.sample.itemData(i))
        self.rescan_frequency.blockSignals(False);self.sample.blockSignals(False)
    def draw(self,*_):
        if self.stage==0:return
        self.last_plot_error=None
        view=self.view.currentText()
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
        from viewer_theme import colour
        if scalars is None:self.plotter.add_points(xyz,color='#599bda',point_size=10,render_points_as_spheres=True)
        else:self.plotter.add_mesh(pv.PolyData(xyz),scalars=np.asarray(scalars),cmap='PColor',point_size=10,render_points_as_spheres=True,scalar_bar_args={'title':title,'color':colour('#b8d6e8'),'title_font_size':12,'label_font_size':10})
        from viewer_theme import scene_theme
        scene_theme(self.plotter);self.plotter.add_axes();self.scene_bounds();self.plotter.view_isometric();self.plotter.reset_camera();self.plotter.render()
    def scene_bounds(self,bounds=None):
        from viewer_theme import colour
        unit='mm' if self.stage==2 or self.view.currentText()=='Origins / 3D' else 'm'
        self.plotter.show_bounds(bounds=bounds,grid='back',location='outer',all_edges=False,color=colour('#b8d6e8'),font_size=10,xtitle='X / '+unit,ytitle='Y / '+unit,ztitle='Z / '+unit)
    def reset(self):
        if self.plotter and self.stack.currentWidget() is self.plotter.interactor:self.plotter.reset_camera();self.plotter.render()
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
            else:self.original_results.fig.savefig(path,dpi=180)
        elif self.plotter and self.stack.currentWidget() is self.plotter.interactor:self.plotter.screenshot(str(path))
        else:self.chart.fig.savefig(path,dpi=180)
    def save_image(self):
        path,_=W.QFileDialog.getSaveFileName(self,'Save result image',str(self.image_path()),'PNG (*.png)')
        if path:
            if not Path(path).suffix:path+='.png'
            self.write_image(path)
    def autosave_plots(self):
        # The Tk result windows performed these saves; the Qt workspace owns them now.
        kinds={1:['FDW results'],2:['Validation'],3:['Order recommendations'],4:['Fit error','Condition number']}[self.stage]
        selected=self.view.currentText()
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
            self.view.setCurrentText(selected);self.view.blockSignals(False);self.draw()
    def save_log(self):
        path,_=W.QFileDialog.getSaveFileName(self,'Save processing log','','Text (*.txt)')
        if path:Path(path).write_text(self.log.toPlainText(),encoding='utf-8')
    def use_order(self):
        n=self.order_choice.currentData()
        if n is not None:self.set_value(4,'target_n_max',n);self.select_stage(4)
    def change_reference(self):
        if self.stage!=3 or self.reference_order.currentData() is None:return
        self.run('reference')
    def edit_orders(self):
        rows=self.table_dialog('Manual harmonic order table',['Upper frequency / Hz','Order N'],sorted(self.manual_table.items()),True)
        if rows is not None:
            try:self.manual_table={float(f):int(n) for f,n in rows}
            except ValueError:W.QMessageBox.warning(self,'Order table','Enter numeric frequencies and integer orders.')
    def edit_origins(self):
        if 2 not in self.results:return
        rows=self.table_dialog('Edit acoustic origins - save applies to Stage 1 data',['Frequency / Hz','X / mm','Y / mm','Z / mm'],[[f'{f:.2f}',*[f'{x:.2f}' for x in v['final_c']]] for f,v in sorted(self.results[2][0].items())],False)
        if rows is not None:
            try:self.run('save_origins',[(f,[float(old) if text==f'{old:.2f}' else float(text) for old,text in zip(self.results[2][0][f]['final_c'],row[1:])]) for f,row in zip(sorted(self.results[2][0]),rows)])
            except ValueError:W.QMessageBox.warning(self,'Origins','Enter numeric coordinates.')
    def table_dialog(self,title,headers,rows,add):
        d=W.QDialog(self);d.setWindowTitle(title);box=W.QVBoxLayout(d);table=W.QTableWidget(len(rows),len(headers));table.setHorizontalHeaderLabels(headers);box.addWidget(table)
        for i,row in enumerate(rows):
            for j,v in enumerate(row):table.setItem(i,j,W.QTableWidgetItem(str(v)))
        if add:
            b=W.QPushButton('Add row');b.clicked.connect(lambda:table.insertRow(table.rowCount()));box.addWidget(b);b=W.QPushButton('Remove row');b.clicked.connect(lambda:table.removeRow(table.currentRow()));box.addWidget(b)
        else:
            for i in range(table.rowCount()):table.item(i,0).setFlags(table.item(i,0).flags() & ~C.Qt.ItemIsEditable)
        buttons=W.QDialogButtonBox(W.QDialogButtonBox.Save|W.QDialogButtonBox.Cancel);buttons.accepted.connect(d.accept);buttons.rejected.connect(d.reject);box.addWidget(buttons);d.resize(520,420)
        if d.exec()==W.QDialog.Accepted:return [[table.item(i,j).text() if table.item(i,j) else '' for j in range(len(headers))] for i in range(table.rowCount())]
    def rft_calculator(self):
        from rft_dialog import RFTDialog
        dialog=RFTDialog(self,self.speed.value())
        if dialog.exec()==W.QDialog.Accepted:self.set_value(1,'fdw_rft_ms',round(dialog.result['rft_ms'],4))
    def coefficient_path(self):
        if not self.owner.project_path:return None
        return Path(self.owner.project_path).parent/'outputs'/'coefficients'/(self.project_name.text().strip()+'_coefficients.h5')

    def reload_coefficients(self, force=False):
        path=self.coefficient_path()
        if self.job or path is None or not path.is_file():return False
        stat=path.stat();stamp=(str(path.resolve()),stat.st_mtime_ns,stat.st_size)
        if self.owner.worker and self.owner.worker.isRunning():
            return getattr(self,'_loading_coeff_stamp',None)==stamp
        if not force and getattr(self,'_published_coeff_stamp',None)==stamp:return True
        from project_ui import ensure_export
        from export_preview import PreviewCache
        from app import Atlas
        try:
            pane=ensure_export(self.owner)
            # Stage 4 can replace the same filename. Discard open evaluation
            # sessions and plotted-result caches rather than relying on its path.
            pane.timer.stop();pane.preview_cache=PreviewCache();pane.result=None
            pane.response_panel.key=None;pane.ir_panel.key=None
            options=deepcopy(self.owner.source_options) if self.owner.source_path and Path(self.owner.source_path).resolve()==path.resolve() else {}
            self.owner.pending_session=None
            self._published_coeff_stamp=None;self._loading_coeff_stamp=stamp
            Atlas.open_path(self.owner,path,options=options or {})
            pane.apply_config(dict(pane.config,coeff_path=str(path)),refresh_metadata=False)
            worker=self.owner.worker
            if worker is None:
                self._loading_coeff_stamp=None;return False
            def loaded(_):
                if not self.owner.job_cancelled:
                    self._published_coeff_stamp=stamp
                    self.summary.setText('Stage 4 complete. Coefficients reloaded ? ready for Analysis or Export.')
            def finished():
                self._loading_coeff_stamp=None
                if self.owner.workspace_mode.currentData()==1:pane.preview_if_live()
            def failed(message):
                self.summary.setText('Stage 4 complete; coefficient reload failed. See CLI output.')
                self.log.appendPlainText('Coefficient reload failed: '+str(message))
            worker.loaded.connect(loaded);worker.failed.connect(failed);worker.finished.connect(finished)
            self.summary.setText('Stage 4 complete. Reloading coefficients for Analysis and Export...')
            return True
        except Exception as exc:
            self._loading_coeff_stamp=None
            self.log.appendPlainText('Coefficient reload failed: '+str(exc))
            self.summary.setText('Stage 4 complete; coefficient reload failed. See CLI output.')
            return False

    def publish(self, workspace=0):
        if self.job:return
        path=self.coefficient_path()
        if path is None or not path.is_file():
            W.QMessageBox.information(self,'Coefficients','Run Stage 4 first.');return
        if self.reload_coefficients():self.owner.set_workspace(workspace)
