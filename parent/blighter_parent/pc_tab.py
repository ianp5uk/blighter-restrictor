# -----------------------------------------------------------------------------
# Blighter Restrictor - "PC" tab (live configuration and health).
#
# Purpose: show exactly what is in force on the child's PC, read back
# from the PC itself (not what the app last sent): the health checks
# (system, Squid running, firewall active, proxy locked, which user is
# filtered, whether the child is an administrator) and the raw files -
# generated Squid rules, allow/block lists, squid.conf and the firewall
# rules.  "Reload Squid" re-reads the configuration on demand.
# "Mode in force" also shows the Controls tab's switch when it is not
# Filtered (Block all / Open all, since 1.3.0, which replaced the Pause /
# Resume buttons that were here).
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
                               QPlainTextEdit, QPushButton, QTabWidget,
                               QVBoxLayout, QWidget)

from .shared import ADMIN_WARNING, domains, same_user
from .workers import run_bg

MODE_NAMES = {domains.MODE_BLOCKLIST: "Allow all, block some",
              domains.MODE_ALLOWLIST: "Block all, allow some"}


def _flag(ok, yes="Yes", no="No"):
    colour = "#27ae60" if ok else "#c0392b"
    return f"<span style='color:{colour}'><b>{yes if ok else no}</b></span>"


class PCTab(QWidget):
    status = Signal(str)
    control_known = Signal(str, dict)    # child id, {"state", "by", "since", "bypassed"}

    def __init__(self, remotes, parent=None):
        super().__init__(parent)
        self.remotes = remotes
        self.child = None
        self.busy = False
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
        on = on and self.child is not None and not self.busy
        self.btn_refresh.setEnabled(on)
        self.btn_reload.setEnabled(on)

    def _set_busy(self, on):
        self.busy = on
        self._enable(True)

    def set_child(self, child):
        self.child = child
        self.helper_version = None
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
            mode = MODE_NAMES.get(cfg.get("mode"), cfg.get("mode"))
            ctl = (cfg.get("control") or {}).get("state", domains.CONTROL_FILTERED)
            if ctl != domains.CONTROL_FILTERED:
                mode = (f"<span style='color:#c0392b'><b>{domains.CONTROL_NAMES.get(ctl, ctl)}</b></span>"
                        f"  (Controls tab; the filters are kept: {mode})")
            self.fields["mode"].setText(mode)
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
            if st.get("control"):
                self.control_known.emit(child.id, dict(st["control"], bypassed=bool(st.get("bypassed"))))
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
