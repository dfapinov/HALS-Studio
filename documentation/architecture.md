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

<!-- help-group: hidden -->

## Leave-one-out origin search

The application stage adapter selects leave-one-out prediction for new Stage 2
runs. Numerical prediction fitting lives in `process_engine/press_fitting.py`;
it uses the same `harmonic_basis.build_field_matrix` as coefficient solving,
condition checks and export pressure reconstruction. `build_she_matrix` remains
the dual-field adapter for existing solver callers. Export can request just the
internal or external columns without constructing the unused field.
`press_origins.py` owns the bidirectional search, LF comparisons and saved-plan
validation. Stage 4 consumes that plan and uses the existing condition-growth
optimizer and final solver. Existing `press_*` NPZ keys remain stable for saved
project compatibility; these names are not UI settings.

`origin_workers.py` schedules complete directional sweeps on the app-owned pool.
Each direction remains sequential across frequency and retains its continuation
seed. LF comparisons are independent anchor tasks on that same pool. Numerical
sweep and comparison functions are shared with the standalone thread fallback.
A parent-side coordinator forwards progress/log messages and a spawn-safe
cancellation signal is checked within simplex evaluations. Cancelling drains
this operation before disposing of its communication proxies, keeping the
shared pool available to later stages. The final Stage 4 solve continues to
use the existing pool path. No worker recursively submits work to that pool.

The IR capture review utility is a separate application in
`tools/ir_capture_review`, with its own dependencies, launcher, documentation
and tests. Its numerical/file-review backend does not import Studio or Tkinter;
the Tkinter frontend handles presentation and user confirmation. Studio does
not import this utility. Renamed recordings enter Studio through a fresh Stage 1
import, rather than through a second blacklist configuration.

The added production tests cover numerical equivalence, prediction of omitted
measurements, order selection, saved-plan integrity and end-to-end processing.
UI wording and configurable defaults are not release contracts.
