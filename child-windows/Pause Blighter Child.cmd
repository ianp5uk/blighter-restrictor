@echo off
rem ---------------------------------------------------------------------------
rem Blighter Restrictor - pause filtering on a child's Windows PC.
rem
rem Purpose: switch Blighter OFF without uninstalling, for troubleshooting:
rem the firewall, browser policies and the child's proxy go back to how they
rem were before setup, and the self-repair task is switched off.  Activity is
rem NOT recorded while it is off.  The parent app can still connect, and its
rem "Resume filtering" (or "Resume Blighter Child.cmd") switches it on again.
rem (The parent app's own Pause is different: it allows every site but keeps
rem recording activity.)
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
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%ProgramData%\BlighterChild\blighter-system.ps1" pause
echo.
pause
