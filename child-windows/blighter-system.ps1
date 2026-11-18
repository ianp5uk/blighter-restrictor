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
#     ping, and - unless switched off - UDP 50000-65535 (Discord voice/video)
#     and the home network (HOME_NETS in child.conf: printers, NAS drives...;
#     Blighter controls internet access only).
#   * Every other "allow outgoing" firewall rule (Store apps, games, Xbox...)
#     is switched off; their names are recorded so they can be switched on again.
#   * Incoming SSH (port 22) is allowed only from the local subnet or the
#     recorded home network (HOME_NETS, even with home network access off -
#     Windows sometimes works out "local subnet" wrongly after a cold start),
#     and only when Windows calls the network "Private" (set your home Wi-Fi
#     to Private).
#   * The child's own proxy setting, Windows' proxy page lock and the Edge,
#     Chrome, Brave, Vivaldi and Firefox proxy policies all point at Squid
#     (127.0.0.1:3128).
#
# Before the first change, "capture" saves how the laptop was set up
# (state\pre-install.json: firewall defaults, browser proxy policies, the
# child's own proxy setting, whether OpenSSH / Squid / the blighter account
# already existed).  "pause" and "disable" put back exactly that.
#
# Actions:
#   capture   save the "before" state (only the first time; never overwritten)
#   enable    apply everything above and create the scheduled tasks
#   enforce   re-check and repair (run by the "Enforce" task every 10 minutes,
#             at start-up and at every log-on, as SYSTEM); does nothing while paused
#   pause     switch filtering off but leave everything installed: firewall,
#             browser policies and the child's proxy back to their "before"
#             state, self-repair task switched off.  SSH from the home network
#             keeps working so the parent app can still connect.
#   resume    switch filtering back on after "pause"
#   disable   undo everything this script did (used by blighter-setup.ps1 -Remove)
#   options   add, change or remove the Discord voice rule (UDP 50000-65535)
#             and the home network rule to match child.conf (run by
#             blighter-apply.py when the parent app's switches change; nothing
#             while paused).  "voice" is the 1.2.2 name for the same thing.
#   netinfo   JSON list of this laptop's current networks (adapters with a
#             default route): address, prefix length and network name
#   status    print a JSON summary (used by blighter-apply.py "status")
#
# Usage (as administrator):
#   powershell -ExecutionPolicy Bypass -File blighter-system.ps1 capture|enable|enforce|pause|resume|disable|options|netinfo|status
#
# Copyright (C) 2026 Ian Packer
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version.  It is distributed WITHOUT ANY WARRANTY; see the
# LICENSE file or <https://www.gnu.org/licenses/> for details.
# -----------------------------------------------------------------------------
param([Parameter(Mandatory = $true)][ValidateSet("capture", "enable", "enforce", "pause", "resume", "disable", "options", "voice", "netinfo", "status")][string]$Action)

$ErrorActionPreference = "Stop"
# No progress bars: each firewall cmdlet would otherwise flash one, which is
# slow and looks like a fault.
$ProgressPreference    = "SilentlyContinue"
$Here       = Split-Path -Parent $MyInvocation.MyCommand.Path
$ChildConf  = Join-Path $Here "child.conf"
$StateDir   = Join-Path $Here "state"
$DisabledDb = Join-Path $StateDir "disabled-rules.txt"
$PreFile    = Join-Path $StateDir "pre-install.json"
$PausedFlag = Join-Path $StateDir "paused"
$Incomplete = Join-Path $StateDir "setup-incomplete.txt"
$SshRuleWin = "OpenSSH-Server-In-TCP"
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
    $c = @{ CHILD_USER = ""; CHILD_SID = ""; ALLOW_VOICE_UDP = "yes"; HOME_NET_ALLOWED = "yes"; HOME_NETS = "" }
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
    if ($HomeNets.Count) {
        $rules += @{ Name = "BR-HomeNet"; Display = "Blighter: home network (printers, NAS...)"; RemoteAddress = $HomeNets }
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

function Get-SshAddresses {
    # Windows' own "local subnet" plus the recorded home subnet(s).
    return @(@("LocalSubnet") + @($RecordedNets))
}

function Get-SshRule {
    return @{ Name = "BR-SSH-In"; Display = "Blighter: parent app SSH (home network only)";
              Program = "%SystemRoot%\System32\OpenSSH\sshd.exe"; Protocol = "TCP"; LocalPort = "22";
              RemoteAddress = (Get-SshAddresses); Profile = "Private" }
}

function Update-SshAddresses {
    # Change the addresses in place (no delete / re-create), so the parent
    # app's open SSH session is not disturbed.
    $rule = Get-NetFirewallRule -Name "BR-SSH-In" -ErrorAction SilentlyContinue
    if (-not $rule) { return }
    $want = @(Get-SshAddresses)
    $have = @(($rule | Get-NetFirewallAddressFilter).RemoteAddress)
    if (($have -join ",") -ne ($want -join ",")) {
        Set-NetFirewallRule -Name "BR-SSH-In" -RemoteAddress $want
        Write-BLog ("SSH allowed from: " + ($want -join " ") + ".")
    }
}

# Speed: Windows has hundreds of firewall rules (322 on a typical Windows 11
# laptop).  Asking for them one at a time takes about a second each, so every
# function below reads ALL rules once (Get-AllRules) and works on that list.
function Get-AllRules {
    # Every rule in the local (persistent) store, as one list.
    return @(Get-NetFirewallRule -ErrorAction SilentlyContinue)
}

function Get-OtherOutboundAllowRules($all = $null) {
    # Enabled "allow outgoing" rules that are not ours and not Core Networking.
    if ($null -eq $all) { $all = Get-AllRules }
    return @($all | Where-Object {
        "$($_.Direction)" -eq "Outbound" -and "$($_.Action)" -eq "Allow" -and "$($_.Enabled)" -eq "True" -and
        $_.Group -ne $Group -and $_.Group -ne $CoreGroup -and $_.DisplayGroup -ne "Core Networking" -and $_.Name -ne $SshRuleWin })
}

function Disable-OtherOutboundRules($all = $null) {
    $others = Get-OtherOutboundAllowRules $all
    if (-not $others.Count) { return }
    if ($Action -ne "enforce") { Write-Host "Switching off $($others.Count) other outgoing allow rule(s) in one batch..." }
    # Record the names FIRST, so an interruption can never lose track of a rule.
    # (A rule that then fails to switch off is still on; switching it "back on"
    # later changes nothing.)
    $known = @()
    if (Test-Path $DisabledDb) { $known = @(Get-Content $DisabledDb) }
    $new = @($others | ForEach-Object { $_.Name } | Where-Object { $known -notcontains $_ })
    if ($new.Count) { Add-Content -Path $DisabledDb -Value $new }
    $errs = $null
    # One call for all of them.  Only rules in the local store can be changed;
    # others (e.g. Group Policy) are reported.
    $others | Disable-NetFirewallRule -ErrorAction SilentlyContinue -ErrorVariable errs
    $failed = @($errs).Count
    $count = $others.Count - $failed
    if ($count) { Write-BLog "Switched off $count other outgoing allow rule(s)." }
    if ($failed) { Write-BLog "WARNING: $failed outgoing allow rule(s) could not be switched off." }
}

function Enable-Firewall([bool]$voice, [bool]$force = $true) {
    # $force = $false (repairs): only re-create rules that are missing or switched off.
    if (-not (Test-Path $StateDir)) { New-Item -ItemType Directory -Path $StateDir -Force | Out-Null }
    foreach ($r in Get-WantedRules $voice) { Set-BlighterRule $r "Outbound" $force }
    if (-not $voice) { Remove-NetFirewallRule -Name "BR-Voice" -ErrorAction SilentlyContinue }
    if (-not $HomeNets.Count) { Remove-NetFirewallRule -Name "BR-HomeNet" -ErrorAction SilentlyContinue }
    Set-BlighterRule (Get-SshRule) "Inbound" $force
    # Windows' own OpenSSH rule allows port 22 from anywhere on every profile - ours replaces it.
    # (Not recorded with the others: removal restores it from the "before" state.)
    Get-NetFirewallRule -Name $SshRuleWin -ErrorAction SilentlyContinue |
        Where-Object { $_.Enabled -eq "True" } | Disable-NetFirewallRule
    Disable-OtherOutboundRules (Get-AllRules)
    Set-NetFirewallProfile -Profile Domain, Private, Public -Enabled True -DefaultOutboundAction Block
}

function Test-FirewallOk([bool]$voice, $all = $null) {
    if ($null -eq $all) { $all = Get-AllRules }
    $byName = @{}
    foreach ($r in $all) { $byName[$r.Name] = $r }
    $problems = @()
    foreach ($p in Get-NetFirewallProfile -PolicyStore ActiveStore) {
        if ($p.Enabled -ne "True") { $problems += "Firewall is OFF for the $($p.Name) profile" }
        if ($p.DefaultOutboundAction -ne "Block") { $problems += "Outgoing traffic is not blocked by default ($($p.Name) profile)" }
    }
    $names = @((Get-WantedRules $voice).Name) + "BR-SSH-In"
    foreach ($n in $names) {
        $r = $byName[$n]
        if (-not $r) { $problems += "Rule $n is missing" }
        elseif ("$($r.Enabled)" -ne "True") { $problems += "Rule $n is switched off" }
    }
    $others = Get-OtherOutboundAllowRules $all
    if ($others.Count) { $problems += "$($others.Count) other outgoing allow rule(s) are on: " + (($others | Select-Object -First 5 | ForEach-Object { $_.DisplayName }) -join "; ") }
    return ,$problems
}

function Restore-FirewallDefaults($pre) {
    # Outgoing default and on/off state per profile, as they were before setup.
    foreach ($name in "Domain", "Private", "Public") {
        $was = $null
        if ($pre) { $was = @($pre.profiles) | Where-Object { $_.Name -eq $name } | Select-Object -First 1 }
        if ($was) {
            Set-NetFirewallProfile -Profile $name -Enabled $was.Enabled -DefaultOutboundAction $was.DefaultOutboundAction
        } else {
            Set-NetFirewallProfile -Profile $name -DefaultOutboundAction NotConfigured
        }
    }
}

function Enable-RecordedRules {
    # Switch back on the "allow outgoing" rules this script switched off.
    if (Test-Path $DisabledDb) {
        $names = @(Get-Content $DisabledDb | Where-Object { $_ } | Sort-Object -Unique)
        # One call for all of them (rules deleted since are skipped silently).
        if ($names.Count) { Enable-NetFirewallRule -Name $names -ErrorAction SilentlyContinue }
        Remove-Item $DisabledDb -Force
    }
}

function Disable-Firewall($pre) {
    Get-NetFirewallRule -Group $Group -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    Enable-RecordedRules
    # Windows' own SSH rule: back on only if it was on before setup.
    if ($pre -and $pre.openssh_rule_enabled) {
        Set-NetFirewallRule -Name $SshRuleWin -Enabled True -ErrorAction SilentlyContinue
    }
    Restore-FirewallDefaults $pre
}

# -------------------------------------------------------------------- proxy ---
# Chromium-based browsers: the same ProxySettings policy under each one's own
# key.  (Brave and Vivaldi were added in 1.2.4; on laptops set up earlier
# pre-install.json has no "before" value for them, so pause / removal simply
# deletes them.)
$PolicyKeys = @{
    "HKLM:\SOFTWARE\Policies\Microsoft\Edge"         = "ProxySettings"
    "HKLM:\SOFTWARE\Policies\Google\Chrome"          = "ProxySettings"
    "HKLM:\SOFTWARE\Policies\BraveSoftware\Brave"    = "ProxySettings"
    "HKLM:\SOFTWARE\Policies\Vivaldi"                 = "ProxySettings"
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

function Get-RegValues($path) {
    # All values of a key as name -> @{type; data}, binary data as base64; $null if no key.
    if (-not (Test-Path $path)) { return $null }
    $key = Get-Item -Path $path
    $vals = [ordered]@{}
    foreach ($n in $key.GetValueNames()) {
        $kind = $key.GetValueKind($n).ToString()
        $data = $key.GetValue($n, $null, "DoNotExpandEnvironmentNames")
        if ($kind -eq "Binary") { $data = [Convert]::ToBase64String([byte[]]$data) }
        $vals[$n] = [ordered]@{ type = $kind; data = $data }
    }
    return $vals
}

function Set-SavedValue($path, [string]$name, $saved) {
    # Put one value back as saved by Get-RegValues ($null = it did not exist).
    if ($null -eq $saved) { Remove-ItemProperty -Path $path -Name $name -ErrorAction SilentlyContinue; return }
    $data = $saved.data
    if ($saved.type -eq "Binary") { $data = [Convert]::FromBase64String($data) }
    if ($saved.type -eq "MultiString") { $data = [string[]]@($data) }
    Set-RegValue $path $name $data $saved.type
}

function Get-Saved($vals, [string]$name) {
    if ($null -eq $vals) { return $null }
    $p = $vals.PSObject.Properties[$name]
    if ($p) { return $p.Value } else { return $null }
}

function Restore-ProxyPolicies($pre) {
    foreach ($k in $PolicyKeys.Keys) {
        $saved = $null
        if ($pre) { $saved = Get-Saved $pre.policies.($k) $PolicyKeys[$k] }
        Set-SavedValue $k $PolicyKeys[$k] $saved
    }
    Remove-Item -Path $FirefoxKey -Recurse -Force -ErrorAction SilentlyContinue
    if ($pre -and $pre.policies.($FirefoxKey)) {
        foreach ($p in $pre.policies.($FirefoxKey).PSObject.Properties) { Set-SavedValue $FirefoxKey $p.Name $p.Value }
    }
    $savedLock = $null
    if ($pre) { $savedLock = Get-Saved $pre.policies.($IeLockKey) "Proxy" }
    Set-SavedValue $IeLockKey "Proxy" $savedLock
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

function Set-ChildProxy([string]$sid, [bool]$on, $pre = $null) {
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
            # Put back exactly what the child had before setup.
            $saved = $null
            if ($pre) { $saved = $pre.child_proxy }
            if ($saved -and $saved.captured) {
                foreach ($n in "ProxyEnable", "ProxyServer", "ProxyOverride", "AutoConfigURL") {
                    Set-SavedValue $k $n (Get-Saved $saved.settings $n)
                }
                if (-not (Test-Path "$k\Connections")) { New-Item -Path "$k\Connections" -Force | Out-Null }
                foreach ($n in "DefaultConnectionSettings", "SavedLegacySettings") {
                    Set-SavedValue "$k\Connections" $n (Get-Saved $saved.connections $n)
                }
            } elseif ($cur.ProxyServer -eq $Proxy) {
                Set-RegValue $k "ProxyEnable" 0 "DWord"
                Remove-ItemProperty -Path $k -Name "ProxyServer", "ProxyOverride" -ErrorAction SilentlyContinue
                Remove-ItemProperty -Path "$k\Connections" -Name "DefaultConnectionSettings", "SavedLegacySettings" -ErrorAction SilentlyContinue
            }
            return "restored"
        }
    } finally { Close-ChildHive $loaded }
}

function Get-ChildProxyState([string]$sid) {
    $loaded = $false
    $hive = Get-ChildHive $sid ([ref]$loaded)
    if (-not $hive) { return [ordered]@{ captured = $false } }
    try {
        $k = "$hive\Software\Microsoft\Windows\CurrentVersion\Internet Settings"
        $all = Get-RegValues $k
        $settings = [ordered]@{}
        foreach ($n in "ProxyEnable", "ProxyServer", "ProxyOverride", "AutoConfigURL") {
            if ($all -and $all.Contains($n)) { $settings[$n] = $all[$n] }
        }
        return [ordered]@{ captured = $true; settings = $settings; connections = (Get-RegValues "$k\Connections") }
    } finally { Close-ChildHive $loaded }
}

function Save-PreState($conf) {
    # Called once, before setup changes anything.  Never overwritten.
    if (Test-Path $PreFile) { Write-BLog "Earlier 'before' state kept ($PreFile)."; return }
    if (-not (Test-Path $StateDir)) { New-Item -ItemType Directory -Path $StateDir -Force | Out-Null }
    $sshRule = Get-NetFirewallRule -Name $SshRuleWin -ErrorAction SilentlyContinue
    $sshd = Get-Service -Name sshd -ErrorAction SilentlyContinue
    $policies = [ordered]@{}
    foreach ($k in @($PolicyKeys.Keys) + $FirefoxKey + $IeLockKey) { $policies[$k] = Get-RegValues $k }
    $ul = "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon\SpecialAccounts\UserList"
    $state = [ordered]@{
        captured_at          = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
        profiles             = @(Get-NetFirewallProfile -PolicyStore PersistentStore | ForEach-Object {
                                   [ordered]@{ Name = $_.Name; Enabled = "$($_.Enabled)"; DefaultOutboundAction = "$($_.DefaultOutboundAction)" } })
        openssh_rule_exists  = [bool]$sshRule
        openssh_rule_enabled = [bool]($sshRule -and $sshRule.Enabled -eq "True")
        sshd_exists          = [bool]$sshd
        sshd_start_type      = if ($sshd) { "$($sshd.StartType)" } else { $null }
        sshd_running         = [bool]($sshd -and $sshd.Status -eq "Running")
        squid_installed      = (Test-Path $SquidExe)
        admin_exists         = [bool](Get-LocalUser -Name "blighter" -ErrorAction SilentlyContinue)
        admin_hidden_value   = [bool](Get-ItemProperty -Path $ul -Name "blighter" -ErrorAction SilentlyContinue)
        policies             = $policies
        child_proxy          = (Get-ChildProxyState $conf.CHILD_SID)
    }
    $state | ConvertTo-Json -Depth 8 | Set-Content -Path $PreFile -Encoding UTF8
    Write-BLog "Saved the laptop's 'before' state to $PreFile."
}

function Read-PreState {
    if (Test-Path $PreFile) { return (Get-Content $PreFile -Raw | ConvertFrom-Json) }
    return $null
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
# Home network subnets, only while the switch is on (checked again by the helper).
# The recorded home subnets are also used for the SSH rule, switch on or off.
$RecordedNets = @("$($conf.HOME_NETS)" -split '\s+' | Where-Object { $_ -match '^[0-9a-fA-F:.]+(/\d{1,3})?$' })
$HomeNets = @()
if ($conf.HOME_NET_ALLOWED -ne "no") { $HomeNets = $RecordedNets }

function Start-Filtering {
    Enable-Firewall $voice
    Enable-ProxyPolicies
    $r = Set-ChildProxy $conf.CHILD_SID $true
    if ($r -eq "unavailable") {
        Write-BLog "The child's proxy setting will be applied when they first log on (their profile does not exist yet)."
    }
    Register-Tasks
    Confirm-Services
}

function Stop-Filtering($pre) {
    # Everything back to "before", except our inbound SSH rule (parent app access).
    Get-NetFirewallRule -Group $Group -Direction Outbound -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    Enable-RecordedRules
    Restore-FirewallDefaults $pre
    Restore-ProxyPolicies $pre
    Set-ChildProxy $conf.CHILD_SID $false $pre | Out-Null
}

switch ($Action) {
    "capture" {
        Save-PreState $conf
    }
    "enable" {
        if (-not (Test-Path $PreFile)) { Save-PreState $conf }
        Remove-Item $PausedFlag -Force -ErrorAction SilentlyContinue
        Start-Filtering
        Write-BLog "Blighter firewall and proxy enabled."
    }
    "resume" {
        Remove-Item $PausedFlag -Force -ErrorAction SilentlyContinue
        Start-Filtering
        Write-BLog "Filtering RESUMED."
    }
    "pause" {
        $pre = Read-PreState
        if (-not $pre) { Write-BLog "WARNING: no saved 'before' state - using Windows defaults." }
        Get-ScheduledTask -TaskPath $TaskPath -TaskName "Enforce" -ErrorAction SilentlyContinue | Disable-ScheduledTask | Out-Null
        Stop-Filtering $pre
        Set-Content -Path $PausedFlag -Value (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
        Write-BLog "Filtering PAUSED (run resume to switch it back on)."
    }
    "enforce" {
        if (Test-Path $PausedFlag) { return }
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
    { $_ -in "options", "voice" } {
        # SSH stays on while paused, so its addresses follow the settings now.
        try { Update-SshAddresses } catch { Write-BLog "ERROR (SSH rule): $($_.Exception.Message)" }
        if (Test-Path $PausedFlag) { Write-BLog "Settings saved; they take effect when filtering is resumed."; return }
        $wanted = @(Get-WantedRules $voice)
        foreach ($n in "BR-Voice", "BR-HomeNet") {
            $r = $wanted | Where-Object { $_.Name -eq $n }
            if ($r) { Set-BlighterRule $r "Outbound" $true }
            else { Remove-NetFirewallRule -Name $n -ErrorAction SilentlyContinue }
        }
        Write-BLog ("Firewall options: Discord voice " + $(if ($voice) { "on" } else { "off" }) +
                    "; home network " + $(if ($HomeNets.Count) { $HomeNets -join " " } else { "off" }) + ".")
    }
    "netinfo" {
        $out = @()
        $ifs = @(Get-NetRoute -DestinationPrefix "0.0.0.0/0" -ErrorAction SilentlyContinue | ForEach-Object { $_.ifIndex } | Sort-Object -Unique)
        foreach ($i in $ifs) {
            $name = (Get-NetConnectionProfile -InterfaceIndex $i -ErrorAction SilentlyContinue | Select-Object -First 1).Name
            if (-not $name) { $name = (Get-NetAdapter -InterfaceIndex $i -ErrorAction SilentlyContinue).Name }
            foreach ($a in Get-NetIPAddress -InterfaceIndex $i -AddressFamily IPv4 -ErrorAction SilentlyContinue) {
                $out += [pscustomobject]@{ address = $a.IPAddress; prefix = [int]$a.PrefixLength; name = "$name" }
            }
        }
        ConvertTo-Json -InputObject @($out) -Compress
    }
    "disable" {
        $pre = Read-PreState
        if (-not $pre) { Write-BLog "WARNING: no saved 'before' state - using Windows defaults." }
        Unregister-Tasks
        Disable-Firewall $pre
        Restore-ProxyPolicies $pre
        Set-ChildProxy $conf.CHILD_SID $false $pre | Out-Null
        Remove-Item $PausedFlag -Force -ErrorAction SilentlyContinue
        Write-BLog "Blighter firewall and proxy removed; previous settings restored."
    }
    "status" {
        $ErrorActionPreference = "Continue"
        $paused = Test-Path $PausedFlag
        $all = Get-AllRules
        $problems = Test-FirewallOk $voice $all
        if ($paused) { $problems = @("Filtering is PAUSED since " + (Get-Content $PausedFlag -TotalCount 1)) + $problems }
        $warnings = @()
        if (Test-Path $Incomplete) {
            $warnings += ("Setup on this laptop did not finish (started " + (Get-Content $Incomplete -TotalCount 1) +
                          ").  Run 'Install Blighter Child.cmd' again to finish it, or 'Remove Blighter Child.cmd' to undo it.")
        }
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
        # Asking for each rule's port/program/service details separately took over
        # a minute; instead read every filter of each kind once and match them up
        # by InstanceID (a filter has the same InstanceID as its rule).
        $ours = @($all | Where-Object { $_.Group -eq $Group } | Sort-Object Name)
        $ports = @{}; $apps = @{}; $svcs = @{}; $addrs = @{}
        if ($ours.Count) {
            foreach ($f in Get-NetFirewallPortFilter -All -ErrorAction SilentlyContinue) { $ports[$f.InstanceID] = $f }
            foreach ($f in Get-NetFirewallApplicationFilter -All -ErrorAction SilentlyContinue) { $apps[$f.InstanceID] = $f }
            foreach ($f in Get-NetFirewallServiceFilter -All -ErrorAction SilentlyContinue) { $svcs[$f.InstanceID] = $f }
            if ($ours | Where-Object { $_.Name -eq "BR-HomeNet" -or $_.Name -eq "BR-SSH-In" }) {
                foreach ($f in Get-NetFirewallAddressFilter -All -ErrorAction SilentlyContinue) { $addrs[$f.InstanceID] = $f }
            }
        }
        foreach ($r in $ours) {
            $port = $ports[$r.InstanceID]
            $app = $apps[$r.InstanceID]
            $svc = if ($svcs[$r.InstanceID]) { $svcs[$r.InstanceID].Service } else { $null }
            $what = @()
            if ($app.Program -and $app.Program -ne "Any") { $what += $app.Program }
            if ($svc -and $svc -ne "Any") { $what += "service $svc" }
            if ($port.Protocol -and $port.Protocol -ne "Any") { $what += $port.Protocol }
            if ($port.RemotePort -and "$($port.RemotePort)" -ne "Any") { $what += "remote port " + ($port.RemotePort -join ",") }
            if ($port.LocalPort -and "$($port.LocalPort)" -ne "Any") { $what += "local port " + ($port.LocalPort -join ",") }
            $ad = $addrs[$r.InstanceID]
            if ($ad -and $ad.RemoteAddress -and "$($ad.RemoteAddress)" -ne "Any") { $what += "to " + ($ad.RemoteAddress -join ",") }
            $lines += ("  {0,-8} {1,-16} on={2,-5} {3}" -f $r.Direction, $r.Name, $r.Enabled, ($what -join "  "))
        }
        $lines += ""
        $lines += "Network: " + ($prof -join "; ")
        if ($problems.Count) { $lines += ""; $lines += "Problems:"; $problems | ForEach-Object { $lines += "  $_" } }
        $osv = (Get-CimInstance Win32_OperatingSystem -ErrorAction SilentlyContinue)
        [pscustomobject]@{
            paused          = $paused
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
