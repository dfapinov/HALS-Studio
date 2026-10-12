# HALS misc tools

These utilities and historical validation scripts were copied from HALS Post. They remain available in both repositories. The top-level tools use the `hals_studio.process_engine` package under `src/`.

Run from the repository with `.venv/Scripts/python.exe misc/<script>.py`. Some scripts open Tk dialogs; others take arguments or expect a grid/measurement file selected or configured by the user. Synthetic recordings and generated export/report data are not committed. Historical system tests may require external measurements. Optional report packages are in `requirements-reports.txt`.

`scripts/verify_pipeline.py` is the portable processing smoke test; it generates its own inputs instead of relying on the old checkout's datasets.
