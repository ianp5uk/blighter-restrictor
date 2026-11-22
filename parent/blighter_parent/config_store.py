# -----------------------------------------------------------------------------
# Blighter Restrictor - local settings and password storage.
#
# Purpose: keep the list of children (name, the PC's last known IPv4
# address, the child's username on that PC, admin login, SSH port and the
# PC's SSH identity) in a JSON file in the user's config folder, and keep
# the admin passwords in the operating system's keyring (GNOME Keyring on
# Ubuntu, Credential Manager on Windows).
# The SSH identity (host_key, "<type> <base64>") is remembered the first time
# the app connects after "Add child".  It is how the app recognises the PC
# when home-network DHCP gives it a different address (see discovery.py);
# the address is then updated here automatically.  Children saved by 1.2.5
# and earlier have no host_key yet: it is taken from the old known_hosts
# file (or the next connection) and saved.
# Saving is safe from background threads (a lock), because a changed address
# is saved by the connection code.
# If no keyring is available, passwords are kept in memory for this session
# only and the user is asked again next time.
# Display preferences (text size) are kept in settings.json alongside.
#   Linux:   ~/.config/blighter-restrictor/children.json
#   Windows: %APPDATA%\BlighterRestrictor\children.json
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
import sys
import threading
import uuid
from dataclasses import asdict, dataclass, field, fields

KEYRING_SERVICE = "blighter-restrictor"


def config_dir():
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        path = os.path.join(base, "BlighterRestrictor")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
        path = os.path.join(base, "blighter-restrictor")
    os.makedirs(path, exist_ok=True)
    return path


@dataclass
class Child:
    name: str
    ip: str
    child_user: str
    admin_user: str = "blighter"
    port: int = 22
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    host_key: str = ""          # the PC's SSH identity, "<type> <base64>"

    def label(self):
        return f"{self.name}  ({self.ip})"


class Store:
    def __init__(self):
        self.path = os.path.join(config_dir(), "children.json")
        self.known_hosts = os.path.join(config_dir(), "known_hosts")
        self.settings_path = os.path.join(config_dir(), "settings.json")
        self.children = []
        self._lock = threading.RLock()
        self._memory_pw = {}
        self.keyring_error = None
        try:
            import keyring  # noqa: F401
            self._keyring = keyring
        except Exception as e:  # pragma: no cover - depends on platform
            self._keyring = None
            self.keyring_error = str(e)
        self.load()

    # ---- children -------------------------------------------------------------
    def load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            known = {f.name for f in fields(Child)}
            self.children = [Child(**{k: v for k, v in c.items() if k in known})
                             for c in data.get("children", [])]
        except FileNotFoundError:
            self.children = []
        except (ValueError, TypeError) as e:
            raise RuntimeError(f"Settings file {self.path} is damaged: {e}")

    def save(self):
        with self._lock:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"children": [asdict(c) for c in self.children]}, f, indent=2)
            os.replace(tmp, self.path)

    def upsert(self, child):
        for i, c in enumerate(self.children):
            if c.id == child.id:
                self.children[i] = child
                break
        else:
            self.children.append(child)
        self.save()

    @staticmethod
    def same_pc(a, b):
        """Two entries for the same PC?  With SSH identities known on both,
        those decide (addresses move with DHCP); otherwise the same address
        and child username (compared ignoring case, as Windows does)."""
        if a.host_key and b.host_key:
            return a.host_key == b.host_key
        if a.host_key or b.host_key:
            return False
        return (a.ip.strip() == b.ip.strip()
                and a.child_user.strip().lower() == b.child_user.strip().lower())

    def find_duplicate(self, child):
        """Another entry for the same PC.  Each child's PC may be listed only
        once - two entries for one PC each kept their own connection and
        state and confused each other."""
        for c in self.children:
            if c.id != child.id and self.same_pc(c, child):
                return c
        return None

    def duplicates(self):
        """[(entry, earlier entry for the same PC)] in the saved list."""
        found = []
        for i, c in enumerate(self.children):
            for earlier in self.children[:i]:
                if self.same_pc(earlier, c):
                    found.append((c, earlier))
                    break
        return found

    def remove(self, child):
        self.children = [c for c in self.children if c.id != child.id]
        self.delete_password(child)
        self.save()

    # ---- display settings -------------------------------------------------------
    def get_setting(self, key, default=None):
        try:
            with open(self.settings_path, encoding="utf-8") as f:
                return json.load(f).get(key, default)
        except (FileNotFoundError, ValueError):
            return default

    def set_setting(self, key, value):
        try:
            with open(self.settings_path, encoding="utf-8") as f:
                data = json.load(f)
        except (FileNotFoundError, ValueError):
            data = {}
        data[key] = value
        with open(self.settings_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    # ---- passwords --------------------------------------------------------------
    def get_password(self, child):
        if child.id in self._memory_pw:
            return self._memory_pw[child.id]
        if self._keyring:
            try:
                return self._keyring.get_password(KEYRING_SERVICE, child.id)
            except Exception as e:
                self.keyring_error = str(e)
        return None

    def set_password(self, child, password):
        """Store the password. Returns True if saved to the keyring,
        False if only kept in memory for this session."""
        self._memory_pw[child.id] = password
        if self._keyring:
            try:
                self._keyring.set_password(KEYRING_SERVICE, child.id, password)
                return True
            except Exception as e:
                self.keyring_error = str(e)
        return False

    def delete_password(self, child):
        self._memory_pw.pop(child.id, None)
        if self._keyring:
            try:
                self._keyring.delete_password(KEYRING_SERVICE, child.id)
            except Exception:
                pass
