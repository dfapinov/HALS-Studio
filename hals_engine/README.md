# HALS Studio Stage 5 engines

These engine files originated in HALS Post and now belong to HALS Studio. Original license headers and snapshot provenance are retained. Later Studio fixes mean the source is no longer an unmodified snapshot.

Analysis and Export share `calculate_cta2034_energy_metrics` in `stage5_extract_pressures.py`. `cta_coordinates.py` supplies their common angular sampling. The processing snapshot delegates its CTA adapter here too. See `../documentation/cta2034_methodology.md`.

`bootstrap.py` loads Studio's real processing pool before the legacy Stage 5 pool shim can be imported. All application workspaces share Studio's worker pool; no sibling checkout is imported at runtime.
