# -----------------------------------------------------------------------------
# Blighter Restrictor - finding a child's PC again after its address changes.
#
# Purpose: home routers hand out addresses by DHCP, so a child's PC may come
# back with a different IPv4 address (and phones / PCs may also use random
# MAC addresses).  Blighter does not depend on either: each child's PC is
# recognised by its SSH identity (host key), remembered when it was added.
# When the PC is not at its last known address, find_pc() looks for it:
#   1. which addresses to try: the /24 network of the PC's last known
#      address and the /24 network(s) of this (the parent's) PC - private
#      (RFC 1918) addresses only, at most 1024 of them
#   2. which of those answer on the SSH port (short TCP connections, many at
#      once - a few seconds for a typical home network)
#   3. for each that answers, the SSH server's host key is read (the SSH
#      greeting only - no login, so the password is never sent to another
#      machine) and compared with the remembered one
# The address of the matching PC is returned; None if it was not found.
# Nothing is scanned outside the home network, and only the SSH port.
#
# Copyright (C) 2026 Ian Packer
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version.  It is distributed WITHOUT ANY WARRANTY; see the
# LICENSE file or <https://www.gnu.org/licenses/> for details.
# -----------------------------------------------------------------------------

import ipaddress
import socket
from concurrent.futures import ThreadPoolExecutor

import paramiko

MAX_HOSTS = 1024
CONNECT_TIMEOUT = 0.7
KEY_TIMEOUT = 6


# ---- host keys ------------------------------------------------------------------
def key_to_text(key):
    """'<type> <base64>' for a Paramiko key."""
    return f"{key.get_name()} {key.get_base64()}"


def key_from_text(text):
    """Paramiko key from '<type> <base64>' (None if empty or unreadable)."""
    if not text:
        return None
    try:
        entry = paramiko.hostkeys.HostKeyEntry.from_line("pc " + text.strip())
        return entry.key if entry else None
    except Exception:
        return None


def same_key(a, b):
    return bool(a and b and a.get_name() == b.get_name() and a.asbytes() == b.asbytes())


def read_host_key(ip, port=22, prefer=None, timeout=KEY_TIMEOUT):
    """The SSH server's host key at ip:port, from the greeting only (no login)."""
    sock = socket.create_connection((ip, port), timeout=timeout)
    t = paramiko.Transport(sock)
    try:
        t.banner_timeout = timeout
        if prefer:
            opts = t.get_security_options()
            types = list(opts.key_types)
            if prefer in types:
                opts.key_types = [prefer] + [k for k in types if k != prefer]
        t.start_client(timeout=timeout)
        return t.get_remote_server_key()
    finally:
        t.close()


# ---- which addresses to try ----------------------------------------------------
def _private(ip):
    try:
        a = ipaddress.IPv4Address(ip)
    except ValueError:
        return False
    return a.is_private and not (a.is_loopback or a.is_link_local or a.is_unspecified)


def local_addresses():
    """This PC's own private IPv4 addresses (no packets are sent)."""
    found = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("192.0.2.1", 9))      # picks the address used for the default route
            found.append(s.getsockname()[0])
        finally:
            s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            found.append(info[4][0])
    except OSError:
        pass
    out = []
    for ip in found:
        if _private(ip) and ip not in out:
            out.append(ip)
    return out


def candidate_hosts(last_ip):
    """Addresses to try, nearest first: the last known one, then its /24,
    then this PC's own /24 network(s).  Private addresses only."""
    nets = []
    for ip in [last_ip] + local_addresses():
        if _private(ip):
            net = ipaddress.IPv4Network(f"{ip}/24", strict=False)
            if net not in nets:
                nets.append(net)
    own = set(local_addresses())
    hosts = [last_ip] if _private(last_ip) else []
    for net in nets:
        for h in net.hosts():
            h = str(h)
            if h not in hosts and h not in own:
                hosts.append(h)
            if len(hosts) >= MAX_HOSTS:
                return hosts
    return hosts


# ---- the search ------------------------------------------------------------------
def _port_open(ip, port):
    try:
        with socket.create_connection((ip, port), timeout=CONNECT_TIMEOUT):
            return ip
    except OSError:
        return None


def find_pc(host_key_text, last_ip, port=22):
    """The address where the PC with this SSH identity answers now, or None."""
    want = key_from_text(host_key_text)
    if not want:
        return None
    hosts = candidate_hosts(last_ip)
    with ThreadPoolExecutor(max_workers=64) as pool:
        open_hosts = [ip for ip in pool.map(lambda h: _port_open(h, port), hosts) if ip]

    def check(ip):
        try:
            return ip if same_key(read_host_key(ip, port, want.get_name()), want) else None
        except Exception:
            return None

    if not open_hosts:
        return None
    with ThreadPoolExecutor(max_workers=8) as pool:
        for ip in pool.map(check, open_hosts):
            if ip:
                return ip
    return None
