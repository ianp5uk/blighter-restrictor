# -----------------------------------------------------------------------------
# Blighter Restrictor - connection details and repair for a PARENT, on the
# child's Windows PC.
#
# Purpose: started by Blighter-Details.cmd (administrator rights needed).
# It shows the address to type into the parent app's "Add child" or
# "Reconnect" (the PC's home-network IPv4 address, read afresh each time),
# and offers:
#   1  check and repair the connection - OpenSSH and Squid services, the
#      SSH firewall rule, the rest of the firewall (blighter-system.ps1
#      repair) and the network type (must be "Private" for the parent app).
#      The PC's SSH identity (host keys) is kept: it is how the parent app
#      recognises this PC when its address changes.
#   2  change the "blighter" account's password (then enter the new one in
#      the parent app: Edit child, or Reconnect)
# Nothing here changes the filter rules, the activity log or the child's
# settings.  There is deliberately no Start menu or desktop shortcut: the
# parent opens it with Windows key + R and the path
# C:\ProgramData\BlighterChild\Blighter-Details.cmd
#
# Copyright (C) 2026 Ian Packer
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version.  It is distributed WITHOUT ANY WARRANTY; see the
# LICENSE file or <https://www.gnu.org/licenses/> for details.
# -----------------------------------------------------------------------------
$ErrorActionPreference = "Continue"
$ProgressPreference    = "SilentlyContinue"
$Here    = Split-Path -Parent $MyInvocation.MyCommand.Path
$System  = Join-Path $Here "blighter-system.ps1"
$NetFile = Join-Path $Here "state\networks-changed.txt"
$Admin   = "blighter"

$id = [Security.Principal.WindowsIdentity]::GetCurrent()
if (-not ([Security.Principal.WindowsPrincipal]$id).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "Please run this as administrator (double-click Blighter-Details.cmd)." -ForegroundColor Red
    exit 1
}

function Test-Private([string]$ip) {
    return ($ip -match '^10\.') -or ($ip -match '^192\.168\.') -or ($ip -match '^172\.(1[6-9]|2[0-9]|3[01])\.')
}

function Get-Addresses {
    # Adapters with a default route first (that is the home network), private addresses first.
    $withRoute = @(Get-NetRoute -DestinationPrefix "0.0.0.0/0" -ErrorAction SilentlyContinue | ForEach-Object { $_.ifIndex } | Sort-Object -Unique)
    $all = @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
             Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" })
    $list = @()
    foreach ($a in $all) {
        $name = (Get-NetConnectionProfile -InterfaceIndex $a.InterfaceIndex -ErrorAction SilentlyContinue | Select-Object -First 1).Name
        if (-not $name) { $name = $a.InterfaceAlias }
        $rank = 0
        if ($withRoute -contains $a.InterfaceIndex) { $rank += 2 }
        if (Test-Private $a.IPAddress) { $rank += 1 }
        $list += [pscustomobject]@{ Address = $a.IPAddress; Name = "$name"; Rank = $rank }
    }
    return @($list | Sort-Object -Property Rank -Descending)
}

function Show-Details {
    $addrs = Get-Addresses
    Write-Host ""
    Write-Host "  Blighter Child - connection details" -ForegroundColor Cyan
    Write-Host ""
    if ($addrs.Count) {
        Write-Host "  On your own PC, open Blighter Restrictor and enter this address"
        Write-Host "  (Add child, or Reconnect for a child already in the list):"
        Write-Host ""
        Write-Host ("        {0}" -f $addrs[0].Address) -ForegroundColor Green
        Write-Host ""
        Write-Host ("  (network: {0})" -f $addrs[0].Name)
        if ($addrs.Count -gt 1) {
            Write-Host ""
            Write-Host "  Other addresses on this PC (only needed if the one above does not work):"
            foreach ($a in $addrs[1..($addrs.Count - 1)]) { Write-Host ("        {0}   ({1})" -f $a.Address, $a.Name) }
        }
    } else {
        Write-Host "  This PC is not connected to a network right now." -ForegroundColor Yellow
        Write-Host "  Connect it to your home Wi-Fi or network and try again."
    }
    Write-Host ""
    Write-Host "  Login for the parent app: $Admin  (and the password chosen at setup)"
    Write-Host "  Keep both PCs switched on and connected to your home network."
    Write-Host ""
}

function Repair-Connection {
    Write-Host ""
    Write-Host "Checking the connection (this can take a minute)..." -ForegroundColor Cyan
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $System repair
    foreach ($np in @(Get-NetConnectionProfile -ErrorAction SilentlyContinue)) {
        Write-Host ("  Network '{0}': {1}" -f $np.Name, $np.NetworkCategory)
        if ("$($np.NetworkCategory)" -eq "Public") {
            Write-Host "  The parent app can only connect while Windows calls the home network 'Private'."
            $a = Read-Host "  Is '$($np.Name)' your HOME network?  Mark it Private? [Y/n]"
            if (-not $a -or $a -match '^[Yy]') {
                Set-NetConnectionProfile -InterfaceIndex $np.InterfaceIndex -NetworkCategory Private
                Add-Content -Path $NetFile -Value ("{0}`t{1}" -f $np.InterfaceAlias, "Public")
                Write-Host "  '$($np.Name)' is now Private (removing Blighter sets it back)."
            }
        }
    }
    $s = Get-Service sshd -ErrorAction SilentlyContinue
    if ($s -and $s.Status -eq "Running") { Write-Host "  SSH server: running" -ForegroundColor Green }
    else { Write-Host "  SSH server: NOT running - run the Blighter Child installer again." -ForegroundColor Red }
    if (-not (Get-LocalUser -Name $Admin -ErrorAction SilentlyContinue)) {
        Write-Host "  The '$Admin' account is missing - run the Blighter Child installer again." -ForegroundColor Red
    }
    Write-Host "Done." -ForegroundColor Cyan
}

function Set-AdminPassword {
    if (-not (Get-LocalUser -Name $Admin -ErrorAction SilentlyContinue)) {
        Write-Host "The '$Admin' account is missing - run the Blighter Child installer again." -ForegroundColor Red
        return
    }
    while ($true) {
        $p1 = Read-Host "New password for '$Admin' (leave empty to cancel)" -AsSecureString
        $b1 = [Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR($p1))
        if (-not $b1) { Write-Host "Password not changed."; return }
        $p2 = Read-Host "Type it again" -AsSecureString
        $b2 = [Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR($p2))
        if ($b1 -ne $b2) { Write-Host "They do not match - try again."; continue }
        if ($b1.Length -lt 10) { Write-Host "Use at least 10 characters - this account has full control of the PC."; continue }
        if ($b1.ToLower().Contains($Admin)) { Write-Host "Windows does not allow the password to contain the word '$Admin'."; continue }
        try {
            Set-LocalUser -Name $Admin -Password $p1 -ErrorAction Stop
            Write-Host "Password changed.  In the parent app, select the child and use Edit (or Reconnect) to enter it." -ForegroundColor Green
            return
        } catch {
            Write-Host "Windows rejected that password ($($_.Exception.Message)).  Try again."
        }
    }
}

while ($true) {
    Show-Details
    Write-Host "  1  Check and repair the connection"
    Write-Host "  2  Change the '$Admin' password"
    Write-Host "  3  Close"
    $c = Read-Host "Choose 1, 2 or 3"
    switch ($c) {
        "1" { Repair-Connection }
        "2" { Set-AdminPassword }
        default { exit 0 }
    }
}
