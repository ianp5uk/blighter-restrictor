# -----------------------------------------------------------------------------
# Blighter Restrictor - "Add / Edit child", "Reconnect" and the password prompt.
#
# Purpose:
#   ChildDialog      enter a child's name, the address shown at the end of
#                    setup on their PC, their username on the PC (the account
#                    that is filtered), the admin login created by the setup,
#                    its password (saved to the keyring) and the SSH port.
#                    "Test connection" logs in and asks the PC for its status.
#                    The PC's SSH identity is remembered from the first
#                    connection, so the app can find the PC again by itself
#                    when its address changes (no router settings needed).
#                    A second entry for the same PC is refused.
#                    "Find PCs…" (Add only, since 1.4.0) opens FindPCsDialog.
#   FindPCsDialog    lists the Blighter child PCs on this PC's own
#                    network(s) - name, system, Blighter version, address -
#                    read from each PC's SSH greeting without a password
#                    (discovery.find_pcs).  PCs already in the list are
#                    marked "already added" and cannot be picked.  Picking
#                    one fills in the address (and the name, if empty) in
#                    Add child; the rest is entered as before.  PCs on other
#                    networks (e.g. a guest network) must be entered by hand.
#   ReconnectDialog  when the app cannot find a child's PC: "Find
#                    automatically" searches the home network for it; or
#                    enter the address shown on the PC (Blighter-Details.cmd
#                    on Windows, "sudo blighter-setup --details" on Ubuntu)
#                    and optionally a new password.  If the computer at that
#                    address has a different identity (Blighter reinstalled,
#                    or a new PC) the parent must confirm before the saved
#                    identity is replaced.  The child's name, username and
#                    the PC's own filters and activity log are not changed.
#   ask_password     asks for a password that is not saved.
#   FitDialog        base for the dialogs: sized from the text size and
#                    the main window (not fixed pixels), and grows to fit
#                    messages as they appear, so nothing overlaps.
#
# Copyright (C) 2026 Ian Packer
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version.  It is distributed WITHOUT ANY WARRANTY; see the
# LICENSE file or <https://www.gnu.org/licenses/> for details.
# -----------------------------------------------------------------------------

import dataclasses
import ipaddress
import re

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QDialogButtonBox, QFormLayout,
                               QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit,
                               QMessageBox, QPushButton, QSpinBox, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout)

from . import discovery
from .config_store import Child
from .remote import IdentityChanged, Remote
from .shared import admin_warning_html, same_user
from .workers import run_bg

WHERE_TO_FIND = ("To see the address on the child's PC:<br>"
                 "&nbsp;&nbsp;<b>Windows</b>: press Windows key + R and type<br>"
                 "&nbsp;&nbsp;&nbsp;&nbsp;<b><nobr>C:\\ProgramData\\BlighterChild\\Blighter-Details.cmd</nobr></b><br>"
                 "&nbsp;&nbsp;<b>Ubuntu</b>: open a Terminal and type <b><nobr>sudo blighter-setup --details</nobr></b>")

class FitDialog(QDialog):
    """A dialog sized for its text, not in fixed pixels (since 1.2.9).

    Its width follows the text size (View > Text size) and the main window:
    at least `chars` average characters wide, and at least 45% of the main
    window's width (capped to 90% of the screen).  Its height grows to fit
    word-wrapped messages when they appear (call refit()), so nothing is
    squeezed or overlaps at large text sizes."""

    chars = 60

    def _target_width(self):
        w = self.fontMetrics().averageCharWidth() * self.chars
        parent = self.parentWidget()
        if parent is not None:
            w = max(w, int(parent.window().width() * 0.45))
        screen = self.screen()
        if screen is not None:
            w = min(w, int(screen.availableGeometry().width() * 0.9))
        return w

    def showEvent(self, event):
        self.setMinimumWidth(self._target_width())
        self._grow()
        super().showEvent(event)

    def refit(self):
        """Grow to fit new text (after the event loop has laid it out)."""
        QTimer.singleShot(0, self._grow)

    def _grow(self):
        lay = self.layout()
        width = max(self.width(), self.minimumWidth())
        need = lay.heightForWidth(width) if lay is not None and lay.hasHeightForWidth() else -1
        if need < 0:
            need = self.sizeHint().height()
        if need > self.height() or width > self.width():
            self.resize(width, max(need, self.height()))


# Ubuntu usernames, plus Windows local account names (letters, digits,
# spaces, dots, hyphens, underscores; up to 20 characters on Windows).
_USER_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9 _.-]{0,31}$")


class ChildDialog(FitDialog):
    chars = 62

    def __init__(self, store, child=None, parent=None):
        super().__init__(parent)
        self.store = store
        self.original = child
        self.setWindowTitle("Edit child" if child else "Add child")

        self.name = QLineEdit(child.name if child else "")
        self.ip = QLineEdit(child.ip if child else "")
        self.ip.setPlaceholderText("shown at the end of setup on the child's PC, e.g. 192.168.1.50")
        self.child_user = QLineEdit(child.child_user if child else "")
        self.child_user.setPlaceholderText("the child's login name on their PC")
        self.admin_user = QLineEdit(child.admin_user if child else "blighter")
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        if child and store.get_password(child):
            self.password.setPlaceholderText("(saved - leave blank to keep)")
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(child.port if child else 22)

        form = QFormLayout()
        form.addRow("Child's name:", self.name)
        if child:
            form.addRow("PC address:", self.ip)
        else:
            find = QPushButton("Find PCs…")
            find.setToolTip("List the Blighter child PCs on this PC's network")
            find.clicked.connect(self._find_pcs)
            ip_row = QHBoxLayout()
            ip_row.addWidget(self.ip, 1)
            ip_row.addWidget(find)
            form.addRow("PC address:", ip_row)
        form.addRow("Child's username:", self.child_user)
        form.addRow("Admin login:", self.admin_user)
        form.addRow("Admin password:", self.password)
        form.addRow("SSH port:", self.port)

        hint = QLabel("Enter the address, username and login shown at the end of the Blighter "
                      "setup on the child's PC" + ("" if child else " (or press Find PCs to fill in the address)")
                      + ".  You only need to do this once: if the PC's "
                      "address changes later, the app finds it again by itself.")
        hint.setWordWrap(True)

        self.result_label = QLabel("")
        self.result_label.setWordWrap(True)
        test = QPushButton("Test connection")
        test.clicked.connect(self._test)
        row = QHBoxLayout()
        row.addWidget(test)
        row.addStretch()
        self._tested = None          # (address, identity) from a successful Test

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(hint)
        lay.addLayout(row)
        lay.addWidget(self.result_label)
        lay.addWidget(buttons)
        self.saved_child = None

    def _collect(self):
        name = self.name.text().strip()
        ip = self.ip.text().strip()
        cu = self.child_user.text().strip()
        au = self.admin_user.text().strip()
        if not name:
            raise ValueError("Please enter the child's name.")
        try:
            ipaddress.IPv4Address(ip)
        except ValueError:
            raise ValueError(f"'{ip}' is not a valid IPv4 address.")
        for label, u in (("Child's username", cu), ("Admin login", au)):
            if not _USER_RE.match(u):
                raise ValueError(f"{label} '{u}' is not a valid username.")
        if cu.lower() == au.lower():
            raise ValueError("The child's username and the admin login must be different.")
        c = Child(name=name, ip=ip, child_user=cu, admin_user=au, port=self.port.value())
        if self.original:
            c.id = self.original.id
            c.host_key = self.original.host_key
        if not c.host_key and self._tested and self._tested[0] == ip:
            c.host_key = self._tested[1]
        dup = self.store.find_duplicate(c)
        if dup:
            raise ValueError(f"{dup.name} ({dup.ip}, user {dup.child_user}) is already in the list.  "
                             "Each child's PC can only be listed once - edit that entry instead.")
        pw = self.password.text() or (self.store.get_password(self.original) if self.original else "")
        if not pw:
            raise ValueError("Please enter the admin password.")
        return c, pw

    def _result(self, text):
        self.result_label.setText(text)
        self.refit()

    def _find_pcs(self):
        d = FindPCsDialog(self.store, self.port.value(), parent=self)
        if d.exec() and d.picked:
            self.ip.setText(d.picked["ip"])
            if not self.name.text().strip():
                self.name.setText(d.picked["name"])
            self._result("")

    def _test(self):
        try:
            child, pw = self._collect()
        except ValueError as e:
            self._result(f"<span style='color:#c0392b'>{e}</span>")
            return
        self._result("Connecting and checking the PC (this can take up to a minute)…")

        def job():
            r = Remote(child, pw, self.store.known_hosts, discover=False)
            try:
                st = r.status()
                return st, child.ip, child.host_key
            finally:
                r.close()

        def ok(res):
            st, ip, key = res
            self._tested = (ip, key)
            system = "Windows" if st.get("platform") == "windows" else "Ubuntu"
            msg = (f"<span style='color:#27ae60'><b>Connected</b></span> ({system}). "
                   f"The PC filters user <b>{st.get('child_user')}</b>; "
                   f"{st.get('squid_version')}; Squid "
                   f"{'running' if st.get('squid_running') else '<b>NOT running</b>'}; firewall "
                   f"{'active' if st.get('firewall_active') else '<b>NOT active</b>'}.")
            if not same_user(st.get("child_user"), child.child_user, st.get("platform")):
                msg += (f"<br><span style='color:#c0392b'>Warning: the PC was set up for "
                        f"'{st.get('child_user')}', not '{child.child_user}'.</span>")
            msg += admin_warning_html(st)
            self._result(msg)

        def err(m):
            if self.original:
                m += "  (If the PC was reinstalled, close this and use Reconnect.)"
            self._result(f"<span style='color:#c0392b'>{m}</span>")

        run_bg(job, ok, err)

    def _save(self):
        try:
            child, pw = self._collect()
        except ValueError as e:
            QMessageBox.warning(self, "Check details", str(e))
            return
        self.store.upsert(child)
        if not self.store.set_password(child, pw):
            QMessageBox.information(
                self, "Keyring unavailable",
                "The password could not be saved to the system keyring "
                f"({self.store.keyring_error}).\nIt will be remembered until you close the app.")
        self.saved_child = child
        self.accept()


class FindPCsDialog(FitDialog):
    """The Blighter child PCs on this PC's own network(s), to pick one for Add child."""
    chars = 70

    def __init__(self, store, port=22, parent=None):
        super().__init__(parent)
        self.store = store
        self.port = port
        self.picked = None
        self._open = True               # False once closed: a late search result is ignored
        self.setWindowTitle("Find PCs")

        note = QLabel("Only this PC's own network is searched.  A PC on another network "
                      "(for example a guest network) must be added by entering its address.")
        note.setWordWrap(True)
        self.list = QTreeWidget()
        self.list.setHeaderLabels(["Name", "System", "Blighter", "Address", ""])
        self.list.setRootIsDecorated(False)
        self.list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.list.header().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.list.header().setStretchLastSection(True)
        self.list.itemSelectionChanged.connect(self._selection)
        self.list.itemDoubleClicked.connect(lambda *_: self._pick())
        self.message = QLabel("")
        self.message.setWordWrap(True)
        self.btn_search = QPushButton("Search again")
        self.btn_search.clicked.connect(self._search)
        self.btn_use = QPushButton("Use this PC")
        self.btn_use.setEnabled(False)
        self.btn_use.clicked.connect(self._pick)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        row = QHBoxLayout()
        row.addWidget(self.btn_search)
        row.addStretch()
        row.addWidget(self.btn_use)
        row.addWidget(cancel)

        lay = QVBoxLayout(self)
        lay.addWidget(note)
        lay.addWidget(self.list)
        lay.addWidget(self.message)
        lay.addLayout(row)
        QTimer.singleShot(0, self._search)

    def done(self, result):
        self._open = False
        super().done(result)

    def _say(self, text, colour=None):
        self.message.setText(f"<span style='color:{colour}'>{text}</span>" if colour else text)
        self.refit()

    def _search(self):
        self.btn_search.setEnabled(False)
        self.btn_search.setText("Searching…")
        self.btn_use.setEnabled(False)
        self.list.clear()
        self._say("Searching this PC's network for Blighter child PCs (a few seconds)…")
        known = [c.host_key for c in self.store.children if c.host_key]
        port = self.port

        def finished():
            self.btn_search.setEnabled(True)
            self.btn_search.setText("Search again")

        def ok(found):
            if not self._open:
                return
            finished()
            for pc in found:
                it = QTreeWidgetItem([pc["name"], pc["os"], pc["version"], pc["ip"],
                                      "already added" if pc["known"] else ""])
                it.setData(0, Qt.UserRole, pc)
                if pc["known"]:
                    it.setFlags(Qt.NoItemFlags)
                    it.setToolTip(0, "This PC is already in the list")
                self.list.addTopLevelItem(it)
            new = [pc for pc in found if not pc["known"]]
            if not found:
                self._say("No Blighter child PCs found.  Make sure the PC is switched on, Blighter "
                          "is set up on it and it is on the same network as this PC - or enter its "
                          "address.", "#c0392b")
            elif not new:
                self._say("All the PCs found are already in the list.")
            else:
                self._say("Pick a PC, then press Use this PC.")
                if len(new) == 1:
                    for i in range(self.list.topLevelItemCount()):
                        it = self.list.topLevelItem(i)
                        if not it.data(0, Qt.UserRole)["known"]:
                            self.list.setCurrentItem(it)

        def err(m):
            if not self._open:
                return
            finished()
            self._say(f"The search failed: {m}", "#c0392b")

        run_bg(lambda: discovery.find_pcs(known, port), ok, err)

    def _selection(self):
        it = self.list.currentItem()
        self.btn_use.setEnabled(bool(it and it.isSelected() and not it.data(0, Qt.UserRole)["known"]))

    def _pick(self):
        it = self.list.currentItem()
        if not it or it.data(0, Qt.UserRole)["known"]:
            return
        self.picked = it.data(0, Qt.UserRole)
        self.accept()


class ReconnectDialog(FitDialog):
    """Find a child's PC again, or connect it at a new address / identity."""
    chars = 78

    def __init__(self, store, child, parent=None):
        super().__init__(parent)
        self.store = store
        self.child = child
        self.new_key = ""               # identity offered at the address, if different
        self.setWindowTitle(f"Reconnect {child.name}'s PC")

        intro = QLabel(f"Use this if the app cannot find <b>{child.name}</b>'s PC, or after Blighter was "
                       f"reinstalled on it.  {child.name}'s name, username, the PC's filters and its "
                       "activity log are not changed.")
        intro.setWordWrap(True)
        self.btn_find = QPushButton("Find automatically")
        self.btn_find.setToolTip("Search the home network for this PC (a few seconds)")
        self.btn_find.clicked.connect(self._find)
        if not child.host_key:
            self.btn_find.setEnabled(False)
            self.btn_find.setToolTip("Not possible yet: the app has not connected to this PC before.  "
                                     "Enter its address below.")
        where = QLabel("Or enter the address shown on the child's PC.<br>" + WHERE_TO_FIND)
        where.setWordWrap(True)
        self.ip = QLineEdit(child.ip)
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.password.setPlaceholderText("leave blank to keep the saved password")
        form = QFormLayout()
        form.addRow("PC address:", self.ip)
        form.addRow("Admin password:", self.password)
        self.btn_connect = QPushButton("Connect")
        self.btn_connect.clicked.connect(lambda: self._connect(replace=False))
        self.btn_replace = QPushButton("This is the right PC - connect and remember it")
        self.btn_replace.clicked.connect(lambda: self._connect(replace=True))
        self.btn_replace.hide()
        self.message = QLabel("")
        self.message.setWordWrap(True)
        row = QHBoxLayout()
        row.addWidget(self.btn_connect)
        row.addWidget(self.btn_replace)
        row.addStretch()
        close = QDialogButtonBox(QDialogButtonBox.Close)
        close.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addWidget(intro)
        lay.addWidget(self.btn_find)
        lay.addSpacing(8)
        lay.addWidget(where)
        lay.addLayout(form)
        lay.addLayout(row)
        lay.addWidget(self.message)
        lay.addWidget(close)

    def _busy(self, on):
        for b in (self.btn_find, self.btn_connect, self.btn_replace):
            b.setEnabled(not on and (b is not self.btn_find or bool(self.child.host_key)))

    def _say(self, text, colour=None):
        self.message.setText(f"<span style='color:{colour}'>{text}</span>" if colour else text)
        self.refit()

    def _find(self):
        c = self.child
        self._busy(True)
        self._say(f"Searching the home network for {c.name}'s PC…")

        def ok(ip):
            self._busy(False)
            if not ip:
                self._say(f"{c.name}'s PC was not found.  Make sure it is switched on and connected to the "
                          "same home network, or enter its address below.", "#c0392b")
                return
            c.ip = ip
            self.ip.setText(ip)
            self.store.save()
            self._say(f"Found {c.name}'s PC at {ip}.", "#27ae60")
            self.accept()

        run_bg(lambda: discovery.find_pc(c.host_key, c.ip, c.port), ok,
               lambda m: (self._busy(False), self._say(m, "#c0392b")))

    def _connect(self, replace):
        c = self.child
        ip = self.ip.text().strip()
        try:
            ipaddress.IPv4Address(ip)
        except ValueError:
            self._say(f"'{ip}' is not a valid address.", "#c0392b")
            return
        pw = self.password.text() or self.store.get_password(c)
        if not pw:
            self._say("Please enter the admin password.", "#c0392b")
            return
        trial = dataclasses.replace(c, ip=ip, host_key="" if replace else c.host_key)
        self._busy(True)
        self._say("Connecting (this can take up to a minute)…")

        def job():
            r = Remote(trial, pw, self.store.known_hosts, discover=False)
            try:
                return r.status()
            finally:
                r.close()

        def ok(st):
            self._busy(False)
            if not same_user(st.get("child_user"), c.child_user, st.get("platform")):
                self._say(f"Connected, but this PC is set up for '{st.get('child_user')}', not "
                          f"'{c.child_user}'.  Nothing was changed.  If it is the right PC, use Edit to "
                          "change the child's username first.", "#c0392b")
                return
            c.ip, c.host_key = trial.ip, trial.host_key
            if self.password.text():
                self.store.set_password(c, self.password.text())
            self.store.save()
            self.accept()

        def err(m, e_type=None):
            self._busy(False)
            self._say(m, "#c0392b")

        def job_wrapped():
            try:
                return ("ok", job())
            except IdentityChanged as e:
                return ("identity", str(e))

        def done(res):
            kind, value = res
            if kind == "ok":
                ok(value)
                return
            self._busy(False)
            self.btn_replace.show()
            self.refit()
            self._say(f"The computer at {ip} is not the one saved as {c.name}'s PC.<br>This happens after "
                      f"Blighter is reinstalled on it, or with a different computer.  Press the button below "
                      f"only if this really is {c.name}'s PC.", "#c0392b")

        run_bg(job_wrapped, done, err)


def ask_password(parent, store, child):
    pw, ok = QInputDialog.getText(parent, "Password needed",
                                  f"Admin password for {child.name}'s PC ({child.admin_user}@{child.ip}):",
                                  QLineEdit.Password)
    if ok and pw:
        store.set_password(child, pw)
        return pw
    return None
