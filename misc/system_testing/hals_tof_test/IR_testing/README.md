# HALS IR validation

`HALS_IR_Validation_version2.docx` is the finished editable report. It contains the plots and results; the PNG files are not stored separately.

## Reproduce the analysis

Run these commands from this directory in a Python environment with NumPy, SciPy, SoundFile and Matplotlib installed:

```powershell
python analyze_ir.py
python analyze_edited_report.py
python analyze_pipeline.py
```

The scripts regenerate the figures and numerical summaries in `figures/` and `edited_figures/`. They also create temporary comparison files under `data/`. These are generated outputs and do not need to be retained in the clean report package.

## Included evidence and tools

- `data/` contains the two measured IR samples, Stage 1 tweeter response and fit data, Stage 5 WAVs, and saved complex/FRD exports needed to repeat the report analysis.
- `reproduction/` contains the configured synthetic IR generator, its measurement grid and project settings, plus the processing functions used by the analysis.
- `export_ir.py` repeats a Stage 5 export when run in a configured HALS environment with the appropriate coefficient file. Example commands:

```powershell
python export_ir.py synthetic --coeff path/to/MySpeaker_coefficients.h5
python export_ir.py tweeter --coeff path/to/DirectivaR2-Tweeter_coefficients.h5
```

The full synthetic measurement dataset is kept outside this report folder. The bundled evidence is sufficient to reproduce the report comparisons without that full dataset. The report records export coordinates and settings, including TOF Off, capture padding 0 and microphone calibration Off.
