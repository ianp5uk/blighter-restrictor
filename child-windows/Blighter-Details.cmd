@echo off
rem ---------------------------------------------------------------------------
rem Blighter Restrictor - connection details for a parent (child's Windows PC).
rem
rem Purpose: ask Windows for administrator rights (a UAC prompt) and run
rem blighter-details.ps1, which shows the address to enter in the parent app
rem and can check / repair the connection or change the "blighter" password.
rem There is no Start menu shortcut, so it does not catch the child's eye.
rem Open it with Windows key + R and type:
rem     C:\ProgramData\BlighterChild\Blighter-Details.cmd
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
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0blighter-details.ps1"
