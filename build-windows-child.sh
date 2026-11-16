#!/bin/bash
# -----------------------------------------------------------------------------
# Blighter Restrictor - build the Windows child-laptop package (on Linux).
#
# Purpose: assemble dist/blighter-child-windows-<ver>.zip, which the parent
# unzips on the child's Windows 10/11 laptop and runs
# "Install Blighter Child.cmd".  It contains the helper, the setup and
# firewall scripts, the managed squid.conf, the shared common/domains.py
# (same file as the parent app and the Ubuntu package) and the official
# python.org "embeddable" Python, so nothing has to be compiled on Windows.
# Squid itself is downloaded from Diladele by the setup script.
# Usage: ./build-windows-child.sh      (needs curl and zip)
#
# Copyright (C) 2026 Ways Property
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
PY_VER=3.13.17
PY_ZIP=build/cache/python-$PY_VER-embed-amd64.zip
NAME=blighter-child-windows-$VER
OUT=dist
STAGE=build/$NAME

mkdir -p build/cache "$OUT"
if [ ! -f "$PY_ZIP" ]; then
    curl -fL -o "$PY_ZIP.tmp" "https://www.python.org/ftp/python/$PY_VER/python-$PY_VER-embed-amd64.zip"
    mv "$PY_ZIP.tmp" "$PY_ZIP"
fi

rm -rf "$STAGE"
mkdir -p "$STAGE/python"
unzip -q "$PY_ZIP" -d "$STAGE/python"
cp child-windows/blighter-apply.py child-windows/blighter-system.ps1 \
   child-windows/blighter-setup.ps1 child-windows/squid.conf "$STAGE/"
cp common/domains.py "$STAGE/"
cp LICENSE "$STAGE/LICENSE.txt"
# Windows command files need CRLF line endings.
for f in child-windows/*.cmd; do
    sed 's/\r$//; s/$/\r/' "$f" > "$STAGE/$(basename "$f")"
done
for f in "$STAGE"/*.ps1; do sed -i 's/\r$//; s/$/\r/' "$f"; done
sed -i "s/^\$Version   = \".*\"/\$Version   = \"$VER\"/" "$STAGE/blighter-setup.ps1"

# Windows PowerShell 5.1 reads BOM-less scripts as ANSI: keep them pure ASCII.
if LC_ALL=C grep -nP '[^\x00-\x7F]' "$STAGE"/*.ps1 "$STAGE"/*.cmd; then
    echo "Non-ASCII characters found in Windows scripts (see above)" >&2; exit 1
fi

rm -f "$OUT/$NAME.zip"
(cd build && zip -qr "../$OUT/$NAME.zip" "$NAME")
ls -l "$OUT/$NAME.zip"
