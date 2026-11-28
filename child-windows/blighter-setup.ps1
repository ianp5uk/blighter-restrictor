# -----------------------------------------------------------------------------
# Blighter Restrictor - one-time setup of a child's WINDOWS PC.
#
# Purpose: prepare this PC so the parent app can manage it over the home
# network.  Safe to run again.  Normally started by the Windows installer
# BlighterChild-Setup-<ver>.exe (-Gui, no console window: the installer asks
# every question first and shows this script's progress on its own page), or
# by "Install Blighter Child.cmd" for technical users.  It:
#   1. checks the child's account and WARNS if it is an administrator
#   2. copies the helper and its private Python to C:\ProgramData\BlighterChild
#      (locked so only administrators can change it) and records the
#      child's account (child.conf)
#   3. BEFORE CHANGING ANYTHING ELSE: creates a Windows restore point
#      ("Before Blighter Restrictor") and saves the PC's current
#      settings (state\pre-install.json) so removal can put them back
#   4. installs the tested Squid for Windows (Diladele MSI, downloaded): the
#      download must carry a valid Diladele B.V. signature (otherwise setup
#      stops); if it is not the exact file Blighter was tested with (SHA-256)
#      setup carries on and says so at the end.  A Squid that an earlier
#      Blighter installed is replaced, keeping Blighter's lists, settings and
#      logs.  A Squid installed by something else is only replaced with
#      -ReplaceSquid (or when the user agrees); its settings are saved to
#      backup\squid-before-blighter first.  The MSI's firewall rule (port
#      3128) and desktop shortcuts are removed, and the folder is locked
#   5. creates the hidden "blighter" administrator account (password login
#      over SSH) that the parent app uses
#   6. installs and starts Windows' own OpenSSH Server
#   7. replaces squid.conf with the Blighter one (old file backed up)
#   8. turns on the whole-PC firewall, the proxy settings and the
#      self-repair task (blighter-system.ps1 enable)
#   9. offers to mark the current network as Private (needed for SSH);
#      the change is recorded so removal can undo it
#
# It takes 15-30 minutes in all.  It says so first, and says which steps are
# slow; long steps print "still working" every 30 seconds.  If setup stops
# part-way (an error, or Ctrl+C), it offers to undo what it has done so far
# (default yes).  A marker file (state\setup-incomplete.txt) records an
# unfinished setup; running setup again then offers to finish or undo it,
# and the parent app shows a warning.
#
# Removal (-Remove) puts the PC back as it was before step 3: firewall,
# proxy and browser settings, network types, and - if setup added them -
# deletes the blighter account and stops and uninstalls OpenSSH Server and
# Squid (it asks first; the defaults are "yes"), then deletes its own folder.
#
# Usage (PowerShell as administrator):
#   blighter-setup.ps1 [-Child <username>] [-NoVoice] [-DnsServers "1.1.1.1 8.8.8.8"]
#                      [-ReplaceSquid] [-KeepPassword] [-NoMarkPrivate]
#   (Discord is allowed on a new install, -NoVoice blocks it; a re-run keeps
#   the earlier choice.  The parent app can change it.)
#   blighter-setup.ps1 -Remove [-Yes]        undo everything
#   blighter-setup.ps1 -Query                facts for the installer's pages
#                                            (accounts, Squid owner, networks)
# -Gui (used by the installer) = -Yes, plus "##BLIGHTER ..." progress lines
# for the installer and no automatic undo (the installer asks instead).
# -Yes answers every question with its default (for automated tests); the
# blighter password is then taken from the BLIGHTER_ADMIN_PASSWORD
# environment variable.  -TestFailAt <step> (tests only) stops with an error
# at the start of that step, to check that the undo works.
#
# Copyright (C) 2026 Ian Packer
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version.  It is distributed WITHOUT ANY WARRANTY; see the
# LICENSE file or <https://www.gnu.org/licenses/> for details.
# -----------------------------------------------------------------------------
param(
    [string]$Child = "",
    [switch]$NoVoice,
    [string]$DnsServers = "1.1.1.1 8.8.8.8",
    [switch]$Remove,
    [switch]$Yes,
    [switch]$Gui,
    [switch]$Query,
    [switch]$ReplaceSquid,
    [switch]$KeepPassword,
    [switch]$NoMarkPrivate,
    [int]$TestFailAt = 0
)
if ($Gui) { $Yes = [switch]$true }
# If started from PowerShell 7 (pwsh), its module folders are inherited and
# Windows PowerShell 5.1 then fails to load built-in commands such as Set-Acl.
# Use only Windows PowerShell's own module folders.
if ($PSVersionTable.PSEdition -eq "Desktop") {
    $env:PSModulePath = (Join-Path $env:ProgramFiles "WindowsPowerShell\Modules") + ";" +
                        (Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\Modules")
}

$ErrorActionPreference = "Stop"
# Progress bars are hidden (they flash on and off and look like a fault);
# slow steps print their own "still working" lines instead.
$ProgressPreference    = "SilentlyContinue"
$Version   = "1.2.9"
$Admin     = "blighter"
$Dest      = Join-Path $env:ProgramData "BlighterChild"
$Src       = Split-Path -Parent $MyInvocation.MyCommand.Path
$SquidUrl  = "https://www.diladele.com/pkg/squid/7.8/squid-7.8_amd64.msi"
$SquidPage = "https://www.diladele.com/squid/download.html"
# The exact Squid MSI Blighter was tested with (signed by Diladele B.V.).
$SquidSha256 = "a2ba4fde87e7deacab84c13fab20dcc1fb0e226b72fee81612f7cb66022d8cc3"
if ($env:BLIGHTER_TEST_SQUID_SHA) { $SquidSha256 = $env:BLIGHTER_TEST_SQUID_SHA }   # tests only
$script:SquidChanged = $false
$script:Notes = @()
$SidAdmins = "S-1-5-32-544"
$SidUsers  = "S-1-5-32-545"
$SidSystem = "S-1-5-18"
$StateDir  = Join-Path $Dest "state"
$PreFile   = Join-Path $StateDir "pre-install.json"
$NetFile   = Join-Path $StateDir "networks-changed.txt"
$System    = Join-Path $Dest "blighter-system.ps1"
$Marker    = Join-Path $StateDir "setup-incomplete.txt"
$ShaFile   = Join-Path $StateDir "squid-msi.sha256"
$BackupDir = Join-Path $Dest "backup"
$OurSquidBackup   = Join-Path $BackupDir "squid-blighter"
$OtherSquidBackup = Join-Path $BackupDir "squid-before-blighter"

function Say($m)  { Write-Host ""; Write-Host "==> $m" -ForegroundColor Cyan }
function Warn($m) { Write-Host "WARNING: $m" -ForegroundColor Yellow }
function Die($m)  { Write-Host "ERROR: $m" -ForegroundColor Red; exit 1 }
# Lines for the Windows installer (only with -Gui).
function Tag($m)  { if ($Gui) { Write-Host "##BLIGHTER $m" } }
function Note($m) { $script:Notes += $m; Tag "note $m" }
$script:StepStart = $null
function Write-StepTime {
    if ($script:StepStart) {
        $t = (Get-Date) - $script:StepStart
        Write-Host ("    (that step took {0}:{1:00})" -f [int][math]::Floor($t.TotalMinutes), $t.Seconds) -ForegroundColor DarkGray
    }
    $script:StepStart = Get-Date
}
function Step([int]$n, [string]$title, [string]$time) {
    Write-StepTime
    Say "$n/9 $title"
    Tag "step $n $title"
    if ($time) { Write-Host "    (usually $time)" -ForegroundColor DarkGray }
    if ($TestFailAt -eq $n) { Die "Test failure requested at step $n (-TestFailAt)." }
}

function Write-StillWorking([string]$what, [datetime]$start) {
    $t = (Get-Date) - $start
    Write-Host ("    ... still {0} - {1}:{2:00} so far.  This is normal; please wait." -f $what, [int][math]::Floor($t.TotalMinutes), $t.Seconds)
}

function Invoke-Slow([string]$what, [scriptblock]$block, [object[]]$argList = @()) {
    # Run a long PowerShell command in the background and say "still working"
    # every 30 seconds, so the window never looks frozen.  Errors are passed on.
    $start = Get-Date
    $job = Start-Job -ScriptBlock $block -ArgumentList $argList
    try {
        while (-not (Wait-Job $job -Timeout 30)) { Write-StillWorking $what $start }
        if ($job.State -eq "Failed") {
            $reason = $job.ChildJobs[0].JobStateInfo.Reason
            throw $(if ($reason) { $reason.Message } else { "$what failed" })
        }
        return (Receive-Job $job -ErrorAction Stop)
    } finally {
        Stop-Job $job -ErrorAction SilentlyContinue
        Remove-Job $job -Force -ErrorAction SilentlyContinue
    }
}

function Start-Slow([string]$what, [string]$exe, [string]$arguments) {
    # Run a program in this window, saying "still working" every 30 seconds;
    # returns its exit code.
    $start = Get-Date
    $p = Start-Process -FilePath $exe -ArgumentList $arguments -NoNewWindow -PassThru
    $null = $p.Handle          # (Windows PowerShell needs this to read the exit code later)
    try {
        while (-not $p.WaitForExit(30000)) { Write-StillWorking $what $start }
        return $p.ExitCode
    } finally {
        if (-not $p.HasExited) { try { $p.Kill() } catch { } }
    }
}
function Ask($q, $default = "n") {
    if ($Yes) { return ($default -eq "y") }
    $a = Read-Host "$q [$(if ($default -eq 'y') {'Y/n'} else {'y/N'})]"
    if (-not $a) { $a = $default }
    return $a -match '^[Yy]'
}

function Get-SquidRoot {
    try {
        $p = (Get-ItemProperty -Path "HKLM:\SOFTWARE\Squid" -Name InstallDir -ErrorAction Stop).InstallDir
        if ($p -and (Test-Path (Join-Path $p "bin\squid.exe"))) { return $p.TrimEnd('\') }
    } catch { }
    if (Test-Path "C:\Squid\bin\squid.exe") { return "C:\Squid" }
    return $null
}

function Lock-Folder([string]$path) {
    # Only SYSTEM and Administrators may change it; ordinary users may read and run.
    # (Folders made at the root of C: are otherwise changeable by every signed-in user.)
    # The folder gets a fresh, protected ACL; everything inside is reset to inherit it.
    $inherit = [Security.AccessControl.InheritanceFlags]"ContainerInherit, ObjectInherit"
    $none = [Security.AccessControl.PropagationFlags]::None
    $acl = New-Object Security.AccessControl.DirectorySecurity
    $acl.SetAccessRuleProtection($true, $false)
    $acl.SetOwner((New-Object Security.Principal.SecurityIdentifier $SidAdmins))
    foreach ($e in @(@($SidSystem, "FullControl"), @($SidAdmins, "FullControl"), @($SidUsers, "ReadAndExecute"))) {
        $rule = New-Object Security.AccessControl.FileSystemAccessRule(
            (New-Object Security.Principal.SecurityIdentifier $e[0]), [Security.AccessControl.FileSystemRights]$e[1], $inherit, $none, "Allow")
        $acl.AddAccessRule($rule)
    }
    Set-Acl -LiteralPath $path -AclObject $acl
    $ErrorActionPreference = "Continue"
    & icacls.exe "$path\*" /reset /T /C /Q | Out-Null
    if ($LASTEXITCODE -ne 0) { Warn "Some files in $path could not be reset to the locked permissions (they may be in use)." }
}

function Get-AdminSids {
    try { return @(Get-LocalGroupMember -SID $SidAdmins -ErrorAction Stop | ForEach-Object { $_.SID.Value }) }
    catch {
        $sids = @()
        $name = (New-Object Security.Principal.SecurityIdentifier $SidAdmins).Translate([Security.Principal.NTAccount]).Value.Split('\')[-1]
        $g = [ADSI]"WinNT://$env:COMPUTERNAME/$name,group"
        foreach ($m in @($g.psbase.Invoke("Members"))) {
            $bytes = $m.GetType().InvokeMember("objectSid", "GetProperty", $null, $m, $null)
            $sids += (New-Object Security.Principal.SecurityIdentifier($bytes, 0)).Value
        }
        return $sids
    }
}

# ------------------------------------------------------------------ checks ---
$id = [Security.Principal.WindowsIdentity]::GetCurrent()
if (-not ([Security.Principal.WindowsPrincipal]$id).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Die "Run this as administrator (use 'Install Blighter Child.cmd')."
}
if (-not [Environment]::Is64BitOperatingSystem) { Die "Squid for Windows needs 64-bit Windows." }
if ([Environment]::OSVersion.Version.Major -lt 10) { Die "Windows 10 or newer is needed." }

function Get-SquidOwner {
    # none / blighter (an earlier Blighter installed or took over this Squid) / other
    $r = Get-SquidRoot
    if (-not $r) { return "none" }
    if (Test-Path (Join-Path $r "etc\squid\blighter")) { return "blighter" }
    if (Test-Path $PreFile) {
        try { if (-not (Get-Content $PreFile -Raw | ConvertFrom-Json).squid_installed) { return "blighter" } } catch { }
    }
    return "other"
}

if ($Query) {
    # Tab-separated facts for the installer's pages.  Nothing is changed.
    $adminSids = Get-AdminSids
    Get-LocalUser | Where-Object { $_.Enabled -and $_.Name -ne $Admin -and $_.Name -notin @("Administrator", "Guest", "DefaultAccount", "WDAGUtilityAccount") } |
        ForEach-Object { Write-Output ("account`t{0}`t{1}`t{2}" -f $_.Name, $_.FullName, [int]($adminSids -contains $_.SID.Value)) }
    Write-Output ("adminexists`t{0}" -f [int][bool](Get-LocalUser -Name $Admin -ErrorAction SilentlyContinue))
    Write-Output ("squid`t{0}" -f (Get-SquidOwner))
    foreach ($np in @(Get-NetConnectionProfile -ErrorAction SilentlyContinue)) {
        if ("$($np.NetworkCategory)" -eq "Public") { Write-Output ("network`t{0}" -f $np.Name) }
    }
    Write-Output ("incomplete`t{0}" -f [int](Test-Path $Marker))
    exit 0
}

# ----------------------------------------------------------------- removal ---
function Get-SquidProductCodes {
    foreach ($root in "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
                      "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall") {
        Get-ChildItem $root -ErrorAction SilentlyContinue | ForEach-Object {
            $p = Get-ItemProperty $_.PSPath -ErrorAction SilentlyContinue
            if ($p.DisplayName -eq "Squid" -and $_.PSChildName -match '^\{[0-9A-Fa-f-]+\}$') { $_.PSChildName }
        }
    }
}

if ($Remove) {
    Say "Removing Blighter Restrictor from this PC"
    $pre = $null
    if (Test-Path $PreFile) {
        $pre = Get-Content $PreFile -Raw | ConvertFrom-Json
        Write-Host "Putting back the settings saved on $($pre.captured_at)."
    } else {
        Warn "No saved 'before' state was found - Windows defaults will be used instead."
    }

    Say "Firewall, proxy and browser settings"
    if (Test-Path $System) {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $System disable
    } else {
        Get-ScheduledTask -TaskPath "\Blighter Restrictor\" -ErrorAction SilentlyContinue | Unregister-ScheduledTask -Confirm:$false
        Get-NetFirewallRule -Group "Blighter Restrictor" -ErrorAction SilentlyContinue | Remove-NetFirewallRule
        Set-NetFirewallProfile -Profile Domain, Private, Public -DefaultOutboundAction NotConfigured
    }

    Say "Network types"
    if (Test-Path $NetFile) {
        foreach ($line in Get-Content $NetFile) {
            $alias, $cat = $line -split "`t", 2
            $np = Get-NetConnectionProfile -InterfaceAlias $alias -ErrorAction SilentlyContinue
            if ($np -and $cat) {
                Set-NetConnectionProfile -InterfaceAlias $alias -NetworkCategory $cat -ErrorAction SilentlyContinue
                Write-Host "  $alias set back to $cat"
            }
        }
    } else { Write-Host "  No network types were changed by setup." }

    Say "SSH server"
    $sshd = Get-Service sshd -ErrorAction SilentlyContinue
    if ($sshd) {
        if ($pre -and $pre.sshd_exists) {
            Set-Service sshd -StartupType $pre.sshd_start_type
            if (-not $pre.sshd_running) { Stop-Service sshd -Force -ErrorAction SilentlyContinue }
            Write-Host "OpenSSH Server was already installed before setup - left as it was ($($pre.sshd_start_type))."
        } else {
            Stop-Service sshd -Force -ErrorAction SilentlyContinue
            Set-Service sshd -StartupType Disabled
            Write-Host "OpenSSH Server stopped and disabled."
            if (Ask "OpenSSH Server was installed by Blighter setup.  Uninstall it?" "y") {
                $cap = Get-WindowsCapability -Online -Name "OpenSSH.Server*" -ErrorAction SilentlyContinue | Select-Object -First 1
                if ($cap -and $cap.State -eq "Installed") {
                    try { Remove-WindowsCapability -Online -Name $cap.Name | Out-Null; Write-Host "OpenSSH Server uninstalled." }
                    catch { Warn "Could not uninstall OpenSSH Server ($($_.Exception.Message)); it stays stopped and disabled." }
                }
            }
            if (-not ($pre -and $pre.openssh_rule_exists)) {
                Remove-NetFirewallRule -Name "OpenSSH-Server-In-TCP" -ErrorAction SilentlyContinue
            }
        }
    }

    Say "Squid"
    $root = Get-SquidRoot
    if ($root) {
        $conf = Join-Path $root "etc\squid\squid.conf"
        $backup = Get-ChildItem (Join-Path $root "etc\squid") -Filter "squid.conf.pre-blighter-*" -ErrorAction SilentlyContinue |
                  Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if ($backup) { Copy-Item $backup.FullName $conf -Force; Write-Host "Restored $($backup.Name) -> squid.conf" }
        $installedBySetup = -not ($pre -and $pre.squid_installed)
        if ($pre -and -not $pre.squid_installed -and (Ask "Squid was installed by Blighter setup.  Uninstall it?" "y")) {
            Stop-Service squidsrv -Force -ErrorAction SilentlyContinue
            foreach ($code in Get-SquidProductCodes) {
                $p = Start-Process msiexec.exe -ArgumentList "/x $code /qn /norestart" -Wait -PassThru
                if ($p.ExitCode -eq 0 -or $p.ExitCode -eq 3010) { Write-Host "Squid uninstalled." }
                else { Warn "The Squid uninstaller returned code $($p.ExitCode) - remove 'Squid' in Settings > Apps." }
            }
            if (Test-Path $root) { Remove-Item $root -Recurse -Force -ErrorAction SilentlyContinue }
        } else {
            Restart-Service squidsrv -ErrorAction SilentlyContinue
            if ($installedBySetup) { Write-Host "Squid for Windows is still installed (remove 'Squid' in Settings > Apps if you wish)." }
            else { Write-Host "Squid was installed before setup - left installed with its previous squid.conf." }
        }
    }

    if (Test-Path $OtherSquidBackup) {
        $keep = Join-Path $env:ProgramData "Squid-settings-before-Blighter"
        Copy-Item $OtherSquidBackup $keep -Recurse -Force -ErrorAction SilentlyContinue
        Write-Host "The Squid settings saved before Blighter replaced Squid are kept in $keep"
    }

    Say "The '$Admin' account"
    if (Get-LocalUser -Name $Admin -ErrorAction SilentlyContinue) {
        $ours = -not ($pre -and $pre.admin_exists)
        if (Ask "Delete the '$Admin' administrator account?" $(if ($ours) { "y" } else { "n" })) {
            $sid = (Get-LocalUser -Name $Admin).SID.Value
            Remove-LocalUser -Name $Admin
            Get-CimInstance Win32_UserProfile -ErrorAction SilentlyContinue | Where-Object { $_.SID -eq $sid } |
                Remove-CimInstance -ErrorAction SilentlyContinue
            Write-Host "Account '$Admin' and its profile deleted."
        } else { Warn "Account '$Admin' kept - it is an administrator; change its password or delete it later." }
        if (-not ($pre -and $pre.admin_hidden_value)) {
            Remove-ItemProperty "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon\SpecialAccounts\UserList" -Name $Admin -ErrorAction SilentlyContinue
        }
    }

    Say "Done"
    $rp = Join-Path $StateDir "restore-point.txt"
    if (Test-Path $rp) {
        Write-Host "If anything still behaves differently, use System Restore and pick the restore point"
        Write-Host "'Before Blighter Restrictor' from $(Get-Content $rp -TotalCount 1) (Start > 'Create a restore point' > System Restore)."
    }
    if (Test-Path $Dest) {
        if (Ask "Delete the folder $Dest (helper, logs and saved state)?" "y") {
            Set-Location $env:TEMP
            # Deleted a few seconds after this script ends, as files in it are still in use now.
            Start-Process cmd.exe -ArgumentList "/c ping -n 6 127.0.0.1 >nul & rmdir /s /q `"$Dest`"" -WindowStyle Hidden
            Write-Host "The folder will be deleted in a few seconds."
        }
    }
    exit 0
}

# ------------------------------------------------------------ before start ---
if (-not $Yes -and -not (Test-Path $PreFile)) {
    # First install: the parent app must be on the parent's own PC first.
    Write-Host ""
    Write-Host "  Install Blighter Restrictor on your OWN PC first." -ForegroundColor Yellow
    Write-Host "  This setup is for the child's PC.  You need the parent app to finish"
    Write-Host "  connecting to it and to manage it."
    if (-not (Ask "  Have you already installed the parent app on your own PC?" "n")) {
        Write-Host "Nothing has been changed.  Install the parent app first, then run this again."
        exit 0
    }
}
Write-Host ""
Write-Host "  Blighter Restrictor $Version - child PC setup" -ForegroundColor Cyan
Write-Host ""
Write-Host "  This takes about 15-30 minutes.  The slow steps are:"
Write-Host "     3/9  restore point                          1-5 minutes"
Write-Host "     4/9  downloading and installing Squid       1-5 minutes"
Write-Host "     6/9  OpenSSH Server from Windows Update     2-20 minutes"
Write-Host "     8/9  firewall                               1-3 minutes"
Write-Host "  During slow steps the window prints a 'still working' line every"
Write-Host "  30 seconds.  That is normal - please do not close the window."
Write-Host "  Keep the PC plugged in and on the home Wi-Fi."
Write-Host ""
Write-Host "  If you need to stop part-way, press Ctrl+C: setup will offer to undo"
Write-Host "  what it has done so far.  If the PC is switched off part-way,"
Write-Host "  run 'Install Blighter Child.cmd' again - it will offer to finish or undo."
Write-Host ""
if (Test-Path $Marker) {
    Warn "An earlier setup on this PC did not finish (started $(Get-Content $Marker -TotalCount 1))."
    if (Ask "Undo what it did, instead of carrying on with setup?" "n") {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Dest "blighter-setup.ps1") -Remove
        exit $LASTEXITCODE
    }
    Write-Host "Carrying on - setup is safe to run again and will finish the job."
} elseif (-not (Ask "Start now?" "y")) {
    Write-Host "Nothing has been changed.  Run 'Install Blighter Child.cmd' when you have time."
    exit 0
}

# Stop the PC going to sleep while setup runs (until this window closes).
try {
    Add-Type -Namespace Blighter -Name Power -MemberDefinition '[DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint f);'
    [Blighter.Power]::SetThreadExecutionState([uint32]"0x80000001") | Out-Null   # ES_CONTINUOUS | ES_SYSTEM_REQUIRED
} catch { }

$SetupDone = $false
# Blighter already installed and working (this is a re-run or an update): if
# this run fails, the installer suggests keeping it rather than undoing it.
$WasInstalled = (Test-Path $PreFile) -and -not (Test-Path $Marker)
try {
# ------------------------------------------------------ 1. child account ---
Step 1 "The child's account" "a few seconds"
$locals = @(Get-LocalUser | Where-Object { $_.Enabled -and $_.Name -ne $Admin -and $_.Name -notin @("Administrator", "Guest", "DefaultAccount", "WDAGUtilityAccount") })
if (-not $Child) {
    Write-Host "Accounts on this PC:"
    $locals | ForEach-Object { Write-Host ("   {0,-20} {1}" -f $_.Name, $_.FullName) }
    $Child = Read-Host "Which account is the child's? (type the name in the first column)"
}
$Child = $Child.Trim()
if (-not $Child) { Die "No account given." }
if ($Child -eq $Admin) { Die "'$Admin' cannot be the child's account." }
try {
    $childSid = (New-Object Security.Principal.NTAccount($Child)).Translate([Security.Principal.SecurityIdentifier]).Value
} catch { Die "There is no account called '$Child' on this PC." }
$isAdmin = (Get-AdminSids) -contains $childSid
if ($isAdmin) {
    Write-Host ""
    Write-Host "  *****************************************************************" -ForegroundColor Red
    Write-Host "  '$Child' is an ADMINISTRATOR on this PC." -ForegroundColor Red
    Write-Host "  An administrator can switch off the firewall, stop Squid, delete" -ForegroundColor Red
    Write-Host "  the scheduled task or uninstall all of this.  Blighter Restrictor" -ForegroundColor Red
    Write-Host "  will still filter, and the parent app will show what is in force," -ForegroundColor Red
    Write-Host "  but it cannot stop an administrator who goes looking." -ForegroundColor Red
    Write-Host "" 
    Write-Host "  To fix it: keep your own (parent) administrator account, then in" -ForegroundColor Yellow
    Write-Host "  Settings > Accounts > Other users, change '$Child' to 'Standard user'." -ForegroundColor Yellow
    Write-Host "  If '$Child' is the ONLY account, first create a parent account and" -ForegroundColor Yellow
    Write-Host "  make it an administrator, sign in to it, then demote '$Child'." -ForegroundColor Yellow
    Write-Host "  *****************************************************************" -ForegroundColor Red
    if (-not $Yes) { Read-Host "Press Enter to continue anyway, or Ctrl+C to stop" | Out-Null }
    Note "The child's account '$Child' is an administrator - see the install guide on making it a standard account."
}
# Squid installed by something else: only replaced with permission (decided
# here, before anything is changed).
$squidOwner = Get-SquidOwner
if ($squidOwner -eq "other" -and -not $ReplaceSquid) {
    Write-Host "Squid (web filter software) is already installed on this PC, but it wasn't"
    Write-Host "installed by Blighter.  Something else may be using it.  Blighter needs to replace"
    Write-Host "it with the version it was tested with; its settings are saved first."
    if ($Yes -or -not (Ask "Replace Squid?" "n")) {
        Die "Squid is already installed and was not installed by Blighter - nothing has been changed.  Run setup again and choose 'Replace Squid' to continue."
    }
    $ReplaceSquid = [switch]$true
}

# --------------------------------------------------------- 2. helper files ---
Step 2 "Helper files in $Dest" "under a minute"
if (-not (Test-Path $Dest)) { New-Item -ItemType Directory -Path $Dest | Out-Null }
Lock-Folder $Dest
if ((Resolve-Path $Src).Path.TrimEnd('\') -ne (Resolve-Path $Dest).Path.TrimEnd('\')) {
    foreach ($item in "blighter-apply.py", "blighter-apply.cmd", "blighter-system.ps1", "blighter-setup.ps1",
                      "domains.py", "blockpage.py", "logtail.py", "squid.conf", "python", "LICENSE.txt",
                      "Remove Blighter Child.cmd", "Pause Blighter Child.cmd", "Resume Blighter Child.cmd",
                      "blighter-details.ps1", "Blighter-Details.cmd") {
        $from = Join-Path $Src $item
        if (-not (Test-Path $from)) { Die "Missing file $item next to this script - unzip the whole package first." }
        Copy-Item $from $Dest -Recurse -Force
    }
}
Get-ChildItem $Dest -Recurse -File | Unblock-File -ErrorAction SilentlyContinue
Lock-Folder $Dest
# Discord: one switch for its web addresses (Squid) and voice/video (firewall).
# The parent app can change it later; a re-run keeps the earlier choice as the default.
$oldConf = Join-Path $Dest "child.conf"
# Not asked at setup: allowed on a new install, an earlier choice is kept.
$voice = "yes"
if ((Test-Path $oldConf) -and (Select-String -Path $oldConf -Pattern '^\s*ALLOW_VOICE_UDP\s*=\s*"?no' -Quiet)) { $voice = "no" }
if ($NoVoice) { $voice = "no" }
Write-Host ("Discord: {0} (the parent app can change this)." -f $(if ($voice -eq "yes") { "allowed" } else { "blocked" }))
# Home network (printers, NAS...): kept from an earlier setup; otherwise the
# private (RFC 1918) network the PC is on now.  The parent app can change it.
function Get-OldConf([string]$key) {
    if (-not (Test-Path $oldConf)) { return $null }
    $m = Select-String -Path $oldConf -Pattern ('^\s*' + $key + '\s*=\s*"?([^"]*)"?\s*$') | Select-Object -Last 1
    if ($m) { return $m.Matches[0].Groups[1].Value } else { return $null }
}
$homeAllowed = Get-OldConf "HOME_NET_ALLOWED"
$homeNets = Get-OldConf "HOME_NETS"
$homeName = Get-OldConf "HOME_NET_NAME"
if (-not $homeAllowed) {
    $homeAllowed = "yes"; $homeNets = ""; $homeName = ""
    try {
        $ErrorActionPreference = "Continue"
        $ni = (& (Join-Path $Dest "python\python.exe") -I (Join-Path $Dest "blighter-apply.py") netinfo) -join "" | ConvertFrom-Json
        $ErrorActionPreference = "Stop"
        $first = @($ni.networks | Where-Object { $_.private }) | Select-Object -First 1
        if ($first) { $homeNets = $first.subnet; $homeName = ("$($first.name)" -replace '"', "'") }
    } catch { $ErrorActionPreference = "Stop" }
}
if ($homeAllowed -eq "yes" -and $homeNets) { Write-Host "Home network allowed (printers, file sharing): $homeNets$(if ($homeName) { " ($homeName)" })" }
elseif ($homeAllowed -eq "yes") { Warn "This PC is not on a private home network now - set the home network later in the parent app (Filters tab)." }
@"
# Blighter Restrictor - which account on this PC is the child's.
# Written by blighter-setup.ps1 $Version.  On Windows the firewall filters the
# whole PC; CHILD_USER is used for the proxy setting and admin warnings.
CHILD_USER="$Child"
CHILD_SID="$childSid"
# yes = Discord allowed: its web addresses through Squid and outgoing
# UDP 50000-65535 for voice/video calls.  Changed by the parent app's
# "Allow Discord" switch (Filters tab).
ALLOW_VOICE_UDP="$voice"
# Home network access (printers, NAS...): yes/no, the subnet(s), and the
# network's name when recorded.  Changed in the parent app (Filters tab).
HOME_NET_ALLOWED="$homeAllowed"
HOME_NETS="$homeNets"
HOME_NET_NAME="$homeName"
"@ | Set-Content -Path (Join-Path $Dest "child.conf") -Encoding ASCII
& (Join-Path $Dest "python\python.exe") -I -c "print('Bundled Python OK')"
if ($LASTEXITCODE -ne 0) { Die "The bundled Python does not run on this PC." }

# ------------------------------------------- 3. restore point and backup ---
Step 3 "Restore point and a record of the current settings" "1-5 minutes"
if (-not (Test-Path $PreFile)) {
    try {
        # Windows allows one restore point per 24 hours unless told otherwise.
        $srKey = "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\SystemRestore"
        Enable-ComputerRestore -Drive "$env:SystemDrive\" -ErrorAction SilentlyContinue
        if (-not (Test-Path $srKey)) { New-Item -Path $srKey -Force | Out-Null }
        New-ItemProperty -Path $srKey -Name SystemRestorePointCreationFrequency -Value 0 -PropertyType DWord -Force | Out-Null
        Write-Host "Creating a Windows restore point..."
        Invoke-Slow "creating the restore point" {
            $ErrorActionPreference = "Stop"
            Checkpoint-Computer -Description "Before Blighter Restrictor" -RestorePointType MODIFY_SETTINGS
        } | Out-Null
        Remove-ItemProperty -Path $srKey -Name SystemRestorePointCreationFrequency -ErrorAction SilentlyContinue
        if (-not (Test-Path $StateDir)) { New-Item -ItemType Directory -Path $StateDir -Force | Out-Null }
        Set-Content -Path (Join-Path $StateDir "restore-point.txt") -Value (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
        Write-Host "Restore point 'Before Blighter Restrictor' created."
    } catch {
        Warn "Could not create a restore point ($($_.Exception.Message)).  Removal will still put the settings back."
        Note "Windows could not create a restore point (removal will still put the settings back)."
        if (-not $Yes) { Read-Host "Press Enter to continue, or Ctrl+C to stop" | Out-Null }
    }
}
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $System capture
if ($LASTEXITCODE -ne 0 -or -not (Test-Path $PreFile)) { Die "Could not save the current settings - nothing else has been changed." }
# From here on there is something to undo: mark setup as unfinished until the end.
Set-Content -Path $Marker -Value (Get-Date -Format "yyyy-MM-dd HH:mm:ss")

# ------------------------------------------------------------- 4. Squid ---
Step 4 "Squid for Windows" "1-5 minutes"
function Copy-IfThere([string]$from, [string]$to) {
    if (Test-Path $from) {
        if (-not (Test-Path $to)) { New-Item -ItemType Directory -Path $to -Force | Out-Null }
        Copy-Item (Join-Path $from "*") $to -Recurse -Force
    }
}
function Remove-SquidExtras {
    # The MSI opens port 3128 to the local network and adds two desktop
    # shortcuts.  Blighter's Squid only listens on the PC itself.
    Get-NetFirewallRule -DisplayName "Squid Cache Server" -ErrorAction SilentlyContinue | Remove-NetFirewallRule -ErrorAction SilentlyContinue
    foreach ($d in @([Environment]::GetFolderPath("CommonDesktopDirectory"), [Environment]::GetFolderPath("Desktop"))) {
        foreach ($n in "Squid Terminal.lnk", "Squid Server Tray.lnk") {
            $f = Join-Path $d $n
            if ($d -and (Test-Path $f)) { Remove-Item $f -Force -ErrorAction SilentlyContinue }
        }
    }
}
$root = Get-SquidRoot
$owner = Get-SquidOwner
$recorded = if (Test-Path $ShaFile) { (Get-Content $ShaFile -TotalCount 1).Trim() } else { "" }
if ($root -and $owner -eq "blighter" -and $recorded -eq $SquidSha256) {
    Write-Host "The tested Squid is already installed."
} else {
    Write-Host "Downloading Squid from Diladele..."
    $msi = Join-Path $env:TEMP "squid-blighter.msi"
    # On a re-run Blighter's own firewall blocks PowerShell from the internet.
    # Allow it to reach Diladele's download server only, for the download only.
    $tempRule = "BR-SetupDownload"
    $fwOn = @(Get-NetFirewallProfile -ErrorAction SilentlyContinue | Where-Object { "$($_.DefaultOutboundAction)" -eq "Block" }).Count -gt 0
    try {
        if ($fwOn) {
            $hostName = ([Uri]$SquidUrl).Host
            $ips = @([Net.Dns]::GetHostAddresses($hostName) | ForEach-Object { $_.IPAddressToString })
            if ($ips.Count) {
                New-NetFirewallRule -Name $tempRule -DisplayName "Blighter: setup downloading Squid (temporary)" -Group "Blighter Restrictor" `
                    -Direction Outbound -Action Allow -Profile Any -Protocol TCP -RemotePort 443 -RemoteAddress $ips `
                    -Program (Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe") | Out-Null
            }
        }
        Invoke-Slow "downloading Squid" {
            param($url, $file)
            $ErrorActionPreference = "Stop"
            [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
            # Direct, not through the PC's proxy setting (Squid would block it).
            $wc = New-Object Net.WebClient
            $wc.Proxy = $null
            $wc.DownloadFile($url, $file)
        } @($SquidUrl, $msi) | Out-Null
    } catch {
        Die "The Squid download failed ($($_.Exception.Message)).  Check your internet connection and run setup again."
    } finally {
        Remove-NetFirewallRule -Name $tempRule -ErrorAction SilentlyContinue
    }
    # 1. It must really be Diladele's file (valid signature).
    $sig = Get-AuthenticodeSignature -FilePath $msi
    $signer = if ($sig.SignerCertificate) { $sig.SignerCertificate.Subject } else { "" }
    Write-Host "Signature: $($sig.Status) - $signer"
    if ("$($sig.Status)" -ne "Valid" -or $signer -notmatch 'CN="?Diladele B\.V\.') {
        Remove-Item $msi -Force -ErrorAction SilentlyContinue
        Die "The Squid download could not be verified.  Check your internet connection and run setup again."
    }
    # 2. Is it the exact file Blighter was tested with?  If not, carry on and say so at the end.
    $hash = (Get-FileHash -Path $msi -Algorithm SHA256).Hash.ToLower()
    if ($hash -ne $SquidSha256) {
        $script:SquidChanged = $true
        Warn "This Squid download is not the exact file Blighter $Version was tested with (SHA-256 $hash)."
    }
    if ($root) {
        Write-Host "Replacing the Squid already installed in $root ($(if ($owner -eq 'blighter') { 'installed by Blighter' } else { 'not installed by Blighter' }))..."
        if ($owner -eq "blighter") {
            # Keep Blighter's lists, mode, switches and the activity log.
            if (Test-Path $OurSquidBackup) { Remove-Item $OurSquidBackup -Recurse -Force }
            New-Item -ItemType Directory -Path $OurSquidBackup -Force | Out-Null
            Copy-IfThere (Join-Path $root "etc\squid\blighter") (Join-Path $OurSquidBackup "blighter")
            Copy-IfThere (Join-Path $root "var\log\squid") (Join-Path $OurSquidBackup "logs")
            Get-ChildItem (Join-Path $root "etc\squid") -Filter "squid.conf.pre-blighter-*" -ErrorAction SilentlyContinue |
                Copy-Item -Destination $OurSquidBackup -Force
            Write-Host "Blighter's lists and settings saved to $OurSquidBackup"
        } else {
            if (-not (Test-Path $OtherSquidBackup)) {
                New-Item -ItemType Directory -Path $OtherSquidBackup -Force | Out-Null
                Copy-IfThere (Join-Path $root "etc\squid") (Join-Path $OtherSquidBackup "etc-squid")
            }
            Write-Host "The existing Squid settings are saved in $OtherSquidBackup"
        }
        Stop-Service squidsrv -Force -ErrorAction SilentlyContinue
        Get-Process squid -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
        foreach ($code in @(Get-SquidProductCodes)) {
            $p = Start-Process msiexec.exe -ArgumentList "/x $code /qn /norestart" -Wait -PassThru
            Write-Host "Old Squid uninstalled (code $($p.ExitCode))."
        }
        if ($owner -eq "blighter" -and (Test-Path $root)) { Remove-Item $root -Recurse -Force -ErrorAction SilentlyContinue }
    }
    Write-Host "Installing Squid..."
    $code = Start-Slow "installing Squid" "msiexec.exe" "/i `"$msi`" /qn /norestart INSTALLFOLDER=`"C:\Squid\`""
    Remove-Item $msi -Force -ErrorAction SilentlyContinue
    if ($code -ne 0 -and $code -ne 3010) { Die "The Squid installer failed (code $code)." }
    $root = Get-SquidRoot
    if (-not $root) { Die "Squid did not install correctly." }
    Remove-SquidExtras
    if ($owner -eq "blighter" -and (Test-Path $OurSquidBackup)) {
        # The new Squid starts straight away and holds its log files open.
        Stop-Service squidsrv -Force -ErrorAction SilentlyContinue
        Get-Process squid -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2
        # Most important first: the configuration removal puts back, then the lists.
        Get-ChildItem $OurSquidBackup -Filter "squid.conf.pre-blighter-*" -File -ErrorAction SilentlyContinue |
            Copy-Item -Destination (Join-Path $root "etc\squid") -Force
        Copy-IfThere (Join-Path $OurSquidBackup "blighter") (Join-Path $root "etc\squid\blighter")
        Write-Host "Blighter's lists and settings put back."
        # The activity log is best effort: the old log files usually survive the
        # Squid uninstall, and one that is in use or protected is left as it is.
        $logTo = Join-Path $root "var\log\squid"
        if (-not (Test-Path $logTo)) { New-Item -ItemType Directory -Path $logTo -Force | Out-Null }
        $logFrom = Join-Path $OurSquidBackup "logs"
        $logProblems = 0
        Get-ChildItem $logFrom -File -ErrorAction SilentlyContinue | ForEach-Object {
            $f = $_
            $dst = Join-Path $logTo $f.Name
            $same = (Test-Path $dst) -and ((Get-Item $dst).Length -eq $f.Length)
            if (-not $same) {
                try { Copy-Item $f.FullName $dst -Force -ErrorAction Stop }
                catch { $logProblems++; Write-Host "    Could not put back log file $($f.Name) ($($_.Exception.Message))" }
            }
        }
        if ($logProblems) { Note "Part of the activity log from before the Squid update could not be put back." }
        else { Write-Host "Activity log kept." }
    } elseif ($owner -eq "other") {
        # So that removal puts the earlier Squid configuration back.
        $old = Join-Path $OtherSquidBackup "etc-squid\squid.conf"
        if (Test-Path $old) {
            $to = Join-Path $root ("etc\squid\squid.conf.pre-blighter-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
            Copy-Item $old $to -Force
            (Get-Item $to).LastWriteTime = Get-Date
        }
    }
    if (-not (Test-Path $StateDir)) { New-Item -ItemType Directory -Path $StateDir -Force | Out-Null }
    Set-Content -Path $ShaFile -Value $hash
}
Remove-SquidExtras
Write-Host "Squid is in $root"
Lock-Folder $root
# The Squid log is written by the service (SYSTEM); the helper reads it as administrator.
Write-Host "Squid folder locked: only administrators can change it."

# ------------------------------------------------------- 5. admin account ---
Step 5 "Administrator account '$Admin'" "a few seconds, plus typing the password"
$user = Get-LocalUser -Name $Admin -ErrorAction SilentlyContinue
$setPw = $true
if ($user) {
    Write-Host "Account '$Admin' already exists."
    if ($KeepPassword) { $setPw = $false; Write-Host "Its password is kept." }
    elseif ($Yes) { $setPw = [bool]$env:BLIGHTER_ADMIN_PASSWORD }
    else { $setPw = Ask "Change its password?" }
}
if ($setPw -and $Yes) {
    if (-not $env:BLIGHTER_ADMIN_PASSWORD) { Die "No password was given for the '$Admin' account." }
    $p1 = ConvertTo-SecureString $env:BLIGHTER_ADMIN_PASSWORD -AsPlainText -Force
    try {
        if ($user) { Set-LocalUser -Name $Admin -Password $p1 }
        else { New-LocalUser -Name $Admin -Password $p1 -FullName "Blighter Restrictor" -Description "Used by the Blighter Restrictor parent app" | Out-Null }
    } catch [Microsoft.PowerShell.Commands.InvalidPasswordException] {
        Die "Windows rejected the password for '$Admin'.  On this PC it may need upper and lower case letters, a digit and a symbol, and it must not contain the word '$Admin'.  Run setup again with a different password."
    } catch { Die "Could not set the password: $($_.Exception.Message)" }
    $setPw = $false
}
if ($setPw) {
    while ($true) {
        $p1 = Read-Host "Choose a password for '$Admin' (you will enter it in the parent app)" -AsSecureString
        $p2 = Read-Host "Type it again" -AsSecureString
        $b1 = [Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR($p1))
        $b2 = [Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR($p2))
        if ($b1 -ne $b2) { Write-Host "They do not match - try again."; continue }
        if ($b1.Length -lt 10) { Write-Host "Use at least 10 characters - this account has full control of the PC."; continue }
        try {
            if ($user) { Set-LocalUser -Name $Admin -Password $p1 }
            else { New-LocalUser -Name $Admin -Password $p1 -FullName "Blighter Restrictor" -Description "Used by the Blighter Restrictor parent app" | Out-Null }
            break
        } catch [Microsoft.PowerShell.Commands.InvalidPasswordException] {
            Write-Host "Windows rejected that password.  On this PC it may need upper and lower case"
            Write-Host "letters, a digit and a symbol, and it must not contain the word '$Admin'.  Try again."
        } catch { Die "Could not set the password: $($_.Exception.Message)" }
    }
}
Set-LocalUser -Name $Admin -PasswordNeverExpires $true -AccountNeverExpires
if ((Get-AdminSids) -notcontains (Get-LocalUser -Name $Admin).SID.Value) {
    Add-LocalGroupMember -SID $SidAdmins -Member $Admin
}
# Hide it from the sign-in screen.
$ul = "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon\SpecialAccounts\UserList"
if (-not (Test-Path $ul)) { New-Item -Path $ul -Force | Out-Null }
New-ItemProperty -Path $ul -Name $Admin -Value 0 -PropertyType DWord -Force | Out-Null

# --------------------------------------------------------------- 6. SSH ---
Step 6 "OpenSSH Server" "2-20 minutes if it has to be installed"
Write-Host "Checking Windows' optional features..."
$cap = Invoke-Slow "checking Windows' optional features" {
    $ErrorActionPreference = "Stop"; $ProgressPreference = "SilentlyContinue"
    Get-WindowsCapability -Online -Name "OpenSSH.Server*" | Select-Object -First 1 Name, State
}
if ($cap -and "$($cap.State)" -ne "Installed") {
    Write-Host "Installing OpenSSH Server from Windows Update (2-20 minutes, depending on the connection)..."
    Invoke-Slow "installing OpenSSH Server" {
        param($name)
        $ErrorActionPreference = "Stop"; $ProgressPreference = "SilentlyContinue"
        Add-WindowsCapability -Online -Name $name | Out-Null
    } @($cap.Name) | Out-Null
}
if (-not (Get-Service sshd -ErrorAction SilentlyContinue)) { Die "OpenSSH Server did not install.  Add it in Settings > System > Optional features." }
Set-Service sshd -StartupType Automatic
Start-Service sshd
$cfg = Join-Path $env:ProgramData "ssh\sshd_config"
if ((Test-Path $cfg) -and (Select-String -Path $cfg -Pattern '^\s*PasswordAuthentication\s+no' -Quiet)) {
    Warn "$cfg has 'PasswordAuthentication no' - the parent app needs password login.  Edit it and restart sshd."
}
Write-Host "SSH server running."

# -------------------------------------------------------------- 7. squid.conf ---
Step 7 "Squid configuration" "under a minute"
$conf = Join-Path $root "etc\squid\squid.conf"
# Keep the first copy of the configuration Blighter found (also put back when
# Squid was replaced above), so removal restores that one.
$preBackups = @(Get-ChildItem (Split-Path $conf) -Filter "squid.conf.pre-blighter-*" -ErrorAction SilentlyContinue)
if ((Test-Path $conf) -and -not $preBackups -and -not ((Get-Content $conf -TotalCount 5) -match "Blighter Restrictor")) {
    $bak = "$conf.pre-blighter-" + (Get-Date -Format "yyyyMMdd-HHmmss")
    Copy-Item $conf $bak
    Write-Host "Existing squid.conf saved as $(Split-Path -Leaf $bak)"
}
# Unix line endings - Squid is a Cygwin program.
$text = (Get-Content (Join-Path $Dest "squid.conf") -Raw) -replace "`r`n", "`n"
[IO.File]::WriteAllText($conf, $text)
$dnsList = ($DnsServers -split '[\s,]+' | Where-Object { $_ -match '^[0-9a-fA-F:.]+$' }) -join " "
if (-not $dnsList) { Die "-DnsServers must be IP addresses, e.g. ""1.1.1.1 8.8.8.8""" }
$blDir = Join-Path $root "etc\squid\blighter"
if (-not (Test-Path $blDir)) { New-Item -ItemType Directory -Path $blDir | Out-Null }
[IO.File]::WriteAllText((Join-Path $blDir "dns.conf"), "dns_nameservers $dnsList`n")
& (Join-Path $Dest "blighter-apply.cmd") init
if ($LASTEXITCODE -ne 0) { Die "blighter-apply init failed." }
# Windows PowerShell 5.1 turns a program's error output into a fatal error under "Stop".
$ErrorActionPreference = "Continue"
$parse = & (Join-Path $root "bin\squid.exe") -k parse -f /etc/squid/squid.conf 2>&1
$parseCode = $LASTEXITCODE
$ErrorActionPreference = "Stop"
if ($parseCode -ne 0) { $parse | Select-Object -Last 15 | Write-Host; Die "Squid rejected the configuration." }
Set-Service squidsrv -StartupType Automatic
Restart-Service squidsrv
Start-Sleep -Seconds 3
if (-not (Get-Process squid -ErrorAction SilentlyContinue)) { Warn "squid.exe is not running yet - the service retries every 20 seconds." }
Write-Host "Squid configured (DNS servers: $dnsList)."

# --------------------------------------------- 8. firewall, proxy, repair ---
Step 8 "Firewall (whole PC), proxy settings and self-repair task" "1-3 minutes"
$code = Start-Slow "setting up the firewall" "powershell.exe" "-NoProfile -ExecutionPolicy Bypass -File `"$System`" enable"
if ($code -ne 0) { Die "Firewall setup failed - see the messages above." }

# ------------------------------------------------------- 9. network type ---
Step 9 "Network type" "a few seconds"
$profiles = @(Get-NetConnectionProfile -ErrorAction SilentlyContinue)
foreach ($np in $profiles) {
    Write-Host ("  {0}: {1}" -f $np.Name, $np.NetworkCategory)
    if ($np.NetworkCategory -eq "Public") {
        Write-Host "  The parent app can only connect while Windows calls the network 'Private'."
        if ($NoMarkPrivate) {
            Write-Host "  Left as Public (as chosen)."
            Note "The network '$($np.Name)' was left as Public - the parent app cannot connect until Windows calls the home network Private."
        } elseif (Ask "  Is '$($np.Name)' your HOME network?  Mark it Private?" "y") {
            Set-NetConnectionProfile -InterfaceIndex $np.InterfaceIndex -NetworkCategory Private
            Add-Content -Path $NetFile -Value ("{0}`t{1}" -f $np.InterfaceAlias, "Public")
            Write-Host "  '$($np.Name)' is now Private (removal sets it back)."
        }
    }
}

Write-StepTime
Remove-Item $Marker -Force -ErrorAction SilentlyContinue
if (Test-Path $OurSquidBackup) { Remove-Item $OurSquidBackup -Recurse -Force -ErrorAction SilentlyContinue }
$SetupDone = $true
} finally {
    # Runs after an error (Die), an unexpected failure, or Ctrl+C.
    if (-not $SetupDone) {
        Write-Host ""
        Write-Host "Setup did NOT finish." -ForegroundColor Red
        if (Test-Path $OurSquidBackup) { Write-Host "Blighter's lists and settings are saved in $OurSquidBackup" }
        if ($Gui) {
            # The installer asks whether to undo.
            Tag ("failed undo={0} rerun={1}" -f [int](Test-Path $PreFile), [int]$WasInstalled)
        } elseif (Test-Path $PreFile) {
            $undo = $true
            Write-Host "Undoing removes Blighter Restrictor completely and puts the PC back as it was"
            Write-Host "before Blighter was first installed (as 'Remove Blighter Child.cmd' does)."
            try { $undo = Ask "Undo now (recommended)?" "y" } catch { $undo = $true }
            if ($undo) {
                Write-Host "Undoing - this can take a few minutes; please wait for 'Done'..."
                & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Dest "blighter-setup.ps1") -Remove -Yes
            } else {
                Write-Host "Left as it is.  Run 'Install Blighter Child.cmd' again to finish setup,"
                Write-Host "or 'Remove Blighter Child.cmd' in $Dest to undo it."
            }
        } else {
            Write-Host "Nothing on the PC had been changed yet, apart from copying files to $Dest."
        }
    }
}

# ---------------------------------------------------------------- summary ---
Say "Setup complete"
# The address to type into the parent app: the home network's (adapter with
# a default route, private address) first.
$routeIfs = @(Get-NetRoute -DestinationPrefix "0.0.0.0/0" -ErrorAction SilentlyContinue | ForEach-Object { $_.ifIndex } | Sort-Object -Unique)
$ips = @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
         Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" } |
         Sort-Object -Property @{ Expression = { [int]($routeIfs -contains $_.InterfaceIndex) * 2 +
                                                 [int]($_.IPAddress -match '^(10\.|192\.168\.|172\.(1[6-9]|2[0-9]|3[01])\.)') } ; Descending = $true } |
         ForEach-Object { $_.IPAddress })
$mainIp = if ($ips.Count) { $ips[0] } else { "" }
Tag ("result child={0}" -f $Child)
Tag ("result admin={0}" -f $Admin)
Tag ("result ip={0}" -f $mainIp)
if ($script:SquidChanged) { Tag "squid-updated" }
Write-Host "On your own PC, open Blighter Restrictor, choose Add and enter:"
Write-Host "  Address       : $mainIp" -ForegroundColor Green
Write-Host "  Child account : $Child$(if ($isAdmin) { '   (ADMINISTRATOR - see warning above)' })"
Write-Host "  Admin login   : $Admin  (and its password)"
Write-Host "Keep this PC switched on and on your home network until the parent app has connected."
Write-Host "If the address changes later, the parent app finds this PC again by itself."
Write-Host "To see these details again: Windows key + R, then C:\ProgramData\BlighterChild\Blighter-Details.cmd"
Write-Host ""
Write-Host "IMPORTANT: on Windows the filter applies to EVERY account on this PC,"
Write-Host "including yours.  The child should sign out and back in once."
Write-Host ""
Write-Host "If something stops working, run 'Pause Blighter Child.cmd' in $Dest"
Write-Host "to switch Blighter off without uninstalling (activity is not recorded while it is"
Write-Host "off); 'Resume ...' or the parent app's Resume filtering switches it on again."
Write-Host "'Remove Blighter Child.cmd' there undoes everything."
if ($script:SquidChanged) {
    Write-Host ""
    Write-Host "Setup finished. Note: Squid, the web filter Blighter uses, has been updated by its"
    Write-Host "maintainer since this version of Blighter was tested. Filtering should work normally."
    Write-Host "If you notice any problems, please email ianp5@pm.me."
}
Tag "done"
