param([string]$Version = '1.0.0')
$ErrorActionPreference = 'Stop'
if ($Version -notmatch '^\d+\.\d+\.\d+$') { throw 'Expected a numeric x.y.z version' }
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$python = Join-Path $repo '.venv\Scripts\python.exe'
$compiler = Join-Path $repo 'tools\InnoSetup\ISCC.exe'
if (-not (Test-Path -LiteralPath $compiler)) { throw 'Inno Setup compiler not found in tools/InnoSetup' }
& $python -m PyInstaller --noconfirm --distpath (Join-Path $repo 'dist') --workpath (Join-Path $repo 'build\ir-tester') (Join-Path $PSScriptRoot 'ir_tester.spec')
if ($LASTEXITCODE -ne 0) { throw 'Executable build failed' }
& $compiler "/DAppVersion=$Version" (Join-Path $PSScriptRoot 'ir_tester_installer.iss')
if ($LASTEXITCODE -ne 0) { throw 'Installer build failed' }
