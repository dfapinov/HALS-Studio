# IR Capture Review

## Standalone Windows installer

`installer/HALS-IR-Tester-Setup-1.0.0.exe` installs the standalone x64 Windows
tester with Python, Tk, NumPy, SciPy and Matplotlib bundled. Jan only needs the
installer. Installation is per-user and does not require administrator rights.
Open HALS IR Tester from the Start menu and select the `measurement_set` folder.

Uninstall through Windows Settings > Apps > Installed apps. The uninstaller
removes installed files, shortcuts, its uninstall registry entry, and its
dedicated `%LOCALAPPDATA%/HALS IR Tester/cache` folder. Measurements and explicitly
saved reports are user documents and are retained. The application does not
create a preferences registry key or persist the last selected measurement path.

Rebuild from the repository root using:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/ir_capture_review/build.ps1
```

The build uses the repository virtual environment with PyInstaller and the Inno
Setup compiler in `tools/InnoSetup`. The packaged executable has been validated
with a generated nine-capture dataset and all five plots, followed by an actual
uninstall checking removal of the installation, cache, registry and shortcuts.

## Running from Python

This standalone Tkinter app requires Python with Tkinter, NumPy, SciPy and
Matplotlib. It has no HALS Studio imports or runtime dependency. Keep the three
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
3. Select a row. The main screen shows the full electrical loopback,
   microphone capture and uncropped IR on the left, with LF response/local
   predictions and measurement locations on the right. The loopback event and
   verified full-IR crop origin are marked. Both capture channels share a time
   axis for zooming. The detector compares complex pressure, so a timing/phase
   discrepancy can matter even when magnitude looks reasonable.
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

**Suspect** (CSV `repeat`) means both neighbourhoods exceed the threshold in the same band, or strong capture evidence was found.
**Review** means only one does. The displayed score is the consensus ratio;
1 is its repeat threshold, not a calibrated probability. A review row can
therefore have a consensus score below 1; its detailed single-neighbourhood
scores explain the warning. **Okay** (CSV `pass`) means no available check exceeded its threshold.

At least 25 unique valid positions are required. Duplicate-coordinate attempts
are reported separately and omitted from neighbour prediction rather than
silently treated as independent points.

## Optional full-capture checks

The scanner automatically pairs each IR with `debug/<stem>_capture.wav` and
`Distortion/<stem>_ir_dist.wav`. It uses a single shared reference archive in
`debug/references/*/*.npz` to establish channel identity and sweep timing.
Currently supported: `marker_then_dual_sweep_v1`, one sweep, declared electrical
loopback then microphone channels. Multiple archives without capture-to-reference
associations produce a metadata review warning; the scanner does not guess.
Missing optional files are shown in coverage without invalidating legacy IR sets.

- Build an aligned, gain-normalized median electrical template from up to 31
  evenly distributed captures, requiring at least nine and a consistent majority.
  Constant latency/gain are removed for comparison and checked separately for
  unusual session departures. No ideal flat interface response is assumed.
- Compare 10 ms waveform residual blocks at 24 kHz. Limits are the largest of
  2% of reference block RMS, eight times the median reference residual, and
  0.2% of overall reference RMS. Full-rate 10 ms amplitude envelopes also use
  a 10% floor, eight times their baseline variation, and a 0.3% overall floor.
  Ratios over 1 require review; over 3 are suspect. Blocks below 10% of expected
  electrical level are identified as signal loss. Durations are approximate
  block totals, not exact dropout boundaries. Clipping and constant/silent
  channels are checked at the original sample rate.
- Measure microphone pre-silence after 50 ms settling and before a 20 ms marker
  guard. Measure the final 200 ms only with at least 400 ms after the sweep.
  A noise warning must exceed both session and local robust baselines by at
  least 12 dB or six robust standard deviations, and exceed -45 dB relative
  to the microphone sweep RMS. Initial settling RMS is exported for inspection.
- Verify the full IR's crop origin against the actual cropped waveform. Compare
  the earliest 20% of its pre-linear region, normalized by early linear IR RMS,
  against session and local baselines (15 dB / six robust standard deviations).
  Avoid the immediately preceding harmonic-response region. This evidence is
  review-only: even far-prefix energy can include distortion/deconvolution effects.

Categories distinguish **Electrical/capture**, **Acoustic/microphone**,
**Acoustic/spatial**, and **File/metadata**; a capture can have several categories.
The results table shows the plain-language **Issue description**, matching the
capture finding shown above the main plots (for example, loopback signal loss and its timing).
The broader categories remain in the CSV export. Scroll horizontally to read
long descriptions or filenames.
Detected loopback signal loss always takes priority: it marks the capture as
**Suspect**, leads its description and categories, and places it above other
findings in the results. Other issues remain available as secondary evidence.
The CSV `primary_issue` field records the leading finding.
Electrical evidence does not distinguish driver, hardware, playback, cabling or
recording problems. Spatial disagreement is not proof of environmental noise.
Acoustic pre-silence/tail/prefix tests never independently force a suspect label.

The main inspection plots display both full capture channels and the uncropped
IR, with an event marker and verified crop origin. CSV exports retain the spatial score
separately and include JSON metrics, thresholds and individual issue codes.
The table's LF score is exclusively the original spatial score; it is not a
combined confidence or a capture-health probability.

## What it cannot establish

This detects inconsistency, not its cause. Real localized acoustic structure,
coordinate errors, gain changes or timing changes may also trigger a flag.
Re-measurement is preferable to assuming every flagged recording is corrupted.
Errors common to the whole scan can pass. Without optional capture files, coverage remains the original short-window LF check.
The electrical waveform comparison reaches 12 kHz; full-rate amplitude envelopes
extend dropout coverage to the recording bandwidth, but do not establish
phase/distortion quality above 12 kHz. A common fault affecting most captures
can still pass. Acoustic checks do not detect every transient during the sweep.
The thresholds are practical prototype thresholds, not an accuracy certificate.

## Earlier prototype verification

The scanner reproduced all seven previously identified candidates when reading
the 953 raw 8C IRs. Tests cover delayed-impulse phase/amplitude preservation,
a clean spatial field and an injected LF anomaly, technical failures, duplicate
coordinates, insufficient neighbours, cancellation, and rename/restore safety.
The Tkinter smoke test exercises the actual scan, plots, marks, cancelled
confirmation and confirmed rename/restore using generated files for mutations.
The complete repository suite passes 376 tests. Source measurement files were
not renamed during development validation.

## New capture verification

The automated scanner suite additionally covers fractional delay/gain changes,
interface filtering, loopback dropouts/clicks, microphone noise/clipping, silent
channels, late noise, full-IR prefix energy, legitimate pre-linear energy,
non-finite full IRs, ambiguous references, cancellation, ultrasonic dropout
envelopes and rejection of an inconsistent reference majority. Real-data findings
are recorded in `documentation/ir_capture_diagnostics_8c_02.md`.
