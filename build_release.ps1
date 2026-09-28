$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $projectRoot
$pythonExe = Join-Path $projectRoot '.venv\Scripts\python.exe'
$innoInstall = Get-ItemProperty `
  'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*', `
  'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*', `
  'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*' `
  -ErrorAction SilentlyContinue | Where-Object DisplayName -like 'Inno Setup*' |
  Select-Object -First 1
$compilerExe = if ($innoInstall) {
  Join-Path $innoInstall.InstallLocation 'ISCC.exe'
} else {
  (Get-Command ISCC.exe -ErrorAction SilentlyContinue).Source
}
if (-not (Test-Path -LiteralPath $pythonExe)) { throw 'Python environment is missing.' }
if (-not (Test-Path -LiteralPath $compilerExe)) { throw 'Inno Setup 6 is missing.' }
& $pythonExe 'assets\build_icon.py'
if ($LASTEXITCODE -ne 0) { throw 'Could not build application icons.' }
& $pythonExe 'assets\build_installer_art.py'
if ($LASTEXITCODE -ne 0) { throw 'Could not build installer art.' }
$pyinstallerArgs = @(
  '-m', 'PyInstaller', '--noconfirm', '--clean', '--windowed', '--onedir',
  '--name', '老必灯', '--icon', 'assets\ripple.ico',
  '--add-data', 'ui.qss;.', '--add-data', 'keyboard_map.json;.',
  '--add-data', 'assets\ripple.ico;assets',
  '--add-data', 'assets\ripple.png;assets',
  '--add-data', 'assets\ripple.svg;assets',
  '--add-data', 'assets\fonts;assets\fonts',
  '--add-data', 'third_party;third_party', 'main.py'
)
& $pythonExe @pyinstallerArgs
if ($LASTEXITCODE -ne 0) { throw 'Application build failed.' }
# The host Python runtime ships an ICU DLL that shadows Windows' compatible
# ICU export set when QtCore is loaded from the bundled PySide6 directory.
$shadowIcu = Join-Path $projectRoot 'dist\老必灯\_internal\icuuc.dll'
if (Test-Path -LiteralPath $shadowIcu) {
  Remove-Item -LiteralPath $shadowIcu
}
& $compilerExe 'installer.iss'
if ($LASTEXITCODE -ne 0) { throw 'Installer build failed.' }
Get-Item -LiteralPath (Join-Path $projectRoot 'release\老必灯-Setup-1.5.0.exe') |
  Select-Object FullName, Length, LastWriteTime
