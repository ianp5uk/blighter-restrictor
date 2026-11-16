# -----------------------------------------------------------------------------
# Blighter Restrictor - Windows firewall, proxy and self-repair.
#
# Purpose: make Squid the ONLY way programs on this laptop can reach the web,
# and keep it that way.  Windows Firewall cannot reliably filter outgoing
# traffic per user account (as nftables does on Ubuntu), so on Windows the
# rules apply to the WHOLE LAPTOP - every account on it is filtered.
#
#   * Outgoing traffic is blocked by default on all network profiles.
#   * Allowed out: squid.exe (the filter itself), Windows' own services
#     (DNS, DHCP, time, Windows Update, Defender, network status check),
#     ping, and - unless switched off - UDP 50000-65535 (Discord voice/video).
#   * Every other "allow outgoing" firewall rule (Store apps, games, Xbox...)
#     is switched off; their names are recorded so "disable" can restore them.
#   * Incoming SSH (port 22) is allowed only from the local subnet and only
#     when Windows calls the network "Private" (set your home Wi-Fi to Private).
#   * The child's own proxy setting, Windows' proxy page lock and the Edge,
#     Chrome and Firefox proxy policies all point at Squid (127.0.0.1:3128).
#
# Actions:
#   enable    apply everything above and create the scheduled tasks
#   enforce   re-check and repair (run by the "Enforce" task every 10 minutes,
#             at start-up and at every log-on, as SYSTEM)
#   disable   undo everything (firewall back to Windows defaults, rules that
#             were switched off are switched back on, policies removed)
#   status    print a JSON summary (used by blighter-apply.py "status")
#
# Usage (as administrator):
#   powershell -ExecutionPolicy Bypass -File blighter-system.ps1 enable|enforce|disable|status
#
# Copyright (C) 2026 Ways Property
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version.  It is distributed WITHOUT ANY WARRANTY; see the
# LICENSE file or <https://www.gnu.org/licenses/> for details.
# -----------------------------------------------------------------------------
param([Parameter(Mandatory = $true)][ValidateSet("enable", "enforce", "disable", "status")][string]$Action)

$ErrorActionPreference = "Stop"
$Here       = Split-Path -Parent $MyInvocation.MyCommand.Path
$ChildConf  = Join-Path $Here "child.conf"
$StateDir   = Join-Path $Here "state"
$DisabledDb = Join-Path $StateDir "disabled-rules.txt"
$Group      = "Blighter Restrictor"
$Proxy      = "127.0.0.1:3128"
$TaskPath   = "\Blighter Restrictor\"
$SidAdmins  = "S-1-5-32-544"
# Built-in "Core Networking" rules (DHCP, DNS client, IPv6 neighbour discovery,
# IGMP, ...) are left on: Windows needs them and they are service-specific.
$CoreGroup  = "@FirewallAPI.dll,-25000"

function Get-SquidRoot {
    try {
        $p = (Get-ItemProperty -Path "HKLM:\SOFTWARE\Squid" -Name InstallDir -ErrorAction Stop).InstallDir
        if ($p) { return $p.TrimEnd('\') }
    } catch { }
    return "C:\Squid"
}
$SquidRoot = Get-SquidRoot
$SquidExe  = Join-Path $SquidRoot "bin\squid.exe"
$SquidSvc  = Join-Path $SquidRoot "bin\Diladele.Squid.Service.exe"

function Read-ChildConf {
    $c = @{ CHILD_USER = ""; CHILD_SID = ""; ALLOW_VOICE_UDP = "yes" }
    if (Test-Path $ChildConf) {
        foreach ($line in Get-Content $ChildConf) {
            if ($line -match '^\s*([A-Z_]+)\s*=\s*"?(.*?)"?\s*$') { $c[$Matches[1]] = $Matches[2] }
        }
    }
    return $c
}

function Write-BLog([string]$msg) {
    if (-not (Test-Path $StateDir)) { New-Item -ItemType Directory -Path $StateDir -Force | Out-Null }
    $line = "{0}  {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
    $log = Join-Path $StateDir "enforce.log"
    if ((Test-Path $log) -and (Get-Item $log).Length -gt 1MB) { Move-Item $log "$log.old" -Force }
    Add-Content -Path $log -Value $line
    if ($Action -ne "status") { Write-Host $msg }
}

# ----------------------------------------------------------------- firewall ---
function Get-WantedRules([bool]$voice) {
    $svchost = "%SystemRoot%\System32\svchost.exe"
    $rules = @(
        @{ Name = "BR-Squid";        Display = "Blighter: Squid web filter";            Program = $SquidExe },
        @{ Name = "BR-SquidService"; Display = "Blighter: Squid service update check";  Program = $SquidSvc; Protocol = "TCP"; RemotePort = "443" },
        @{ Name = "BR-DNS-UDP";      Display = "Blighter: DNS client (UDP)";            Program = $svchost; Service = "Dnscache"; Protocol = "UDP"; RemotePort = "53" },
        @{ Name = "BR-DNS-TCP";      Display = "Blighter: DNS client (TCP)";            Program = $svchost; Service = "Dnscache"; Protocol = "TCP"; RemotePort = "53" },
        @{ Name = "BR-DHCP";         Display = "Blighter: DHCP client";                 Program = $svchost; Service = "Dhcp";     Protocol = "UDP"; RemotePort = "67" },
        @{ Name = "BR-Time";         Display = "Blighter: Windows time";                Program = $svchost; Service = "W32Time";  Protocol = "UDP"; RemotePort = "123" },
        @{ Name = "BR-NCSI";         Display = "Blighter: network status check";        Program = $svchost; Service = "NlaSvc";   Protocol = "TCP"; RemotePort = "80" },
        @{ Name = "BR-WU";           Display = "Blighter: Windows Update";              Program = $svchost; Service = "wuauserv"; Protocol = "TCP"; RemotePort = @("80", "443") },
        @{ Name = "BR-UsoSvc";       Display = "Blighter: Update orchestrator";         Program = $svchost; Service = "UsoSvc";   Protocol = "TCP"; RemotePort = @("80", "443") },
        @{ Name = "BR-BITS";         Display = "Blighter: background downloads (BITS)"; Program = $svchost; Service = "BITS";     Protocol = "TCP"; RemotePort = @("80", "443") },
        @{ Name = "BR-DoSvc";        Display = "Blighter: delivery optimisation";       Program = $svchost; Service = "DoSvc";    Protocol = "TCP" },
        @{ Name = "BR-CryptSvc";     Display = "Blighter: certificate updates";         Program = $svchost; Service = "CryptSvc"; Protocol = "TCP"; RemotePort = @("80", "443") },
        @{ Name = "BR-wlidsvc";      Display = "Blighter: Microsoft account sign-in";   Program = $svchost; Service = "wlidsvc";  Protocol = "TCP"; RemotePort = "443" },
        @{ Name = "BR-Defender";     Display = "Blighter: Microsoft Defender";          Service = "WinDefend"; Protocol = "TCP"; RemotePort = @("80", "443") },
        @{ Name = "BR-EdgeUpdate";   Display = "Blighter: Edge updates";                Program = "${env:ProgramFiles(x86)}\Microsoft\EdgeUpdate\MicrosoftEdgeUpdate.exe"; Protocol = "TCP"; RemotePort = @("80", "443") },
        @{ Name = "BR-Ping4";        Display = "Blighter: ping";                        Protocol = "ICMPv4" }
    )
    if ($voice) {
        $rules += @{ Name = "BR-Voice"; Display = "Blighter: Discord voice/video (UDP 50000-65535)"; Protocol = "UDP"; RemotePort = "50000-65535" }
    }
    return $rules
}

function Set-BlighterRule($r, [string]$direction = "Outbound", [bool]$force = $true) {
    $existing = Get-NetFirewallRule -Name $r.Name -ErrorAction SilentlyContinue
    if ($existing -and -not $force -and $existing.Enabled -eq "True") { return }
    if ($existing) { Remove-NetFirewallRule -Name $r.Name }
    $p = @{ Name = $r.Name; DisplayName = $r.Display; Group = $Group; Direction = $direction;
            Action = "Allow"; Profile = "Any"; Enabled = "True" }
    foreach ($k in "Program", "Service", "Protocol", "RemotePort", "LocalPort", "RemoteAddress") {
        if ($r.ContainsKey($k)) { $p[$k] = $r[$k] }
    }
    if ($r.ContainsKey("Profile")) { $p.Profile = $r.Profile }
    New-NetFirewallRule @p | Out-Null
}

function Get-SshRule {
    return @{ Name = "BR-SSH-In"; Display = "Blighter: parent app SSH (home network only)";
              Program = "%SystemRoot%\System32\OpenSSH\sshd.exe"; Protocol = "TCP"; LocalPort = "22";
              RemoteAddress = "LocalSubnet"; Profile = "Private" }
}

function Get-OtherOutboundAllowRules {
    # Enabled "allow outgoing" rules that are not ours and not Core Networking.
    Get-NetFirewallRule -Direction Outbound -Action Allow -Enabled True -ErrorAction SilentlyContinue |
        Where-Object { $_.Group -ne $Group -and $_.Group -ne $CoreGroup -and $_.DisplayGroup -ne "Core Networking" }
}

function Disable-OtherOutboundRules {
    $known = @()
    if (Test-Path $DisabledDb) { $known = @(Get-Content $DisabledDb) }
    $count = 0; $failed = 0
    foreach ($rule in @(Get-OtherOutboundAllowRules)) {
        try {
            # Only rules in the local store can be changed; others (e.g. Group Policy) are reported.
            Set-NetFirewallRule -Name $rule.Name -Enabled False -PolicyStore PersistentStore -ErrorAction Stop
            if ($known -notcontains $rule.Name) { Add-Content -Path $DisabledDb -Value $rule.Name; $known += $rule.Name }
            $count++
        } catch { $failed++ }
    }
    if ($count) { Write-BLog "Switched off $count other outgoing allow rule(s)." }
    if ($failed) { Write-BLog "WARNING: $failed outgoing allow rule(s) could not be switched off." }
}

function Enable-Firewall([bool]$voice, [bool]$force = $true) {
    # $force = $false (repairs): only re-create rules that are missing or switched off.
    if (-not (Test-Path $StateDir)) { New-Item -ItemType Directory -Path $StateDir -Force | Out-Null }
    foreach ($r in Get-WantedRules $voice) { Set-BlighterRule $r "Outbound" $force }
    if (-not $voice) { Remove-NetFirewallRule -Name "BR-Voice" -ErrorAction SilentlyContinue }
    Set-BlighterRule (Get-SshRule) "Inbound" $force
    # Windows' own OpenSSH rule allows port 22 from anywhere on every profile - ours replaces it.
    Get-NetFirewallRule -Name "OpenSSH-Server-In-TCP" -ErrorAction SilentlyContinue |
        Where-Object { $_.Enabled -eq "True" } | ForEach-Object {
            Set-NetFirewallRule -Name $_.Name -Enabled False
            Add-Content -Path $DisabledDb -Value $_.Name
        }
    Disable-OtherOutboundRules
    Set-NetFirewallProfile -Profile Domain, Private, Public -Enabled True -DefaultOutboundAction Block
}

function Test-FirewallOk([bool]$voice) {
    $problems = @()
    foreach ($p in Get-NetFirewallProfile -PolicyStore ActiveStore) {
        if ($p.Enabled -ne "True") { $problems += "Firewall is OFF for the $($p.Name) profile" }
        if ($p.DefaultOutboundAction -ne "Block") { $problems += "Outgoing traffic is not blocked by default ($($p.Name) profile)" }
    }
    $names = @((Get-WantedRules $voice).Name) + "BR-SSH-In"
    foreach ($n in $names) {
        $r = Get-NetFirewallRule -Name $n -ErrorAction SilentlyContinue
        if (-not $r) { $problems += "Rule $n is missing" }
        elseif ($r.Enabled -ne "True") { $problems += "Rule $n is switched off" }
    }
    $others = @(Get-OtherOutboundAllowRules)
    if ($others.Count) { $problems += "$($others.Count) other outgoing allow rule(s) are on: " + (($others | Select-Object -First 5 | ForEach-Object { $_.DisplayName }) -join "; ") }
    return ,$problems
}

function Disable-Firewall {
    Get-NetFirewallRule -Group $Group -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    if (Test-Path $DisabledDb) {
        foreach ($n in Get-Content $DisabledDb | Sort-Object -Unique) {
            Set-NetFirewallRule -Name $n -Enabled True -ErrorAction SilentlyContinue
        }
        Remove-Item $DisabledDb -Force
    }
    Set-NetFirewallProfile -Profile Domain, Private, Public -DefaultOutboundAction NotConfigured
}

# -------------------------------------------------------------------- proxy ---
$PolicyKeys = @{
    "HKLM:\SOFTWARE\Policies\Microsoft\Edge"  = "ProxySettings"
    "HKLM:\SOFTWARE\Policies\Google\Chrome"   = "ProxySettings"
}
$ProxyJson = '{"ProxyMode":"fixed_servers","ProxyServer":"' + $Proxy + '","ProxyBypassList":"<local>"}'
$FirefoxKey = "HKLM:\SOFTWARE\Policies\Mozilla\Firefox\Proxy"
$IeLockKey  = "HKLM:\SOFTWARE\Policies\Microsoft\Internet Explorer\Control Panel"

function Set-RegValue($path, $name, $value, $type = "String") {
    if (-not (Test-Path $path)) { New-Item -Path $path -Force | Out-Null }
    New-ItemProperty -Path $path -Name $name -Value $value -PropertyType $type -Force | Out-Null
}

function Enable-ProxyPolicies {
    foreach ($k in $PolicyKeys.Keys) { Set-RegValue $k $PolicyKeys[$k] $ProxyJson }
    Set-RegValue $FirefoxKey "Mode" "manual"
    Set-RegValue $FirefoxKey "HTTPProxy" $Proxy
    Set-RegValue $FirefoxKey "SSLProxy" $Proxy
    Set-RegValue $FirefoxKey "UseHTTPProxyForAllProtocols" 1 "DWord"
    Set-RegValue $FirefoxKey "Passthrough" "localhost, 127.0.0.1"
    Set-RegValue $FirefoxKey "Locked" 1 "DWord"
    # Greys out the proxy page in Windows' settings (best effort on newer Windows).
    Set-RegValue $IeLockKey "Proxy" 1 "DWord"
}

function Disable-ProxyPolicies {
    foreach ($k in $PolicyKeys.Keys) { Remove-ItemProperty -Path $k -Name $PolicyKeys[$k] -ErrorAction SilentlyContinue }
    Remove-Item -Path $FirefoxKey -Recurse -Force -ErrorAction SilentlyContinue
    Remove-ItemProperty -Path $IeLockKey -Name "Proxy" -ErrorAction SilentlyContinue
}

function Test-ProxyPolicies {
    foreach ($k in $PolicyKeys.Keys) {
        $v = (Get-ItemProperty -Path $k -Name $PolicyKeys[$k] -ErrorAction SilentlyContinue).($PolicyKeys[$k])
        if ($v -ne $ProxyJson) { return $false }
    }
    return [bool](Get-ItemProperty -Path $FirefoxKey -Name "HTTPProxy" -ErrorAction SilentlyContinue)
}

function Get-ChildHive([string]$sid, [ref]$loadedByUs) {
    # The child's registry (HKCU) is loaded while they are logged on; otherwise load it from disk.
    $loadedByUs.Value = $false
    if (-not $sid) { return $null }
    if (Test-Path "Registry::HKEY_USERS\$sid") { return "Registry::HKEY_USERS\$sid" }
    $prof = (Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\ProfileList\$sid" -ErrorAction SilentlyContinue).ProfileImagePath
    if (-not $prof) { return $null }
    $dat = Join-Path $prof "NTUSER.DAT"
    if (-not (Test-Path $dat)) { return $null }
    $ErrorActionPreference = "Continue"   # reg.exe messages must not be fatal
    & reg.exe load "HKU\BlighterChild" "$dat" 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { return $null }
    $loadedByUs.Value = $true
    return "Registry::HKEY_USERS\BlighterChild"
}

function Close-ChildHive([bool]$loadedByUs) {
    if ($loadedByUs) {
        $ErrorActionPreference = "Continue"
        [GC]::Collect(); [GC]::WaitForPendingFinalizers()
        & reg.exe unload "HKU\BlighterChild" 2>&1 | Out-Null
    }
}

function Set-ChildProxy([string]$sid, [bool]$on) {
    $loaded = $false
    $hive = Get-ChildHive $sid ([ref]$loaded)
    if (-not $hive) { return "unavailable" }
    try {
        $k = "$hive\Software\Microsoft\Windows\CurrentVersion\Internet Settings"
        if (-not (Test-Path $k)) { New-Item -Path $k -Force | Out-Null }
        $cur = Get-ItemProperty -Path $k -ErrorAction SilentlyContinue
        if ($on) {
            if ($cur.ProxyEnable -ne 1 -or $cur.ProxyServer -ne $Proxy -or $cur.AutoConfigURL) {
                Set-RegValue $k "ProxyEnable" 1 "DWord"
                Set-RegValue $k "ProxyServer" $Proxy
                Set-RegValue $k "ProxyOverride" "<local>"
                Remove-ItemProperty -Path $k -Name "AutoConfigURL" -ErrorAction SilentlyContinue
                # Make Windows rebuild its cached copy from the values above.
                Remove-ItemProperty -Path "$k\Connections" -Name "DefaultConnectionSettings", "SavedLegacySettings" -ErrorAction SilentlyContinue
                Write-BLog "Child's proxy setting (re)applied."
            }
            return "set"
        } else {
            if ($cur.ProxyServer -eq $Proxy) {
                Set-RegValue $k "ProxyEnable" 0 "DWord"
                Remove-ItemProperty -Path $k -Name "ProxyServer", "ProxyOverride" -ErrorAction SilentlyContinue
                Remove-ItemProperty -Path "$k\Connections" -Name "DefaultConnectionSettings", "SavedLegacySettings" -ErrorAction SilentlyContinue
            }
            return "cleared"
        }
    } finally { Close-ChildHive $loaded }
}

# ------------------------------------------------------------ admin checks ---
function Get-AdminSids {
    $sids = @()
    try {
        $sids = @(Get-LocalGroupMember -SID $SidAdmins -ErrorAction Stop | ForEach-Object { $_.SID.Value })
    } catch {
        # Get-LocalGroupMember fails on some PCs (orphaned or cloud accounts) - use ADSI instead.
        $name = (New-Object Security.Principal.SecurityIdentifier $SidAdmins).Translate([Security.Principal.NTAccount]).Value.Split('\')[-1]
        $g = [ADSI]"WinNT://$env:COMPUTERNAME/$name,group"
        foreach ($m in @($g.psbase.Invoke("Members"))) {
            $bytes = $m.GetType().InvokeMember("objectSid", "GetProperty", $null, $m, $null)
            $sids += (New-Object Security.Principal.SecurityIdentifier($bytes, 0)).Value
        }
    }
    return $sids
}

function Get-AdminNames {
    $names = @()
    foreach ($s in Get-AdminSids) {
        try { $names += (New-Object Security.Principal.SecurityIdentifier $s).Translate([Security.Principal.NTAccount]).Value }
        catch { $names += $s }
    }
    return $names
}

# ------------------------------------------------------------------ tasks ---
function Register-Tasks {
    $ps = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
    $me = Join-Path $Here "blighter-system.ps1"
    $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
                    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) -MultipleInstances IgnoreNew
    $act = New-ScheduledTaskAction -Execute $ps -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$me`" enforce"
    $every = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 10)
    $boot = New-ScheduledTaskTrigger -AtStartup
    $logon = New-ScheduledTaskTrigger -AtLogOn
    Register-ScheduledTask -TaskName "Enforce" -TaskPath $TaskPath -Action $act -Trigger @($every, $boot, $logon) `
        -Principal $principal -Settings $settings -Description "Blighter Restrictor: keep web filtering in force" -Force | Out-Null

    $rot = New-ScheduledTaskAction -Execute $SquidExe -Argument "-k rotate -f /etc/squid/squid.conf"
    $daily = New-ScheduledTaskTrigger -Daily -At "03:00"
    Register-ScheduledTask -TaskName "Rotate Squid log" -TaskPath $TaskPath -Action $rot -Trigger $daily `
        -Principal $principal -Settings $settings -Description "Blighter Restrictor: start a new Squid log each day" -Force | Out-Null
}

function Unregister-Tasks {
    Get-ScheduledTask -TaskPath $TaskPath -ErrorAction SilentlyContinue | Unregister-ScheduledTask -Confirm:$false
}

# --------------------------------------------------------------- services ---
function Confirm-Services {
    foreach ($svc in "squidsrv", "sshd") {
        $s = Get-Service -Name $svc -ErrorAction SilentlyContinue
        if (-not $s) { Write-BLog "WARNING: service $svc is not installed."; continue }
        if ($s.StartType -ne "Automatic") { Set-Service -Name $svc -StartupType Automatic }
        if ($s.Status -ne "Running") {
            try { Start-Service -Name $svc; Write-BLog "Service $svc was stopped - started it." }
            catch { Write-BLog "WARNING: could not start $svc ($($_.Exception.Message))" }
        }
    }
}

# ----------------------------------------------------------------- actions ---
$conf  = Read-ChildConf
$voice = $conf.ALLOW_VOICE_UDP -ne "no"

switch ($Action) {
    "enable" {
        Enable-Firewall $voice
        Enable-ProxyPolicies
        $r = Set-ChildProxy $conf.CHILD_SID $true
        if ($r -eq "unavailable") {
            Write-BLog "The child's proxy setting will be applied when they first log on (their profile does not exist yet)."
        }
        Register-Tasks
        Confirm-Services
        Write-BLog "Blighter firewall and proxy enabled."
    }
    "enforce" {
        # Each check is separate so one failure does not stop the others.
        try {
            $problems = Test-FirewallOk $voice
            if ($problems.Count) {
                Write-BLog ("Repairing: " + ($problems -join " | "))
                Enable-Firewall $voice $false
            }
        } catch { Write-BLog "ERROR (firewall): $($_.Exception.Message)" }
        try {
            if (-not (Test-ProxyPolicies)) { Write-BLog "Repairing browser proxy policies."; Enable-ProxyPolicies }
            # Only touch the child's settings while they are logged on (hive already loaded).
            if ($conf.CHILD_SID -and (Test-Path "Registry::HKEY_USERS\$($conf.CHILD_SID)")) { Set-ChildProxy $conf.CHILD_SID $true | Out-Null }
        } catch { Write-BLog "ERROR (proxy): $($_.Exception.Message)" }
        try { Confirm-Services } catch { Write-BLog "ERROR (services): $($_.Exception.Message)" }
    }
    "disable" {
        Unregister-Tasks
        Disable-Firewall
        Disable-ProxyPolicies
        Set-ChildProxy $conf.CHILD_SID $false | Out-Null
        Write-BLog "Blighter firewall and proxy removed."
    }
    "status" {
        $ErrorActionPreference = "Continue"
        $problems = Test-FirewallOk $voice
        $warnings = @()
        $adminSids = @(Get-AdminSids)
        $childAdmin = $null
        if ($conf.CHILD_SID) { $childAdmin = $adminSids -contains $conf.CHILD_SID }
        if ($childAdmin) { $warnings += "The child's account is an ADMINISTRATOR - they can undo all of this." }
        $prof = @(Get-NetConnectionProfile -ErrorAction SilentlyContinue | ForEach-Object { "$($_.Name): $($_.NetworkCategory)" })
        $lines = @()
        $lines += "Profiles:"
        foreach ($p in Get-NetFirewallProfile -PolicyStore ActiveStore) {
            $lines += ("  {0,-8} enabled={1}  outbound default={2}" -f $p.Name, $p.Enabled, $p.DefaultOutboundAction)
        }
        $lines += ""
        $lines += "Blighter rules:"
        foreach ($r in Get-NetFirewallRule -Group $Group -ErrorAction SilentlyContinue | Sort-Object Name) {
            $port = ($r | Get-NetFirewallPortFilter)
            $app = ($r | Get-NetFirewallApplicationFilter)
            $svc = ($r | Get-NetFirewallServiceFilter).Service
            $what = @()
            if ($app.Program -and $app.Program -ne "Any") { $what += $app.Program }
            if ($svc -and $svc -ne "Any") { $what += "service $svc" }
            if ($port.Protocol -and $port.Protocol -ne "Any") { $what += $port.Protocol }
            if ($port.RemotePort -and "$($port.RemotePort)" -ne "Any") { $what += "remote port " + ($port.RemotePort -join ",") }
            if ($port.LocalPort -and "$($port.LocalPort)" -ne "Any") { $what += "local port " + ($port.LocalPort -join ",") }
            $lines += ("  {0,-8} {1,-16} on={2,-5} {3}" -f $r.Direction, $r.Name, $r.Enabled, ($what -join "  "))
        }
        $lines += ""
        $lines += "Network: " + ($prof -join "; ")
        if ($problems.Count) { $lines += ""; $lines += "Problems:"; $problems | ForEach-Object { $lines += "  $_" } }
        $osv = (Get-CimInstance Win32_OperatingSystem -ErrorAction SilentlyContinue)
        [pscustomobject]@{
            firewall_active = ($problems.Count -eq 0)
            firewall_rules  = ($lines -join "`n")
            proxy_locked    = (Test-ProxyPolicies)
            child_is_admin  = $childAdmin
            other_admins    = @(Get-AdminNames)
            network_profile = ($prof -join "; ")
            os_version      = if ($osv) { "$($osv.Caption) ($($osv.Version))" } else { "Windows" }
            warnings        = $warnings
        } | ConvertTo-Json -Depth 4 -Compress
    }
}
