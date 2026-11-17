# -----------------------------------------------------------------------------
# Blighter Restrictor - shared domain-list rules.
#
# Purpose: validate and normalise the domain lists that the parent app edits and
# the child-laptop helper writes into Squid "dstdomain" ACL files.  The same
# file is shipped in BOTH packages (parent app and child helper) so the parent's
# on-screen checks and the laptop's final checks always agree.
#
# Squid dstdomain syntax supported:
#   .example.com   -> example.com AND every subdomain (the usual "wildcard")
#   example.com    -> exactly example.com only
#   192.168.1.10   -> an IPv4 literal (only matches if the URL uses the IP)
#   # comment      -> comment lines and blank lines are kept as-is
# Convenience conversions (with a note to the user):
#   *.example.com  -> .example.com
#   https://www.example.com/path -> www.example.com
#   example.com:443 -> example.com
# Entries already covered by a wider ".domain" entry are removed, because Squid
# warns about (and may reject) overlapping entries in one ACL.
# Discord is NOT controlled by the lists but by its own per-child switch
# ("Allow Discord"): DISCORD_DOMAINS, is_discord() and discord_rules() below
# are used by the parent app (to warn about Discord lines in a list) and by
# both child helpers (to write the Squid rules).
#
# Copyright (C) 2026 Ways Property
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version.  It is distributed WITHOUT ANY WARRANTY; see the
# LICENSE file or <https://www.gnu.org/licenses/> for details.
# -----------------------------------------------------------------------------

import ipaddress
import re
from urllib.parse import urlsplit

MODE_BLOCKLIST = "allow-all-block-some"
MODE_ALLOWLIST = "block-all-allow-some"
MODES = (MODE_BLOCKLIST, MODE_ALLOWLIST)

_LABEL = r"(?!-)[a-z0-9_-]{1,63}(?<!-)"
_DOMAIN_RE = re.compile(rf"^\.?(?:{_LABEL}\.)*{_LABEL}$")


def normalise_entry(raw):
    """Return (value, note, error) for one non-comment line.

    value is the Squid-ready entry (or None on error), note is an optional
    message describing an automatic conversion, error is an optional message
    explaining why the line was rejected.
    """
    original = raw
    s = raw.strip().lower()
    note = None

    if "://" in s or "/" in s:
        try:
            host = urlsplit(s if "://" in s else "//" + s).hostname
        except ValueError:
            host = None
        if not host:
            return None, None, f"'{original.strip()}' is not a domain"
        note = f"'{original.strip()}' converted to '{host}'"
        s = host

    if s.startswith("*."):
        s = s[1:]
        note = f"'{original.strip()}' converted to '{s}' (Squid uses a leading dot as the wildcard)"
    if "*" in s:
        return None, None, (f"'{original.strip()}': Squid domain lists only support a leading "
                            f"'.' wildcard, e.g. '.example.com'")

    if re.search(r":\d+$", s):
        s = re.sub(r":\d+$", "", s)
        note = f"'{original.strip()}' port removed -> '{s}'"

    s = s.rstrip(".")
    if s in ("", "."):
        return None, None, f"'{original.strip()}' is empty"

    try:
        ipaddress.IPv4Address(s)
        return s, note, None
    except ValueError:
        pass

    if not _DOMAIN_RE.match(s):
        return None, None, f"'{original.strip()}' is not a valid domain name"
    return s, note, None


def _covers(wide, entry):
    """True if Squid entry `wide` (must start with '.') already matches `entry`."""
    if not wide.startswith(".") or wide == entry:
        return False
    bare = entry.lstrip(".")
    return bare == wide[1:] or bare.endswith(wide)


def clean_list(lines):
    """Validate a whole list.

    Returns (clean_lines, notes, errors):
      clean_lines - lines ready to write to a Squid ACL file (comments kept)
      notes       - human-readable messages about automatic changes
      errors      - human-readable messages; if non-empty the list must not be applied
    """
    notes, errors = [], []
    parsed = []  # (kind, text) kind in {"keep", "entry"}
    for n, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped == "" or stripped.startswith("#"):
            parsed.append(("keep", stripped))
            continue
        value, note, err = normalise_entry(stripped)
        if err:
            errors.append(f"Line {n}: {err}")
            continue
        if note:
            notes.append(f"Line {n}: {note}")
        parsed.append(("entry", value))

    entries = [t for k, t in parsed if k == "entry"]
    wides = [e for e in set(entries) if e.startswith(".")]
    seen = set()
    out = []
    for kind, text in parsed:
        if kind == "keep":
            out.append(text)
            continue
        if text in seen:
            notes.append(f"Duplicate '{text}' removed")
            continue
        cover = next((w for w in wides if _covers(w, text)), None)
        if cover:
            notes.append(f"'{text}' removed - already covered by '{cover}'")
            continue
        seen.add(text)
        out.append(text)

    # Trim leading/trailing blank lines for tidiness.
    while out and out[0] == "":
        out.pop(0)
    while out and out[-1] == "":
        out.pop()
    return out, notes, errors


def entries_only(lines):
    """Return just the domain entries (no comments/blanks)."""
    return [l for l in lines if l and not l.startswith("#")]


def suggest_parent_domain(host):
    """Best-effort guess at the 'site' domain for a host, e.g.
    www.bbc.co.uk -> bbc.co.uk, video.google.com -> google.com.
    Used only to offer a convenient right-click choice in the log viewer."""
    host = host.lower().strip(".")
    try:
        ipaddress.IPv4Address(host)
        return host
    except ValueError:
        pass
    parts = host.split(".")
    if len(parts) <= 2:
        return host
    # Two-letter country TLD with short second level (co.uk, com.au, ac.uk ...)
    if len(parts[-1]) == 2 and len(parts[-2]) <= 3:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


# ---- Discord switch -------------------------------------------------------------
# Discord's own domains (text chat, voice/video signalling, images, invites).
DISCORD_DOMAINS = (".discord.com", ".discord.gg", ".discordapp.com", ".discordapp.net",
                   ".discord.media", ".discord.co", ".dis.gd", ".discordstatus.com")


def is_discord(entry):
    """True if a list entry is one of Discord's domains (or inside one)."""
    e = entry.strip().lower().lstrip(".")
    return any(e == d[1:] or e.endswith(d) for d in DISCORD_DOMAINS)


def discord_rules(allowed):
    """Squid lines for the Discord switch.  They come BEFORE the mode rules,
    so the switch wins over both lists in both modes."""
    acl = "acl blighter_discord dstdomain " + " ".join(DISCORD_DOMAINS) + "\n"
    if allowed:
        return "# Discord: allowed (Discord switch)\n" + acl + "http_access allow localhost blighter_discord\n"
    return "# Discord: blocked (Discord switch)\n" + acl + "http_access deny blighter_discord\n"
