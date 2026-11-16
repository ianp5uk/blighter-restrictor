# -----------------------------------------------------------------------------
# Blighter Restrictor - "Add / Edit child" dialog and password prompt.
#
# Purpose: enter a child's name, laptop IPv4 address, their username on the
# laptop (the account that is filtered), the admin login created by
# blighter-setup, its password (saved to the keyring) and the SSH port.
# "Test connection" logs in and asks the laptop for its status before saving.
# -----------------------------------------------------------------------------

import ipaddress
import re

from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
                               QInputDialog, QLabel, QLineEdit, QMessageBox,
                               QPushButton, QSpinBox, QVBoxLayout)

from .config_store import Child
from .remote import Remote, forget_host_key
from .workers import run_bg

_USER_RE = re.compile(r"^[a-z_][a-z0-9_.-]{0,31}$")


class ChildDialog(QDialog):
    def __init__(self, store, child=None, parent=None):
        super().__init__(parent)
        self.store = store
        self.original = child
        self.setWindowTitle("Edit child" if child else "Add child")
        self.setMinimumWidth(460)

        self.name = QLineEdit(child.name if child else "")
        self.ip = QLineEdit(child.ip if child else "")
        self.ip.setPlaceholderText("e.g. 192.168.1.50")
        self.child_user = QLineEdit(child.child_user if child else "")
        self.child_user.setPlaceholderText("the child's login name on their laptop")
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
        form.addRow("Laptop IPv4 address:", self.ip)
        form.addRow("Child's username:", self.child_user)
        form.addRow("Admin login:", self.admin_user)
        form.addRow("Admin password:", self.password)
        form.addRow("SSH port:", self.port)

        hint = QLabel("The child's username must match the one given to "
                      "<b>sudo blighter-setup</b> on the laptop.  Tip: reserve the "
                      "laptop's IP address in your router so it does not change.")
        hint.setWordWrap(True)

        self.result_label = QLabel("")
        self.result_label.setWordWrap(True)
        test = QPushButton("Test connection")
        test.clicked.connect(self._test)
        row = QHBoxLayout()
        row.addWidget(test)
        if child:
            forget = QPushButton("Forget host key")
            forget.setToolTip("Use after reinstalling the laptop's operating system")
            forget.clicked.connect(self._forget)
            row.addWidget(forget)
        row.addStretch()

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
                raise ValueError(f"{label} '{u}' is not a valid Ubuntu username.")
        if cu == au:
            raise ValueError("The child's username and the admin login must be different.")
        c = Child(name=name, ip=ip, child_user=cu, admin_user=au, port=self.port.value())
        if self.original:
            c.id = self.original.id
        pw = self.password.text() or (self.store.get_password(self.original) if self.original else "")
        if not pw:
            raise ValueError("Please enter the admin password.")
        return c, pw

    def _test(self):
        try:
            child, pw = self._collect()
        except ValueError as e:
            self.result_label.setText(f"<span style='color:#c0392b'>{e}</span>")
            return
        self.result_label.setText("Connecting…")

        def job():
            r = Remote(child, pw, self.store.known_hosts)
            try:
                return r.status()
            finally:
                r.close()

        def ok(st):
            msg = (f"<span style='color:#27ae60'><b>Connected.</b></span> "
                   f"Laptop filters user <b>{st.get('child_user')}</b>; "
                   f"{st.get('squid_version')}; Squid "
                   f"{'running' if st.get('squid_running') else '<b>NOT running</b>'}; firewall "
                   f"{'active' if st.get('firewall_active') else '<b>NOT active</b>'}.")
            if st.get("child_user") != child.child_user:
                msg += (f"<br><span style='color:#c0392b'>Warning: the laptop was set up for "
                        f"'{st.get('child_user')}', not '{child.child_user}'.</span>")
            self.result_label.setText(msg)

        run_bg(job, ok, lambda m: self.result_label.setText(f"<span style='color:#c0392b'>{m}</span>"))

    def _forget(self):
        forget_host_key(self.store.known_hosts, self.original.ip, self.original.port)
        self.result_label.setText("Host key forgotten - it will be learned again on next connection.")

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


def ask_password(parent, store, child):
    pw, ok = QInputDialog.getText(parent, "Password needed",
                                  f"Admin password for {child.name}'s laptop ({child.admin_user}@{child.ip}):",
                                  QLineEdit.Password)
    if ok and pw:
        store.set_password(child, pw)
        return pw
    return None
