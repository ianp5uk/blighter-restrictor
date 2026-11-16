# -----------------------------------------------------------------------------
# Blighter Restrictor - shared domain rules and small shared helpers.
# Purpose: import common/domains.py whether running from the packaged app
# (where the build copies it into this package) or straight from the source
# tree (where it lives in ../../common).  Also holds helpers used by several
# windows: comparing usernames (Windows names ignore case) and the warning
# shown when a child's account is an administrator on their laptop.
#
# Copyright (C) 2026 Ways Property
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version.  It is distributed WITHOUT ANY WARRANTY; see the
# LICENSE file or <https://www.gnu.org/licenses/> for details.
# -----------------------------------------------------------------------------
import os
import sys

try:
    from . import domains  # noqa: F401  (packaged)
except ImportError:  # running from source
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "common"))
    import domains  # noqa: F401



def same_user(a, b, platform=None):
    """True if two account names are the same (case-insensitive on Windows)."""
    a, b = (a or ""), (b or "")
    return a.lower() == b.lower() if platform == "windows" else a == b


ADMIN_WARNING = ("The child's account is an ADMINISTRATOR on this laptop, so they can "
                 "switch off the filter, firewall or this app's access.  Filtering still "
                 "works, but it cannot stop an administrator who goes looking.  Fix: give "
                 "yourself a separate administrator account on the laptop and make the "
                 "child a Standard user.")


def admin_warning_html(status):
    """Red warning (HTML) if the laptop reports the child as an administrator."""
    if status.get("child_is_admin"):
        return f"<br><span style='color:#c0392b'><b>Warning:</b> {ADMIN_WARNING}</span>"
    return ""


__all__ = ["domains", "same_user", "admin_warning_html", "ADMIN_WARNING"]
