#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Blighter Restrictor - local test of the parent app's "Find PCs" (1.4.0).
#
# Purpose: check discovery.find_pcs() against real OpenSSH servers on this
# (Linux) machine, without root: three sshd processes on 127.0.0.1, each on
# its own port, with their own host keys -
#   1. a Blighter child: the banner written by the Ubuntu helper's own code
#      (blighter-apply banner_text), shown only to the "blighter" account
#      (Match User block, as blighter-setup writes it) -> listed, with the
#      right name / system / version and host key; marked "already added"
#      when its host key is passed in as a known one (also when the saved
#      key is of another type)
#   2. the same banner, but for another account only -> not listed
#   3. a plain sshd without a banner -> not listed
# It also checks the Windows helper's banner text parses, and that no
# password is ever offered (sshd's log shows only the "none" method).
# Usage:  python3 tests/test_find_pcs.py      (needs paramiko and OpenSSH's
#         sshd and ssh-keygen; exits non-zero on failure)
#
# Copyright (C) 2026 Ian Packer
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version.  It is distributed WITHOUT ANY WARRANTY; see the
# LICENSE file or <https://www.gnu.org/licenses/> for details.
# -----------------------------------------------------------------------------

import importlib.machinery
import importlib.util
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "parent"))
sys.path.insert(0, os.path.join(ROOT, "common"))
from blighter_parent import discovery  # noqa: E402

SSHD = shutil.which("sshd") or "/usr/sbin/sshd"


def load_helper(path, name):
    loader = importlib.machinery.SourceFileLoader(name, path)
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_sshd(tmp, label, match_user=None, banner=None):
    d = os.path.join(tmp, label)
    os.makedirs(d)
    for t in ("ed25519", "rsa"):
        subprocess.run(["ssh-keygen", "-q", "-t", t, "-N", "", "-f", os.path.join(d, f"key_{t}")], check=True)
    port = free_port()
    lines = [f"Port {port}", "ListenAddress 127.0.0.1",
             f"HostKey {d}/key_ed25519", f"HostKey {d}/key_rsa",
             f"PidFile {d}/sshd.pid", "UsePAM no", "PasswordAuthentication yes",
             "AuthorizedKeysFile none", "LogLevel DEBUG1"]
    if banner is not None:
        with open(os.path.join(d, "ssh-banner"), "w", encoding="utf-8") as f:
            f.write(banner)
        lines += ["# Blighter Restrictor: settings for the admin account only.",
                  f"Match User {match_user}", f"    Banner {d}/ssh-banner"]
    cfg = os.path.join(d, "sshd_config")
    with open(cfg, "w") as f:
        f.write("\n".join(lines) + "\n")
    subprocess.run([SSHD, "-t", "-f", cfg], check=True)
    log = open(os.path.join(d, "sshd.log"), "w")
    proc = subprocess.Popen([SSHD, "-D", "-e", "-f", cfg], stderr=log, stdout=log)
    for _ in range(50):
        if discovery._port_open("127.0.0.1", port):
            break
        time.sleep(0.1)
    else:
        raise RuntimeError(f"sshd {label} did not start: " + open(log.name).read())
    pub = {t: open(os.path.join(d, f"key_{t}.pub")).read().split()[:2] for t in ("ed25519", "rsa")}
    return proc, port, pub, log.name


def check(cond, what):
    print(("OK:   " if cond else "FAIL: ") + what)
    if not cond:
        check.failed = True


check.failed = False


def main():
    linux = load_helper(os.path.join(ROOT, "child/files/usr/sbin/blighter-apply"), "blighter_apply_linux")
    banner = linux.banner_text()
    print("Ubuntu helper banner:", banner.strip())
    win = load_helper(os.path.join(ROOT, "child-windows/blighter-apply.py"), "blighter_apply_windows")
    wb = discovery.parse_banner(win.banner_text())
    check(wb and wb["version"] == win.VERSION, "Windows helper banner parses: " + win.banner_text().strip())
    check(discovery.parse_banner("Welcome to my NAS") is None, "other banners are not Blighter's")
    check(discovery.parse_banner("") is None, "empty banner is not Blighter's")

    tmp = tempfile.mkdtemp(prefix="br-scan-test-")
    procs = []
    try:
        child, p_child, pub_child, log_child = start_sshd(tmp, "child", "blighter", banner)
        other, p_other, _, _ = start_sshd(tmp, "other-user", "someoneelse", banner)
        plain, p_plain, _, _ = start_sshd(tmp, "plain")
        procs = [child, other, plain]

        key, text = discovery.read_banner("127.0.0.1", p_child)
        check(text == banner, f"banner read without a password: {text.strip()!r}")
        check(discovery.key_to_text(key) == " ".join(pub_child["ed25519"]), "host key read with the banner")

        found = discovery.find_pcs([], p_child, hosts=["127.0.0.1"])
        check(len(found) == 1, f"Blighter child listed ({len(found)} found)")
        if found:
            pc = found[0]
            want = discovery.parse_banner(banner)
            check(pc["ip"] == "127.0.0.1" and pc["name"] == want["name"] and pc["os"] == want["os"]
                  and pc["version"] == linux.VERSION,
                  f"name / system / version: {pc['name']} / {pc['os']} / {pc['version']}")
            check(pc["host_key_text"] == " ".join(pub_child["ed25519"]), "host key text matches the PC's")
            check(not pc["known"], "not marked already added")
        found = discovery.find_pcs([" ".join(pub_child["ed25519"])], p_child, hosts=["127.0.0.1"])
        check(found and found[0]["known"], "marked already added (same ed25519 key)")
        found = discovery.find_pcs([" ".join(pub_child["rsa"])], p_child, hosts=["127.0.0.1"])
        check(found and found[0]["known"], "marked already added (saved key is the RSA one)")
        found = discovery.find_pcs([" ".join(pub_child["rsa"]).replace("A", "B", 1)], p_child, hosts=["127.0.0.1"])
        check(found and not found[0]["known"], "a different saved key is not 'already added'")

        check(discovery.find_pcs([], p_other, hosts=["127.0.0.1"]) == [],
              "banner for another account only: not listed")
        check(discovery.find_pcs([], p_plain, hosts=["127.0.0.1"]) == [], "plain sshd: not listed")
        check(discovery.find_pcs([], free_port(), hosts=["127.0.0.1"]) == [], "nothing on the port: empty list")

        time.sleep(0.5)
        log = open(log_child).read()
        methods = set(re.findall(r"userauth-request for user \S+ service \S+ method (\S+)", log))
        check(methods == {"none"}, f"only the 'none' login was tried, no password (sshd log: {sorted(methods)})")
        check("userauth_send_banner: sent" in log, "sshd sent the banner (sshd log)")
    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            p.wait(timeout=10)
        if os.environ.get("BR_KEEP_LOG"):
            print(open(log_child).read())
        shutil.rmtree(tmp, ignore_errors=True)
    if check.failed:
        sys.exit(1)
    print("All Find PCs checks passed.")


if __name__ == "__main__":
    main()
