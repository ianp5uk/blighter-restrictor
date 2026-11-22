# -----------------------------------------------------------------------------
# Blighter Restrictor - reading the Squid access log a piece at a time.
#
# Purpose: shared by both PC helpers (Ubuntu blighter-apply and Windows
# blighter-apply.py) so the parent app can collect activity without
# downloading the same lines again and again:
#   start(...)  the last N lines (optionally reaching into older, rotated
#               logs) plus a position: the log file's identity and the byte
#               offset just after the last complete line
#   next(...)   only the complete lines written since that position.  If
#               the log was rotated in between, the rest of the old file is
#               read first, then the new file from its start.  If the old
#               file can no longer be found (compressed or deleted), or the
#               log was truncated, "gap" says some lines may be missing.
# A file's identity is its inode number (Ubuntu) or NTFS file ID (Windows);
# both survive a rename, which is how Squid / logrotate rotate the log.
# A partly written last line is never returned; it is picked up next time.
# At most MAX_BYTES are returned per call; "more" asks the app to call again.
#
# Copyright (C) 2026 Ian Packer
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version.  It is distributed WITHOUT ANY WARRANTY; see the
# LICENSE file or <https://www.gnu.org/licenses/> for details.
# -----------------------------------------------------------------------------

import gzip
import os

MAX_BYTES = 512 * 1024
_BLOCK = 256 * 1024


def ident(path):
    """The file's identity as a short string of digits ("" if missing)."""
    try:
        st = os.stat(path)
    except OSError:
        return ""
    if st.st_ino:
        return str(st.st_ino)
    return "c" + str(int(getattr(st, "st_ctime_ns", int(st.st_ctime * 1e9))))


def _decode(data):
    return data.decode("utf-8", "replace").splitlines()


def _read_from(path, offset, max_bytes=MAX_BYTES):
    """Complete lines from `offset`: (lines, new_offset, more)."""
    with open(path, "rb") as f:
        f.seek(offset)
        data = f.read(max_bytes + 1)
    more = len(data) > max_bytes
    data = data[:max_bytes]
    cut = data.rfind(b"\n")
    if cut < 0:
        if more:                      # one enormous line: return it as it is
            return _decode(data), offset + len(data), True
        return [], offset, False      # only a partly written line so far
    chunk = data[:cut + 1]
    return _decode(chunk), offset + len(chunk), more


def _tail(path, n):
    """The last n complete lines of a plain file and the end offset of the
    last complete line: (lines, end_offset)."""
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        pos, buf = size, b""
        while pos > 0 and buf.count(b"\n") <= n:
            step = min(_BLOCK, pos)
            pos -= step
            f.seek(pos)
            buf = f.read(step) + buf
    cut = buf.rfind(b"\n")
    end = size - (len(buf) - cut - 1) if cut >= 0 else size - len(buf)
    lines = _decode(buf[:cut + 1]) if cut >= 0 else []
    if pos > 0 and lines:
        lines = lines[1:]             # the first one may be cut off
    return lines[-n:] if n else [], end


def _all_lines(path):
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8", errors="replace") as f:
        return f.read().splitlines()


def start(current, rotated, n, include_rotated):
    """current: path of access.log.  rotated: older logs, newest first
    (plain or .gz).  Returns {"ino", "offset", "lines"} (oldest line first)."""
    n = max(1, int(n))
    ino = ident(current)
    lines, offset = [], 0
    if ino:
        try:
            lines, offset = _tail(current, n)
        except OSError:
            lines, offset = [], 0
    if include_rotated and len(lines) < n:
        for p in rotated:
            try:
                older = _all_lines(p)
            except (OSError, EOFError):
                continue
            lines = older + lines
            if len(lines) >= n:
                break
    return {"ino": ino, "offset": offset, "lines": lines[-n:]}


def next_lines(current, rotated_plain, ino, offset):
    """Lines written since (ino, offset).  rotated_plain: uncompressed older
    logs, newest first.  Returns {"ino", "offset", "lines", "more", "gap"}."""
    try:
        offset = max(0, int(offset))
    except (TypeError, ValueError):
        offset = 0
    cur = ident(current)
    if not cur:
        return {"ino": "", "offset": 0, "lines": [], "more": False, "gap": False}
    if ino and ino == cur:
        gap = False
        if offset > os.path.getsize(current):     # truncated / replaced in place
            offset, gap = 0, True
        lines, new_off, more = _read_from(current, offset)
        return {"ino": cur, "offset": new_off, "lines": lines, "more": more, "gap": gap}
    # The log was rotated since the last call: finish the old file first.
    if ino:
        for p in rotated_plain:
            if ident(p) == ino:
                try:
                    lines, new_off, more = _read_from(p, offset)
                except OSError:
                    break
                if more:
                    return {"ino": ino, "offset": new_off, "lines": lines, "more": True, "gap": False}
                return {"ino": cur, "offset": 0, "lines": lines, "more": True, "gap": False}
    # Old file not found (or no position yet): start the current file.
    return {"ino": cur, "offset": 0, "lines": [], "more": True, "gap": bool(ino)}
