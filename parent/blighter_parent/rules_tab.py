# -----------------------------------------------------------------------------
# Blighter Restrictor - "Rules" tab.
#
# Purpose: show and edit one child's filtering mode and domain lists, check
# them as you type (same rules as the laptop), and apply them.  Applying
# sends the lists to the laptop, which checks them with Squid and reloads,
# or restores the previous rules if Squid rejects them.
#   Mode "Allow all, block some"  -> only the Block list is used
#   Mode "Block all, allow some"  -> only the Allow list is used
# Both lists are always kept, so switching mode never loses either one.
# -----------------------------------------------------------------------------

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (QButtonGroup, QGroupBox, QHBoxLayout, QLabel,
                               QListWidget, QMessageBox, QPlainTextEdit,
                               QPushButton, QRadioButton, QSplitter, QVBoxLayout,
                               QWidget)

from .shared import domains
from .workers import run_bg

HELP = ("One domain per line.  <b>.example.com</b> = the site and all its subdomains; "
        "<b>example.com</b> = that exact name only.  Lines starting with # are comments.  "
        "<b>*.example.com</b> and pasted web addresses are converted automatically.")


class RulesTab(QWidget):
    status = Signal(str)

    def __init__(self, remotes, parent=None):
        super().__init__(parent)
        self.remotes = remotes
        self.child = None
        self.loaded = None  # (mode, allow_text, block_text) as last read from the laptop
        self.busy = False

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
        mode_row.addStretch()
        self.dirty_label = QLabel("")
        mode_row.addWidget(self.dirty_label)

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

        self.btn_reload = QPushButton("Reload from laptop")
        self.btn_tidy = QPushButton("Tidy lists")
        self.btn_tidy.setToolTip("Apply the automatic conversions and remove duplicates in the editor")
        self.btn_revert = QPushButton("Revert")
        self.btn_apply = QPushButton("Apply to laptop")
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
        return (self.mode(), self.allow_edit.toPlainText().strip(), self.block_edit.toPlainText().strip())

    def is_dirty(self):
        return self.loaded is not None and self._current() != self.loaded

    def _set_enabled(self, on):
        for w in (self.rb_block, self.rb_allow, self.block_edit, self.allow_edit,
                  self.btn_reload, self.btn_tidy, self.btn_revert, self.btn_apply):
            w.setEnabled(on)

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
        if self.mode() == domains.MODE_ALLOWLIST and not domains.entries_only(
                domains.clean_list(self.allow_edit.toPlainText().splitlines())[0]):
            self.issues.addItem("Note: the allow list is empty - every site will be blocked.")
        return not errors

    def _fill(self, mode, allow_lines, block_lines):
        for e in (self.block_edit, self.allow_edit):
            e.blockSignals(True)
        self.allow_edit.setPlainText("\n".join(allow_lines).strip())
        self.block_edit.setPlainText("\n".join(block_lines).strip())
        for e in (self.block_edit, self.allow_edit):
            e.blockSignals(False)
        (self.rb_allow if mode == domains.MODE_ALLOWLIST else self.rb_block).setChecked(True)
        self.loaded = self._current()
        self._changed()

    # ---- public -------------------------------------------------------------------
    def set_child(self, child):
        self.child = child
        self.loaded = None
        self._fill(domains.MODE_BLOCKLIST, [], [])
        self.loaded = None
        self._set_enabled(False)
        if child:
            self.reload()

    def reload(self):
        if not self.child or self.busy:
            return
        child = self.child
        self.busy = True
        self.status.emit(f"Reading rules from {child.name}'s laptop…")

        def ok(data):
            self.busy = False
            if child is not self.child:
                return
            self._fill(data.get("mode"), data.get("allow", []), data.get("block", []))
            self._set_enabled(True)
            self.status.emit(f"Rules loaded from {child.name}'s laptop.")

        def err(msg):
            self.busy = False
            self.status.emit(msg)
            if child is self.child:
                self.issues.clear()
                self.issues.addItem("ERROR " + msg)

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
            mode, allow, block = self.loaded
            self._fill(mode, allow.splitlines(), block.splitlines())

    def add_domain(self, which, domain):
        """Called from the Activity tab: which is 'allow' or 'block'."""
        edit = self.allow_edit if which == "allow" else self.block_edit
        lines = edit.toPlainText().rstrip().splitlines()
        if domain in (l.strip() for l in lines):
            return f"{domain} is already in the {which} list."
        lines.append(domain)
        edit.setPlainText("\n".join(lines))
        return f"Added {domain} to the {which} list - press 'Apply to laptop' to make it live."

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
        self.busy = True
        self._set_enabled(False)
        self.status.emit(f"Applying rules to {child.name}'s laptop…")

        def ok(res):
            self.busy = False
            self._set_enabled(True)
            if res.get("ok"):
                if child is self.child:
                    self._fill(res.get("mode"), res.get("allow", []), res.get("block", []))
                    for w in res.get("warnings", []):
                        self.issues.addItem("Squid: " + w)
                self.status.emit(f"{child.name}: {res.get('message')}")
            else:
                details = "\n".join(res.get("errors", []))
                QMessageBox.critical(self, "Not applied", f"{res.get('message')}\n\n{details}")
                self.status.emit(f"{child.name}: {res.get('message')}")

        def err(msg):
            self.busy = False
            self._set_enabled(True)
            QMessageBox.critical(self, "Could not apply", msg)
            self.status.emit(msg)

        run_bg(lambda: self.remotes.get(child).apply(mode, allow, block), ok, err)
