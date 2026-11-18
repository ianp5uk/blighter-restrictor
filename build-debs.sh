#!/bin/bash
# -----------------------------------------------------------------------------
# Blighter Restrictor - build both Ubuntu packages.
#
# Purpose: assemble and build
#   dist/blighter-restrictor_<ver>_all.deb  (parent app with the GUI)
#   dist/blighter-child_<ver>_all.deb       (installed on each child's laptop)
# The shared common/domains.py is copied into both so their checks match.
# Each gets the GPL copyright file and THIRD-PARTY-NOTICES.txt in
# /usr/share/doc/<package>/.
# Usage: ./build-debs.sh      (needs dpkg-deb, run on Ubuntu/Debian)
#
# Copyright (C) 2026 Ian Packer
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version.  It is distributed WITHOUT ANY WARRANTY; see the
# LICENSE file or <https://www.gnu.org/licenses/> for details.
# -----------------------------------------------------------------------------
set -euo pipefail
cd "$(dirname "$0")"
VER=$(grep -oP '__version__ = "\K[^"]+' parent/blighter_parent/__init__.py)
OUT=dist
BUILD=build
rm -rf "$BUILD"
mkdir -p "$OUT" "$BUILD"
find . -name __pycache__ -prune -exec rm -rf {} +

# ---- child package -----------------------------------------------------------
C=$BUILD/blighter-child
mkdir -p "$C"
cp -a child/files/. "$C/"
cp -a child/DEBIAN "$C/DEBIAN"
sed -i "s/^Version: .*/Version: $VER/" "$C/DEBIAN/control"
install -D -m 644 common/domains.py "$C/usr/lib/blighter-child/domains.py"
install -D -m 644 common/blockpage.py "$C/usr/lib/blighter-child/blockpage.py"
chmod 755 "$C/usr/sbin/"*
mkdir -p "$C/usr/share/doc/blighter-child" && grep -v "^#" packaging-copyright > "$C/usr/share/doc/blighter-child/copyright"
install -m 644 THIRD-PARTY-NOTICES.txt "$C/usr/share/doc/blighter-child/THIRD-PARTY-NOTICES.txt"
dpkg-deb --root-owner-group --build "$C" "$OUT/blighter-child_${VER}_all.deb"

# ---- parent package ----------------------------------------------------------
P=$BUILD/blighter-restrictor
mkdir -p "$P/usr/lib/blighter-restrictor"
cp -a parent/blighter_parent "$P/usr/lib/blighter-restrictor/"
install -m 644 common/domains.py "$P/usr/lib/blighter-restrictor/blighter_parent/domains.py"
install -D -m 755 parent/packaging/blighter-restrictor "$P/usr/bin/blighter-restrictor"
install -D -m 644 parent/packaging/blighter-restrictor.desktop \
    "$P/usr/share/applications/blighter-restrictor.desktop"
install -D -m 644 parent/blighter_parent/icon.svg \
    "$P/usr/share/icons/hicolor/scalable/apps/blighter-restrictor.svg"
cp -a parent/packaging/DEBIAN "$P/DEBIAN"
sed -i "s/^Version: .*/Version: $VER/" "$P/DEBIAN/control"
mkdir -p "$P/usr/share/doc/blighter-restrictor" && grep -v "^#" packaging-copyright > "$P/usr/share/doc/blighter-restrictor/copyright"
install -m 644 THIRD-PARTY-NOTICES.txt "$P/usr/share/doc/blighter-restrictor/THIRD-PARTY-NOTICES.txt"
dpkg-deb --root-owner-group --build "$P" "$OUT/blighter-restrictor_${VER}_all.deb"

ls -l "$OUT"
