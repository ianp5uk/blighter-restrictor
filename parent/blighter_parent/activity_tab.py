# -----------------------------------------------------------------------------
# Blighter Restrictor - "Activity" tab.
#
# Purpose: download a child's Squid access log over SSH and show it as a
# searchable table (newest first) plus a per-site summary.  Filters: time
# range, text search, blocked-only.  "Live" refreshes every 5 seconds.
# Right-click a row to add the site (or its parent domain) to the allow or
# block list in the Rules tab.
#
# Copyright (C) 2026 Ways Property
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version.  It is distributed WITHOUT ANY WARRANTY; see the
# LICENSE file or <https://www.gnu.org/licenses/> for details.
# -----------------------------------------------------------------------------

import time
from datetime import datetime

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QGuiApplication
from PySide6.QtWidgets import (QCheckBox, QComboBox, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit, QMenu, QPushButton, QSpinBox,
                               QTableView, QTabWidget, QVBoxLayout, QWidget)

from . import accesslog
from .shared import domains
from .workers import run_bg

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

    def __init__(self, remotes, parent=None):
        super().__init__(parent)
        self.remotes = remotes
        self.child = None
        self.entries = []
        self.busy = False

        self.lines = QSpinBox()
        self.lines.setRange(100, 100000)
        self.lines.setSingleStep(1000)
        self.lines.setValue(5000)
        self.rotated = QCheckBox("Include older logs")
        self.range = QComboBox()
        for label, _ in RANGES:
            self.range.addItem(label)
        self.range.setCurrentIndex(1)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter by site…")
        self.search.setClearButtonEnabled(True)
        self.blocked_only = QCheckBox("Blocked only")
        self.live = QCheckBox("Live (every 5 s)")
        self.btn_refresh = QPushButton("Refresh")
        self.btn_refresh.clicked.connect(self.refresh)
        self.count_label = QLabel("")

        top = QHBoxLayout()
        top.addWidget(QLabel("Last"))
        top.addWidget(self.lines)
        top.addWidget(QLabel("lines"))
        top.addWidget(self.rotated)
        top.addSpacing(12)
        top.addWidget(self.range)
        top.addWidget(self.search, 1)
        top.addWidget(self.blocked_only)
        top.addWidget(self.live)
        top.addWidget(self.btn_refresh)

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
        lay.addLayout(top)
        lay.addWidget(self.views, 1)
        lay.addWidget(self.count_label)

        for w in (self.range.currentIndexChanged, self.search.textChanged,
                  self.blocked_only.toggled):
            w.connect(self._apply_filters)
        self.timer = QTimer(self, interval=5000)
        self.timer.timeout.connect(self.refresh)
        self.live.toggled.connect(lambda on: self.timer.start() if on else self.timer.stop())

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
        self.entries = []
        self._apply_filters()
        self.count_label.setText("" if child else "Select a child.")
        self.btn_refresh.setEnabled(child is not None)

    def refresh(self):
        if not self.child or self.busy:
            return
        child, n, rot = self.child, self.lines.value(), self.rotated.isChecked()
        self.busy = True
        if not self.live.isChecked():
            self.status.emit(f"Downloading {child.name}'s activity log…")

        def job():
            return accesslog.parse(self.remotes.get(child).log(n, rot))

        def ok(entries):
            self.busy = False
            if child is self.child:
                self.entries = entries
                self._apply_filters()
                if not self.live.isChecked():
                    self.status.emit(f"Loaded {len(entries)} log entries from {child.name}'s laptop.")

        def err(msg):
            self.busy = False
            self.live.setChecked(False)
            self.status.emit(msg)

        run_bg(job, ok, err)

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
