# -----------------------------------------------------------------------------
# Blighter Restrictor - the neutral "This site isn't available" page.
#
# Purpose: stop Squid announcing itself to the child.  Squid's own error
# pages name Squid, its version and the PC, which invites a curious
# child to start investigating.  This module:
#   * writes ONE plain page under the name of every Squid error page
#     (ERR_ACCESS_DENIED, ERR_DNS_FAIL, ...) into a Blighter folder, so a
#     blocked site, a mistyped address and a network fault all look the same
#     and give nothing away;
#   * returns the squid.conf lines that use that folder and remove Squid's
#     own reply headers (Server, X-Squid-Error, X-Cache, Via, ...).
#     ("via off" would do the same for Via but makes every "squid -k parse"
#     print a warning, which the parent app would then show.).
# The lines go into the generated rules.conf, so an existing PC picks
# them up the next time its rules are written - squid.conf itself does not
# have to be replaced.
# Squid 7 looks deny_info pages up by name only (not by path), so replacing
# the whole error folder is the supported way to change them.
# Secure (https) sites show the BROWSER's own error instead (e.g. "The proxy
# server is refusing connections"); nothing on the PC can change that.
# Shipped in both child packages (Ubuntu and Windows), like domains.py.
#
# Copyright (C) 2026 Ian Packer
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version.  It is distributed WITHOUT ANY WARRANTY; see the
# LICENSE file or <https://www.gnu.org/licenses/> for details.
# -----------------------------------------------------------------------------

import os

# No "%" anywhere: Squid treats %-codes in error pages as substitutions.
PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>This site isn't available</title>
<style>
body { font-family: Segoe UI, Ubuntu, Arial, sans-serif; color: #333; background: #fafafa;
       margin: 0; display: flex; align-items: center; justify-content: center; min-height: 100vh; }
main { max-width: 32em; padding: 2em; }
h1 { font-size: 1.6em; font-weight: 600; margin: 0 0 0.5em 0; }
p { line-height: 1.5; margin: 0; }
</style>
</head>
<body>
<main>
<h1>This site isn't available</h1>
<p>The page you asked for can't be shown.</p>
</main>
</body>
</html>
"""

# Squid 7's error page names.  Any extra names found in the installed
# Squid's own templates folder are added too (a newer Squid may have more).
NAMES = (
    "ERR_ACCESS_DENIED", "ERR_ACL_TIME_QUOTA_EXCEEDED", "ERR_AGENT_CONFIGURE",
    "ERR_AGENT_WPAD", "ERR_CACHE_ACCESS_DENIED", "ERR_CACHE_MGR_ACCESS_DENIED",
    "ERR_CANNOT_FORWARD", "ERR_CONFLICT_HOST", "ERR_CONNECT_FAIL",
    "ERR_DIR_LISTING", "ERR_DNS_FAIL", "ERR_ESI", "ERR_FORWARDING_DENIED",
    "ERR_FTP_DISABLED", "ERR_FTP_FAILURE", "ERR_FTP_FORBIDDEN", "ERR_FTP_NOT_FOUND",
    "ERR_FTP_PUT_CREATED", "ERR_FTP_PUT_ERROR", "ERR_FTP_PUT_MODIFIED",
    "ERR_FTP_UNAVAILABLE", "ERR_GATEWAY_FAILURE", "ERR_ICAP_FAILURE",
    "ERR_INVALID_REQ", "ERR_INVALID_RESP", "ERR_INVALID_URL", "ERR_LIFETIME_EXP",
    "ERR_NO_RELAY", "ERR_ONLY_IF_CACHED_MISS", "ERR_PRECONDITION_FAILED",
    "ERR_PROTOCOL_UNKNOWN", "ERR_READ_ERROR", "ERR_READ_TIMEOUT",
    "ERR_SECURE_CONNECT_FAIL", "ERR_SHUTTING_DOWN", "ERR_SOCKET_FAILURE",
    "ERR_TOO_BIG", "ERR_UNSUP_HTTPVERSION", "ERR_UNSUP_REQ", "ERR_URN_RESOLVE",
    "ERR_WRITE_ERROR", "ERR_ZERO_SIZE_OBJECT",
)


def write_pages(dest, stock_dirs=()):
    """Write the neutral page under every error-page name into dest.

    stock_dirs: the installed Squid's own template folders, read only to
    learn extra page names.  Files are rewritten only when they differ.
    Returns the number of pages in dest.
    """
    names = set(NAMES)
    for d in stock_dirs:
        try:
            names.update(n for n in os.listdir(d) if n.startswith("ERR_"))
        except OSError:
            pass
    os.makedirs(dest, exist_ok=True)
    try:
        os.chmod(dest, 0o755)
    except OSError:
        pass
    for n in sorted(names):
        p = os.path.join(dest, n)
        try:
            with open(p, encoding="utf-8") as f:
                if f.read() == PAGE:
                    continue
        except OSError:
            pass
        tmp = p + ".tmp"
        # newline="\n": the Windows Squid is a Cygwin program.
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(PAGE)
        os.replace(tmp, p)
        try:
            os.chmod(p, 0o644)
        except OSError:
            pass
    return len(names)


def squid_lines(squid_path):
    """squid.conf lines using the folder (squid_path as Squid sees it)."""
    return ("# Neutral error pages; do not reveal Squid to the child.\n"
            f"error_directory {squid_path}\n"
            "httpd_suppress_version_string on\n"
            "request_header_access Via deny all\n"
            "reply_header_access Via deny all\n"
            "reply_header_access Server deny all\n"
            "reply_header_access X-Squid-Error deny all\n"
            "reply_header_access X-Cache deny all\n"
            "reply_header_access X-Cache-Lookup deny all\n"
            "reply_header_access Cache-Status deny all\n")
