# -----------------------------------------------------------------------------
# Blighter Restrictor - main window.
#
# Purpose: the application shell.  Left: the list of children with an
# online/offline indicator (checked every 20 s) and Add / Edit / Remove /
# Test buttons.  Right: three tabs for the selected child -
#   Rules    - mode, allow/block lists, Allow Discord, home network, Apply
#   Activity - the Squid access log, filters, per-site summary
#   Laptop   - what is actually in force on the laptop, health, Reload Squid,
#              Pause / Resume filtering
# A status bar shows progress and errors, and "Working…" with a moving bar
# while the app waits for a laptop.  A paused child is shown "- PAUSED" in red.
# Children with an open SSH session are shown in bold.
# A laptop listed twice (same IP and child username, from before 1.2.4) is
# reported at start-up so the extra entry can be removed.
# Log out: "Log out" button (selected child), File > Log out of all laptops,
# automatically after 5 minutes without use, and always when the app closes.
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

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QFont, QFontDatabase, QIcon, QKeySequence, QPainter, QPixmap
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QMainWindow, QMessageBox,
                               QPlainTextEdit, QProgressBar, QPushButton, QSplitter,
                               QTableView, QTabWidget, QVBoxLayout, QWidget)

from . import APP_NAME, COPYRIGHT, LICENSE_NAME, __version__, style
from .activity_tab import ActivityTab
from .config_store import Store
from .dialogs import ChildDialog, ask_password
from .laptop_tab import LaptopTab
from .remote import RemoteManager, is_reachable
from .rules_tab import RulesTab
from .workers import busy_signal, run_bg

ICON_PATH = os.path.join(os.path.dirname(__file__), "icon.svg")
IDLE_LOGOUT_SECONDS = 300
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
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.setWindowIcon(QIcon(ICON_PATH))
        self.resize(1150, 720)
        self.store = Store()
        self.remotes = RemoteManager(self.store)
        self.online = {}
        self.paused = {}      # child id -> True/False, as last reported by the laptop
        self.icons = {True: _dot("#27ae60"), False: _dot("#95a5a6"), None: _dot("#f1c40f")}
        self.current = None

        # ---- children panel
        self.list = QListWidget()
        self.list.setIconSize(QSize(14, 14))
        self.list.currentItemChanged.connect(self._selected)
        self.list.itemDoubleClicked.connect(lambda *_: self.edit_child())
        b_add, b_edit, b_del, b_test = (QPushButton(t) for t in ("Add", "Edit", "Remove", "Test"))
        self.b_logout = QPushButton("Log out")
        self.b_logout.setToolTip("Close the SSH session to the selected child's laptop")
        self.b_logout.clicked.connect(self.logout_child)
        b_add.clicked.connect(self.add_child)
        b_edit.clicked.connect(self.edit_child)
        b_del.clicked.connect(self.remove_child)
        b_test.clicked.connect(self.test_child)
        grid1, grid2 = QHBoxLayout(), QHBoxLayout()
        grid1.addWidget(b_add)
        grid1.addWidget(b_edit)
        grid2.addWidget(b_del)
        grid2.addWidget(b_test)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.addWidget(QLabel("<b>Children</b>"))
        ll.addWidget(self.list, 1)
        ll.addLayout(grid1)
        ll.addLayout(grid2)
        ll.addWidget(self.b_logout)

        # ---- tabs
        self.rules = RulesTab(self.remotes)
        self.activity = ActivityTab(self.remotes)
        self.laptop = LaptopTab(self.remotes)
        self.tabs = QTabWidget()
        self.tabs.addTab(self.rules, "Rules")
        self.tabs.addTab(self.activity, "Activity")
        self.tabs.addTab(self.laptop, "Laptop")
        self.tabs.currentChanged.connect(self._tab_changed)
        for t in (self.rules, self.activity, self.laptop):
            t.status.connect(self.say)
        self.activity.add_domain.connect(self._add_domain)
        self.laptop.paused_known.connect(self._paused_known)

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
        logout_all = QAction("&Log out of all laptops", self, shortcut="Ctrl+L")
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
        about = QAction("&About", self)
        about.triggered.connect(self._about)
        h.addAction(about)

        app = QApplication.instance()
        self.base_point_size = app.font().pointSizeF()
        self.scale = self.store.get_setting("text_scale", 100)
        if self.scale not in SCALES:
            self.scale = 100
        self.apply_scale()

        # ---- "Working…" indicator: shown while the app waits for a laptop, so a
        # parent can see it hasn't hung (Windows laptops take a few seconds).
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
        self.idle = QTimer(self, interval=15000)
        self.idle.timeout.connect(self._idle_logout)
        self.idle.start()
        self.poll = QTimer(self, interval=20000)
        self.poll.timeout.connect(self._check_online)
        self.poll.start()
        self._check_online()
        if self.store.keyring_error:
            self.say(f"Keyring not available ({self.store.keyring_error}) - passwords kept for this session only.")
        elif not self.store.children:
            self.say("Add a child to get started.")
        QTimer.singleShot(0, self._warn_duplicates)

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

    def _idle_logout(self):
        keep = [self.current.id] if self.current and self.activity.live.isChecked() else []
        names = self.remotes.close_idle(IDLE_LOGOUT_SECONDS, keep)
        if names:
            self.say("Logged out of " + ", ".join(names) + " (not used for 5 minutes).")
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
            return {c.id: is_reachable(c.ip, c.port) for c in kids}

        def ok(res):
            self.online.update(res)
            for i in range(self.list.count()):
                it = self.list.item(i)
                it.setIcon(self.icons[self.online.get(it.data(Qt.UserRole))])
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
        self.rules.set_child(child)
        self.activity.set_child(child)
        self.laptop.set_child(child)
        self._tab_changed(self.tabs.currentIndex())

    def _tab_changed(self, index):
        if not self.current:
            return
        w = self.tabs.widget(index)
        if w is self.activity and not self.activity.entries:
            self.activity.refresh()
        elif w is self.laptop:
            self.laptop.refresh()

    def _add_domain(self, which, domain):
        self.say(self.rules.add_domain(which, domain))
        self.tabs.setCurrentWidget(self.rules)

    def _warn_duplicates(self):
        dups = self.store.duplicates()
        if not dups:
            return
        lines = "\n".join(f"  {c.name} ({c.ip}, user {c.child_user}) - same laptop as {e.name}"
                          for c, e in dups)
        QMessageBox.warning(self, "Laptop listed more than once",
                            "These entries are for a laptop that is already in the list:\n\n"
                            f"{lines}\n\nTwo entries for one laptop confuse each other.  Select the "
                            "extra entry and press Remove (this changes nothing on the laptop).")

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
            self.current = None
            self._populate(d.saved_child.id)
            self._check_online()

    def remove_child(self):
        c = self.current
        if not c:
            return
        r = QMessageBox.question(self, "Remove child",
                                 f"Remove {c.name} from this app?\n\nThis does not change anything "
                                 "on the laptop - its filtering stays as it is.")
        if r == QMessageBox.Yes:
            self.remotes.drop(c)
            self.store.remove(c)
            self.current = None
            self._populate()

    def logout_child(self):
        c = self.current
        if not c:
            return
        self.activity.live.setChecked(False)
        self.remotes.drop(c)
        self._refresh_labels()
        self.say(f"Logged out of {c.name}'s laptop.")

    def logout_all(self):
        self.activity.live.setChecked(False)
        self.remotes.close_all()
        self._refresh_labels()
        self.say("Logged out of all laptops.")

    def test_child(self):
        c = self.current
        if not c:
            return
        self.say(f"Testing connection to {c.name}'s laptop (this can take up to a minute)…")

        def ok(st):
            self.say(f"{c.name}: connected - Squid {'running' if st.get('squid_running') else 'NOT running'}, "
                     f"firewall {'active' if st.get('firewall_active') else 'NOT active'}"
                     + (".  WARNING: the child is an administrator on that laptop."
                        if st.get("child_is_admin") else "."))

        run_bg(lambda: self.remotes.get(c).status(), ok, self.say)

    def _about(self):
        QMessageBox.about(self, APP_NAME,
                          f"<b>{APP_NAME} {__version__}</b><br>Monitor and restrict web access on "
                          "children's Ubuntu and Windows laptops using Squid.<br><br>"
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
