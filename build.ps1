param([string]$InnoCompiler = "$PSScriptRoot\tools\InnoSetup\ISCC.exe", [string]$Version = "0.1.0")
$ErrorActionPreference = 'Stop'
$studioRoot = $PSScriptRoot
$pythonPath = Join-Path $studioRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Run install.bat, then install requirements-dev.txt.' }
$env:PYTHONPATH = "$studioRoot\_vendor;$studioRoot;$studioRoot\hals_engine;$studioRoot\process_engine"
& $pythonPath -m PyInstaller --noconfirm --distpath "$studioRoot\dist" --workpath "$studioRoot\build" "$studioRoot\studio.spec"
if ($LASTEXITCODE -ne 0) { throw 'Executable build failed' }
if (Test-Path -LiteralPath $InnoCompiler) {
    & $InnoCompiler "/DAppVersion=$Version" "$studioRoot\studio_installer.iss"
    if ($LASTEXITCODE -ne 0) { throw 'Installer build failed' }
} else { Write-Host 'Executable built. Pass -InnoCompiler with the path to ISCC.exe to create the installer.' }
