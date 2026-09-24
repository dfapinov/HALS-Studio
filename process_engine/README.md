# HALS Studio processing engine

This is the single home for the processing stages and shared acoustic
calculation modules used by the Process, Analysis, and Export workspaces.
`stage5_extract_pressures.py` owns the shared CTA-2034 metrics and Stage 5
export implementation; the workspaces import those same functions.

`fdw_smoothing_core.py` is the maintained implementation used by Stage 1,
including the sliding high-frequency smoothing kernel. `session_pool.py` is
the Studio worker-pool adapter. Do not add a second engine directory for
shared processing helpers.

The snapshot manifests record upstream HALS Post provenance for imported
modules. They are historical provenance only; Studio's files here are the
runtime source of truth.
