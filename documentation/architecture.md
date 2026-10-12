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
`JobCoordinator` tracks running threads, cancellation and asynchronous pool
shutdown. Completion is handled after worker termination, so closing windows or
starting dependent stages does not block the GUI waiting for a worker.

Export customization uses `ExportHooks`. Shared sweep-coordinate construction
serves preview and export. Plot implementations are normal imports with explicit
renderer dispatch, rather than source extraction or runtime replacement of
function globals.

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

## Remaining improvement opportunities

The workspace and pane classes still contain substantial widget construction and
interaction code. Further extraction should follow individual features, with
populated-workspace regression coverage before changing signal wiring. Large
numerical routines have deliberately retained their algorithmic structure;
orchestration and runtime dependencies were extracted around them. Avoid splitting
those routines merely to reduce line counts.

`misc` holds standalone diagnostics and historical reproductions, not application
dependencies. Keep production changes and automated tests in the package and
`tests`, respectively. Ruff currently checks undefined names; broad formatting
or additional lint rules should be adopted separately from behavioral changes.
