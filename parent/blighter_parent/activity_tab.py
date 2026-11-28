# -----------------------------------------------------------------------------
# Blighter Restrictor - "Activity" tab.
#
# Purpose: show a child's web activity (their PC's Squid access log) as a
# searchable table (newest first) plus a per-site summary.  Filters: time
# range, text search, blocked-only.
# The activity itself is collected in the background by collector.py, all
# the time the app is logged in to that child's PC - whichever tab is open,
# and also while filtering is paused.  This tab only shows it, and says when
# it was last updated, or that it is out of date if the PC cannot be
# reached (the app keeps retrying).  "First fetch: last N lines" (100 by
# default) only limits the history fetched when collection starts; "Load
# history" fetches more and adds it without duplicates.
# Right-click a row to add the site (or its parent domain) to the allow or
# block list in the Filters tab.
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
from datetime import datetime

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QGuiApplication
from PySide6.QtWidgets import (QCheckBox, QComboBox, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit, QMenu, QPushButton, QSpinBox,
                               QTableView, QTabWidget, QVBoxLayout, QWidget)

from . import accesslog
from .collector import DEFAULT_LINES, POLL_SECONDS
from .flowlayout import FlowLayout, hbox
from .shared import domains

RANGES = [("Last hour", 3600), ("Last 24 hours", 86400), ("Today", "today"),
          ("Last 7 days", 7 * 86400), ("Everything loaded", None)]
COLOURS = {"Blocked": QColor("#c0392b"), "Error": QColor("#7f8c8d")}


def _fmt_time(ts):
    return datetime.fromtimestamp(ts).strftime("%a %d %b %H:%M:%S")


class _Model(QAbstractTableModel):
    def __init__(self, headers, row_fn, sort_keys):
        super().__init__()
        self.headers, self.row_fn, self.sort_keys = headers, row_fn, sort_keys
        self.items = []

    def set_items(self, items):
        self.beginResetModel()
        self.items = items
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.items)

    def columnCount(self, parent=QModelIndex()):
        return len(self.headers)

    def headerData(self, section, orient, role=Qt.DisplayRole):
        if orient == Qt.Horizontal and role == Qt.DisplayRole:
            return self.headers[section]
        return None

    def data(self, index, role=Qt.DisplayRole):
        item = self.items[index.row()]
        if role == Qt.DisplayRole:
            return self.row_fn(item)[index.column()]
        if role == Qt.ForegroundRole:
            outcome = getattr(item, "outcome", "Blocked" if getattr(item, "blocked", 0) else "")
            if outcome in COLOURS:
                return QBrush(COLOURS[outcome])
        return None

    def sort(self, column, order=Qt.AscendingOrder):
        self.beginResetModel()
        self.items.sort(key=self.sort_keys[column], reverse=(order == Qt.DescendingOrder))
        self.endResetModel()


class ActivityTab(QWidget):
    status = Signal(str)
    add_domain = Signal(str, str)  # which ("allow"/"block"), domain

    def __init__(self, collector, parent=None):
        super().__init__(parent)
        self.collector = collector
        self.child = None
        self.entries = []

        self.lines = QSpinBox()
        self.lines.setRange(100, 100000)
        self.lines.setSingleStep(100)
        self.lines.setValue(DEFAULT_LINES)
        self.lines.setToolTip("How much history to fetch when collection starts, or with Load history.  "
                              "Everything after that is collected as it happens.")
        self.lines.valueChanged.connect(lambda v: setattr(self.collector, "initial_lines", v))
        self.rotated = QCheckBox("Include older logs")
        self.rotated.toggled.connect(lambda on: setattr(self.collector, "include_rotated", on))
        self.range = QComboBox()
        for label, _ in RANGES:
            self.range.addItem(label)
        self.range.setCurrentIndex(1)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter by site…")
        self.search.setClearButtonEnabled(True)
        self.blocked_only = QCheckBox("Blocked only")
        self.btn_refresh = QPushButton("Load history")
        self.btn_refresh.setToolTip("Fetch the last N lines again (more history) and add any not already shown")
        self.btn_refresh.clicked.connect(self.refresh)
        self.count_label = QLabel("")
        self.state_label = QLabel("")
        self.state_label.setWordWrap(True)

        # One row that wraps in a narrow window or at large text sizes.
        top_w = QWidget()
        top = FlowLayout(top_w)
        top.addWidget(hbox(QLabel("First fetch: last"), self.lines, QLabel("lines")))
        top.addWidget(self.rotated)
        top.addWidget(self.btn_refresh)
        top.addWidget(self.range)
        self.search.setMinimumWidth(160)
        top.addWidget(self.search, stretch=True)
        top.addWidget(self.blocked_only)

        self.req_model = _Model(
            ["Time", "Result", "Site", "Method", "Status", "Size"],
            lambda e: (_fmt_time(e.ts), e.outcome, e.host, e.method, str(e.status),
                       accesslog.human_size(e.size)),
            [lambda e: e.ts, lambda e: e.outcome, lambda e: e.host, lambda e: e.method,
             lambda e: e.status, lambda e: e.size])
        self.sum_model = _Model(
            ["Site", "Requests", "Blocked", "Data", "First seen", "Last seen"],
            lambda s: (s.host, str(s.requests), str(s.blocked), accesslog.human_size(s.size),
                       _fmt_time(s.first), _fmt_time(s.last)),
            [lambda s: s.host, lambda s: s.requests, lambda s: s.blocked, lambda s: s.size,
             lambda s: s.first, lambda s: s.last])

        self.views = QTabWidget()
        self.req_view = self._make_view(self.req_model, 2)
        self.sum_view = self._make_view(self.sum_model, 0)
        self.views.addTab(self.req_view, "Requests")
        self.views.addTab(self.sum_view, "Summary by site")

        lay = QVBoxLayout(self)
        lay.addWidget(top_w)
        lay.addWidget(self.state_label)
        lay.addWidget(self.views, 1)
        lay.addWidget(self.count_label)

        for w in (self.range.currentIndexChanged, self.search.textChanged,
                  self.blocked_only.toggled):
            w.connect(self._apply_filters)
        self.collector.updated.connect(self._collected)

    def _make_view(self, model, host_col):
        v = QTableView()
        v.setModel(model)
        v.setSortingEnabled(True)
        v.setSelectionBehavior(QTableView.SelectRows)
        v.setAlternatingRowColors(True)
        v.verticalHeader().hide()
        v.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        v.horizontalHeader().setSectionResizeMode(host_col, QHeaderView.Stretch)
        v.setContextMenuPolicy(Qt.CustomContextMenu)
        v.customContextMenuRequested.connect(lambda pos, view=v: self._menu(view, pos))
        return v

    # ---- data ---------------------------------------------------------------------
    def set_child(self, child):
        self.child = child
        self.entries = list(self.collector.activity(child.id).entries) if child else []
        self._apply_filters()
        self._show_state()
        if not child:
            self.count_label.setText("Select a child.")
        self.btn_refresh.setEnabled(child is not None)

    def _collected(self, child_id):
        if self.child and child_id == self.child.id:
            a = self.collector.activity(child_id)
            if len(a.entries) != len(self.entries) or (a.entries and self.entries and a.entries[0] is not self.entries[0]):
                self.entries = list(a.entries)
                self._apply_filters()
            self._show_state()
            self.btn_refresh.setEnabled(not a.busy)

    def _show_state(self):
        """One line saying how current the activity is."""
        if not self.child:
            self.state_label.setText("")
            return
        c = self.child
        a = self.collector.activity(c.id)
        red = "<span style='color:#c0392b'>{}</span>"
        notes = []
        if not self.collector.is_active(c.id):
            text = (f"Not logged in to {c.name}'s PC - activity is not being collected.  "
                    "Select the child again (or press Load history) to log in.")
        elif a.last_error:
            when = (f"last updated {datetime.fromtimestamp(a.last_ok).strftime('%H:%M:%S')}"
                    if a.last_ok else "nothing collected yet")
            text = red.format(f"Activity is out of date ({when}): {a.last_error}  Retrying automatically.")
        elif a.last_ok:
            text = (f"Collecting automatically while logged in (every {POLL_SECONDS} s) - "
                    f"last updated {datetime.fromtimestamp(a.last_ok).strftime('%H:%M:%S')}.")
        else:
            text = f"Collecting {c.name}'s activity…"
        if a.bypassed:
            notes.append(red.format(f"Blighter is switched off on {c.name}'s PC itself ('Pause Blighter Child'), "
                                    "so no activity is being recorded.  Press Resume filtering on the PC tab."))
        if a.legacy:
            notes.append(f"{c.name}'s PC has an older Blighter child (before 1.2.6): the app has to fetch "
                         "the latest lines again each time.  Update the PC to 1.2.6.")
        if a.gap:
            notes.append("Some activity may be missing: the PC's log was started afresh (rotated) before "
                         "everything was collected.")
        self.state_label.setText("<br>".join([text] + notes))

    def refresh(self):
        """Load history: fetch the last N lines and add any not already shown."""
        if not self.child:
            return
        if self.collector.load_history(self.child, self.lines.value(), self.rotated.isChecked()):
            self.btn_refresh.setEnabled(False)
            self.status.emit(f"Fetching {self.child.name}'s activity history…")

    def _apply_filters(self):
        _, rng = RANGES[self.range.currentIndex()]
        now = time.time()
        if rng == "today":
            since = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        elif rng:
            since = now - rng
        else:
            since = 0
        text = self.search.text().strip().lower()
        blocked = self.blocked_only.isChecked()
        rows = [e for e in self.entries
                if e.ts >= since and (not text or text in e.host)
                and (not blocked or e.outcome == "Blocked")]
        self.req_model.set_items(rows)
        self.sum_model.set_items(accesslog.summarise(rows))
        n_blocked = sum(1 for e in rows if e.outcome == "Blocked")
        if self.child:
            self.count_label.setText(
                f"{len(rows)} requests shown ({n_blocked} blocked) across "
                f"{len(self.sum_model.items)} sites; {len(self.entries)} loaded.  "
                "HTTPS shows the site name only, not individual pages.")
        elif not self.child:
            self.count_label.setText("Select a child.")

    # ---- right-click ----------------------------------------------------------------
    def _menu(self, view, pos):
        idx = view.indexAt(pos)
        if not idx.isValid():
            return
        item = view.model().items[idx.row()]
        host = item.host
        site = domains.suggest_parent_domain(host)
        menu = QMenu(self)
        options = [f".{host}"] + ([f".{site}"] if site != host else [])
        for which in ("block", "allow"):
            for d in options:
                act = menu.addAction(f"{which.capitalize()} {d}")
                act.triggered.connect(lambda _=False, w=which, dom=d: self.add_domain.emit(w, dom))
            menu.addSeparator()
        menu.addAction("Copy site name").triggered.connect(
            lambda: QGuiApplication.clipboard().setText(host))
        menu.exec(view.viewport().mapToGlobal(pos))
