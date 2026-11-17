# -----------------------------------------------------------------------------
# Blighter Restrictor - talking to a child's laptop over SSH.
#
# Purpose: log in to the laptop's "blighter" admin account with its password
# (Paramiko, pure Python, works the same on Linux and Windows) and run the
# helper.  Nothing else is ever executed remotely.  Connections are reused
# while they stay open.
# The laptop's operating system is recognised from its SSH server's greeting
# (Windows' OpenSSH announces itself as "OpenSSH_for_Windows"):
#   Ubuntu  -> sudo -n /usr/sbin/blighter-apply <args>
#   Windows -> C:\ProgramData\BlighterChild\blighter-apply.cmd <args>
#              (an administrator's SSH session on Windows already has full
#              rights, so there is no sudo)
# Host keys are remembered on first connection (trust on first use) in the
# app's own known_hosts file; if a laptop is reinstalled, use
# "Forget host key" in the child's settings.
# A command that times out is NOT retried (that only doubled the wait);
# a dropped connection (laptop slept) is reconnected once.
# Logging out closes the SSH session on the laptop; this happens on request
# (Log out button / menu), after 5 minutes without use, and when the app closes.
#
# Copyright (C) 2026 Ways Property
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version.  It is distributed WITHOUT ANY WARRANTY; see the
# LICENSE file or <https://www.gnu.org/licenses/> for details.
# -----------------------------------------------------------------------------

import json
import os
import re
import shlex
import socket
import threading
import time

import paramiko

HELPER = "/usr/sbin/blighter-apply"
WIN_HELPER = r"C:\ProgramData\BlighterChild\blighter-apply.cmd"
_SAFE_ARG = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


class RemoteError(Exception):
    pass


def is_reachable(ip, port=22, timeout=1.5):
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except OSError:
        return False


def forget_host_key(known_hosts, ip, port=22):
    if not os.path.exists(known_hosts):
        return
    hk = paramiko.HostKeys(known_hosts)
    for name in (ip, f"[{ip}]:{port}"):
        if name in hk:
            del hk[name]
    hk.save(known_hosts)


class Remote:
    """One SSH connection to one child's laptop."""

    def __init__(self, child, password, known_hosts):
        self.child = child
        self.password = password
        self.known_hosts = known_hosts
        self._client = None
        self._lock = threading.Lock()
        self.last_used = time.monotonic()
        self.windows = False

    @property
    def connected(self):
        c = self._client
        return bool(c and c.get_transport() and c.get_transport().is_active())

    def close(self):
        with self._lock:
            if self._client:
                self._client.close()
            self._client = None

    def _connect(self):
        if self._client and self._client.get_transport() and self._client.get_transport().is_active():
            return self._client
        c = self.child
        client = paramiko.SSHClient()
        if not os.path.exists(self.known_hosts):
            open(self.known_hosts, "a").close()
        client.load_host_keys(self.known_hosts)
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(c.ip, port=c.port, username=c.admin_user, password=self.password,
                           timeout=8, auth_timeout=15, banner_timeout=15,
                           allow_agent=False, look_for_keys=False)
        except paramiko.BadHostKeyException:
            raise RemoteError(
                f"The SSH host key for {c.ip} has changed.  If the laptop was reinstalled, "
                "open the child's settings and press 'Forget host key'.  Otherwise "
                "another machine may be using that address.")
        except paramiko.BadAuthenticationType:
            raise RemoteError(f"{c.ip} does not accept password login for '{c.admin_user}'.  "
                              "Run the Blighter setup on the laptop again.")
        except paramiko.AuthenticationException:
            raise RemoteError(f"Login refused for '{c.admin_user}' on {c.ip} - check the password.")
        except (socket.timeout, TimeoutError, paramiko.ssh_exception.NoValidConnectionsError, OSError) as e:
            raise RemoteError(f"Cannot reach {c.name}'s laptop at {c.ip}:{c.port} ({e}). "
                              "Is it switched on and on the home network?")
        except paramiko.SSHException as e:
            raise RemoteError(f"SSH error talking to {c.ip}: {e}")
        self.windows = "windows" in (client.get_transport().remote_version or "").lower()
        self._client = client
        return client

    def _command(self, args):
        if self.windows:
            # cmd.exe and PowerShell both run this unquoted form; arguments are
            # restricted to simple words so nothing needs quoting.
            for a in args:
                if not _SAFE_ARG.match(a):
                    raise RemoteError(f"Refusing unsafe helper argument {a!r}")
            return WIN_HELPER + " " + " ".join(args)
        return "sudo -n " + HELPER + " " + " ".join(shlex.quote(a) for a in args)

    def run_helper(self, args, stdin_text=None, timeout=90):
        """Run the helper; returns (exit_code, stdout, stderr)."""
        self.last_used = time.monotonic()
        with self._lock:
            for attempt in (1, 2):
                client = self._connect()
                cmd = self._command(args)
                try:
                    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
                    if stdin_text is not None:
                        stdin.write(stdin_text)
                    stdin.channel.shutdown_write()
                    out = stdout.read().decode("utf-8", "replace")
                    err = stderr.read().decode("utf-8", "replace")
                    code = stdout.channel.recv_exit_status()
                    self.last_used = time.monotonic()
                    break
                except (socket.timeout, TimeoutError):
                    # The laptop is connected but slow to answer.  Retrying would
                    # only double the wait, so report it straight away.
                    try:
                        client.close()
                    except Exception:
                        pass
                    self._client = None
                    raise RemoteError(f"{self.child.name}'s laptop did not answer within {timeout} seconds.  "
                                      "It may be busy (for example installing updates) - try again shortly.")
                except (paramiko.SSHException, EOFError, OSError) as e:
                    # Connection went stale (laptop slept) - reconnect once.
                    self._client = None
                    if attempt == 2:
                        raise RemoteError(f"Connection to {self.child.ip} lost: {e}")
        if self.windows:
            if "is not recognized" in err or "cannot find the path" in err.lower():
                raise RemoteError("The Blighter child component is not installed on that Windows laptop.  "
                                  "Run 'Install Blighter Child.cmd' on it.")
            return code, out, err
        if "a password is required" in err or "may not run sudo" in err or "not allowed to execute" in err:
            raise RemoteError("The admin account is not allowed to run the helper.  "
                              "Run 'sudo blighter-setup <child>' on the laptop.")
        if "command not found" in err or "No such file" in err and HELPER in err:
            raise RemoteError("The blighter-child package is not installed on that laptop.")
        return code, out, err

    def _json(self, args, stdin_text=None):
        code, out, err = self.run_helper(args, stdin_text)
        try:
            return json.loads(out)
        except ValueError:
            raise RemoteError(f"Unexpected reply from laptop (exit {code}): {(err or out)[:800]}")

    # ---- operations -----------------------------------------------------------------
    def get(self):
        return self._json(["get"])

    def status(self):
        return self._json(["status"])

    def apply(self, mode, allow, block, discord=None):
        data = {"mode": mode, "allow": allow, "block": block}
        if discord is not None:          # older laptops (before 1.2.2) have no Discord switch
            data["discord"] = bool(discord)
        return self._json(["set"], json.dumps(data))

    def reload(self):
        return self._json(["reload"])

    def log(self, lines, rotated=False):
        args = ["log", str(int(lines))] + (["rotated"] if rotated else [])
        code, out, err = self.run_helper(args, timeout=180)
        if code != 0:
            raise RemoteError(f"Could not read the log: {err or out}")
        return out


class RemoteManager:
    """Keeps one Remote per child and rebuilds it when settings change."""

    def __init__(self, store):
        self.store = store
        self._remotes = {}
        self._lock = threading.Lock()

    def get(self, child):
        pw = self.store.get_password(child)
        if not pw:
            raise RemoteError(f"No password stored for {child.name}.  Edit the child and enter it.")
        with self._lock:
            r = self._remotes.get(child.id)
            if r is None or r.password != pw or r.child != child:
                if r:
                    r.close()
                r = Remote(child, pw, self.store.known_hosts)
                self._remotes[child.id] = r
            return r

    def drop(self, child):
        with self._lock:
            r = self._remotes.pop(child.id, None)
        if r:
            r.close()

    def is_connected(self, child):
        r = self._remotes.get(child.id)
        return bool(r and r.connected)

    def close_idle(self, seconds, keep_ids=()):
        """Log out of laptops not used for `seconds`. Returns names logged out."""
        now = time.monotonic()
        with self._lock:
            idle = [r for cid, r in self._remotes.items()
                    if cid not in keep_ids and r.connected and now - r.last_used > seconds]
        for r in idle:
            r.close()
        return [r.child.name for r in idle]

    def close_all(self):
        with self._lock:
            rs = list(self._remotes.values())
            self._remotes.clear()
        for r in rs:
            r.close()
