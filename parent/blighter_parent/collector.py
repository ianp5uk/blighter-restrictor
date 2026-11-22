# -----------------------------------------------------------------------------
# Blighter Restrictor - collecting each child's web activity in the background.
#
# Purpose: while the app is logged in to a child's PC, keep fetching that
# PC's Squid activity log - whichever child is selected and whichever tab is
# open, and whether filtering is on or paused.  Collection for a child starts
# when the app logs in to their PC (selecting the child does that) and stops
# only when the parent logs out of it (Log out button / menu), removes the
# child, or closes the app.  A timer never logs back in by itself after a
# log-out.
# Every POLL_SECONDS the PC is asked only for the lines written since the
# last fetch ("lognext", see common/logtail.py); a busy PC's backlog is
# fetched in batches until it is all in.  The first fetch takes the last
# `initial_lines` lines (100 by default, set on the Activity tab); "Load
# history" fetches more and merges them in without duplicates.
# Entries already collected are kept for the session (up to MAX_ENTRIES per
# child), so the line count only limits the first history request.
# If the PC cannot be reached the data is kept, shown as out of date, and
# fetching is retried (less often after repeated failures).  Older PCs
# (Blighter child before 1.2.6) have no "lognext": for them the last
# `initial_lines` lines are fetched each time and duplicates dropped.
#
# Copyright (C) 2026 Ian Packer
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version.  It is distributed WITHOUT ANY WARRANTY; see the
# LICENSE file or <https://www.gnu.org/licenses/> for details.
# -----------------------------------------------------------------------------

import time

from PySide6.QtCore import QObject, QTimer, Signal

from . import accesslog
from .remote import TooOld
from .workers import run_bg

POLL_SECONDS = 10
MAX_ENTRIES = 200000
MAX_BATCHES = 40              # per fetch, about 20 MB at most
DEFAULT_LINES = 100


def _key(e):
    return (e.ts, e.result, e.size, e.method, e.url)


class ChildActivity:
    """What has been collected from one child's PC this session."""

    def __init__(self):
        self.entries = []             # newest first
        self.ino = None               # log position (None = not started yet)
        self.offset = 0
        self.legacy = False           # PC older than 1.2.6
        self.last_ok = None           # time.time() of the last good fetch
        self.last_error = ""
        self.failures = 0
        self.gap = False              # some lines may have been missed (log rotated away)
        self.bypassed = False         # Blighter switched off on the PC itself
        self.busy = False
        self.next_due = 0.0

    def merge(self, new_entries):
        if not new_entries:
            return 0
        if self.entries:
            seen = {_key(e) for e in self.entries}
            new_entries = [e for e in new_entries if _key(e) not in seen]
        if not new_entries:
            return 0
        self.entries = sorted(self.entries + new_entries, key=lambda e: e.ts, reverse=True)[:MAX_ENTRIES]
        return len(new_entries)


class Collector(QObject):
    updated = Signal(str)          # child id: new data or a change of state

    def __init__(self, remotes, store, parent=None):
        super().__init__(parent)
        self.remotes = remotes
        self.store = store
        self.data = {}               # child id -> ChildActivity
        self.active = set()          # child ids being collected
        self.initial_lines = DEFAULT_LINES
        self.include_rotated = False
        self.timer = QTimer(self, interval=1000)
        self.timer.timeout.connect(self._tick)
        self.timer.start()

    # ---- sessions -------------------------------------------------------------
    def activity(self, child_id):
        return self.data.setdefault(child_id, ChildActivity())

    def start(self, child):
        """Logged in to this child's PC: collect until stop()."""
        if child is None:
            return
        a = self.activity(child.id)
        if child.id not in self.active:
            self.active.add(child.id)
            a.next_due = 0.0
            self.updated.emit(child.id)

    def stop(self, child_id):
        self.active.discard(child_id)
        self.updated.emit(child_id)

    def stop_all(self):
        ids = list(self.active)
        self.active.clear()
        for cid in ids:
            self.updated.emit(cid)

    def forget(self, child_id):
        self.stop(child_id)
        self.data.pop(child_id, None)

    def is_active(self, child_id):
        return child_id in self.active

    # ---- fetching -------------------------------------------------------------
    def _child(self, cid):
        return next((c for c in self.store.children if c.id == cid), None)

    def _tick(self):
        now = time.monotonic()
        for cid in list(self.active):
            a = self.activity(cid)
            child = self._child(cid)
            if child is None:
                self.active.discard(cid)
                continue
            if not a.busy and now >= a.next_due:
                self._fetch(child, a)

    def _fetch(self, child, a, history=None):
        """history=(lines, rotated): explicit 'Load history' (merged in)."""
        a.busy = True
        cid = child.id
        start_lines = history[0] if history else self.initial_lines
        rotated = history[1] if history else self.include_rotated
        restart = history is not None or a.ino is None or a.legacy

        def job():
            r = self.remotes.get(child)
            lines, gap, bypassed = [], False, None
            pos = (a.ino, a.offset)
            legacy = a.legacy

            def catch_up(pos):
                got, g, byp = [], False, None
                for _ in range(MAX_BATCHES):
                    res = r.log_next(pos[0], pos[1])
                    got += res.get("lines", [])
                    pos = (res.get("ino", ""), int(res.get("offset", 0)))
                    g = g or bool(res.get("gap"))
                    byp = res.get("bypassed")
                    if not res.get("more"):
                        break
                return got, pos, g, byp

            if history is not None and a.ino is not None and not legacy:
                # Nothing written since the last fetch may be skipped.
                got, pos, gap, bypassed = catch_up(pos)
                lines += got
            if restart and not legacy:
                try:
                    res = r.log_start(start_lines, rotated)
                    lines += res.get("lines", [])
                    pos = (res.get("ino", ""), int(res.get("offset", 0)))
                    bypassed = res.get("bypassed")
                except TooOld:
                    legacy = True
            if legacy:
                text = r.log(start_lines, rotated)
                return {"lines": text.splitlines(), "pos": (None, 0), "legacy": True,
                        "gap": False, "bypassed": None, "history": history is not None}
            if not restart:
                got, pos, gap, bypassed = catch_up(pos)
                lines += got
            return {"lines": lines, "pos": pos, "legacy": False, "gap": gap,
                    "bypassed": bypassed, "history": history is not None}

        def ok(res):
            a.busy = False
            a.legacy = res["legacy"]
            a.ino, a.offset = res["pos"]
            entries = [e for e in (accesslog.parse_line(l) for l in res["lines"]) if e]
            a.merge(entries)
            a.gap = a.gap or res["gap"]
            if res["bypassed"] is not None:
                a.bypassed = bool(res["bypassed"])
            a.last_ok, a.last_error, a.failures = time.time(), "", 0
            a.next_due = time.monotonic() + POLL_SECONDS
            self.updated.emit(cid)

        def err(msg):
            a.busy = False
            a.failures += 1
            a.last_error = msg
            wait = POLL_SECONDS if a.failures < 3 else (30 if a.failures < 10 else 60)
            a.next_due = time.monotonic() + wait
            self.updated.emit(cid)

        run_bg(job, ok, err, quiet=history is None)

    def load_history(self, child, lines, rotated):
        """Explicit request for more history (not quiet: shows 'Working...')."""
        a = self.activity(child.id)
        if a.busy:
            return False
        self.start(child)
        self._fetch(child, a, history=(lines, rotated))
        return True
