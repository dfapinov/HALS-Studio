# Application architecture

The application lives in `src/hals_studio`. Launch it with `python entry.py`,
or install it with `python -m pip install -e .` and use `python -m hals_studio`.

## Boundaries

- `ui` owns Qt widgets, workspace interaction and plotting adapters.
- `application` owns analysis control, job coordination, validated processing
  requests, stage dispatch and export orchestration.
- `process_engine` owns numerical processing. `EngineRuntime` supplies output,
  progress, cancellation and pool access explicitly, without replacing process
  working directories, standard streams or module globals.
- `analysis` contains acoustic calculations and metrics.
- `persistence` owns project/session JSON, cache envelopes, paths and preferences.
- `infrastructure` adapts application jobs to Qt threads and the shared process
  pool. `WarmPool` delegates executor lifecycle to `SessionPool`.
- `resources` contains packaged icons, images and the processing schema.

`Workspace` composes `AnalysisController`; it no longer inherits a second
application window. Controllers remain Qt-aware where queued signals are needed.
`ExportWorkspace` composes `ExportController`, which owns the export thread and
delivers results tagged with the settings generation that produced them. The
workspace handles debouncing and rejects outdated previews. The controller
releases completed threads before notifying the workspace, and cancellation
cannot queue another preview while the application is closing.
`JobCoordinator` tracks running threads, cancellation and asynchronous pool
shutdown. Completion is handled after worker termination, so closing windows or
starting dependent stages does not block the GUI waiting for a worker.

Export customization uses `ExportHooks`. Shared sweep-coordinate construction
serves preview and export. Plot implementations are normal imports with explicit
renderer dispatch, rather than source extraction or runtime replacement of
function globals.

Plot configuration and setting visibility live in `ui/plotting/plot_settings.py`.
Analysis and Export share decay defaults and editors; `ui/pane_setup.py` owns
the settings dialog. These modules do not import the main window or `PlotPane`.
`ui/view_state.py` owns view defaults, restoration and the project-local named
view collection. Complete snapshots are validated before widgets are changed,
and restored configurations are copied so editing a pane cannot alter a saved
template. `ui/plotting/export_geometry.py` draws export scenes from explicit
geometry/configuration inputs without depending on workspace controls or tables.

`ui/process_forms.py` owns schema-driven stage fields, advanced sections and
local field dependencies. It emits action signals for RFT reset and manual-order
editing; `ProcessWorkspace` retains project state and processing actions.
`ui/plotting/analysis_renderers.py` selects the Analysis content renderer and
shares lazy decay-view creation and unavailable-data presentation. `PlotPane`
retains render caching, navigation, plot titles and interaction state.

Project writes are atomic. Persisted sessions, embedded state and processing
caches have version checks. Existing HALS project/cache readers remain supported.
Preferences use the HALS/Studio namespace; no old-brand settings are migrated.
Export folders now contain `hals-studio-export.json`, a machine-readable record
of the export configuration and generated outputs.

## Regression checks

From the repository root, using the project environment:

```powershell
python -m pip install -r requirements-dev.txt
python -m ruff check src tests scripts
python -m pytest -q
python scripts/verify_pipeline.py
python scripts/verify_studio_workspace.py
```

The Windows regression workflow runs these checks. Tests cover numerical
behavior, persistence, runtime isolation, cancellation, controller boundaries,
real worker exports and Qt workspace interactions. The pipeline smoke check runs
all four processing stages with spawned workers.

Build with `build.ps1`. The bundled executable accepts `--self-test <report.json>`
to check packaged resources, Qt workspace construction, CTA metrics and spawned
worker startup without changing user settings.

The refactor was additionally compared against the original implementation:
pipeline outputs and 372 export arrays across 12 configurations matched within
numerical tolerance. Empty Process, Analysis and Export workspace screenshots
matched exactly with the live CPU label held constant. These comparisons do not
replace interactive testing of every populated plot or measurement dataset.

The next UI extraction pass added regressions for populated view switching and
session restoration, view deletion, dialog accept/cancel, isolated settings
snapshots, stale preview rejection, export cancellation/restart and closing with
an active preview. Comparison with the preceding revision found identical values
in 134 plotted arrays and 18 export scene meshes. Headless screenshots matched
for the four default Analysis views and the three Export geometry modes. These
screenshots check layout and plotted charts; they do not establish native-window
font or GPU rendering behavior, so scene meshes were compared separately.

The final named UI extractions were compared against the preceding revision:
all four Process forms and six Analysis plot states matched headless screenshots,
and 46 captured arrays were identical. Regression tests exercise form signal
routing, manual-order/regularization controls, sparse-bin error recovery,
surface/chart switching and reuse of the 3D scene between plot types.

## Remaining improvement opportunities

The named UI extractions are complete: view collection, plot settings/dialogs,
export job lifecycle, export scene drawing, Process stage forms and Analysis
renderer selection. The remaining workspace code primarily assembles widgets
and coordinates their interaction. Keep future changes within these boundaries
and extend regression coverage when changing signal order or render caching.

Large numerical routines have deliberately retained their algorithmic structure;
orchestration and runtime dependencies were extracted around them. Avoid splitting
those routines merely to reduce line counts.

`misc` holds standalone diagnostics and historical reproductions, not application
dependencies. Keep production changes and automated tests in the package and
`tests`, respectively. Ruff currently checks undefined names; broad formatting
or additional lint rules should be adopted separately from behavioral changes.

Stage 2 normal origin searches derive a cylinder from the parsed NPZ filename
coordinates (outer radius and minimum/maximum Z). `origin_scan_region.py` owns
these constraints and projects initial simplex vertices into the volume.
Manual XYZ bounds and grid resolution belong to the full grid re-scan only;
re-scans explicitly discard the cylinder constraint before refinement.

Full grid re-scan fields initially use the Cartesian box enclosing that cylinder.
StageForms tracks per-axis manual overrides; process layout state saves those
overrides so automatic defaults can follow measurement updates without replacing
user-entered bounds. Filename coordinates already loaded for Stage 1 are reused.

<!-- help-group: hidden -->
