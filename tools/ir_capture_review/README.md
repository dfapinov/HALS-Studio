# IR Capture Review

This standalone Tkinter app requires Python with Tkinter, NumPy, SciPy and
Matplotlib. It has no HALS Studio imports or runtime dependency. Keep the two
Python files together when copying it to another computer.

From this directory, set up its own environment once:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Then double-click `run.bat`, or run:

```powershell
.venv\Scripts\python.exe ir_capture_review.py
```

Run its independent tests with `python -m pytest tests` in an environment with
pytest and the dependencies above installed.

## Review and exclude

1. Browse to the directory directly containing the `*_ir.wav` recordings.
   The scan does not recurse into subdirectories, to avoid mixing attempts or
   different measurement sets. Click **Scan**. Scanning never renames files.
2. **Needs review** shows repeat candidates, one-neighbourhood warnings,
   technical problems and datasets with too few valid neighbours. Switch to
   **All recordings** to inspect apparently normal points as well.
3. Select a row. The plots show the leading IR with three nearby traces,
   the LF magnitude with neighbouring responses and both local predictions,
   and an azimuth/height map. The detector compares complex pressure, so a
   timing/phase discrepancy can matter even when magnitude looks reasonable.
   The text gives the 12/24-neighbour scores for each octave band.
4. Click **Mark selected** or the **Exclude?** cell for the files you have
   reviewed. Nothing is pre-marked. **Rename marked** shows a confirmation
   before adding `.blacklisted` to the selected names:
   `point_ir.wav` becomes `point_ir.wav.blacklisted`.
5. **Excluded** lists renamed files. Select one or more and click
   **Restore selected** to undo the rename. A new capture at the original name
   blocks restoration, so the replacement cannot be overwritten. Existing
   `.blacklisted` files likewise block a second exclusion of the same name.

The rename changes no sample data. The tool checks that each file still matches
the reviewed file's size, modification time and identity, preflights destination
collisions for the batch, and attempts rollback if a rename fails partway.
After successful renaming it rescans, updating the neighbourhood predictions.

Stage 1 loads files ending in `.wav`, so the new suffix excludes the recording
from the next import. **Re-run Stage 1 and subsequent stages** to update an
existing NPZ/coefficient result. Renaming cannot remove data already imported.
If retaining the existing Stage 1 NPZ, **Export blacklist** writes the original
names of confirmed excluded files for the Stage 2 blacklist setting; rerun
Stage 2 and subsequent stages. If you have re-measured replacements, rebuild
Stage 1 and remove obsolete filename exclusions so the new captures are used.

**Export report** saves all findings, scores and current marks to CSV. The
standalone read-only CLI can also produce candidates without renaming:

```powershell
.venv\Scripts\python.exe ir_capture_quality.py "D:\capture\measurement_set" --output "D:\capture\quality_report"
```

`blacklist_candidates.txt` from the CLI is an unconfirmed suggestion. The GUI's
blacklist export contains only already-renamed exclusions.

## How the detector works

The numerical detector is the lightweight prototype previously tested on the
8C, SS, ELAC and Genelec datasets. It uses raw IRs and coordinates from filenames,
without a source-origin search, harmonic-order choice or SHE coefficients.

- Inspect the first 0.35 s, identifying unreadable, short, silent, constant or
  non-finite leading IRs. Mono audio and parseable coordinates are required.
  Memory mapping avoids loading the full recording when its WAV format allows;
  some formats, including 24-bit PCM, require SciPy's full-file fallback read.
- Find an early arrival, downsample to 4 kHz and apply a 200 ms cosine taper
  after the arrival. Keep the common recording time reference: do not align
  away inter-position phase differences.
- Extract 37 complex response values from 40 to 320 Hz. For each measurement,
  predict that response from its nearest 12 and nearest 24 physical positions.
  A local affine fit models smooth spatial variation. Robust fitting within
  this small detector reduces contamination from suspect neighbours; it does
  not introduce measurement weights into HALS reconstruction.
- In each of the 40–80, 80–160 and 160–320 Hz bands, compare the discrepancy
  against the larger of 10% of typical local pressure and eight times the
  local deleted-residual scale, adjusted for prediction uncertainty.

**Repeat** means both neighbourhoods exceed the threshold in the same band.
**Review** means only one does. The displayed score is the consensus ratio;
1 is its repeat threshold, not a calibrated probability. A review row can
therefore have a consensus score below 1; its detailed single-neighbourhood
scores explain the warning. **Pass** means no discrepancy exceeded the test.

At least 25 unique valid positions are required. Duplicate-coordinate attempts
are reported separately and omitted from neighbour prediction rather than
silently treated as independent points.

## What it cannot establish

This detects inconsistency, not its cause. Real localized acoustic structure,
coordinate errors, gain changes or timing changes may also trigger a flag.
Re-measurement is preferable to assuming every flagged recording is corrupted.
Errors common to the whole scan can pass. The tool does not comprehensively
check HF behaviour, clipping, or the late waveform beyond the short window.
The thresholds are practical prototype thresholds, not an accuracy certificate.

## Verification

The scanner reproduced all seven previously identified candidates when reading
the 953 raw 8C IRs. Tests cover delayed-impulse phase/amplitude preservation,
a clean spatial field and an injected LF anomaly, technical failures, duplicate
coordinates, insufficient neighbours, cancellation, and rename/restore safety.
The Tkinter smoke test exercises the actual scan, plots, marks, cancelled
confirmation and confirmed rename/restore using generated files for mutations.
The complete repository suite passes 376 tests. Source measurement files were
not renamed during development validation.
