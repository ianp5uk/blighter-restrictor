@echo off
rem ---------------------------------------------------------------------------
rem Blighter Restrictor - "Open all" on a child's Windows PC, set on the PC.
rem
rem Purpose: the same as Open all on the parent app's Controls tab, for a
rem parent at the child's PC: every website and Discord are allowed, but the
rem firewall and proxy settings stay on, so activity is STILL RECORDED and
rem the parent app shows "Opened on the PC itself".  The filters are kept.
rem "Blighter Filtered.cmd", or the parent app's Controls tab, puts them back.
rem Asks for administrator rights first.  (Replaces 1.2.x's "Pause Blighter
rem Child.cmd", which switched Blighter off and stopped recording.)
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
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$r = & %ProgramData%\BlighterChild\blighter-apply.cmd open local | ConvertFrom-Json; Write-Host $r.message; if ($r.errors) { $r.errors | ForEach-Object { Write-Host $_ -ForegroundColor Red } }"
echo.
pause
