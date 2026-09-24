# HALS Studio

HALS Studio is the next-generation HALS desktop app for processing loudspeaker measurements, analysing the sound field, and exporting responses and impulse responses. This is a standalone repository; HALS Post is not required.

## Run from source (Windows)

1. Install Python 3.11 or newer (tested here with Python 3.14).
2. Run `install.bat` to create this repository's `.venv` and install dependencies.
3. Run `launch.bat`. Optionally pass a project JSON or coefficient HDF5 path.

The workspace order is **Process, Analysis, Export**. Analysis stays empty until data is loaded. Existing HALS Post projects and earlier Viewer projects can be opened. Studio reads legacy `hals_viewer` layout data and saves it under `hals_studio`. Existing Viewer preferences are copied once into Studio's separate preferences.

## Source layout

- Root Python modules: application UI, analysis, plotting and export coordination.
- `process_engine/`: Studio-owned Stages 1-4 and processing diagnostics.
- `hals_engine/`: Stage 5 evaluation/export support; shared CTA calculations live here.
- `documentation/`: the copied HALS documentation, with Studio-specific Stage 1 updates.
- `misc/`: useful standalone measurement and diagnostic scripts copied from HALS Post.
- `assets/`, `images/`, `licenses/`, `LICENSE`: runtime resources and licensing.

Measurement projects are saved wherever you choose. Generated outputs, caches, virtual environments, dependency downloads and build products are excluded from Git.

## Development checks

```powershell
.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
.venv/Scripts/python.exe -m pytest
.venv/Scripts/python.exe verify_studio_workspace.py
```

The numerical tests generate their own synthetic inputs. The workspace check covers empty-data handling, selectable Export panes, CLI mirroring and saved layouts.

## Build the Windows app and installer

Keep `studio.spec`, `studio_installer.iss`, `build.ps1`, `studio.ico` and the license files under version control. Install the development requirements and Inno Setup 6, then run:

```powershell
./build.ps1 -InnoCompiler 'C:/Program Files (x86)/Inno Setup 6/ISCC.exe' -Version '0.1.0'
```

The portable app is produced in `dist/HALS Studio/` and the installer in `installer/`. These are generated artifacts, not repository source. Automatic release builds have not been configured yet; this build entry point is retained for that future work. The installer has a separate application ID from the earlier Atlas installer.

See [migration notes](documentation/studio_migration.md) for compatibility and provenance.
