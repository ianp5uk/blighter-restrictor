# -----------------------------------------------------------------------------
# Blighter Restrictor - build the Windows app and installer.
#
# Purpose: on a Windows 10/11 PC, create a private Python environment, build
# BlighterRestrictor.exe with PyInstaller, then (if Inno Setup 6 is
# installed) wrap it into dist\BlighterRestrictor-Setup-<ver>.exe.
# Requirements: Python 3.11+ from python.org ("py" launcher), and optionally
# Inno Setup 6 (https://jrsoftware.org/isdl.php) for the installer.
# Usage (PowerShell, in the project folder):
#   powershell -ExecutionPolicy Bypass -File windows\build_windows.ps1
# -----------------------------------------------------------------------------
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

$ver = (Select-String -Path parent\blighter_parent\__init__.py -Pattern '__version__ = "(.+)"').Matches[0].Groups[1].Value
Write-Host "Building Blighter Restrictor $ver"

if (-not (Test-Path .venv-win)) {
    if (Get-Command py -ErrorAction SilentlyContinue) { py -3 -m venv .venv-win } else { python -m venv .venv-win }
}
$py = ".\.venv-win\Scripts\python.exe"
& $py -m pip install --upgrade pip
if ($LASTEXITCODE) { throw "pip failed" }
# cryptography 50+ links python3t.dll, which PyInstaller does not bundle - stay below 50.
& $py -m pip install "PySide6-Essentials>=6.6" "paramiko>=3.4" "cryptography>=44,<50" "keyring>=24" "pyinstaller>=6.5"
if ($LASTEXITCODE) { throw "pip install failed" }
& $py -m pip list

# Same shared rules file the Linux packages use.
Copy-Item common\domains.py parent\blighter_parent\domains.py -Force

# cryptography/bcrypt/pynacl (used by SSH) need python3.dll, which PyInstaller
# does not always collect from a virtual environment - add it explicitly.
$base = & $py -c "import sys; print(sys.base_prefix)"
$py3dll = Join-Path $base "python3.dll"
if (-not (Test-Path $py3dll)) { throw "python3.dll not found in $base" }

& $py -m PyInstaller --noconfirm --clean --windowed `
    --add-binary "$py3dll;." `
    --collect-binaries cryptography `
    --hidden-import cryptography.hazmat.bindings._rust `
    --name BlighterRestrictor `
    --icon windows\blighter.ico `
    --paths parent `
    --add-data "parent\blighter_parent\icon.svg;blighter_parent" `
    --hidden-import keyring.backends.Windows `
    parent\blighter_parent\__main__.py
if ($LASTEXITCODE) { throw "PyInstaller failed" }

Remove-Item parent\blighter_parent\domains.py -Force

$iscc = Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"
if (Test-Path $iscc) {
    & $iscc "/DAppVersion=$ver" windows\installer.iss
    if ($LASTEXITCODE) { throw "Inno Setup failed" }
    Write-Host "Installer: dist\BlighterRestrictor-Setup-$ver.exe"
} else {
    Write-Host "Inno Setup 6 not found - the app is in dist\BlighterRestrictor\BlighterRestrictor.exe"
    Write-Host "Install Inno Setup 6 and run this script again to get a single Setup.exe."
}
