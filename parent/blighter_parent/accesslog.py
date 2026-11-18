# -----------------------------------------------------------------------------
# Blighter Restrictor - Squid access-log parsing.
#
# Purpose: turn lines of Squid's native access.log format
#   time elapsed client result/status bytes method URL user hierarchy type
# e.g.
#   1763208000.123  45 127.0.0.1 TCP_TUNNEL/200 3456 CONNECT www.bbc.co.uk:443 - HIER_DIRECT/1.2.3.4 -
#   1763208001.456   0 127.0.0.1 TCP_DENIED/403 3870 CONNECT store.steampowered.com:443 - HIER_NONE/- text/html
# into simple records, and summarise them per site for the Activity tab.
# For HTTPS only the site name is visible (no SSL decryption), not the page.
#
# Copyright (C) 2026 Ian Packer
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version.  It is distributed WITHOUT ANY WARRANTY; see the
# LICENSE file or <https://www.gnu.org/licenses/> for details.
# -----------------------------------------------------------------------------

from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass
class Entry:
    ts: float
    host: str
    outcome: str   # "Allowed", "Blocked" or "Error"
    method: str
    status: int
    size: int
    url: str
    result: str


def parse_line(line):
    parts = line.split()
    if len(parts) < 7:
        return None
    try:
        ts = float(parts[0])
        size = int(parts[4])
    except ValueError:
        return None
    result, _, status = parts[3].partition("/")
    try:
        status_n = int(status)
    except ValueError:
        status_n = 0
    method, url = parts[5], parts[6]
    if url.startswith("error:"):
        return None  # connection noise (e.g. closed before any request)
    if method == "CONNECT":
        host = url.rsplit(":", 1)[0]
    else:
        try:
            host = urlsplit(url).hostname or url
        except ValueError:
            host = url
    host = host.strip("[]").lower()
    if "DENIED" in result:
        outcome = "Blocked"
    elif status_n >= 400 or status_n == 0:
        outcome = "Error"
    else:
        outcome = "Allowed"
    return Entry(ts, host, outcome, method, status_n, size, url, parts[3])


def parse(text):
    entries = []
    for line in text.splitlines():
        e = parse_line(line)
        if e:
            entries.append(e)
    entries.sort(key=lambda e: e.ts, reverse=True)
    return entries


@dataclass
class SiteSummary:
    host: str
    requests: int = 0
    blocked: int = 0
    size: int = 0
    first: float = 0.0
    last: float = 0.0


def summarise(entries):
    sites = {}
    for e in entries:
        s = sites.get(e.host)
        if s is None:
            s = sites[e.host] = SiteSummary(e.host, first=e.ts, last=e.ts)
        s.requests += 1
        s.size += e.size
        if e.outcome == "Blocked":
            s.blocked += 1
        s.first = min(s.first, e.ts)
        s.last = max(s.last, e.ts)
    return sorted(sites.values(), key=lambda s: s.requests, reverse=True)


def human_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
