#!/bin/bash
# -----------------------------------------------------------------------------
# Blighter Restrictor - build both Ubuntu packages.
#
# Purpose: assemble and build
#   dist/blighter-restrictor_<ver>_all.deb  (parent app with the GUI)
#   dist/blighter-child_<ver>_all.deb       (installed on each child's laptop)
# The shared common/domains.py is copied into both so their checks match.
# Usage: ./build-debs.sh      (needs dpkg-deb, run on Ubuntu/Debian)
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
chmod 755 "$C/usr/sbin/"*
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
dpkg-deb --root-owner-group --build "$P" "$OUT/blighter-restrictor_${VER}_all.deb"

ls -l "$OUT"
