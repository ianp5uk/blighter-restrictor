# -----------------------------------------------------------------------------
# Blighter Restrictor - "Controls" tab (since 1.3.0).
#
# Purpose: the quick controls for one child's PC.
#   Internet access - a three-way switch, applied as soon as it is clicked:
#     Filtered   the filters on the Filters tab apply (normal)
#     Block all  every website and Discord blocked; the home network stays
#                as its own switch says
#     Open all   every website and Discord allowed
#   The filters are kept whatever is chosen, so Filtered puts them straight
#   back.  The PC's firewall stays on in all three, so activity is ALWAYS
#   recorded.  (Open all replaces 1.2.x's Pause / Resume on the PC tab.)
#   The switch can also be set on a Windows PC itself ("Blighter Open
#   All.cmd" / "Blighter Filtered.cmd", or "sudo blighter-apply open local"
#   on Ubuntu); the tab then says "set on the PC itself".  If an
#   administrator switched Blighter off completely on a Windows PC for
#   troubleshooting, a red notice says nothing is recorded; choosing any of
#   the three switches it back on.
#   This PC - Log child out, Restart PC, Shut down PC.  Each asks first
#   (unsaved work on the PC is lost) and then happens straight away: the
#   child is not warned.  Log out does not stop them logging back in.
# Everything is read from the PC itself ("get") when a PC is selected or
# "Read from PC" is pressed.  Like the Filters tab, every request is tagged
# with the PC and a sequence number, so a slow or offline PC can't leave the
# tab stuck and late replies from a PC no longer selected are ignored.
#
# Copyright (C) 2026 Ian Packer
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version.  It is distributed WITHOUT ANY WARRANTY; see the
# LICENSE file or <https://www.gnu.org/licenses/> for details.
# -----------------------------------------------------------------------------

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QButtonGroup, QGroupBox, QHBoxLayout, QLabel, QMessageBox,
                               QPushButton, QRadioButton, QVBoxLayout, QWidget)

from .shared import domains
from .workers import run_bg

CHOICES = (
    (domains.CONTROL_FILTERED, "Filtered",
     "The filters on the Filters tab apply."),
    (domains.CONTROL_BLOCK, "Block all",
     "Every website and Discord are blocked.  The home network stays as its switch on the "
     "Filters tab says, and this app can always reach the PC."),
    (domains.CONTROL_OPEN, "Open all",
     "Every website and Discord are allowed.  Activity is still recorded."),
)

ACTIONS = {
    "logout": ("Log child out", "Log {name} out of their PC now?",
               "Anything {name} hasn't saved will be lost.  They can log straight back in."),
    "restart": ("Restart PC", "Restart {name}'s PC now?",
                "Anything not saved on it will be lost.  Blighter comes back on by itself."),
    "shutdown": ("Shut down PC", "Shut down {name}'s PC now?",
                 "Anything not saved on it will be lost.  It will show as not reachable here "
                 "until someone switches it on again."),
}


def describe(info, name):
    """One sentence for a control reply ({"state", "by", "since"} + "bypassed")."""
    state = info.get("state", domains.CONTROL_FILTERED)
    label = domains.CONTROL_NAMES.get(state, state)
    who = "on the PC itself" if info.get("by") == "pc" else "from this app"
    when = f", {info['since']}" if info.get("since") else ""
    return f"In force on {name}'s PC: <b>{label}</b> (set {who}{when})."


class ControlsTab(QWidget):
    status = Signal(str)
    control_known = Signal(str, dict)     # child id, {"state", "by", "since", "bypassed"}

    def __init__(self, remotes, parent=None):
        super().__init__(parent)
        self.remotes = remotes
        self.child = None
        self.busy = False
        self.known = None          # last control info read from the PC
        self._seq = 0

        self.group = QButtonGroup(self)
        self.radios = {}
        access = QGroupBox("Internet access")
        al = QVBoxLayout(access)
        for state, title, text in CHOICES:
            rb = QRadioButton(title)
            self.radios[state] = rb
            self.group.addButton(rb)
            al.addWidget(rb)
            d = QLabel(text)
            d.setWordWrap(True)
            d.setContentsMargins(28, 0, 0, 6)
            al.addWidget(d)
        self.group.setExclusive(True)
        self.group.buttonClicked.connect(self._clicked)
        note = QLabel("Chosen as soon as you click.  The filters are kept whatever you choose, and "
                      "activity is recorded in all three.")
        note.setWordWrap(True)
        al.addWidget(note)

        self.state_label = QLabel("")
        self.state_label.setWordWrap(True)
        self.banner = QLabel("")
        self.banner.setWordWrap(True)
        self.banner.setStyleSheet("background:#c0392b; color:white; padding:8px; font-weight:bold;")
        self.banner.hide()

        pc = QGroupBox("This PC")
        pl = QVBoxLayout(pc)
        row = QHBoxLayout()
        self.action_buttons = {}
        for key in ("logout", "restart", "shutdown"):
            b = QPushButton(ACTIONS[key][0])
            b.clicked.connect(lambda _=False, k=key: self._action(k))
            self.action_buttons[key] = b
            row.addWidget(b)
        row.addStretch()
        pl.addLayout(row)
        pnote = QLabel("These happen straight away after you confirm; the child is not warned first.")
        pnote.setWordWrap(True)
        pl.addWidget(pnote)

        self.btn_read = QPushButton("Read from PC")
        self.btn_read.setToolTip("Ask the PC what is in force now")
        self.btn_read.clicked.connect(self.refresh)
        top = QHBoxLayout()
        top.addWidget(self.btn_read)
        top.addStretch()

        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(self.banner)
        lay.addWidget(self.state_label)
        lay.addWidget(access)
        lay.addWidget(pc)
        lay.addStretch(1)
        self._enable()

    # ---- helpers ------------------------------------------------------------------
    def _enable(self):
        ready = self.child is not None and not self.busy
        known = ready and self.known is not None
        for rb in self.radios.values():
            rb.setEnabled(known)
        for b in self.action_buttons.values():
            b.setEnabled(known)
        self.btn_read.setEnabled(ready)

    def _begin(self):
        self._seq += 1
        self.busy = True
        self._enable()
        return (self.child, self._seq)

    def _end(self, tag):
        """True if the reply is for the PC still selected (and the latest request)."""
        if tag[0] is not self.child or tag[1] != self._seq:
            return False
        self.busy = False
        self._enable()
        return True

    def _show(self, child, info):
        self.known = info
        state = info.get("state", domains.CONTROL_FILTERED)
        rb = self.radios.get(state)
        if rb:
            rb.setChecked(True)
        self.state_label.setText(describe(info, child.name))
        if info.get("bypassed"):
            self.banner.setText(f"BLIGHTER IS SWITCHED OFF on {child.name}'s PC itself (by an administrator, "
                                f"for troubleshooting) - {child.name} has open internet access and NO activity "
                                "is recorded.  Choose any setting below to switch it back on.")
        elif state == domains.CONTROL_OPEN:
            self.banner.setText(f"OPEN ALL on {child.name}'s PC - every website and Discord are allowed.  "
                                "Activity is still recorded.")
        elif state == domains.CONTROL_BLOCK:
            self.banner.setText(f"BLOCK ALL on {child.name}'s PC - every website and Discord are blocked.")
        self.banner.setVisible(bool(info.get("bypassed")) or state != domains.CONTROL_FILTERED)
        self.control_known.emit(child.id, dict(info))
        self._enable()

    def _show_known(self):
        """Put the radio buttons back to what the PC last said (after a failure)."""
        if self.known and self.child:
            self._show(self.child, self.known)

    # ---- public -------------------------------------------------------------------
    def set_child(self, child):
        self._seq += 1
        self.busy = False
        self.child = child
        self.known = None
        self.group.setExclusive(False)
        for rb in self.radios.values():
            rb.setChecked(False)
        self.group.setExclusive(True)
        self.banner.hide()
        self.state_label.setText("")
        self._enable()

    def refresh(self):
        if not self.child or self.busy:
            return
        child = self.child
        tag = self._begin()
        self.state_label.setText(f"Reading from {child.name}'s PC…")

        def ok(data):
            if not self._end(tag):
                return
            info = dict(data.get("control") or {})
            if not info:
                self.known = None
                self.state_label.setText(f"{child.name}'s PC has an older Blighter child "
                                         f"({data.get('helper_version', '?')}).  Update it to 1.3.0 to use "
                                         "these controls.")
                self._enable()
                return
            info["bypassed"] = bool(data.get("bypassed"))
            self._show(child, info)

        def err(msg):
            if not self._end(tag):
                return
            self.state_label.setText(f"Can't read {child.name}'s PC: {msg}")
            self.status.emit(msg)
            self._enable()

        run_bg(lambda: self.remotes.get(child).get(), ok, err)

    def _clicked(self, button):
        state = next((s for s, rb in self.radios.items() if rb is button), None)
        if not self.child or self.busy or state is None:
            self._show_known()
            return
        if self.known and self.known.get("state") == state and not self.known.get("bypassed"):
            return
        child = self.child
        tag = self._begin()
        self.status.emit(f"Setting {domains.CONTROL_NAMES[state]} on {child.name}'s PC…")

        def ok(res):
            mine = self._end(tag)
            msg = res.get("message", "")
            if res.get("errors"):
                msg += "  Problems: " + " ".join(res["errors"])[:300]
            self.status.emit(f"{child.name}: {msg}")
            info = dict(res.get("control") or {})
            if info:
                info["bypassed"] = bool(res.get("bypassed"))
                if mine:
                    self._show(child, info)
                else:
                    self.control_known.emit(child.id, info)
            elif mine:
                self._show_known()
            if not res.get("ok") and mine:
                QMessageBox.warning(self, "Not fully applied", msg)

        def err(msg):
            if self._end(tag):
                self._show_known()
            QMessageBox.critical(self, "Could not change it", f"{child.name}: {msg}")
            self.status.emit(msg)

        run_bg(lambda: self.remotes.get(child).set_control(state), ok, err)

    def _action(self, key):
        if not self.child or self.busy:
            return
        child = self.child
        title, question, detail = ACTIONS[key]
        r = QMessageBox.question(self, title, question.format(name=child.name) + "\n\n" +
                                 detail.format(name=child.name),
                                 QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if r != QMessageBox.Yes:
            return
        tag = self._begin()
        self.status.emit(f"{title}: asking {child.name}'s PC…")

        def call():
            remote = self.remotes.get(child)
            return remote.log_child_out() if key == "logout" else remote.power(key)

        def ok(res):
            self._end(tag)
            self.status.emit(f"{child.name}: {res.get('message', '')}")
            if not res.get("ok"):
                QMessageBox.warning(self, title, f"{child.name}: {res.get('message', '')}")

        def err(msg):
            self._end(tag)
            QMessageBox.critical(self, title, f"{child.name}: {msg}")
            self.status.emit(msg)

        run_bg(call, ok, err)
