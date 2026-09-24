# HALS Studio repository split

HALS Studio was extracted from the `hals_viewer` application in HALS Post. The application, its owned engine copies, runtime assets, numerical tests and installer recipes are independent of the HALS Post checkout. HALS Post source remains unchanged by the split.

The documentation and misc script sources were copied, so both repositories retain them. Some historical examples describe HALS Post or require measurement data supplied separately; generated recordings, caches and report outputs are not bundled as fixtures. Optional Word/PDF report dependencies are listed in `misc/requirements-reports.txt`.

Earlier projects store UI state under `hals_viewer`; Studio reads that key as a fallback and writes `hals_studio` when saving. Other processing metadata is preserved. Preferences migrate once from `HALS/Atlas` to `HALS/Studio`. The installer uses its own application ID.

`hals_engine/snapshot.json` and `process_engine/snapshot.json` record the original upstream snapshot provenance. These files do not assert that today's Studio engines are byte-identical to HALS Post: Studio has since added its own fixes. The shared CTA implementation is in `hals_engine/stage5_extract_pressures.py`.

The split archives obsolete builds, experiment outputs and legacy manual verification scripts outside the new source repository. No remote or automated release workflow is created by the migration.
