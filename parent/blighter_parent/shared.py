# -----------------------------------------------------------------------------
# Blighter Restrictor - access to the shared domain rules.
# Purpose: import common/domains.py whether running from the packaged app
# (where the build copies it into this package) or straight from the source
# tree (where it lives in ../../common).
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

__all__ = ["domains"]
