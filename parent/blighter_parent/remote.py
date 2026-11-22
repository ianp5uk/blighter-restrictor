# -----------------------------------------------------------------------------
# Blighter Restrictor - talking to a child's PC over SSH.
#
# Purpose: log in to the PC's "blighter" admin account with its password
# (Paramiko, pure Python, works the same on Linux and Windows) and run the
# helper.  Nothing else is ever executed remotely.  Connections are reused
# while they stay open.
# The PC's operating system is recognised from its SSH server's greeting
# (Windows' OpenSSH announces itself as "OpenSSH_for_Windows"):
#   Ubuntu  -> sudo -n /usr/sbin/blighter-apply <args>
#   Windows -> C:\ProgramData\BlighterChild\blighter-apply.cmd <args>
#              (an administrator's SSH session on Windows already has full
#              rights, so there is no sudo)
# The PC's SSH identity (host key) is remembered the first time the app
# connects after "Add child" (trust on first use) and saved with the child
# (config_store.Child.host_key).  Every later connection checks it BEFORE
# the password is sent.  If the PC is not at its last known address, or a
# different machine now has that address, discovery.find_pc() looks for it
# on the home network and the new address is saved automatically (at most
# one search a minute per child).  If the identity itself has changed (the
# PC was reinstalled, or replaced) the app does not guess: "Reconnect" in
# the parent app lets the parent confirm it.
# Children saved by 1.2.5 and earlier: their identity is taken from the old
# known_hosts file on first use and saved with the child.
# A command that times out is NOT retried (that only doubled the wait);
# a dropped connection (PC slept) is reconnected once.
# Logging out closes the SSH session on the PC; this happens on request
# (Log out button / menu) and when the app closes.  (There is no automatic
# log-out after a few idle minutes any more: while logged in, the app keeps
# collecting the child's activity - see collector.py.)
#
# Copyright (C) 2026 Ian Packer
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

from . import discovery

HELPER = "/usr/sbin/blighter-apply"
WIN_HELPER = r"C:\ProgramData\BlighterChild\blighter-apply.cmd"
_SAFE_ARG = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


DISCOVERY_INTERVAL = 60          # seconds between searches for one child's PC
_last_search = {}                # child id -> time.monotonic() of the last search
_search_lock = threading.Lock()


class RemoteError(Exception):
    pass


class Unreachable(RemoteError):
    """Nothing answered at the PC's address."""


class IdentityChanged(RemoteError):
    """Something answered, but with a different SSH identity."""

    def __init__(self, msg, key_text=""):
        super().__init__(msg)
        self.key_text = key_text


def legacy_host_key(known_hosts, ip, port=22):
    """The key a 1.2.5-or-earlier app remembered for this address, as text."""
    if not known_hosts or not os.path.exists(known_hosts):
        return ""
    try:
        hk = paramiko.HostKeys(known_hosts)
    except Exception:
        return ""
    for name in (ip, f"[{ip}]:{port}"):
        keys = hk.lookup(name)
        if keys:
            for t in keys.keys():
                return discovery.key_to_text(keys[t])
    return ""


def search_allowed(child_id, force=False):
    """At most one search a minute per child (unless forced)."""
    now = time.monotonic()
    with _search_lock:
        if not force and now - _last_search.get(child_id, -1e9) < DISCOVERY_INTERVAL:
            return False
        _last_search[child_id] = now
        return True


def is_reachable(ip, port=22, timeout=1.5):
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except OSError:
        return False


class Remote:
    """One SSH connection to one child's PC.

    child: the child's record (its .ip is updated when the PC is found at a
    new address).  on_change(child): called (from a background thread) when
    .ip or .host_key changed, to save it.  discover=False: only try the
    address given (used by Add child / Reconnect)."""

    def __init__(self, child, password, known_hosts, on_change=None, discover=True):
        self.child = child
        self.password = password
        self.known_hosts = known_hosts
        self.on_change = on_change
        self.discover = discover
        self._client = None
        self._lock = threading.Lock()
        self.last_used = time.monotonic()
        self.windows = False
        self.moved_from = None          # old address, after the PC was found somewhere else

    @property
    def connected(self):
        c = self._client
        return bool(c and c.get_transport() and c.get_transport().is_active())

    def close(self):
        with self._lock:
            if self._client:
                self._client.close()
            self._client = None

    def _expected_key(self):
        c = self.child
        text = getattr(c, "host_key", "") or legacy_host_key(self.known_hosts, c.ip, getattr(c, "port", 22))
        return discovery.key_from_text(text)

    def _connect_to(self, ip, expected):
        """Log in at ip, checking the SSH identity before the password is sent."""
        c = self.child
        client = paramiko.SSHClient()
        if expected:
            name = ip if c.port == 22 else f"[{ip}]:{c.port}"
            client.get_host_keys().add(name, expected.get_name(), expected)
        # No identity yet (just added): remember the one offered (trust on first use).
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(ip, port=c.port, username=c.admin_user, password=self.password,
                           timeout=8, auth_timeout=15, banner_timeout=15,
                           allow_agent=False, look_for_keys=False)
        except paramiko.BadHostKeyException as e:
            raise IdentityChanged(
                f"The computer at {ip} is not the one saved as {c.name}'s PC.", discovery.key_to_text(e.key))
        except paramiko.BadAuthenticationType:
            raise RemoteError(f"{ip} does not accept password login for '{c.admin_user}'.  "
                              "Run the Blighter setup on the PC again.")
        except paramiko.AuthenticationException:
            raise RemoteError(f"Login refused for '{c.admin_user}' on {c.name}'s PC ({ip}) - check the password.")
        except (socket.timeout, TimeoutError, paramiko.ssh_exception.NoValidConnectionsError, OSError) as e:
            raise Unreachable(f"Cannot reach {c.name}'s PC at {ip}:{c.port} ({e}).")
        except paramiko.SSHException as e:
            raise RemoteError(f"SSH error talking to {ip}: {e}")
        return client

    def _connect(self):
        if self._client and self._client.get_transport() and self._client.get_transport().is_active():
            return self._client
        c = self.child
        expected = self._expected_key()
        try:
            client = self._connect_to(c.ip, expected)
        except (Unreachable, IdentityChanged) as first:
            # Not at its last known address: look for it on the home network.
            found = None
            if self.discover and expected and search_allowed(c.id):
                found = discovery.find_pc(discovery.key_to_text(expected), c.ip, c.port)
            if not found or found == c.ip:
                if isinstance(first, IdentityChanged):
                    raise IdentityChanged(
                        f"{c.name}'s PC was not found: the computer at {c.ip} is a different one, and "
                        f"no computer on the home network has {c.name}'s PC's identity.  If Blighter "
                        f"was reinstalled on {c.name}'s PC, select {c.name} and press Reconnect.",
                        first.key_text)
                raise Unreachable(f"Cannot find {c.name}'s PC.  Make sure it is switched on and connected "
                                  "to the same home network.")
            client = self._connect_to(found, expected)
            self.moved_from, c.ip = c.ip, found
        new_key = discovery.key_to_text(client.get_transport().get_remote_server_key())
        changed = self.moved_from is not None
        if getattr(c, "host_key", None) is not None and c.host_key != new_key:
            c.host_key = new_key            # first connection (or taken over from known_hosts)
            changed = True
        if changed and self.on_change:
            self.on_change(c)
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
                    # The PC is connected but slow to answer.  Retrying would
                    # only double the wait, so report it straight away.
                    try:
                        client.close()
                    except Exception:
                        pass
                    self._client = None
                    raise RemoteError(f"{self.child.name}'s PC did not answer within {timeout} seconds.  "
                                      "It may be busy (for example installing updates) - try again shortly.")
                except (paramiko.SSHException, EOFError, OSError) as e:
                    # Connection went stale (PC slept) - reconnect once.
                    self._client = None
                    if attempt == 2:
                        raise RemoteError(f"Connection to {self.child.ip} lost: {e}")
        if self.windows:
            if "is not recognized" in err or "cannot find the path" in err.lower():
                raise RemoteError("The Blighter child component is not installed on that Windows PC.  "
                                  "Run the Blighter Child installer on it.")
            return code, out, err
        if "a password is required" in err or "may not run sudo" in err or "not allowed to execute" in err:
            raise RemoteError("The admin account is not allowed to run the helper.  "
                              "Run 'sudo blighter-setup <child>' on the PC.")
        if "command not found" in err or "No such file" in err and HELPER in err:
            raise RemoteError("The blighter-child package is not installed on that PC.")
        return code, out, err

    def _json(self, args, stdin_text=None):
        code, out, err = self.run_helper(args, stdin_text)
        try:
            return json.loads(out)
        except ValueError:
            raise RemoteError(f"Unexpected reply from the PC (exit {code}): {(err or out)[:800]}")

    # ---- operations -----------------------------------------------------------------
    def get(self):
        return self._json(["get"])

    def status(self):
        return self._json(["status"])

    def apply(self, mode, allow, block, discord=None, home_net=None, opera=None):
        data = {"mode": mode, "allow": allow, "block": block}
        if opera is not None:            # older PCs (before 1.2.4) have no Opera switch
            data["opera"] = bool(opera)
        if discord is not None:          # older PCs (before 1.2.2) have no Discord switch
            data["discord"] = bool(discord)
        if home_net is not None:         # older PCs (before 1.2.3) have no home network setting
            data["home_net"] = home_net
        return self._json(["set"], json.dumps(data))

    def pause(self):
        return self._json_t(["pause"], 300)

    def resume(self):
        return self._json_t(["resume"], 300)

    def netinfo(self):
        return self._json_t(["netinfo"], 90)

    def _json_t(self, args, timeout):
        code, out, err = self.run_helper(args, timeout=timeout)
        try:
            return json.loads(out)
        except ValueError:
            if "usage" in (err + out).lower():
                raise RemoteError("This PC's Blighter child version is too old for this - "
                                  "update it to 1.2.3 or later.")
            raise RemoteError(f"Unexpected reply from the PC (exit {code}): {(err or out)[:800]}")

    def reload(self):
        return self._json(["reload"])

    def log(self, lines, rotated=False):
        args = ["log", str(int(lines))] + (["rotated"] if rotated else [])
        code, out, err = self.run_helper(args, timeout=180)
        if code != 0:
            raise RemoteError(f"Could not read the log: {err or out}")
        return out

    def log_start(self, lines, rotated=False):
        """{"ino", "offset", "lines", "bypassed"}: the last `lines` lines and
        the log position.  Raises TooOld on PCs before 1.2.6."""
        args = ["logstart", str(int(lines))] + (["rotated"] if rotated else [])
        return self._log_json(args)

    def log_next(self, ino, offset):
        """{"ino", "offset", "lines", "more", "gap", "bypassed"}: lines since then."""
        return self._log_json(["lognext", ino or "-", str(int(offset))])

    def _log_json(self, args):
        code, out, err = self.run_helper(args, timeout=180)
        try:
            return json.loads(out)
        except ValueError:
            if "usage" in (err + out).lower():
                raise TooOld("This PC's Blighter child version is older than 1.2.6.")
            raise RemoteError(f"Could not read the log (exit {code}): {(err or out)[:800]}")


class TooOld(RemoteError):
    """The PC's helper does not know this command (older Blighter child)."""


class RemoteManager:
    """Keeps one Remote per child and rebuilds it when settings change.
    A new address or identity found while connecting is saved at once."""

    def __init__(self, store):
        self.store = store
        self._remotes = {}
        self._lock = threading.Lock()
        self.changed = []           # callbacks(child), run on the connecting thread

    def _child_changed(self, child):
        self.store.save()
        for cb in list(self.changed):
            cb(child)

    def get(self, child):
        pw = self.store.get_password(child)
        if not pw:
            raise RemoteError(f"No password stored for {child.name}.  Edit the child and enter it.")
        with self._lock:
            r = self._remotes.get(child.id)
            if r is None or r.password != pw or r.child != child:
                if r:
                    r.close()
                r = Remote(child, pw, self.store.known_hosts, on_change=self._child_changed)
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

    def close_all(self):
        with self._lock:
            rs = list(self._remotes.values())
            self._remotes.clear()
        for r in rs:
            r.close()
