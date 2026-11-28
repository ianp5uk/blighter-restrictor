@echo off
rem ---------------------------------------------------------------------------
rem Blighter Restrictor - "Filtered" on a child's Windows PC, set on the PC.
rem
rem Purpose: the same as Filtered on the parent app's Controls tab, for a
rem parent at the child's PC: the filters apply again after Open all or Block
rem all.  It also switches Blighter back on if an administrator switched it
rem off completely for troubleshooting (blighter-system.ps1 off).
rem Asks for administrator rights first.  (Replaces 1.2.x's "Resume Blighter
rem Child.cmd".)
rem
rem Copyright (C) 2026 Ian Packer
rem SPDX-License-Identifier: GPL-3.0-or-later
rem This program is free software: you can redistribute it and/or modify it
rem under the terms of the GNU General Public License as published by the Free
rem Software Foundation, either version 3 of the License, or (at your option)
rem any later version.  It is distributed WITHOUT ANY WARRANTY; see the
rem LICENSE file or <https://www.gnu.org/licenses/> for details.
rem ---------------------------------------------------------------------------
net session >nul 2>&1
if errorlevel 1 (
    powershell.exe -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$r = & %ProgramData%\BlighterChild\blighter-apply.cmd filtered local | ConvertFrom-Json; Write-Host $r.message; if ($r.errors) { $r.errors | ForEach-Object { Write-Host $_ -ForegroundColor Red } }"
echo.
pause
