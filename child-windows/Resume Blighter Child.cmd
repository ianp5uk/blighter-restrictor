@echo off
rem ---------------------------------------------------------------------------
rem Blighter Restrictor - resume filtering on a child's Windows laptop.
rem
rem Purpose: switch filtering back ON after "Pause Blighter Child.cmd":
rem firewall, proxy settings and the self-repair task are applied again.
rem Asks for administrator rights first.
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
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%ProgramData%\BlighterChild\blighter-system.ps1" resume
echo.
pause
