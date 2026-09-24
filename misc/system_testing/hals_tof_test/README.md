# HALS Stage 5 point source travel time test

All current scripts, source data, exports and graphs live in this folder:
`src/misc/system_testing/hals_tof_test`.

The latest report files are at the repository root:
- `output/pdf/HALS_Stage5_Synthetic_Phase_Validation_Updated.pdf`
- `output/docx/HALS_Stage5_Synthetic_Phase_Validation.docx` (editable)

## Source generator

`synth_ir_gen_tof_test.py` is already configured for an exactly centred point:

```python
SOURCE_CENTER_M = (0.0, 0.0, 0.0)
PISTON_RADIUS_M = 0.0
PISTON_POINT_COUNT = 1
DEFAULT_C = 343.0
DEFAULT_FS = 48000
DEFAULT_DURATION_S = 0.2
```

`synth_ir_grid.csv` contains 1,443 measurement positions. Run the generator only
when you want to regenerate the input WAVs; it writes to `input_irs_synth` here.
Import the WAVs into HALS and solve with sound speed 343 m/s, maximum order N8,
and Use optimised origins Off. Stage 5 capture padding must be 0 samples.

`test_project_settings.json` supplies the remaining processing settings: Stage 1
RFT 5 ms, octave resolution 12, smoothing Auto, gain off; Stage 4 kR offset 2,
automatic order capped at 8, regularisation off. The supplied solved H5 uses
orders 2 to 8 and has zero origin shifts at every frequency. The original project
JSON still had optimised origins enabled; the stored shifts are all zero and
the test export explicitly disables them.

## Run the test

Open a terminal in this folder with the HALS Python environment active:

```powershell
python export_test.py
python analyze_test.py
```

`export_test.py` defaults to `input_irs_synth/outputs/coefficients/MySpeaker_coefficients.h5`.
To select a different solve:

```powershell
python export_test.py --coeff "path/to/your_model.h5"
```

It writes `test_exports` for Mic A at (2, 0, 0) m and Mic B at (2, 0, 0.5) m:
2 m reference radius, Internal field, no mic calibration, zero capture padding,
no optimised origins, and both Off and Ref Origin TOF modes.

`analyze_test.py` reads these FRD/NPZ exports and the Stage 4 fit errors, producing
`simple_results.json` and all report figures in `simple_graphs`. Both delay
metrics and graphs use **20 Hz to 20 kHz**. The first report table describes the
change caused by raising the mic 500 mm, with columns comparing geometry to HALS.

Latest differential result:
- Geometry: 179.454265 microseconds.
- HALS export: 179.454341 microseconds.
- Delay error: **0.000076 microseconds**, equivalent to **0.000026 mm**.
- Maximum phase error against geometry: **0.031 degrees**.

## Build the reports

```powershell
python build_simple_report.py
python build_word_report.py
```

Report builders require ReportLab; the Word builder also needs python-docx.
Scientific scripts use the existing HALS dependencies plus Matplotlib and h5py.
The Word document has editable text and tables; figures are embedded PNGs.
Upload the DOCX to Google Drive and open it in Google Docs to edit it there.

Older material in `analysis/stage5_synth` is historical and is not the source
of the current report. The original PDF filename was kept untouched because
it was locked by an open viewer; the revised PDF has `_Updated` in its name.
