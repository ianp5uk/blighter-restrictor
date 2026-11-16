# -----------------------------------------------------------------------------
# Blighter Restrictor - "Laptop" tab (live configuration and health).
#
# Purpose: show exactly what is in force on the child's laptop, read back
# from the laptop itself (not what the app last sent): the health checks
# (system, Squid running, firewall active, proxy locked, which user is
# filtered, whether the child is an administrator) and the raw files -
# generated Squid rules, allow/block lists, squid.conf and the firewall
# rules.  "Reload Squid" re-reads the configuration on demand.
# Ubuntu and Windows laptops report the same fields; on Windows the
# firewall covers the whole laptop rather than only the child's account.
#
# Copyright (C) 2026 Ways Property
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
                               QPlainTextEdit, QPushButton, QTabWidget,
                               QVBoxLayout, QWidget)

from .shared import ADMIN_WARNING, domains, same_user
from .workers import run_bg

MODE_NAMES = {domains.MODE_BLOCKLIST: "Allow all, block some",
              domains.MODE_ALLOWLIST: "Block all, allow some"}


def _flag(ok, yes="Yes", no="No"):
    colour = "#27ae60" if ok else "#c0392b"
    return f"<span style='color:{colour}'><b>{yes if ok else no}</b></span>"


class LaptopTab(QWidget):
    status = Signal(str)

    def __init__(self, remotes, parent=None):
        super().__init__(parent)
        self.remotes = remotes
        self.child = None

        self.fields = {}
        form = QFormLayout()
        for key, label in (("platform", "Laptop system"), ("child_user", "Filtered user"),
                           ("child_is_admin", "Child is administrator"), ("mode", "Mode in force"),
                           ("squid_running", "Squid running"), ("squid_version", "Squid version"),
                           ("squid_conf_managed", "squid.conf managed"),
                           ("firewall_active", "Firewall active"), ("voice_udp", "Discord voice allowed"),
                           ("proxy_locked", "Desktop proxy locked"), ("helper_version", "Helper version")):
            self.fields[key] = QLabel("-")
            form.addRow(label + ":", self.fields[key])
        self.warning = QLabel("")
        self.warning.setWordWrap(True)
        self.warning.setStyleSheet("color:#c0392b")
        form.addRow(self.warning)
        health = QGroupBox("Laptop health")
        health.setLayout(form)

        mono = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        self.texts = {}
        self.files = QTabWidget()
        for key, label in (("rules_conf", "Rules in force"), ("allow", "Allow list"),
                           ("block", "Block list"), ("squid_conf", "squid.conf"),
                           ("firewall_rules", "Firewall")):
            t = QPlainTextEdit(readOnly=True)
            t.setFont(mono)
            self.texts[key] = t
            self.files.addTab(t, label)

        self.btn_refresh = QPushButton("Refresh")
        self.btn_reload = QPushButton("Reload Squid")
        self.btn_reload.setToolTip("Check squid.conf and make Squid re-read it")
        self.btn_refresh.clicked.connect(self.refresh)
        self.btn_reload.clicked.connect(self.reload_squid)
        btns = QHBoxLayout()
        btns.addWidget(self.btn_refresh)
        btns.addWidget(self.btn_reload)
        btns.addStretch()

        lay = QVBoxLayout(self)
        lay.addLayout(btns)
        lay.addWidget(health)
        lay.addWidget(self.files, 1)
        self._enable(False)

    def _enable(self, on):
        self.btn_refresh.setEnabled(on)
        self.btn_reload.setEnabled(on)

    def set_child(self, child):
        self.child = child
        for f in self.fields.values():
            f.setText("-")
        self.warning.setText("")
        for t in self.texts.values():
            t.setPlainText("")
        self._enable(child is not None)

    def refresh(self):
        if not self.child:
            return
        child = self.child
        self.status.emit(f"Reading configuration from {child.name}'s laptop…")

        def job():
            r = self.remotes.get(child)
            return r.status(), r.get()

        def ok(res):
            st, cfg = res
            if child is not self.child:
                return
            f = self.fields
            win = st.get("platform") == "windows"
            f["platform"].setText(st.get("os_version") or ("Windows" if win else "Ubuntu"))
            f["child_user"].setText(f"<b>{st.get('child_user')}</b>" + (
                "  (Windows: the firewall filters every account on this laptop)" if win else "") + (
                "" if same_user(st.get("child_user"), child.child_user, st.get("platform")) else
                f"  <span style='color:#c0392b'>(app expects '{child.child_user}')</span>"))
            adm = st.get("child_is_admin")
            f["child_is_admin"].setText("-" if adm is None else _flag(not adm, yes="No", no="YES"))
            notes = []
            if st.get("paused"):
                notes.append("Filtering is PAUSED on this laptop (Pause Blighter Child.cmd) - the "
                             "child has normal internet access until 'Resume Blighter Child.cmd' is run.")
            if adm:
                notes.append(ADMIN_WARNING)
            if win and st.get("network_profile") and "Private" not in st.get("network_profile", ""):
                notes.append("Windows does not call the laptop's current network 'Private', so the "
                             "app may not reach it next time.  Set the home Wi-Fi to Private in "
                             "Windows' network settings.")
            notes += [w for w in st.get("warnings", []) if "ADMINISTRATOR" not in w]
            self.warning.setText("\n\n".join(notes))
            f["mode"].setText(MODE_NAMES.get(cfg.get("mode"), cfg.get("mode")))
            f["squid_running"].setText(_flag(st.get("squid_running")))
            f["squid_version"].setText(st.get("squid_version", "?"))
            f["squid_conf_managed"].setText(_flag(st.get("squid_conf_managed")))
            f["firewall_active"].setText(_flag(st.get("firewall_active"), no=(
                "No - PAUSED" if st.get("paused") else "No - child can bypass Squid")))
            f["voice_udp"].setText("Yes" if st.get("voice_udp") == "yes" else "No")
            f["proxy_locked"].setText(_flag(st.get("proxy_locked")) + (
                "  (browser policies; Windows proxy page locked)" if win else ""))
            f["helper_version"].setText(st.get("helper_version", "?"))
            self.texts["rules_conf"].setPlainText(cfg.get("rules_conf", ""))
            self.texts["allow"].setPlainText("\n".join(cfg.get("allow", [])))
            self.texts["block"].setPlainText("\n".join(cfg.get("block", [])))
            self.texts["squid_conf"].setPlainText(cfg.get("squid_conf", ""))
            self.texts["firewall_rules"].setPlainText(st.get("firewall_rules", ""))
            self.status.emit(f"Configuration read from {child.name}'s laptop.")

        run_bg(job, ok, self.status.emit)

    def reload_squid(self):
        if not self.child:
            return
        child = self.child

        def ok(res):
            msg = res.get("message", "")
            if res.get("errors"):
                msg += ": " + " ".join(res["errors"])[:300]
            self.status.emit(f"{child.name}: {msg}")
            self.refresh()

        run_bg(lambda: self.remotes.get(child).reload(), ok, self.status.emit)
