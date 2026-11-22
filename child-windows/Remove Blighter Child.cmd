@echo off
rem ---------------------------------------------------------------------------
rem Blighter Restrictor - remove the child component from a Windows PC.
rem
rem Purpose: ask for administrator rights and run
rem "blighter-setup.ps1 -Remove": firewall back to Windows defaults, proxy
rem settings and scheduled tasks removed, previous squid.conf restored, and
rem optionally the "blighter" account deleted.  Squid itself stays installed.
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
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0blighter-setup.ps1" -Remove
echo.
pause
