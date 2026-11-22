# -----------------------------------------------------------------------------
# Blighter Restrictor - main window.
#
# Purpose: the application shell.  Left: the list of children with an
# online/offline indicator (checked every 20 s) and Add / Edit / Remove /
# Test / Reconnect / Log out buttons.  Right: three tabs for the selected
# child -
#   Rules    - mode, allow/block lists, Allow Discord, home network, Apply
#   Activity - the Squid access log, filters, per-site summary
#   PC       - what is actually in force on the child's PC, health, Reload
#              Squid, Pause / Resume filtering
# A status bar shows progress and errors, and "Working…" with a moving bar
# while the app waits for a PC.  A paused child is shown "- PAUSED" in red.
# Children with an open SSH session are shown in bold.
# Addresses: a child's PC is recognised by its SSH identity, so when DHCP
# gives it a new address the app finds it again on the home network and
# updates the list by itself (also for PCs found offline by the 20 s check,
# at most one search a minute each).  Reconnect is there for when it cannot
# (PC reinstalled, different network).
# Activity is collected in the background (collector.py) for every child
# the app is logged in to, until the parent logs out of that child.
# A PC listed twice (from before 1.2.4) is reported at start-up so the
# extra entry can be removed.
# Log out: "Log out" button (selected child), File > Log out of all PCs,
# and always when the app closes.  (No automatic log-out after idle minutes:
# that would stop activity being collected.)
# First run (no children yet): a short "Getting started" message - install
# this app first, then the child component on the child's PC, then Add.
# Help > Getting started shows it again.
# Help > About shows the version, licence and donation links (Ko-fi, GitHub
# Sponsors).
# Text size: View > Larger / Smaller / Normal text (Ctrl +, Ctrl -, Ctrl 0),
# remembered between runs - for high-resolution screens.
# Look and feel (colours, buttons, cursor, Linux font/check boxes): style.py.
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
import sys

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QFont, QFontDatabase, QIcon, QKeySequence, QPainter, QPixmap
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QMainWindow, QMessageBox,
                               QPlainTextEdit, QProgressBar, QPushButton, QSplitter,
                               QTableView, QTabWidget, QVBoxLayout, QWidget)

from . import APP_NAME, COPYRIGHT, LICENSE_NAME, __version__, style
from . import discovery
from .activity_tab import ActivityTab
from .collector import Collector
from .config_store import Store
from .dialogs import ChildDialog, ReconnectDialog, ask_password
from .pc_tab import PCTab
from .remote import RemoteManager, is_reachable, search_allowed
from .rules_tab import RulesTab
from .workers import busy_signal, run_bg

ICON_PATH = os.path.join(os.path.dirname(__file__), "icon.svg")
GETTING_STARTED = (
    "<b>Getting started</b><br><br>"
    "1.  Install this app (Blighter Restrictor) on <b>your own</b> PC - done.<br>"
    "2.  On the child's PC, signed in as a parent (administrator), install the Blighter "
    "child component: <b>BlighterChild-Setup</b> on Windows, or the <b>blighter-child</b> "
    "package and <b>sudo blighter-setup &lt;child's username&gt;</b> on Ubuntu.<br>"
    "3.  At the end it shows an address, the child's username and the admin login.  Back here, "
    "press <b>Add</b> and enter them.<br><br>"
    "That is all: you do not need to change any router settings.  If the child's PC gets a "
    "different address later, this app finds it again by itself.  Keep both PCs on the same "
    "home network.")
SCALES = [80, 90, 100, 110, 125, 150, 175, 200, 250, 300]


def _dot(colour):
    pm = QPixmap(14, 14)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(colour))
    p.setPen(Qt.NoPen)
    p.drawEllipse(1, 1, 12, 12)
    p.end()
    return QIcon(pm)


class MainWindow(QMainWindow):
    child_moved = Signal(str)          # child id; emitted from the connecting thread

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.setWindowIcon(QIcon(ICON_PATH))
        self.resize(1150, 720)
        self.store = Store()
        self.remotes = RemoteManager(self.store)
        self.remotes.changed.append(lambda c: self.child_moved.emit(c.id))
        self.child_moved.connect(self._child_moved)
        self.collector = Collector(self.remotes, self.store, self)
        self.online = {}
        self.paused = {}      # child id -> True/False, as last reported by the PC
        self.icons = {True: _dot("#27ae60"), False: _dot("#95a5a6"), None: _dot("#f1c40f")}
        self.current = None

        # ---- children panel
        self.list = QListWidget()
        self.list.setIconSize(QSize(14, 14))
        self.list.currentItemChanged.connect(self._selected)
        self.list.itemDoubleClicked.connect(lambda *_: self.edit_child())
        b_add, b_edit, b_del, b_test = (QPushButton(t) for t in ("Add", "Edit", "Remove", "Test"))
        b_reconnect = QPushButton("Reconnect")
        b_reconnect.setToolTip("Find the selected child's PC again, or connect it at a new address "
                               "(for example after reinstalling Blighter on it)")
        b_reconnect.clicked.connect(self.reconnect_child)
        self.b_logout = QPushButton("Log out")
        self.b_logout.setToolTip("Close the SSH session to the selected child's PC (activity collection stops)")
        self.b_logout.clicked.connect(self.logout_child)
        b_add.clicked.connect(self.add_child)
        b_edit.clicked.connect(self.edit_child)
        b_del.clicked.connect(self.remove_child)
        b_test.clicked.connect(self.test_child)
        grid1, grid2, grid3 = QHBoxLayout(), QHBoxLayout(), QHBoxLayout()
        grid1.addWidget(b_add)
        grid1.addWidget(b_edit)
        grid2.addWidget(b_del)
        grid2.addWidget(b_test)
        grid3.addWidget(b_reconnect)
        grid3.addWidget(self.b_logout)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.addWidget(QLabel("<b>Children</b>"))
        ll.addWidget(self.list, 1)
        ll.addLayout(grid1)
        ll.addLayout(grid2)
        ll.addLayout(grid3)

        # ---- tabs
        self.rules = RulesTab(self.remotes)
        self.activity = ActivityTab(self.collector)
        self.pc_tab = PCTab(self.remotes)
        self.tabs = QTabWidget()
        self.tabs.addTab(self.rules, "Rules")
        self.tabs.addTab(self.activity, "Activity")
        self.tabs.addTab(self.pc_tab, "PC")
        self.tabs.currentChanged.connect(self._tab_changed)
        for t in (self.rules, self.activity, self.pc_tab):
            t.status.connect(self.say)
        self.activity.add_domain.connect(self._add_domain)
        self.pc_tab.paused_known.connect(self._paused_known)

        split = QSplitter()
        split.addWidget(left)
        split.addWidget(self.tabs)
        split.setStretchFactor(1, 1)
        split.setSizes([240, 900])
        self.setCentralWidget(split)

        # ---- menu
        m = self.menuBar().addMenu("&File")
        quit_act = QAction("&Quit", self, shortcut="Ctrl+Q")
        quit_act.triggered.connect(self.close)
        logout_all = QAction("&Log out of all PCs", self, shortcut="Ctrl+L")
        logout_all.triggered.connect(self.logout_all)
        m.addAction(logout_all)
        m.addSeparator()
        m.addAction(quit_act)
        v = self.menuBar().addMenu("&View")
        for text, keys, step in (("&Larger text", [QKeySequence.ZoomIn, "Ctrl+="], 1),
                                 ("&Smaller text", [QKeySequence.ZoomOut], -1),
                                 ("&Normal text size", ["Ctrl+0"], 0)):
            a = QAction(text, self)
            a.setShortcuts([QKeySequence(k) for k in keys])
            a.triggered.connect(lambda _=False, st=step: self.change_scale(st))
            v.addAction(a)
        h = self.menuBar().addMenu("&Help")
        start = QAction("&Getting started", self)
        start.triggered.connect(lambda: QMessageBox.information(self, "Getting started", GETTING_STARTED))
        h.addAction(start)
        about = QAction("&About", self)
        about.triggered.connect(self._about)
        h.addAction(about)

        app = QApplication.instance()
        self.base_point_size = app.font().pointSizeF()
        self.scale = self.store.get_setting("text_scale", 100)
        if self.scale not in SCALES:
            self.scale = 100
        self.apply_scale()

        # ---- "Working…" indicator: shown while the app waits for a PC, so a
        # parent can see it hasn't hung (Windows PCs take a few seconds).
        self.busy_label = QLabel("<b>Working…</b>")
        self.busy_bar = QProgressBar()
        self.busy_bar.setRange(0, 0)          # moving "busy" animation
        self.busy_bar.setMaximumWidth(140)
        self.busy_bar.setMaximumHeight(14)
        self.busy_bar.setTextVisible(False)
        for w in (self.busy_label, self.busy_bar):
            self.statusBar().addPermanentWidget(w)
            w.hide()
        busy_signal().connect(self._busy)

        self._populate()
        self.poll = QTimer(self, interval=20000)
        self.poll.timeout.connect(self._check_online)
        self.poll.start()
        self._check_online()
        if self.store.keyring_error:
            self.say(f"Keyring not available ({self.store.keyring_error}) - passwords kept for this session only.")
        elif not self.store.children:
            self.say("Add a child to get started.")
        QTimer.singleShot(0, self._warn_duplicates)
        if not self.store.children and not self.store.get_setting("welcome_shown"):
            QTimer.singleShot(0, self._welcome)

    # ---- helpers ------------------------------------------------------------------
    def say(self, msg):
        self.statusBar().showMessage(msg, 0)
        if hasattr(self, "b_logout"):
            self._refresh_labels()

    def _populate(self, select_id=None):
        self.list.blockSignals(True)
        self.list.clear()
        for c in self.store.children:
            it = QListWidgetItem(self.icons[self.online.get(c.id)], self._label(c))
            it.setData(Qt.UserRole, c.id)
            self.list.addItem(it)
        self.list.blockSignals(False)
        target = select_id or (self.current.id if self.current else None)
        for i in range(self.list.count()):
            if self.list.item(i).data(Qt.UserRole) == target:
                self.list.setCurrentRow(i)
                return
        if self.list.count() and not self.current:
            self.list.setCurrentRow(0)
        elif not self.list.count():
            self._set_child(None)

    def _label(self, c):
        return c.label() + ("   - PAUSED" if self.paused.get(c.id) else "")

    def _busy(self, n):
        for w in (self.busy_label, self.busy_bar):
            w.setVisible(n > 0)

    def _paused_known(self, child_id, paused):
        if self.paused.get(child_id) != paused:
            self.paused[child_id] = paused
            for i in range(self.list.count()):
                it = self.list.item(i)
                c = self._child_by_id(it.data(Qt.UserRole))
                if c and c.id == child_id:
                    it.setText(self._label(c))
                    it.setForeground(QColor("#c0392b") if paused else self.list.palette().text().color())

    def _refresh_labels(self):
        """Logged-in children are shown in bold (tooltip says so)."""
        for i in range(self.list.count()):
            it = self.list.item(i)
            c = self._child_by_id(it.data(Qt.UserRole))
            if c:
                on = self.remotes.is_connected(c)
                f = it.font()
                f.setBold(on)
                it.setFont(f)
                reach = "Online" if self.online.get(c.id) else "Not reachable"
                it.setToolTip(reach + (" - logged in (SSH session open)" if on else " - not logged in"))
        self.b_logout.setEnabled(bool(self.current and self.remotes.is_connected(self.current)))

    def _welcome(self):
        if "--self-test" in sys.argv:
            return
        self.store.set_setting("welcome_shown", True)
        QMessageBox.information(self, "Welcome to Blighter Restrictor", GETTING_STARTED)

    def _child_moved(self, child_id):
        """A child's PC was found at a new address (or its identity saved)."""
        for i in range(self.list.count()):
            it = self.list.item(i)
            c = self._child_by_id(it.data(Qt.UserRole))
            if c and c.id == child_id:
                it.setText(self._label(c))
                self.online[c.id] = True
                it.setIcon(self.icons[True])
        self._refresh_labels()

    # ---- text size ---------------------------------------------------------------
    def change_scale(self, step):
        if step == 0:
            self.scale = 100
        else:
            i = SCALES.index(self.scale) + step
            self.scale = SCALES[max(0, min(len(SCALES) - 1, i))]
        self.store.set_setting("text_scale", self.scale)
        self.apply_scale()
        self.say(f"Text size {self.scale}%")

    def apply_scale(self):
        app = QApplication.instance()
        size = self.base_point_size * self.scale / 100
        f = QFont(app.font())
        f.setPointSizeF(size)
        app.setFont(f)
        style.apply_stylesheet(app)       # check boxes / buttons follow the text size
        mono = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        mono.setPointSizeF(size)
        for w in self.findChildren(QPlainTextEdit):
            w.setFont(mono)
        row = self.fontMetrics().height() + 8
        for t in self.findChildren(QTableView):
            t.setFont(f)
            t.verticalHeader().setDefaultSectionSize(row)
        icon = max(14, int(14 * self.scale / 100))
        self.list.setIconSize(QSize(icon, icon))

    def _child_by_id(self, cid):
        return next((c for c in self.store.children if c.id == cid), None)

    def _check_online(self):
        kids = list(self.store.children)

        def job():
            res, moved = {}, []
            for c in kids:
                res[c.id] = is_reachable(c.ip, c.port)
                # Not at its last address: look for it (at most once a minute per child).
                if not res[c.id] and c.host_key and search_allowed(c.id):
                    ip = discovery.find_pc(c.host_key, c.ip, c.port)
                    if ip and ip != c.ip:
                        moved.append((c.name, c.ip, ip))
                        c.ip = ip
                        res[c.id] = True
            if moved:
                self.store.save()
            return res, moved

        def ok(result):
            res, moved = result
            self.online.update(res)
            for i in range(self.list.count()):
                it = self.list.item(i)
                it.setIcon(self.icons[self.online.get(it.data(Qt.UserRole))])
                c = self._child_by_id(it.data(Qt.UserRole))
                if c:
                    it.setText(self._label(c))
            for name, old, new in moved:
                self.say(f"{name}'s PC has a new address ({new}, was {old}) - updated.")
            self._refresh_labels()

        run_bg(job, ok, quiet=True)

    def _selected(self, item, _prev=None):
        child = self._child_by_id(item.data(Qt.UserRole)) if item else None
        if child is self.current:
            return
        if self.rules.is_dirty():
            r = QMessageBox.question(self, "Unsaved changes",
                                     f"Discard unsaved rule changes for {self.current.name}?")
            if r != QMessageBox.Yes:
                self.list.blockSignals(True)
                self._populate(self.current.id)
                self.list.blockSignals(False)
                return
        self._set_child(child)

    def _set_child(self, child):
        self.current = child
        if child and not self.store.get_password(child):
            ask_password(self, self.store, child)
        if child and self.store.get_password(child):
            self.collector.start(child)        # selecting a child logs in to their PC
        self.rules.set_child(child)
        self.activity.set_child(child)
        self.pc_tab.set_child(child)
        self._tab_changed(self.tabs.currentIndex())

    def _tab_changed(self, index):
        if not self.current:
            return
        w = self.tabs.widget(index)
        if w is self.pc_tab:
            self.pc_tab.refresh()

    def _add_domain(self, which, domain):
        self.say(self.rules.add_domain(which, domain))
        self.tabs.setCurrentWidget(self.rules)

    def _warn_duplicates(self):
        dups = self.store.duplicates()
        if not dups:
            return
        lines = "\n".join(f"  {c.name} ({c.ip}, user {c.child_user}) - same PC as {e.name}"
                          for c, e in dups)
        QMessageBox.warning(self, "PC listed more than once",
                            "These entries are for a PC that is already in the list:\n\n"
                            f"{lines}\n\nTwo entries for one PC confuse each other.  Select the "
                            "extra entry and press Remove (this changes nothing on the PC).")

    # ---- actions -------------------------------------------------------------------
    def add_child(self):
        d = ChildDialog(self.store, parent=self)
        if d.exec():
            self.current = None
            self._populate(d.saved_child.id)
            self._check_online()

    def edit_child(self):
        if not self.current:
            return
        d = ChildDialog(self.store, self.current, parent=self)
        if d.exec():
            self.remotes.drop(self.current)
            self.collector.stop(self.current.id)
            self.current = None
            self._populate(d.saved_child.id)
            self._check_online()

    def remove_child(self):
        c = self.current
        if not c:
            return
        r = QMessageBox.question(self, "Remove child",
                                 f"Remove {c.name} from this app?\n\nThis does not change anything "
                                 "on the PC - its filtering stays as it is.")
        if r == QMessageBox.Yes:
            self.collector.forget(c.id)
            self.remotes.drop(c)
            self.store.remove(c)
            self.current = None
            self._populate()

    def logout_child(self):
        c = self.current
        if not c:
            return
        self.collector.stop(c.id)
        self.remotes.drop(c)
        self._refresh_labels()
        self.say(f"Logged out of {c.name}'s PC - activity is no longer being collected.")

    def logout_all(self):
        self.collector.stop_all()
        self.remotes.close_all()
        self._refresh_labels()
        self.say("Logged out of all PCs - activity is no longer being collected.")

    def reconnect_child(self):
        c = self.current
        if not c:
            return
        if self.rules.is_dirty():
            r = QMessageBox.question(self, "Unsaved changes",
                                     f"Discard unsaved rule changes for {c.name}?")
            if r != QMessageBox.Yes:
                return
        d = ReconnectDialog(self.store, c, parent=self)
        if d.exec():
            self.remotes.drop(c)
            self.collector.stop(c.id)
            self.online[c.id] = True
            self.current = None
            self._populate(c.id)
            self.say(f"Reconnected to {c.name}'s PC at {c.ip}.")
            self._check_online()

    def test_child(self):
        c = self.current
        if not c:
            return
        self.say(f"Testing connection to {c.name}'s PC (this can take up to a minute)…")

        def ok(st):
            self.say(f"{c.name}: connected - Squid {'running' if st.get('squid_running') else 'NOT running'}, "
                     f"firewall {'active' if st.get('firewall_active') else 'NOT active'}"
                     + (".  WARNING: the child is an administrator on that PC."
                        if st.get("child_is_admin") else "."))

        self.collector.start(c)
        run_bg(lambda: self.remotes.get(c).status(), ok, self.say)

    def _about(self):
        QMessageBox.about(self, APP_NAME,
                          f"<b>{APP_NAME} {__version__}</b><br>Monitor and restrict web access on "
                          "children's Ubuntu and Windows PCs using Squid.<br><br>"
                          "Free to use - donations welcome: "
                          "<a href='https://ko-fi.com/ianp5'>Ko-fi</a> or "
                          "<a href='https://github.com/sponsors/ianp5uk'>GitHub Sponsors</a>.<br><br>"
                          f"{COPYRIGHT}<br>Licensed under the {LICENSE_NAME}. "
                          "This program comes with ABSOLUTELY NO WARRANTY. It is free "
                          "software: you may redistribute and modify it under the terms of "
                          "that licence (<a href='https://www.gnu.org/licenses/gpl-3.0.html'>"
                          "gnu.org/licenses/gpl-3.0</a>); anyone who distributes it must also "
                          "provide the complete source code.<br><br>Settings: "
                          f"{self.store.path}")

    def closeEvent(self, ev):
        if self.rules.is_dirty():
            r = QMessageBox.question(self, "Unsaved changes", "Quit and discard unsaved rule changes?")
            if r != QMessageBox.Yes:
                ev.ignore()
                return
        self.collector.stop_all()
        self.remotes.close_all()
        ev.accept()


def _windowed_logging():
    """The Windows build has no console (sys.stderr is None), so send output
    to a log file in the settings folder - useful when something goes wrong."""
    if sys.stderr is None or sys.stdout is None:
        from .config_store import config_dir
        log = open(os.path.join(config_dir(), "blighter-restrictor.log"), "a",
                   encoding="utf-8", buffering=1)
        sys.stdout = sys.stdout or log
        sys.stderr = sys.stderr or log


def main():
    _windowed_logging()
    if "--self-test" in sys.argv:
        print("self-test: starting", flush=True)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setDesktopFileName("blighter-restrictor")
    style.setup(app)
    win = MainWindow()
    app.aboutToQuit.connect(win.remotes.close_all)
    win.show()
    if "--self-test" in sys.argv:  # used by the Windows build to check the exe starts
        print("self-test: window shown", flush=True)
        QTimer.singleShot(3000, app.quit)
    sys.exit(app.exec())
