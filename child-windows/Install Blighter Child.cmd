@echo off
rem ---------------------------------------------------------------------------
rem Blighter Restrictor - double-click installer for a child's Windows PC.
rem
rem Purpose: ask Windows for administrator rights (a UAC prompt) and run
rem blighter-setup.ps1 from this unzipped folder.  Run it while signed in
rem to a PARENT administrator account, not the child's.
rem To undo everything later, run "Remove Blighter Child.cmd".
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
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0blighter-setup.ps1"
echo.
pause
