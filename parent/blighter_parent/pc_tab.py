# -----------------------------------------------------------------------------
# Blighter Restrictor - "PC" tab (live configuration and health).
#
# Purpose: show exactly what is in force on the child's PC, read back
# from the PC itself (not what the app last sent): the health checks
# (system, Squid running, firewall active, proxy locked, which user is
# filtered, whether the child is an administrator) and the raw files -
# generated Squid rules, allow/block lists, squid.conf and the firewall
# rules.  "Reload Squid" re-reads the configuration on demand.
# "Pause filtering" allows every website; "Resume filtering" switches the
# rules back on.  While paused the web traffic still goes through Squid, so
# activity is still recorded (since 1.2.6 on both Ubuntu and Windows).  A red
# banner here (and "- PAUSED" in the children list) says so.  If Blighter was
# switched off on the PC itself ("Pause Blighter Child" on Windows, for
# troubleshooting), the banner says that nothing is recorded; Resume
# filtering switches it back on.  A PC with an older Blighter child (before
# 1.2.6) stops recording while paused: the app warns before pausing it.
# Buttons are greyed out while a request to the PC is running.
# Ubuntu and Windows PCs report the same fields; on Windows the
# firewall covers the whole PC rather than only the child's account.
# The settings files are read first and shown at once; the slower health
# checks follow in a second request.
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
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (QFormLayout, QGroupBox, QHBoxLayout, QLabel,
                               QMessageBox, QPlainTextEdit, QPushButton, QTabWidget,
                               QVBoxLayout, QWidget)

from .shared import ADMIN_WARNING, domains, same_user
from .workers import run_bg

MODE_NAMES = {domains.MODE_BLOCKLIST: "Allow all, block some",
              domains.MODE_ALLOWLIST: "Block all, allow some"}


def _flag(ok, yes="Yes", no="No"):
    colour = "#27ae60" if ok else "#c0392b"
    return f"<span style='color:{colour}'><b>{yes if ok else no}</b></span>"


def _older(version, than):
    try:
        return tuple(int(x) for x in version.split(".")[:3]) < than
    except (AttributeError, ValueError):
        return False


class PCTab(QWidget):
    status = Signal(str)
    paused_known = Signal(str, bool)     # child id, paused?

    def __init__(self, remotes, parent=None):
        super().__init__(parent)
        self.remotes = remotes
        self.child = None
        self.busy = False
        self.paused = None
        self.helper_version = None

        self.fields = {}
        form = QFormLayout()
        for key, label in (("platform", "PC system"), ("child_user", "Filtered user"),
                           ("child_is_admin", "Child is administrator"), ("mode", "Mode in force"),
                           ("squid_running", "Squid running"), ("squid_version", "Squid version"),
                           ("squid_conf_managed", "squid.conf managed"),
                           ("firewall_active", "Firewall active"), ("voice_udp", "Discord allowed"), ("home_net", "Home network access"),
                           ("proxy_locked", "Desktop proxy locked"), ("helper_version", "Helper version")):
            self.fields[key] = QLabel("-")
            form.addRow(label + ":", self.fields[key])
        self.warning = QLabel("")
        self.warning.setWordWrap(True)
        self.warning.setStyleSheet("color:#c0392b")
        form.addRow(self.warning)
        health = QGroupBox("PC health")
        health.setLayout(form)

        mono = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        self.texts = {}
        self.files = QTabWidget()
        for key, label in (("rules_conf", "Squid rules in force"), ("allow", "Allow list"),
                           ("block", "Block list"), ("squid_conf", "squid.conf"),
                           ("firewall_rules", "Firewall")):
            t = QPlainTextEdit(readOnly=True)
            t.setFont(mono)
            self.texts[key] = t
            self.files.addTab(t, label)

        self.btn_refresh = QPushButton("Refresh")
        self.btn_reload = QPushButton("Reload Squid")
        self.btn_reload.setToolTip("Check squid.conf and make Squid re-read it")
        self.btn_pause = QPushButton("Pause filtering")
        self.btn_pause.setToolTip("Allow every website on this PC until you press Resume.  "
                                  "Activity is still recorded.")
        self.btn_resume = QPushButton("Resume filtering")
        self.btn_resume.setToolTip("Switch filtering back on")
        self.btn_refresh.clicked.connect(self.refresh)
        self.btn_reload.clicked.connect(self.reload_squid)
        self.btn_pause.clicked.connect(lambda: self.set_paused(True))
        self.btn_resume.clicked.connect(lambda: self.set_paused(False))
        btns = QHBoxLayout()
        btns.addWidget(self.btn_refresh)
        btns.addWidget(self.btn_reload)
        btns.addStretch()
        btns.addWidget(self.btn_pause)
        btns.addWidget(self.btn_resume)

        self.banner = QLabel("")
        self.banner.setWordWrap(True)
        self.banner.setStyleSheet("background:#c0392b; color:white; padding:8px; font-weight:bold;")
        self.banner.hide()

        lay = QVBoxLayout(self)
        lay.addLayout(btns)
        lay.addWidget(self.banner)
        lay.addWidget(health)
        lay.addWidget(self.files, 1)
        self._enable(False)

    def _enable(self, on):
        on = on and self.child is not None and not self.busy
        self.btn_refresh.setEnabled(on)
        self.btn_reload.setEnabled(on)
        # Until the PC has said whether it is paused, both are offered.
        self.btn_pause.setEnabled(on and self.paused is not True)
        self.btn_resume.setEnabled(on and self.paused is not False)

    def _set_busy(self, on):
        self.busy = on
        self._enable(True)

    def _show_paused(self, child, paused, bypassed=False):
        self.paused = paused
        self.banner.setVisible(bool(paused))
        if paused and not bypassed and _older(self.helper_version, (1, 2, 6)):
            self.banner.setText(f"FILTERING IS PAUSED on {child.name}'s PC - {child.name} has OPEN internet "
                                f"access.  This PC has an older Blighter child ({self.helper_version}), so "
                                "activity may not be recorded while paused.  Update it to 1.2.6.")
        elif bypassed:
            self.banner.setText(f"BLIGHTER IS SWITCHED OFF on {child.name}'s PC itself ('Pause Blighter Child' "
                                f"was run on it) - {child.name} has OPEN internet access and NO activity is "
                                "recorded.  Press Resume filtering to switch it back on.")
        elif paused:
            self.banner.setText(f"FILTERING IS PAUSED on {child.name}'s PC - every website is allowed until you "
                                "press Resume filtering.  Activity is still recorded.")
        self.paused_known.emit(child.id, bool(paused))
        self._enable(True)

    def set_child(self, child):
        self.child = child
        self.paused = None
        self.helper_version = None
        self.banner.hide()
        for f in self.fields.values():
            f.setText("-")
        self.warning.setText("")
        for t in self.texts.values():
            t.setPlainText("")
        self._enable(child is not None)

    def refresh(self):
        # Two steps so the parent is not left staring at an empty tab: the
        # settings files ("get") come back in a second or two; the health
        # checks ("status") can take longer on Windows, so they follow.
        if not self.child:
            return
        if self.busy:
            return
        child = self.child
        self._set_busy(True)
        self.status.emit(f"Reading settings from {child.name}'s PC…")
        for k in ("platform", "child_user", "child_is_admin", "squid_running", "squid_version",
                  "squid_conf_managed", "firewall_active", "voice_udp", "home_net", "proxy_locked",
                  "helper_version"):
            self.fields[k].setText("…")

        def got_cfg(cfg):
            if child is not self.child:
                return
            self.fields["mode"].setText(MODE_NAMES.get(cfg.get("mode"), cfg.get("mode")))
            self.texts["rules_conf"].setPlainText(cfg.get("rules_conf", ""))
            self.texts["allow"].setPlainText("\n".join(cfg.get("allow", [])))
            self.texts["block"].setPlainText("\n".join(cfg.get("block", [])))
            self.texts["squid_conf"].setPlainText(cfg.get("squid_conf", ""))
            self.texts["firewall_rules"].setPlainText("Checking…")
            self.status.emit(f"Settings read.  Checking {child.name}'s PC health "
                             "(firewall, Squid, accounts) - this can take up to a minute…")
            run_bg(lambda: self.remotes.get(child).status(), got_status, failed)

        def failed(msg):
            self._set_busy(False)
            if child is self.child:
                for f in self.fields.values():
                    if f.text() == "…":
                        f.setText("-")
            self.status.emit(msg)

        def got_status(st):
            self._set_busy(False)
            if child is not self.child:
                return
            self.helper_version = st.get("helper_version")
            self._show_paused(child, bool(st.get("paused")), bool(st.get("bypassed")))
            f = self.fields
            win = st.get("platform") == "windows"
            f["platform"].setText(st.get("os_version") or ("Windows" if win else "Ubuntu"))
            f["child_user"].setText(f"<b>{st.get('child_user')}</b>" + (
                "  (Windows: the firewall filters every account on this PC)" if win else "") + (
                "" if same_user(st.get("child_user"), child.child_user, st.get("platform")) else
                f"  <span style='color:#c0392b'>(app expects '{child.child_user}')</span>"))
            adm = st.get("child_is_admin")
            f["child_is_admin"].setText("-" if adm is None else _flag(not adm, yes="No", no="YES"))
            notes = []
            if adm:
                notes.append(ADMIN_WARNING)
            if win and st.get("network_profile") and "Private" not in st.get("network_profile", ""):
                notes.append("Windows does not call the PC's current network 'Private', so the "
                             "app may not reach it next time.  Set the home Wi-Fi to Private in "
                             "Windows' network settings.")
            notes += [w for w in st.get("warnings", []) if "ADMINISTRATOR" not in w]
            self.warning.setText("\n\n".join(notes))
            f["squid_running"].setText(_flag(st.get("squid_running")))
            f["squid_version"].setText(st.get("squid_version", "?"))
            f["squid_conf_managed"].setText(_flag(st.get("squid_conf_managed")))
            f["firewall_active"].setText(_flag(st.get("firewall_active"), no=(
                "No - switched off on the PC" if st.get("bypassed") else "No - child can bypass Squid")))
            f["voice_udp"].setText("Yes" if st.get("voice_udp") == "yes" else "No")
            h = st.get("home_net")
            if h is None:
                f["home_net"].setText("- (PC older than 1.2.3)")
            elif h.get("allowed") and h.get("subnets"):
                f["home_net"].setText("Yes - " + ", ".join(h["subnets"]) + (f"  ({h['name']})" if h.get("name") else ""))
            elif h.get("allowed"):
                f["home_net"].setText("On, but no home network set (Filters tab)")
            else:
                f["home_net"].setText("No")
            f["proxy_locked"].setText(_flag(st.get("proxy_locked")) + (
                "  (browser policies; Windows proxy page locked)" if win else ""))
            f["helper_version"].setText(st.get("helper_version", "?"))
            self.texts["firewall_rules"].setPlainText(st.get("firewall_rules", ""))
            self.status.emit(f"Configuration read from {child.name}'s PC.")

        run_bg(lambda: self.remotes.get(child).get(), got_cfg, failed)

    def reload_squid(self):
        if not self.child or self.busy:
            return
        child = self.child
        self._set_busy(True)

        def ok(res):
            self._set_busy(False)
            msg = res.get("message", "")
            if res.get("errors"):
                msg += ": " + " ".join(res["errors"])[:300]
            self.status.emit(f"{child.name}: {msg}")
            self.refresh()

        def err(msg):
            self._set_busy(False)
            self.status.emit(msg)

        run_bg(lambda: self.remotes.get(child).reload(), ok, err)

    def set_paused(self, pause):
        """Pause (open access) or resume filtering on the selected child's PC."""
        if not self.child or self.busy:
            return
        child = self.child
        if pause and _older(self.helper_version, (1, 2, 6)):
            r = QMessageBox.question(
                self, "Pause filtering",
                f"{child.name}'s PC has an older Blighter child ({self.helper_version}).  On it, pausing "
                "also stops activity being recorded.  Update the PC to Blighter 1.2.6 to keep recording "
                "while paused.\n\nPause anyway?")
            if r != QMessageBox.Yes:
                return
        self._set_busy(True)
        self.status.emit(f"{'Pausing' if pause else 'Resuming'} filtering on {child.name}'s PC "
                         "(this can take up to a minute)…")

        def ok(res):
            self._set_busy(False)
            msg = res.get("message", "")
            if res.get("errors"):
                msg += "  Problems: " + " ".join(res["errors"])[:300]
            self.status.emit(f"{child.name}: {msg}")
            if child is self.child:
                self._show_paused(child, bool(res.get("paused")), bool(res.get("bypassed")))
                self.refresh()

        def err(msg):
            self._set_busy(False)
            self.status.emit(msg)

        run_bg(lambda: (self.remotes.get(child).pause() if pause else self.remotes.get(child).resume()),
               ok, err)
