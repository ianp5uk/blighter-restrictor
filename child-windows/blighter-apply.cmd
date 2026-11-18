@echo off
rem ---------------------------------------------------------------------------
rem Blighter Restrictor - launcher for the Windows child-laptop helper.
rem
rem Purpose: the command the parent app runs over SSH, e.g.
rem   C:\ProgramData\BlighterChild\blighter-apply.cmd status
rem It starts blighter-apply.py with the private Python bundled next to it,
rem in isolated mode (-I: ignores PYTHON* settings and user folders), with
rem UTF-8 input/output, and passes back the helper's exit code.
rem The path has no spaces so it works the same whether the SSH server's
rem shell is cmd.exe (the default) or PowerShell.
rem
rem Copyright (C) 2026 Ian Packer
rem SPDX-License-Identifier: GPL-3.0-or-later
rem This program is free software: you can redistribute it and/or modify it
rem under the terms of the GNU General Public License as published by the Free
rem Software Foundation, either version 3 of the License, or (at your option)
rem any later version.  It is distributed WITHOUT ANY WARRANTY; see the
rem LICENSE file or <https://www.gnu.org/licenses/> for details.
rem ---------------------------------------------------------------------------
"%~dp0python\python.exe" -I -X utf8 "%~dp0blighter-apply.py" %*
exit /b %ERRORLEVEL%
