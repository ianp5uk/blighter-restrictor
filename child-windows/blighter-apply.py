# -----------------------------------------------------------------------------
# Blighter Restrictor - child-laptop helper for WINDOWS.
#
# Purpose: the command the parent app runs on a child's Windows laptop over
# SSH, as the "blighter" administrator account.  It offers exactly the same
# commands and JSON replies as the Ubuntu helper (/usr/sbin/blighter-apply),
# so the parent app treats both systems alike.  It is started through
# blighter-apply.cmd with the private Python bundled in
# C:\ProgramData\BlighterChild\python, in isolated mode (-I).
#
# Unlike Ubuntu there is no sudo: an administrator's SSH session on Windows
# already has full rights.  The helper checks this and says so if not.
#
# Commands (output is JSON unless stated):
#   get                 current mode, allow list, block list and config text
#   status              Squid / firewall / proxy / child-account state
#   set                 read {"mode","allow","block"[,"discord","home_net","opera"]} JSON on stdin, validate,
#                       back up, write, check with "squid -k parse", reload
#                       Squid; restore the previous files if anything fails
#   reload              rewrite rules.conf from the saved lists and re-read
#                       config ("restart Squid on command")
#   log N [rotated]     plain text: last N lines of the Squid access log,
#                       optionally including older rotated logs
#   init                (used by blighter-setup.ps1) create default files
#   netinfo             the networks the laptop is on now (for the home network setting)
#   pause / resume      blighter-system.ps1 pause / resume (as the .cmd files do)
#
# Copyright (C) 2026 Ways Property
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version.  It is distributed WITHOUT ANY WARRANTY; see the
# LICENSE file or <https://www.gnu.org/licenses/> for details.
# -----------------------------------------------------------------------------

import ctypes
import ipaddress
import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import domains  # noqa: E402  (shared validation, same file as the parent app)
import blockpage  # noqa: E402  (neutral error pages, same file as the Ubuntu helper)

VERSION = "1.2.5"
PLATFORM = "windows"
SERVICE = "squidsrv"            # service name used by Diladele's installer
CHILD_CONF = os.path.join(HERE, "child.conf")
SYSTEM_PS1 = os.path.join(HERE, "blighter-system.ps1")
STATE_DIR = os.path.join(HERE, "state")
PAUSED_FLAG = os.path.join(STATE_DIR, "paused")
MAX_LOG_LINES = 100000
NO_WINDOW = 0x08000000          # CREATE_NO_WINDOW


def squid_root():
    """Squid's install folder (also Cygwin's "/"), from the installer's registry key."""
    override = os.environ.get("BLIGHTER_SQUID_ROOT")   # used by tests only
    if override:
        return override
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"Software\Squid") as k:
            path = winreg.QueryValueEx(k, "InstallDir")[0]
            if path:
                return path.rstrip("\\/")
    except (ImportError, OSError):
        pass
    return r"C:\Squid"


ROOT = squid_root()
SQUID_EXE = os.path.join(ROOT, "bin", "squid.exe")
BASE = os.path.join(ROOT, "etc", "squid", "blighter")
MODE_FILE = os.path.join(BASE, "mode")
ALLOW_FILE = os.path.join(BASE, "allow.list")
BLOCK_FILE = os.path.join(BASE, "block.list")
RULES_FILE = os.path.join(BASE, "rules.conf")
DNS_FILE = os.path.join(BASE, "dns.conf")
PREV_DIR = os.path.join(BASE, ".previous")
ERR_DIR = os.path.join(BASE, "errors")
# Squid's own templates (read only to learn the page names).
STOCK_ERR_DIRS = (os.path.join(ROOT, "usr", "share", "squid", "errors", "templates"),
                  os.path.join(ROOT, "usr", "share", "squid", "errors", "en"))
SQUID_CONF = os.path.join(ROOT, "etc", "squid", "squid.conf")
LOG_DIR = os.path.join(ROOT, "var", "log", "squid")
MANAGED = (MODE_FILE, ALLOW_FILE, BLOCK_FILE, RULES_FILE)
# Squid itself sees the Cygwin form of these paths.
CYG_ALLOW = "/etc/squid/blighter/allow.list"
CYG_BLOCK = "/etc/squid/blighter/block.list"
CYG_CONF = "/etc/squid/squid.conf"
CYG_ERR = "/etc/squid/blighter/errors"

DEFAULT_ALLOW = """# Sites allowed when the mode is "Block all, allow some".
# One domain per line.  A leading dot means "this domain and all subdomains".
# (Discord is not in this list: it has its own "Allow Discord" switch.)
# Schoolwork basics
.wikipedia.org
.bbc.co.uk
.bbci.co.uk
"""

DEFAULT_BLOCK = """# Sites blocked when the mode is "Allow all, block some".
# One domain per line.  A leading dot means "this domain and all subdomains".
# Game stores / launchers
.steampowered.com
.steamcommunity.com
.steamstatic.com
.epicgames.com
.roblox.com
"""


def out(obj, code=0):
    print(json.dumps(obj))
    sys.exit(code)


def read(path, default=""):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return default


def write(path, text):
    # newline="\n": Squid is a Cygwin program and expects Unix line endings.
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    os.replace(tmp, path)


# ---- Per-child switches, stored in child.conf -----------------------------------
#   ALLOW_VOICE_UDP   yes/no   Discord allowed (Squid rules + UDP 50000-65535)
#   HOME_NET_ALLOWED  yes/no   home network access (firewall + Squid)
#   HOME_NETS         "192.168.18.0/24 ..."   the home network's subnet(s)
#   HOME_NET_NAME     the network's name when it was recorded (for display)
#   BLOCK_OPERA       yes/no   Opera downloads blocked in Squid (default yes)
def conf_value(key, default=""):
    for line in read(CHILD_CONF).splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            if k.strip() == key:
                return v.strip().strip('"')
    return default


def save_conf(values):
    """Set KEY="value" lines in child.conf (adding missing keys at the end)."""
    lines = read(CHILD_CONF).splitlines()
    for key, value in values.items():
        new = f'{key}="{value}"'
        for i, line in enumerate(lines):
            if not line.lstrip().startswith("#") and line.split("=", 1)[0].strip() == key:
                lines[i] = new
                break
        else:
            lines.append(new)
    write(CHILD_CONF, "\n".join(lines) + "\n")
    fix_conf_permissions()


def discord_allowed():
    """Discord allowed?  One setting covers the Squid rules AND the firewall's
    UDP 50000-65535 opening for voice/video."""
    return conf_value("ALLOW_VOICE_UDP", "yes") != "no"


def opera_blocked():
    """Opera downloads blocked?  (Missing from child.conf = yes, so updated
    laptops get the block too.)"""
    return conf_value("BLOCK_OPERA", "yes") != "no"


def home_net():
    """The home network switch: {"allowed", "subnets", "name"}."""
    subnets, _, _ = domains.clean_subnets(conf_value("HOME_NETS").split())
    return {"allowed": conf_value("HOME_NET_ALLOWED", "yes") != "no",
            "subnets": subnets, "name": conf_value("HOME_NET_NAME")}


def parse_options(data):
    """Read the optional "discord" and "home_net" parts of a set request.
    Older parent apps send neither; then the laptop's settings are kept.
    Returns (discord, home, errors, warnings)."""
    discord = data.get("discord")
    discord = discord_allowed() if discord is None else bool(discord)
    home = home_net()
    errors, warnings = [], []
    h = data.get("home_net")
    if isinstance(h, dict):
        subnets, errors, warnings = domains.clean_subnets([str(x) for x in h.get("subnets", [])])
        name = str(h.get("name", home["name"]))[:80].replace('"', "'")
        if subnets != home["subnets"] and "name" not in h:
            name = ""
        home = {"allowed": bool(h.get("allowed", home["allowed"])), "subnets": subnets, "name": name}
        if home["allowed"] and not subnets:
            warnings.append("Home network access is on but no home network is set - nothing extra is allowed.")
    return discord, home, [f"Home network: {e}" for e in errors], warnings


def fix_conf_permissions():
    pass   # C:\ProgramData\BlighterChild is locked by setup; files inherit that.


def is_paused():
    return os.path.exists(PAUSED_FLAG)


def paused_rules():
    # On Windows, pausing points the browsers and the child's proxy setting
    # back to how they were before setup, so Squid's rules need no change.
    return ""


def system_ps1(action, timeout=120):
    return run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                "-File", SYSTEM_PS1, action], timeout=timeout)


def apply_firewall_options():
    """Make the Discord voice and home network firewall rules match child.conf."""
    return system_ps1("options")


def is_elevated():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return True   # not on Windows (tests)


def read_mode():
    m = read(MODE_FILE, domains.MODE_BLOCKLIST).strip()
    return m if m in domains.MODES else domains.MODE_BLOCKLIST


def render_rules(mode, allow_lines, block_lines, discord=None, home=None, opera=None):
    # The neutral error pages must exist before Squid reads this file.
    blockpage.write_pages(ERR_DIR, STOCK_ERR_DIRS)
    head = ("# Generated by Blighter Restrictor - do not edit by hand.\n"
            f"# Mode: {mode}\n" + blockpage.squid_lines(CYG_ERR))
    if discord is None:
        discord = discord_allowed()
    if home is None:
        home = home_net()
    if opera is None:
        opera = opera_blocked()
    head += paused_rules()
    head += domains.home_net_rules(home["allowed"], home["subnets"])
    head += domains.opera_rules(opera)
    head += domains.discord_rules(discord)
    if mode == domains.MODE_ALLOWLIST:
        if domains.entries_only(allow_lines):
            return head + (f'acl blighter_allow dstdomain "{CYG_ALLOW}"\n'
                           "http_access allow localhost blighter_allow\n")
        return head + "# Allow list is empty: everything is blocked.\n"
    body = head
    if domains.entries_only(block_lines):
        body += (f'acl blighter_block dstdomain "{CYG_BLOCK}"\n'
                 "http_access deny blighter_block\n")
    return body + "http_access allow localhost\n"


def run(cmd, timeout=120):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           encoding="utf-8", errors="replace",
                           creationflags=NO_WINDOW if os.name == "nt" else 0)
    except FileNotFoundError as e:
        return 127, str(e)
    except subprocess.TimeoutExpired:
        return 124, f"{cmd[0]} timed out"
    return p.returncode, (p.stdout + p.stderr).strip()


def squid_parse():
    return run([SQUID_EXE, "-k", "parse", "-f", CYG_CONF])


def service_state():
    """'RUNNING', 'STOPPED', ... or 'MISSING'."""
    code, text = run(["sc.exe", "query", SERVICE])
    if code != 0:
        return "MISSING"
    for line in text.splitlines():
        if "STATE" in line:
            return line.split()[-1]
    return "UNKNOWN"


def squid_process_alive():
    code, text = run(["tasklist.exe", "/FI", "IMAGENAME eq squid.exe", "/NH"])
    return code == 0 and "squid.exe" in text.lower()


def squid_running():
    return service_state() == "RUNNING" and squid_process_alive()


def restart_service():
    run(["net.exe", "stop", SERVICE], timeout=60)
    code, msg = run(["net.exe", "start", SERVICE], timeout=60)
    return code == 0, msg


def squid_reload():
    """Reconfigure if running, otherwise (re)start the service.  Returns (ok, message)."""
    if squid_running():
        code, msg = run([SQUID_EXE, "-k", "reconfigure", "-f", CYG_CONF])
        if code == 0:
            time.sleep(1.5)
            if squid_process_alive():
                return True, msg
        # Signals between Cygwin processes can fail; a service restart always works.
        return restart_service()
    if service_state() == "RUNNING":       # service up but squid.exe died
        return restart_service()
    code, msg = run(["net.exe", "start", SERVICE], timeout=60)
    return code == 0, msg


def parse_errors(text):
    keep = [l for l in text.splitlines() if "ERROR" in l or "FATAL" in l or "WARNING" in l]
    return "\n".join(keep[-15:]) or text[-1500:]


def child_conf():
    conf = {}
    for line in read(CHILD_CONF).splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            conf[k.strip()] = v.strip().strip('"')
    return conf


def system_status():
    """Firewall / proxy / account checks done by blighter-system.ps1 (JSON)."""
    code, text = run(["powershell.exe", "-NoProfile", "-NonInteractive",
                      "-ExecutionPolicy", "Bypass", "-File", SYSTEM_PS1, "status"], timeout=120)
    start = text.find("{")
    try:
        return json.loads(text[start:]) if start >= 0 else {}
    except ValueError:
        return {"firewall_rules": "Could not read firewall status:\n" + text[-1500:]}


def cmd_get():
    out({
        "helper_version": VERSION,
        "platform": PLATFORM,
        "mode": read_mode(),
        "allow": read(ALLOW_FILE).splitlines(),
        "block": read(BLOCK_FILE).splitlines(),
        "rules_conf": read(RULES_FILE),
        "squid_conf": read(SQUID_CONF),
        "discord": discord_allowed(),
        "home_net": home_net(),
        "opera": opera_blocked(),
        "paused": is_paused(),
    })


def cmd_status():
    child = child_conf()
    sysst = system_status()
    _, ver = run([SQUID_EXE, "-v"])
    out({
        "helper_version": VERSION,
        "platform": PLATFORM,
        "os_version": sysst.get("os_version", "Windows"),
        "elevated": is_elevated(),
        "child_user": child.get("CHILD_USER", "?"),
        "voice_udp": child.get("ALLOW_VOICE_UDP", "yes"),
        "squid_version": ver.splitlines()[0] if ver else "?",
        "squid_running": squid_running(),
        "squid_conf_managed": "Blighter Restrictor" in read(SQUID_CONF)[:600],
        "firewall_active": bool(sysst.get("firewall_active")),
        "firewall_rules": sysst.get("firewall_rules", "Firewall status unavailable"),
        "proxy_locked": bool(sysst.get("proxy_locked")),
        "child_is_admin": sysst.get("child_is_admin"),
        "other_admins": sysst.get("other_admins", []),
        "network_profile": sysst.get("network_profile", "?"),
        "paused": bool(sysst.get("paused")),
        "home_net": home_net(),
        "warnings": sysst.get("warnings", []),
    })


def cmd_set():
    try:
        data = json.loads(sys.stdin.read(2_000_000))
    except ValueError:
        out({"ok": False, "message": "Input was not valid JSON"}, 1)
    mode = data.get("mode")
    if mode not in domains.MODES:
        out({"ok": False, "message": f"Unknown mode {mode!r}"}, 1)
    allow, n1, e1 = domains.clean_list([str(x) for x in data.get("allow", [])])
    block, n2, e2 = domains.clean_list([str(x) for x in data.get("block", [])])
    errors = [f"Allow list {e}" for e in e1] + [f"Block list {e}" for e in e2]
    if errors:
        out({"ok": False, "message": "Lists contain errors - nothing changed.", "errors": errors}, 1)

    # Back up the current files so we can roll back.
    os.makedirs(PREV_DIR, exist_ok=True)
    for p in MANAGED:
        dst = os.path.join(PREV_DIR, os.path.basename(p))
        if os.path.exists(p):
            shutil.copy2(p, dst)
        elif os.path.exists(dst):
            os.remove(dst)

    discord, home, opt_errors, opt_warnings = parse_options(data)
    if opt_errors:
        out({"ok": False, "message": "Settings contain errors - nothing changed.", "errors": opt_errors}, 1)
    opera = data.get("opera")
    opera = opera_blocked() if opera is None else bool(opera)
    discord_changed = discord != discord_allowed()
    home_changed = home != home_net()
    opera_changed = opera != opera_blocked()

    write(ALLOW_FILE, "\n".join(allow) + "\n")
    write(BLOCK_FILE, "\n".join(block) + "\n")
    write(MODE_FILE, mode + "\n")
    write(RULES_FILE, render_rules(mode, allow, block, discord, home, opera))

    code, msg = squid_parse()
    ok = code == 0
    reload_msg = ""
    if ok:
        ok, reload_msg = squid_reload()
    if not ok:
        for p in MANAGED:
            src = os.path.join(PREV_DIR, os.path.basename(p))
            if os.path.exists(src):
                shutil.copy2(src, p)
        squid_reload()
        out({"ok": False,
             "message": "Squid rejected the new configuration - previous rules restored.",
             "errors": [parse_errors(msg + "\n" + reload_msg)]}, 1)

    message = "Applied and Squid reloaded."
    if discord_changed or home_changed or opera_changed:
        # Squid accepted the rules; now the settings (and the firewall) follow.
        save_conf({"ALLOW_VOICE_UDP": "yes" if discord else "no",
                   "HOME_NET_ALLOWED": "yes" if home["allowed"] else "no",
                   "HOME_NETS": " ".join(home["subnets"]),
                   "HOME_NET_NAME": home["name"],
                   "BLOCK_OPERA": "yes" if opera else "no"})
        if opera_changed:
            message += " Opera downloads " + ("blocked." if opera else "allowed.")
    if discord_changed or home_changed:
        fw_code, fw_msg = apply_firewall_options()
        if discord_changed:
            message += " Discord " + ("allowed." if discord else "blocked.")
        if home_changed:
            message += " Home network access " + ("on." if home["allowed"] else "off.")
        if fw_code != 0:
            message += " WARNING: the laptop's firewall could not be updated: " + fw_msg[-300:]
    warn = [l for l in msg.splitlines() if "WARNING" in l] + opt_warnings
    out({"ok": True, "message": message, "discord": discord_allowed(), "home_net": home_net(),
         "opera": opera_blocked(),
         "paused": is_paused(),
         "notes": n1 + n2, "warnings": warn[-10:],
         "allow": allow, "block": block, "mode": mode})


def networks_from(entries):
    """entries: [(address, prefixlen, name)] -> [{"subnet", "name", "private", "address"}]."""
    nets, seen = [], set()
    for addr, plen, name in entries:
        try:
            iface = ipaddress.ip_interface(f"{addr}/{plen}")
        except ValueError:
            continue
        net = iface.network
        if net.is_loopback or net.is_link_local or str(net) in seen:
            continue
        seen.add(str(net))
        nets.append({"subnet": str(net), "name": name or "", "address": str(iface.ip),
                     "private": domains.is_private_net(net)})
    return nets


def current_networks():
    """The networks this laptop is on now (adapters with a default route), with names."""
    code, text = system_ps1("netinfo")
    start = text.find("[")
    try:
        raw = json.loads(text[start:]) if code == 0 and start >= 0 else []
    except ValueError:
        raw = []
    if isinstance(raw, dict):
        raw = [raw]
    return networks_from([(e.get("address"), e.get("prefix"), e.get("name")) for e in raw])


def cmd_netinfo():
    out({"networks": current_networks()})


def cmd_pause(on):
    """Pause (on=True) or resume filtering, as 'Pause / Resume Blighter Child.cmd' do."""
    code, msg = system_ps1("pause" if on else "resume", timeout=300)
    ok = code == 0
    out({"ok": ok, "paused": is_paused(),
         "message": (("Filtering PAUSED - the child has open internet access." if on else "Filtering RESUMED.")
                     if ok else ("Pause" if on else "Resume") + " failed"),
         "errors": [] if ok else [msg[-800:]]}, 0 if ok else 1)


def cmd_reload():
    # Rewrite rules.conf too, so a laptop set up by an older version gets the
    # current Squid settings (e.g. the neutral error pages).
    write(RULES_FILE, render_rules(read_mode(), read(ALLOW_FILE).splitlines(), read(BLOCK_FILE).splitlines()))
    code, msg = squid_parse()
    if code != 0:
        out({"ok": False, "message": "Squid configuration check failed",
             "errors": [parse_errors(msg)]}, 1)
    ok, msg = squid_reload()
    out({"ok": ok, "message": "Squid reloaded." if ok else "Reload failed",
         "errors": [] if ok else [msg]}, 0 if ok else 1)


def cmd_log(args):
    try:
        n = max(1, min(int(args[0]) if args else 2000, MAX_LOG_LINES))
    except ValueError:
        sys.exit("log: N must be a number")
    rotated = len(args) > 1 and args[1] == "rotated"
    files = [os.path.join(LOG_DIR, "access.log")]
    if rotated:   # Squid's own rotation: access.log.0 is the newest old log
        files += [os.path.join(LOG_DIR, f"access.log.{i}") for i in range(0, 15)]
    collected = []
    for p in files:  # newest first
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                lines = f.read().splitlines()
        except (FileNotFoundError, PermissionError):
            continue
        collected = lines + collected
        if len(collected) >= n:
            break
    sys.stdout.write("\n".join(collected[-n:]) + "\n")


def cmd_init():
    os.makedirs(BASE, exist_ok=True)
    if not os.path.exists(ALLOW_FILE):
        write(ALLOW_FILE, DEFAULT_ALLOW)
    if not os.path.exists(BLOCK_FILE):
        write(BLOCK_FILE, DEFAULT_BLOCK)
    if not os.path.exists(MODE_FILE):
        write(MODE_FILE, domains.MODE_BLOCKLIST + "\n")
    if not os.path.exists(DNS_FILE):
        write(DNS_FILE, "dns_nameservers 1.1.1.1 8.8.8.8\n")
    allow = read(ALLOW_FILE).splitlines()
    block = read(BLOCK_FILE).splitlines()
    write(RULES_FILE, render_rules(read_mode(), allow, block))
    print("Blighter rule files ready in " + BASE)


USAGE = "usage: blighter-apply get|status|set|reload|log N [rotated]|init|netinfo|pause|resume"


def main():
    args = sys.argv[1:]
    if not args:
        sys.exit(USAGE)
    if not is_elevated():
        out({"ok": False, "message":
             "This helper needs full administrator rights.  Run it from a PowerShell or "
             "Terminal window opened with 'Run as administrator' (the title starts with "
             "'Administrator:').  If the parent app reports this, the 'blighter' account is "
             "not an administrator: run 'Install Blighter Child.cmd' on the laptop again."}, 3)
    cmd, rest = args[0], args[1:]
    if cmd == "get" and not rest:
        cmd_get()
    elif cmd == "status" and not rest:
        cmd_status()
    elif cmd == "set" and not rest:
        cmd_set()
    elif cmd == "reload" and not rest:
        cmd_reload()
    elif cmd == "log" and len(rest) <= 2:
        cmd_log(rest)
    elif cmd == "init" and not rest:
        cmd_init()
    elif cmd == "netinfo" and not rest:
        cmd_netinfo()
    elif cmd in ("pause", "resume") and not rest:
        cmd_pause(cmd == "pause")
    else:
        sys.exit(USAGE)


if __name__ == "__main__":
    main()
