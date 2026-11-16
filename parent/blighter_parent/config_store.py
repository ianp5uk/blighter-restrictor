# -----------------------------------------------------------------------------
# Blighter Restrictor - local settings and password storage.
#
# Purpose: keep the list of children (name, laptop IPv4 address, the child's
# username on that laptop, admin login, SSH port) in a JSON file in the
# user's config folder, and keep the admin passwords in the operating
# system's keyring (GNOME Keyring on Ubuntu, Credential Manager on Windows).
# If no keyring is available, passwords are kept in memory for this session
# only and the user is asked again next time.
# Display preferences (text size) are kept in settings.json alongside.
#   Linux:   ~/.config/blighter-restrictor/children.json
#   Windows: %APPDATA%\BlighterRestrictor\children.json
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
import sys
import uuid
from dataclasses import asdict, dataclass, field

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

    def label(self):
        return f"{self.name}  ({self.ip})"


class Store:
    def __init__(self):
        self.path = os.path.join(config_dir(), "children.json")
        self.known_hosts = os.path.join(config_dir(), "known_hosts")
        self.settings_path = os.path.join(config_dir(), "settings.json")
        self.children = []
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
            self.children = [Child(**c) for c in data.get("children", [])]
        except FileNotFoundError:
            self.children = []
        except (ValueError, TypeError) as e:
            raise RuntimeError(f"Settings file {self.path} is damaged: {e}")

    def save(self):
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
