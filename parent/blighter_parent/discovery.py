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
#
# find_pcs() (since 1.4.0, the "Find PCs" button when adding a child) lists
# the Blighter child PCs on this PC's own network(s): the same addresses as
# above (this PC's /24 network(s) only), the same SSH-port check, then for
# each the host key and the one-line banner that a Blighter child's SSH
# server shows before login for the "blighter" account, e.g.
# "Blighter child 1.4.0 · Jacks-Laptop · Ubuntu 24.04" (written by the
# child's setup).  It asks for the banner with the SSH "none" login, which
# carries no password, so the password is never sent.  Only computers with
# that banner are listed - routers, NAS drives and other PCs are left out.
# The name shown is the one the PC gives itself, never the router's.
#
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
BANNER_PREFIX = "Blighter child"
ADMIN = "blighter"
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
            # An RSA key is offered as rsa-sha2-512/256 by current OpenSSH
            # (plain ssh-rsa is refused), so ask for those first.
            want = ["rsa-sha2-512", "rsa-sha2-256", "ssh-rsa"] if prefer == "ssh-rsa" else [prefer]
            opts = t.get_security_options()
            types = list(opts.key_types)
            first = [k for k in want if k in types]
            if first:
                opts.key_types = first + [k for k in types if k not in first]
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


def own_network_hosts():
    """This PC's own /24 network(s), without its own addresses.  Private only."""
    own = local_addresses()
    hosts = []
    for ip in own:
        for h in ipaddress.IPv4Network(f"{ip}/24", strict=False).hosts():
            h = str(h)
            if h not in hosts and h not in own:
                hosts.append(h)
            if len(hosts) >= MAX_HOSTS:
                return hosts
    return hosts


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


# ---- "Find PCs": Blighter child PCs on this PC's own network(s) -------------------
def parse_banner(text):
    """{'version', 'name', 'os'} from a Blighter child's banner; None for any other."""
    line = (text or "").strip().splitlines()[0].strip() if (text or "").strip() else ""
    if not line.startswith(BANNER_PREFIX + " "):
        return None
    parts = [p.strip() for p in line[len(BANNER_PREFIX):].split("\u00b7")]
    if len(parts) < 3 or not parts[0]:
        return None
    return {"version": parts[0][:20], "name": parts[1][:64], "os": " \u00b7 ".join(parts[2:])[:64]}


def read_banner(ip, port=22, timeout=KEY_TIMEOUT):
    """(host key, banner text) at ip:port.  The banner is asked for with the
    SSH "none" login for the admin account - no password is ever sent."""
    sock = socket.create_connection((ip, port), timeout=timeout)
    t = paramiko.Transport(sock)
    try:
        t.banner_timeout = timeout
        t.start_client(timeout=timeout)
        key = t.get_remote_server_key()
        try:
            t.auth_none(ADMIN)
        except (paramiko.BadAuthenticationType, paramiko.AuthenticationException, paramiko.SSHException):
            pass
        banner = t.get_banner()
        if isinstance(banner, bytes):
            banner = banner.decode("utf-8", "replace")
        return key, banner or ""
    finally:
        t.close()


def _known(ip, port, key, known_keys):
    """True if this PC is one already in the list (same SSH identity).  A
    saved identity of another key type is read again in that type."""
    for k in known_keys:
        if same_key(key, k):
            return True
    for name in {k.get_name() for k in known_keys} - {key.get_name()}:
        try:
            other = read_host_key(ip, port, prefer=name)
        except Exception:
            continue
        if any(same_key(other, k) for k in known_keys):
            return True
    return False


def find_pcs(known_key_texts=(), port=22, hosts=None):
    """Blighter child PCs on this PC's own network(s), sorted by name:
    [{ip, name, os, version, host_key_text, known}] (known = already in the
    list, by SSH identity).  hosts: the addresses to try (tests only)."""
    known_keys = [k for k in (key_from_text(t) for t in known_key_texts) if k]
    if hosts is None:
        hosts = own_network_hosts()
    with ThreadPoolExecutor(max_workers=64) as pool:
        open_hosts = [ip for ip in pool.map(lambda h: _port_open(h, port), hosts) if ip]

    def check(ip):
        try:
            key, banner = read_banner(ip, port)
        except Exception:
            return None
        info = parse_banner(banner)
        if not info:
            return None
        info.update(ip=ip, host_key_text=key_to_text(key), known=_known(ip, port, key, known_keys))
        return info

    if not open_hosts:
        return []
    with ThreadPoolExecutor(max_workers=8) as pool:
        found = [r for r in pool.map(check, open_hosts) if r]
    return sorted(found, key=lambda r: (r["name"].lower(), ipaddress.IPv4Address(r["ip"])))
