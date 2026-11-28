# -----------------------------------------------------------------------------
# Blighter Restrictor - "Rules" tab.
#
# Purpose: show and edit one child's filtering mode and domain lists, check
# them as you type (same rules as the PC), and apply them.  Applying
# sends the lists to the PC, which checks them with Squid and reloads,
# or restores the previous rules if Squid rejects them.
#   Mode "Allow all, block some"  -> only the Block list is used
#   Mode "Block all, allow some"  -> only the Allow list is used
# Both lists are always kept, so switching mode never loses either one.
# "Allow Discord" is a separate per-child switch (Discord's web addresses and,
# for voice/video calls, UDP 50000-65535 in the PC's firewall).  It wins
# over both lists, and is applied with them by "Apply to PC".  Discord
# lines typed into a list are pointed out, as they have no effect.
# "Allow home network access" (with the home network's subnet(s)) lets the
# PC reach printers, NAS drives and other home devices: Blighter controls
# internet access only.  "Use current network" asks the PC which network
# it is on now.  "Block Opera downloads" (on by default) stops Opera being
# downloaded: its built-in VPN can't be switched off by policy.  All three
# switches are applied with the lists.  Until the PC has answered, their
# hover text says so (it only says "update" if the PC answered without
# that setting).
# Switching PCs: every read or apply is tagged with the PC and a sequence
# number.  Selecting another PC starts a new sequence and clears "busy", so
# a slow or offline PC can't leave the tab stuck; replies that arrive after
# the switch are ignored for the tab (an apply's result is still reported).
#
# Copyright (C) 2026 Ian Packer
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version.  It is distributed WITHOUT ANY WARRANTY; see the
# LICENSE file or <https://www.gnu.org/licenses/> for details.
# -----------------------------------------------------------------------------

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QMessageBox, QPlainTextEdit,
                               QPushButton, QRadioButton, QSplitter, QVBoxLayout,
                               QWidget)

from .shared import domains
from .workers import run_bg

HELP = ("One domain per line.  <b>.example.com</b> = the site and all its subdomains; "
        "<b>example.com</b> = that exact name only.  Lines starting with # are comments.  "
        "<b>*.example.com</b> and pasted web addresses are converted automatically.")


DISCORD_TIP = ("Discord is controlled here, not by the lists.  Takes effect when you "
               "press 'Apply to PC'.")
DISCORD_OLD_TIP = "This PC's Blighter child version has no Discord switch - update it to 1.2.2 or later."
OPERA_TIP = ("Blocks opera.com and Opera's download servers, so the Opera browser can't be "
             "downloaded (Opera's built-in VPN can't be switched off).  An Opera that is already "
             "installed is not removed.  Takes effect when you press 'Apply to PC'.")
OPERA_OLD_TIP = "This PC's Blighter child version has no Opera switch - update it to 1.2.4 or later."
HOME_OLD_TIP = ("This PC's Blighter child version has no home network setting - "
                "update it to 1.2.3 or later.")
WAIT_TIP = "Waiting for the PC to answer…"
FAIL_TIP = "Couldn't read this PC's settings - press 'Reload from PC' to try again."
HOME_TIP = ("Lets the PC reach the home network directly: printers, NAS drives and other home "
            "devices.  Blighter controls internet access only.  Give the home network's subnet(s), "
            "e.g. 192.168.1.0/24, separated by spaces.")


class RulesTab(QWidget):
    status = Signal(str)

    def __init__(self, remotes, parent=None):
        super().__init__(parent)
        self.remotes = remotes
        self.child = None
        self.loaded = None  # (mode, allow_text, block_text, discord, home, opera) as last read from the PC
        self.discord_supported = False
        self.opera_supported = False
        self.home_supported = False
        self.home_name = self.loaded_home_name = ""
        self.busy = False
        self._seq = 0       # bumped on every PC switch and every request

        self.rb_block = QRadioButton("Allow all, block some")
        self.rb_allow = QRadioButton("Block all, allow some")
        self.mode_group = QButtonGroup(self)
        self.mode_group.addButton(self.rb_block)
        self.mode_group.addButton(self.rb_allow)
        self.rb_block.setChecked(True)
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("<b>Mode:</b>"))
        mode_row.addWidget(self.rb_block)
        mode_row.addWidget(self.rb_allow)
        mode_row.addSpacing(24)
        self.cb_discord = QCheckBox("Allow Discord (text, voice and video calls)")
        self.cb_discord.setToolTip(DISCORD_TIP)
        self.cb_discord.toggled.connect(lambda *_: self._changed())
        mode_row.addWidget(self.cb_discord)
        mode_row.addSpacing(12)
        self.cb_opera = QCheckBox("Block Opera downloads")
        self.cb_opera.setToolTip(OPERA_TIP)
        self.cb_opera.toggled.connect(lambda *_: self._changed())
        mode_row.addWidget(self.cb_opera)
        mode_row.addStretch()
        self.dirty_label = QLabel("")
        mode_row.addWidget(self.dirty_label)

        self.cb_home = QCheckBox("Allow home network access (printers, NAS…):")
        self.cb_home.setToolTip(HOME_TIP)
        self.home_edit = QLineEdit()
        self.home_edit.setPlaceholderText("e.g. 192.168.1.0/24")
        self.home_edit.setToolTip(HOME_TIP)
        self.home_label = QLabel("")
        self.btn_home = QPushButton("Use current network")
        self.btn_home.setToolTip("Ask the PC which network it is on now")
        self.cb_home.toggled.connect(lambda *_: self._changed())
        self.home_edit.textChanged.connect(lambda *_: self._changed())
        self.btn_home.clicked.connect(self.use_current_network)
        home_row = QHBoxLayout()
        home_row.addWidget(self.cb_home)
        home_row.addWidget(self.home_edit, 1)
        home_row.addWidget(self.home_label)
        home_row.addWidget(self.btn_home)

        mono = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        self.block_edit = QPlainTextEdit()
        self.allow_edit = QPlainTextEdit()
        for e in (self.block_edit, self.allow_edit):
            e.setFont(mono)
            e.setLineWrapMode(QPlainTextEdit.NoWrap)
            e.setPlaceholderText(".example.com")
            e.textChanged.connect(self._changed)
        self.block_box = QGroupBox("Block list")
        QVBoxLayout(self.block_box).addWidget(self.block_edit)
        self.allow_box = QGroupBox("Allow list")
        QVBoxLayout(self.allow_box).addWidget(self.allow_edit)
        lists = QHBoxLayout()
        lists.addWidget(self.block_box)
        lists.addWidget(self.allow_box)
        lists_w = QWidget()
        lists_w.setLayout(lists)

        self.issues = QListWidget()
        self.issues.setMaximumHeight(110)
        split = QSplitter(Qt.Vertical)
        split.addWidget(lists_w)
        split.addWidget(self.issues)
        split.setStretchFactor(0, 5)
        split.setStretchFactor(1, 1)

        help_label = QLabel(HELP)
        help_label.setWordWrap(True)

        self.btn_reload = QPushButton("Reload from PC")
        self.btn_tidy = QPushButton("Tidy lists")
        self.btn_tidy.setToolTip("Apply the automatic conversions and remove duplicates in the editor")
        self.btn_revert = QPushButton("Revert")
        self.btn_apply = QPushButton("Apply to PC")
        self.btn_apply.setDefault(True)
        self.btn_reload.clicked.connect(self.reload)
        self.btn_tidy.clicked.connect(self.tidy)
        self.btn_revert.clicked.connect(self.revert)
        self.btn_apply.clicked.connect(self.apply)
        btns = QHBoxLayout()
        btns.addWidget(self.btn_reload)
        btns.addWidget(self.btn_tidy)
        btns.addStretch()
        btns.addWidget(self.btn_revert)
        btns.addWidget(self.btn_apply)

        lay = QVBoxLayout(self)
        lay.addLayout(mode_row)
        lay.addLayout(home_row)
        lay.addWidget(help_label)
        lay.addWidget(split, 1)
        lay.addLayout(btns)

        self.mode_group.buttonToggled.connect(lambda *_: self._changed())
        self._timer = QTimer(self, singleShot=True, interval=300)
        self._timer.timeout.connect(self._validate)
        self._set_enabled(False)

    # ---- helpers ------------------------------------------------------------------
    def mode(self):
        return domains.MODE_ALLOWLIST if self.rb_allow.isChecked() else domains.MODE_BLOCKLIST

    def _current(self):
        return (self.mode(), self.allow_edit.toPlainText().strip(), self.block_edit.toPlainText().strip(),
                self.cb_discord.isChecked(), (self.cb_home.isChecked(), " ".join(self.home_edit.text().split())),
                self.cb_opera.isChecked())

    def is_dirty(self):
        return self.loaded is not None and self._current() != self.loaded

    def _set_enabled(self, on):
        for w in (self.rb_block, self.rb_allow, self.block_edit, self.allow_edit,
                  self.btn_reload, self.btn_tidy, self.btn_revert, self.btn_apply):
            w.setEnabled(on)
        self.cb_discord.setEnabled(on and self.discord_supported)
        self.cb_opera.setEnabled(on and self.opera_supported)
        for w in (self.cb_home, self.home_edit, self.btn_home):
            w.setEnabled(on and self.home_supported)

    def _changed(self):
        allow_mode = self.rb_allow.isChecked()
        self.block_box.setTitle("Block list" + ("  (not used in this mode)" if allow_mode else "  - in use"))
        self.allow_box.setTitle("Allow list" + ("  - in use" if allow_mode else "  (not used in this mode)"))
        self.dirty_label.setText("<span style='color:#d35400'><b>Unsaved changes</b></span>"
                                 if self.is_dirty() else "")
        self._timer.start()

    def _validate(self):
        self.issues.clear()
        errors = []
        for name, edit in (("Block", self.block_edit), ("Allow", self.allow_edit)):
            _, notes, errs = domains.clean_list(edit.toPlainText().splitlines())
            for n in notes:
                self.issues.addItem(f"{name} list - {n}  (Tidy lists to fix)")
            for e in errs:
                errors.append(e)
                self.issues.addItem(f"ERROR {name} list - {e}")
            if self.discord_supported:
                for line in domains.entries_only(domains.clean_list(edit.toPlainText().splitlines())[0]):
                    if domains.is_discord(line):
                        self.issues.addItem(f"Note: {name} list - '{line}' is Discord, which the 'Allow Discord' "
                                            "switch controls; this line has no effect.")
        if self.home_supported:
            nets, errs, warns = domains.clean_subnets(self.home_edit.text().replace(",", " ").split())
            for e in errs:
                errors.append(e)
                self.issues.addItem(f"ERROR Home network - {e}")
            for w in warns:
                self.issues.addItem(f"Warning: home network - {w}")
            if self.cb_home.isChecked() and not nets and not errs:
                self.issues.addItem("Note: home network access is on but no home network is given - "
                                    "press 'Use current network' or type its subnet.")
        if self.mode() == domains.MODE_ALLOWLIST and not domains.entries_only(
                domains.clean_list(self.allow_edit.toPlainText().splitlines())[0]):
            self.issues.addItem("Note: the allow list is empty - every site will be blocked.")
        return not errors

    def _set_tips(self, tip_discord, tip_home, tip_opera):
        self.cb_discord.setToolTip(tip_discord)
        self.cb_opera.setToolTip(tip_opera)
        for w in (self.cb_home, self.home_edit, self.btn_home):
            w.setToolTip(tip_home)

    def _fill(self, mode, allow_lines, block_lines, discord=None, home=None, opera=None, answered=True):
        """Show settings.  answered=False: the PC hasn't replied yet (blank tab)."""
        for e in (self.block_edit, self.allow_edit):
            e.blockSignals(True)
        self.allow_edit.setPlainText("\n".join(allow_lines).strip())
        self.block_edit.setPlainText("\n".join(block_lines).strip())
        for e in (self.block_edit, self.allow_edit):
            e.blockSignals(False)
        (self.rb_allow if mode == domains.MODE_ALLOWLIST else self.rb_block).setChecked(True)
        self.discord_supported = discord is not None
        self.cb_discord.blockSignals(True)
        self.cb_discord.setChecked(bool(discord) if discord is not None else True)
        self.cb_discord.blockSignals(False)
        self.opera_supported = opera is not None
        self.cb_opera.blockSignals(True)
        self.cb_opera.setChecked(bool(opera) if opera is not None else True)
        self.cb_opera.blockSignals(False)
        self.home_supported = home is not None
        for w in (self.cb_home, self.home_edit):
            w.blockSignals(True)
        self.cb_home.setChecked(bool(home.get("allowed", True)) if home else False)
        self.home_edit.setText(" ".join(home.get("subnets", [])) if home else "")
        for w in (self.cb_home, self.home_edit):
            w.blockSignals(False)
        self.home_name = self.loaded_home_name = (home or {}).get("name", "")
        self._home_label()
        if answered:
            self._set_tips(DISCORD_TIP if self.discord_supported else DISCORD_OLD_TIP,
                           HOME_TIP if self.home_supported else HOME_OLD_TIP,
                           OPERA_TIP if self.opera_supported else OPERA_OLD_TIP)
        else:
            self._set_tips(WAIT_TIP, WAIT_TIP, WAIT_TIP)
        self.loaded = self._current()
        self._changed()

    # ---- requests -------------------------------------------------------------
    def _begin(self):
        """Start a request: mark busy and return its (child, sequence) tag."""
        self._seq += 1
        self.busy = True
        return self.child, self._seq

    def _current_tag(self, tag):
        """True if a reply with this tag still belongs to what the tab shows."""
        return tag[0] is self.child and tag[1] == self._seq

    def _end(self, tag):
        """Finish a request: clear busy unless a newer one has started."""
        if self._current_tag(tag):
            self.busy = False
            return True
        return False

    # ---- public -------------------------------------------------------------------
    def set_child(self, child):
        # New sequence: any request still running for the previous PC is
        # ignored when it answers, and can't keep the tab busy.
        self._seq += 1
        self.busy = False
        self.child = child
        self.loaded = None
        self._fill(domains.MODE_BLOCKLIST, [], [], answered=False)
        self.loaded = None
        self._set_enabled(False)
        if child:
            self.reload()

    def reload(self):
        if not self.child or self.busy:
            return
        child = self.child
        tag = self._begin()
        self.status.emit(f"Reading rules from {child.name}'s PC…")

        def ok(data):
            if not self._end(tag):
                return
            self._fill(data.get("mode"), data.get("allow", []), data.get("block", []), data.get("discord"),
                       data.get("home_net"), data.get("opera"))
            self._set_enabled(True)
            self.status.emit(f"Rules loaded from {child.name}'s PC.")

        def err(msg):
            if not self._end(tag):
                return
            self.status.emit(msg)
            self.issues.clear()
            self.issues.addItem("ERROR " + msg)
            self.btn_reload.setEnabled(True)    # so 'Reload from PC' can try again
            if self.loaded is None:
                self._set_tips(FAIL_TIP, FAIL_TIP, FAIL_TIP)

        run_bg(lambda: self.remotes.get(child).get(), ok, err)

    def tidy(self):
        for edit in (self.block_edit, self.allow_edit):
            lines, _, errs = domains.clean_list(edit.toPlainText().splitlines())
            if errs:
                # Keep invalid lines so the user can see and fix them.
                continue
            edit.setPlainText("\n".join(lines))

    def revert(self):
        if self.loaded:
            mode, allow, block, discord, (h_on, h_nets), opera = self.loaded
            self._fill(mode, allow.splitlines(), block.splitlines(),
                       discord if self.discord_supported else None,
                       {"allowed": h_on, "subnets": h_nets.split(), "name": self.loaded_home_name}
                       if self.home_supported else None,
                       opera if self.opera_supported else None)

    def add_domain(self, which, domain):
        """Called from the Activity tab: which is 'allow' or 'block'."""
        edit = self.allow_edit if which == "allow" else self.block_edit
        lines = edit.toPlainText().rstrip().splitlines()
        if domain in (l.strip() for l in lines):
            return f"{domain} is already in the {which} list."
        lines.append(domain)
        edit.setPlainText("\n".join(lines))
        return f"Added {domain} to the {which} list - press 'Apply to PC' to make it live."

    def apply(self):
        if not self.child or self.busy:
            return
        if not self._validate():
            QMessageBox.warning(self, "Fix the lists first",
                                "Some lines are not valid domains - see the messages under the lists.")
            return
        child = self.child
        allow = self.allow_edit.toPlainText().splitlines()
        block = self.block_edit.toPlainText().splitlines()
        mode = self.mode()
        discord = self.cb_discord.isChecked() if self.discord_supported else None
        opera = self.cb_opera.isChecked() if self.opera_supported else None
        home = None
        if self.home_supported:
            home = {"allowed": self.cb_home.isChecked(),
                    "subnets": self.home_edit.text().replace(",", " ").split(),
                    "name": self.home_name}
        tag = self._begin()
        self._set_enabled(False)
        self.status.emit(f"Applying rules to {child.name}'s PC…")

        def ok(res):
            mine = self._end(tag)
            if mine:
                self._set_enabled(True)
            if res.get("ok"):
                if mine:
                    self._fill(res.get("mode"), res.get("allow", []), res.get("block", []),
                               res.get("discord", discord), res.get("home_net", home),
                               res.get("opera", opera))
                    for w in res.get("warnings", []):
                        self.issues.addItem("Squid: " + w)
                self.status.emit(f"{child.name}: {res.get('message')}")
            else:
                details = "\n".join(res.get("errors", []))
                QMessageBox.critical(self, "Not applied", f"{res.get('message')}\n\n{details}")
                self.status.emit(f"{child.name}: {res.get('message')}")

        def err(msg):
            if self._end(tag):
                self._set_enabled(True)
            QMessageBox.critical(self, "Could not apply", f"{child.name}: {msg}")
            self.status.emit(msg)

        run_bg(lambda: self.remotes.get(child).apply(mode, allow, block, discord, home, opera), ok, err)

    def _home_label(self):
        self.home_label.setText(f"({self.home_name})" if self.home_name else "")

    def use_current_network(self):
        """Fill in the network(s) the PC is on now (private ranges first)."""
        if not self.child or self.busy:
            return
        child = self.child
        tag = self._begin()
        self._set_enabled(False)
        self.status.emit(f"Asking {child.name}'s PC which network it is on…")

        def ok(res):
            if not self._end(tag):
                return
            self._set_enabled(True)
            nets = res.get("networks", [])
            private = [n for n in nets if n.get("private")]
            pick = private or nets
            if not pick:
                QMessageBox.information(self, "No network found",
                                        "The PC doesn't seem to be on a network right now.")
                self.status.emit(f"{child.name}: no current network found.")
                return
            self.home_edit.setText(pick[0]["subnet"])
            self.home_name = pick[0].get("name", "")
            self._home_label()
            self.cb_home.setChecked(True)
            others = ", ".join(n["subnet"] for n in nets if n is not pick[0])
            self.status.emit(f"{child.name} is on {pick[0]['subnet']}"
                             + (f" ({self.home_name})" if self.home_name else "")
                             + (f"; also {others}" if others else "")
                             + " - press 'Apply to PC' to use it.")

        def err(msg):
            if not self._end(tag):
                return
            self._set_enabled(True)
            self.status.emit(msg)

        run_bg(lambda: self.remotes.get(child).netinfo(), ok, err)
