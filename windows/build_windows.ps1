# -----------------------------------------------------------------------------
# Blighter Restrictor - build the Windows app and installer.
#
# Purpose: on a Windows 10/11 PC, create a private Python environment, build
# BlighterRestrictor.exe with PyInstaller (with the licence files of the
# bundled Python packages in third-party-licenses), then (if Inno Setup 6 is
# installed) wrap it into dist\BlighterRestrictor-Setup-<ver>.exe.
# Requirements: Python 3.11+ from python.org ("py" launcher), and optionally
# Inno Setup 6 (https://jrsoftware.org/isdl.php) for the installer.
# Usage (PowerShell, in the project folder):
#   powershell -ExecutionPolicy Bypass -File windows\build_windows.ps1
#
# Copyright (C) 2026 Ian Packer
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version.  It is distributed WITHOUT ANY WARRANTY; see the
# LICENSE file or <https://www.gnu.org/licenses/> for details.
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

# The exact licence files of every Python package bundled into the app
# (build tools such as PyInstaller and pip are not shipped, so are skipped).
$lic = "dist\BlighterRestrictor\third-party-licenses"
@'
import importlib.metadata as m, os, shutil, sys
out = sys.argv[1]
skip = {"pip", "setuptools", "wheel", "pyinstaller", "pyinstaller-hooks-contrib", "altgraph", "pefile", "packaging"}
for d in m.distributions():
    name = (d.metadata["Name"] or "").lower()
    if not name or name in skip:
        continue
    files = [f for f in (d.files or []) if any(k in f.name.lower() for k in ("licen", "copying", "notice", "authors"))]
    for f in files:
        src = f.locate()
        if os.path.isfile(src):
            dst = os.path.join(out, name, f.name)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copyfile(src, dst)
    print("licence files for", name, len(files))
'@ | Set-Content -Path collect_licences.py -Encoding ASCII
& $py collect_licences.py $lic
if ($LASTEXITCODE) { throw "collecting licence files failed" }
Remove-Item collect_licences.py -Force

$iscc = Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"
if (Test-Path $iscc) {
    & $iscc "/DAppVersion=$ver" windows\installer.iss
    if ($LASTEXITCODE) { throw "Inno Setup failed" }
    Write-Host "Installer: dist\BlighterRestrictor-Setup-$ver.exe"
} else {
    Write-Host "Inno Setup 6 not found - the app is in dist\BlighterRestrictor\BlighterRestrictor.exe"
    Write-Host "Install Inno Setup 6 and run this script again to get a single Setup.exe."
}
