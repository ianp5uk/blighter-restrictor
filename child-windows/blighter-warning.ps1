# -----------------------------------------------------------------------------
# Blighter Restrictor - a warning on the child's screen (since 1.4.0).
#
# Purpose: show one message box, on top of other windows, in the child's
# own session: "Login time ends in 5 minutes..." or "This PC will shut down
# in 15 minutes...".  blighter-apply.py starts it there through a one-off
# scheduled task running as the child (Windows Home has no msg.exe).  The
# text arrives base64-encoded so no quoting can go wrong; it is always
# Blighter's own wording, never anything typed by a person.
#
# Usage: powershell -File blighter-warning.ps1 -Text <base64 UTF-8 text>
#
# Copyright (C) 2026 Ian Packer
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version.  It is distributed WITHOUT ANY WARRANTY; see the
# LICENSE file or <https://www.gnu.org/licenses/> for details.
# -----------------------------------------------------------------------------
param([Parameter(Mandatory = $true)][string]$Text)

$message = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($Text))
Add-Type -AssemblyName System.Windows.Forms
$owner = New-Object System.Windows.Forms.Form
$owner.TopMost = $true
$owner.ShowInTaskbar = $false
$null = [System.Windows.Forms.MessageBox]::Show($owner, $message, "Blighter Restrictor",
    [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Warning)
$owner.Dispose()
