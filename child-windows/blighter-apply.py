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
#   set                 read {"mode","allow","block"} JSON on stdin, validate,
#                       back up, write, check with "squid -k parse", reload
#                       Squid; restore the previous files if anything fails
#   reload              rewrite rules.conf from the saved lists and re-read
#                       config ("restart Squid on command")
#   log N [rotated]     plain text: last N lines of the Squid access log,
#                       optionally including older rotated logs
#   init                (used by blighter-setup.ps1) create default files
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

VERSION = "1.2.2"
PLATFORM = "windows"
SERVICE = "squidsrv"            # service name used by Diladele's installer
CHILD_CONF = os.path.join(HERE, "child.conf")
SYSTEM_PS1 = os.path.join(HERE, "blighter-system.ps1")
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


# ---- Discord switch (stored as ALLOW_VOICE_UDP in child.conf) -----------------
def conf_value(key, default=""):
    for line in read(CHILD_CONF).splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            if k.strip() == key:
                return v.strip().strip('"')
    return default


def discord_allowed():
    """Discord allowed?  One setting covers the Squid rules AND the firewall's
    UDP 50000-65535 opening for voice/video."""
    return conf_value("ALLOW_VOICE_UDP", "yes") != "no"


def save_discord(allowed):
    value = "yes" if allowed else "no"
    lines = read(CHILD_CONF).splitlines()
    done = False
    for i, line in enumerate(lines):
        if line.split("=", 1)[0].strip() == "ALLOW_VOICE_UDP":
            lines[i] = f'ALLOW_VOICE_UDP="{value}"'
            done = True
    if not done:
        lines += ["# yes = Discord allowed (Squid rules and UDP 50000-65535 for voice/video)",
                  f'ALLOW_VOICE_UDP="{value}"']
    write(CHILD_CONF, "\n".join(lines) + "\n")


def apply_discord_firewall():
    """Open or close UDP 50000-65535 (Discord voice) to match child.conf."""
    return run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                "-File", SYSTEM_PS1, "voice"], timeout=120)


def is_elevated():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return True   # not on Windows (tests)


def read_mode():
    m = read(MODE_FILE, domains.MODE_BLOCKLIST).strip()
    return m if m in domains.MODES else domains.MODE_BLOCKLIST


def render_rules(mode, allow_lines, block_lines, discord=None):
    # The neutral error pages must exist before Squid reads this file.
    blockpage.write_pages(ERR_DIR, STOCK_ERR_DIRS)
    head = ("# Generated by Blighter Restrictor - do not edit by hand.\n"
            f"# Mode: {mode}\n" + blockpage.squid_lines(CYG_ERR))
    if discord is None:
        discord = discord_allowed()
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

    # "discord" is optional (older parent apps do not send it).
    discord = data.get("discord")
    discord = discord_allowed() if discord is None else bool(discord)
    discord_changed = discord != discord_allowed()

    write(ALLOW_FILE, "\n".join(allow) + "\n")
    write(BLOCK_FILE, "\n".join(block) + "\n")
    write(MODE_FILE, mode + "\n")
    write(RULES_FILE, render_rules(mode, allow, block, discord))

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
    if discord_changed:
        # Squid accepted the rules; now the setting and the firewall follow.
        save_discord(discord)
        fw_code, fw_msg = apply_discord_firewall()
        message += " Discord " + ("allowed." if discord else "blocked.")
        if fw_code != 0:
            message += " WARNING: the firewall could not be updated for Discord voice: " + fw_msg[-300:]
    warn = [l for l in msg.splitlines() if "WARNING" in l]
    out({"ok": True, "message": message, "discord": discord_allowed(),
         "notes": n1 + n2, "warnings": warn[-10:],
         "allow": allow, "block": block, "mode": mode})


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


USAGE = "usage: blighter-apply get|status|set|reload|log N [rotated]|init"


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
    else:
        sys.exit(USAGE)


if __name__ == "__main__":
    main()
