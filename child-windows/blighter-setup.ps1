# -----------------------------------------------------------------------------
# Blighter Restrictor - one-time setup of a child's WINDOWS laptop.
#
# Purpose: prepare this laptop so the parent app can manage it over the home
# network.  Safe to run again.  Normally started by "Install Blighter
# Child.cmd" (which asks for administrator rights).  It:
#   1. checks the child's account and WARNS if it is an administrator
#   2. installs Squid for Windows (Diladele MSI) if missing, and locks its
#      folder so only administrators can change it
#   3. copies the helper and its private Python to C:\ProgramData\BlighterChild
#      (locked the same way) and records the child's account (child.conf)
#   4. creates the hidden "blighter" administrator account (password login
#      over SSH) that the parent app uses
#   5. installs and starts Windows' own OpenSSH Server
#   6. replaces squid.conf with the Blighter one (old file backed up)
#   7. turns on the whole-laptop firewall, the proxy settings and the
#      self-repair task (blighter-system.ps1 enable)
#   8. offers to mark the current network as Private (needed for SSH)
#
# Usage (PowerShell as administrator):
#   blighter-setup.ps1 [-Child <username>] [-NoVoice] [-DnsServers "1.1.1.1 8.8.8.8"]
#   blighter-setup.ps1 -Remove [-Yes]        undo everything (Squid stays installed)
# -Yes answers every question with its default (for automated tests); the
# blighter password is then taken from the BLIGHTER_ADMIN_PASSWORD
# environment variable.
#
# Copyright (C) 2026 Ways Property
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
    [switch]$Yes
)

$ErrorActionPreference = "Stop"
$Version   = "1.2.0"
$Admin     = "blighter"
$Dest      = Join-Path $env:ProgramData "BlighterChild"
$Src       = Split-Path -Parent $MyInvocation.MyCommand.Path
$SquidUrl  = "https://www.diladele.com/pkg/squid/7.8/squid-7.8_amd64.msi"
$SquidPage = "https://www.diladele.com/squid/download.html"
$SidAdmins = "S-1-5-32-544"
$SidUsers  = "S-1-5-32-545"
$SidSystem = "S-1-5-18"

function Say($m)  { Write-Host ""; Write-Host "==> $m" -ForegroundColor Cyan }
function Warn($m) { Write-Host "WARNING: $m" -ForegroundColor Yellow }
function Die($m)  { Write-Host "ERROR: $m" -ForegroundColor Red; exit 1 }
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

# ----------------------------------------------------------------- removal ---
if ($Remove) {
    Say "Removing Blighter Restrictor from this laptop"
    $sys = Join-Path $Dest "blighter-system.ps1"
    if (Test-Path $sys) { & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $sys disable }
    $root = Get-SquidRoot
    if ($root) {
        $conf = Join-Path $root "etc\squid\squid.conf"
        $backup = Get-ChildItem (Join-Path $root "etc\squid") -Filter "squid.conf.pre-blighter-*" -ErrorAction SilentlyContinue |
                  Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if ($backup) { Copy-Item $backup.FullName $conf -Force; Write-Host "Restored $($backup.Name) -> squid.conf" }
        Restart-Service squidsrv -ErrorAction SilentlyContinue
        Write-Host "Squid for Windows is still installed (remove it in Settings > Apps if you wish)."
    }
    if (Get-LocalUser -Name $Admin -ErrorAction SilentlyContinue) {
        if (Ask "Delete the '$Admin' administrator account too?") {
            Remove-LocalUser -Name $Admin
            Remove-ItemProperty "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon\SpecialAccounts\UserList" -Name $Admin -ErrorAction SilentlyContinue
            Write-Host "Account '$Admin' deleted (its profile folder in C:\Users may remain)."
        } else { Write-Host "Account '$Admin' kept." }
    }
    Write-Host ""
    Write-Host "Done.  You can now delete the folder $Dest."
    Write-Host "OpenSSH Server was left installed (Settings > System > Optional features)."
    exit 0
}

# ------------------------------------------------------ 1. child account ---
Say "1/8 The child's account"
$locals = @(Get-LocalUser | Where-Object { $_.Enabled -and $_.Name -ne $Admin -and $_.Name -notin @("Administrator", "Guest", "DefaultAccount", "WDAGUtilityAccount") })
if (-not $Child) {
    Write-Host "Accounts on this laptop:"
    $locals | ForEach-Object { Write-Host ("   {0,-20} {1}" -f $_.Name, $_.FullName) }
    $Child = Read-Host "Which account is the child's? (type the name in the first column)"
}
$Child = $Child.Trim()
if (-not $Child) { Die "No account given." }
if ($Child -eq $Admin) { Die "'$Admin' cannot be the child's account." }
try {
    $childSid = (New-Object Security.Principal.NTAccount($Child)).Translate([Security.Principal.SecurityIdentifier]).Value
} catch { Die "There is no account called '$Child' on this laptop." }
$isAdmin = (Get-AdminSids) -contains $childSid
if ($isAdmin) {
    Write-Host ""
    Write-Host "  *****************************************************************" -ForegroundColor Red
    Write-Host "  '$Child' is an ADMINISTRATOR on this laptop." -ForegroundColor Red
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
}

# ------------------------------------------------------------- 2. Squid ---
Say "2/8 Squid for Windows"
$root = Get-SquidRoot
if (-not $root) {
    Write-Host "Squid is not installed - downloading it from Diladele..."
    $msi = Join-Path $env:TEMP "squid-blighter.msi"
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri $SquidUrl -OutFile $msi -UseBasicParsing
    } catch {
        Die "Download failed ($($_.Exception.Message)).  Install Squid yourself from $SquidPage and run this again."
    }
    $p = Start-Process msiexec.exe -ArgumentList "/i `"$msi`" /qn /norestart INSTALLFOLDER=`"C:\Squid\`"" -Wait -PassThru
    if ($p.ExitCode -ne 0 -and $p.ExitCode -ne 3010) { Die "The Squid installer failed (code $($p.ExitCode))." }
    Remove-Item $msi -Force -ErrorAction SilentlyContinue
    $root = Get-SquidRoot
    if (-not $root) { Die "Squid did not install correctly." }
}
Write-Host "Squid is in $root"
Lock-Folder $root
# The Squid log is written by the service (SYSTEM); the helper reads it as administrator.
Write-Host "Squid folder locked: only administrators can change it."

# --------------------------------------------------------- 3. helper files ---
Say "3/8 Helper files in $Dest"
if (-not (Test-Path $Dest)) { New-Item -ItemType Directory -Path $Dest | Out-Null }
Lock-Folder $Dest
if ((Resolve-Path $Src).Path.TrimEnd('\') -ne (Resolve-Path $Dest).Path.TrimEnd('\')) {
    foreach ($item in "blighter-apply.py", "blighter-apply.cmd", "blighter-system.ps1", "blighter-setup.ps1",
                      "domains.py", "squid.conf", "python", "LICENSE.txt", "Remove Blighter Child.cmd") {
        $from = Join-Path $Src $item
        if (-not (Test-Path $from)) { Die "Missing file $item next to this script - unzip the whole package first." }
        Copy-Item $from $Dest -Recurse -Force
    }
}
Get-ChildItem $Dest -Recurse -File | Unblock-File -ErrorAction SilentlyContinue
Lock-Folder $Dest
$voice = if ($NoVoice) { "no" } else { "yes" }
@"
# Blighter Restrictor - which account on this laptop is the child's.
# Written by blighter-setup.ps1 $Version.  On Windows the firewall filters the
# whole laptop; CHILD_USER is used for the proxy setting and admin warnings.
CHILD_USER="$Child"
CHILD_SID="$childSid"
# yes = allow outgoing UDP 50000-65535 (Discord voice/video calls)
ALLOW_VOICE_UDP="$voice"
"@ | Set-Content -Path (Join-Path $Dest "child.conf") -Encoding ASCII
& (Join-Path $Dest "python\python.exe") -I -c "print('Bundled Python OK')"
if ($LASTEXITCODE -ne 0) { Die "The bundled Python does not run on this laptop." }

# ------------------------------------------------------- 4. admin account ---
Say "4/8 Administrator account '$Admin'"
$user = Get-LocalUser -Name $Admin -ErrorAction SilentlyContinue
$setPw = $true
if ($user) {
    Write-Host "Account '$Admin' already exists."
    $setPw = Ask "Change its password?"
}
if ($setPw -and $Yes -and $env:BLIGHTER_ADMIN_PASSWORD) {
    $p1 = ConvertTo-SecureString $env:BLIGHTER_ADMIN_PASSWORD -AsPlainText -Force
    try {
        if ($user) { Set-LocalUser -Name $Admin -Password $p1 }
        else { New-LocalUser -Name $Admin -Password $p1 -FullName "Blighter Restrictor" -Description "Used by the Blighter Restrictor parent app" | Out-Null }
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
        if ($b1.Length -lt 10) { Write-Host "Use at least 10 characters - this account has full control of the laptop."; continue }
        break
    }
    try {
        if ($user) { Set-LocalUser -Name $Admin -Password $p1 }
        else { New-LocalUser -Name $Admin -Password $p1 -FullName "Blighter Restrictor" -Description "Used by the Blighter Restrictor parent app" | Out-Null }
    } catch { Die "Could not set the password: $($_.Exception.Message)" }
}
Set-LocalUser -Name $Admin -PasswordNeverExpires $true -AccountNeverExpires
if ((Get-AdminSids) -notcontains (Get-LocalUser -Name $Admin).SID.Value) {
    Add-LocalGroupMember -SID $SidAdmins -Member $Admin
}
# Hide it from the sign-in screen.
$ul = "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon\SpecialAccounts\UserList"
if (-not (Test-Path $ul)) { New-Item -Path $ul -Force | Out-Null }
New-ItemProperty -Path $ul -Name $Admin -Value 0 -PropertyType DWord -Force | Out-Null

# --------------------------------------------------------------- 5. SSH ---
Say "5/8 OpenSSH Server"
$cap = Get-WindowsCapability -Online -Name "OpenSSH.Server*" | Select-Object -First 1
if ($cap -and $cap.State -ne "Installed") {
    Write-Host "Installing OpenSSH Server (this can take a few minutes)..."
    Add-WindowsCapability -Online -Name $cap.Name | Out-Null
}
if (-not (Get-Service sshd -ErrorAction SilentlyContinue)) { Die "OpenSSH Server did not install.  Add it in Settings > System > Optional features." }
Set-Service sshd -StartupType Automatic
Start-Service sshd
$cfg = Join-Path $env:ProgramData "ssh\sshd_config"
if ((Test-Path $cfg) -and (Select-String -Path $cfg -Pattern '^\s*PasswordAuthentication\s+no' -Quiet)) {
    Warn "$cfg has 'PasswordAuthentication no' - the parent app needs password login.  Edit it and restart sshd."
}
Write-Host "SSH server running."

# -------------------------------------------------------------- 6. squid.conf ---
Say "6/8 Squid configuration"
$conf = Join-Path $root "etc\squid\squid.conf"
if ((Test-Path $conf) -and -not ((Get-Content $conf -TotalCount 5) -match "Blighter Restrictor")) {
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

# --------------------------------------------- 7. firewall, proxy, repair ---
Say "7/8 Firewall (whole laptop), proxy settings and self-repair task"
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Dest "blighter-system.ps1") enable
if ($LASTEXITCODE -ne 0) { Die "Firewall setup failed - see the messages above." }

# ------------------------------------------------------- 8. network type ---
Say "8/8 Network type"
$profiles = @(Get-NetConnectionProfile -ErrorAction SilentlyContinue)
foreach ($np in $profiles) {
    Write-Host ("  {0}: {1}" -f $np.Name, $np.NetworkCategory)
    if ($np.NetworkCategory -eq "Public") {
        Write-Host "  The parent app can only connect while Windows calls the network 'Private'."
        if (Ask "  Is '$($np.Name)' your HOME network?  Mark it Private?" "y") {
            Set-NetConnectionProfile -InterfaceIndex $np.InterfaceIndex -NetworkCategory Private
            Write-Host "  '$($np.Name)' is now Private."
        }
    }
}

# ---------------------------------------------------------------- summary ---
Say "Setup complete"
$ips = @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
         Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" } |
         ForEach-Object { $_.IPAddress })
Write-Host "Child account : $Child$(if ($isAdmin) { '   (ADMINISTRATOR - see warning above)' })"
Write-Host "Admin account : $Admin  (use this login and its password in the parent app)"
Write-Host "IPv4 address  : $($ips -join ' ')"
Write-Host "Tip: reserve this address for the laptop in your router's DHCP settings."
Write-Host ""
Write-Host "IMPORTANT: on Windows the filter applies to EVERY account on this laptop,"
Write-Host "including yours.  The child should sign out and back in once."
