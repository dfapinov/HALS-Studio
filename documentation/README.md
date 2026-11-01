# HALS Studio documentation

Choose a topic below for help using HALS Studio and understanding its acoustic processing.

New to HALS Studio? Start with the [project overview](../README.md). The usual workflow is **Process → Analysis → Export**: prepare the recordings, solve the sound-field model, then inspect or export virtual measurements.

## Contents

- [Process your measurements](#process-your-measurements)
- [Explore the Analysis workspace](#explore-the-analysis-workspace)
- [Export measurements](#export-measurements)
- [Validation reports (PDF)](#validation-reports-pdf)
- [Utilities](#utilities)

## Process your measurements

Follow these guides in order when processing a measurement project from HALS Control.

| Guide | What you will find |
| --- | --- |
| [Stage 1: FDW & smoothing](stage1_fdw_gui_help.md) | Import recordings, choose frequency-dependent windowing and complex smoothing settings, and inspect the prepared data. Includes importing WAV files without a project JSON. |
| [Stage 2: Acoustic origins](stage2_origin_help.md) | Find the acoustic origin across frequency, choose search settings, and interpret the origin paths and fitting errors. |
| [Stage 3: Recommended maximum order N](stage3_help.md) | Choose a suitable spherical-harmonic order using field separation, discarded sound power and directivity-change diagnostics. |
| [Stage 4: SHE solver](stage4_she_solver_help.md) | Understand the final sound-field solve, matrix conditioning, fit residuals, order limits and Sound Field Separation. |

## Explore the Analysis workspace

Start with the workspace overview, then choose the view you want to use.

| Guide | What you will find |
| --- | --- |
| [Analysis workspace overview](analysis_00_workspace_overview.md) | Open model data, choose import settings, arrange views and use shared plot controls. |
| [Sound field](analysis_01_sound_field.md) | Explore balloons, colour spheres, probe SPL, phase, polar plots and horizontal SPL sweeps. |
| [Directivity](analysis_02_directivity.md) | Read horizontal and vertical sonograms, intersecting sonograms and waterfall displays. |
| [Time](analysis_03_time.md) | Inspect impulse responses, arrival time and decay using Morlet wavelets and Cumulative Spectral Decay (CSD). |
| [CEA/CTA-2034 (Spinorama)](analysis_04_cea2034.md) | Interpret summary curves, reflection breakouts, predicted in-room response and directivity globes. |

## Export measurements

[Export guide: evaluating the 3D sound field](stage5_export_help.md) covers virtual microphone positions, field selection, coordinate systems, angular sweeps, custom coordinates, FRD and impulse-response exports, calibration and level options.

## Validation reports (PDF)

| Report | Topic |
| --- | --- |
| [HALS IR Validation (PDF)](HALS_IR_Validation.pdf) | Impulse-response validation. |
| [HALS Stage 5 Geometric Phase Validation (PDF)](HALS_Stage5_Geometric_Phase_Validation.pdf) | Geometric phase validation for Stage 5 export. |

## Utilities

| Guide | What you will find |
| --- | --- |
| [Miscellaneous utilities](misc_scripts_help.md) | Synthetic impulse-response generation, grid assessment and complex-frequency visualisation. |
| [Miscellaneous scripts directory](../misc/README.md) | Locate diagnostic tools, development utilities and historical reproductions. |

---

HALS Studio is under active development. Some detailed guides may lag behind the latest implementation; where they differ, use the current application behaviour as the reference.

[Back to the project overview](../README.md)
