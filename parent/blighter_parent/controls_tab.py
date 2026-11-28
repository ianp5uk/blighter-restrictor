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
#   Login times (since 1.4.0) - up to two allowed periods for each day of
#     the week; outside them the child's account is locked (no new logins)
#     and a child who is logged in is warned (15 and 5 minutes, 5 only, or
#     not at all) and then logged out, or the PC is shut down.  A strip for
#     each day shows the allowed (green) and locked (grey) times.  "Extra
#     time" allows logging in until a chosen time today and ends by itself.
#     The schedule is kept and enforced on the PC itself (common/lockout.py),
#     so it works with this app closed.  Only the child's account is locked;
#     the PC refuses a schedule if that account is an administrator.
#   This PC - Log child out, Restart PC, Shut down PC.  Each asks first
#   (unsaved work on the PC is lost), then happens straight away or after a
#   warning on the child's screen: at 5 minutes, or at 15 and 5 minutes
#   (since 1.4.0).  A waiting action can be cancelled.  Log out does not
#   stop the child logging back in unless login times lock the account.
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

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QFrame, QGridLayout, QGroupBox,
                               QHBoxLayout, QLabel, QMessageBox, QPushButton, QRadioButton,
                               QScrollArea, QSizePolicy, QVBoxLayout, QWidget)

from .shared import domains, lockout
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
    "logout": ("Log child out", "Log {name} out of their PC {when}?",
               "Anything {name} hasn't saved will be lost.  They can log straight back in "
               "unless their login times are over."),
    "restart": ("Restart PC", "Restart {name}'s PC {when}?",
                "Anything not saved on it will be lost.  Blighter comes back on by itself."),
    "shutdown": ("Shut down PC", "Shut down {name}'s PC {when}?",
                 "Anything not saved on it will be lost.  It will show as not reachable here "
                 "until someone switches it on again."),
}

WARN_ACTION = ((0, "Straight away"), (5, "After a 5-minute warning"), (15, "After 15 and 5-minute warnings"))
WARN_LOCK = ((15, "Warnings at 15 and 5 minutes"), (5, "A warning at 5 minutes only"), (0, "No warning"))
AT_LOCK = (("logout", "Log the child out"), ("shutdown", "Shut down the PC"))
SHORT_DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
FROM_TIMES = lockout.all_times()                             # 00:00 .. 23:55
TO_TIMES = lockout.all_times(include_24=True)[1:]             # 00:05 .. 24:00
DEFAULT_PERIOD = ("07:00", "21:00")
ALLOWED_COLOUR = QColor("#2e9d4f")
LOCKED_COLOUR = QColor("#b9b9b9")


def describe(info, name):
    """One sentence for a control reply ({"state", "by", "since"} + "bypassed")."""
    state = info.get("state", domains.CONTROL_FILTERED)
    label = domains.CONTROL_NAMES.get(state, state)
    who = "on the PC itself" if info.get("by") == "pc" else "from this app"
    when = f", {info['since']}" if info.get("since") else ""
    return f"In force on {name}'s PC: <b>{label}</b> (set {who}{when})."


def describe_login(login, name):
    """The login times line under the schedule (HTML)."""
    if not login.get("limited"):
        return f"No login times: {name} can log in at any time."
    if login.get("child_is_admin"):
        return (f"<span style='color:#c0392b'><b>Not in force:</b> {name}'s account is an administrator "
                "on the PC, so it is never locked.  Make it a standard account first.</span>")
    if not login.get("enforced"):
        return (f"<span style='color:#c0392b'><b>Not in force</b> on {name}'s PC "
                "(Blighter is switched off there, or the child's account could not be checked).</span>")
    extra = f"  Extra time until {login['extension']} today." if login.get("extension") else ""
    if login.get("allowed"):
        return f"Now: {name} may log in until <b>{login.get('next_lock') or '?'}</b>.{extra}"
    nxt = login.get("next_unlock")
    return f"Now: <b>locked</b> - {name} can't log in" + (f" until <b>{nxt}</b>." if nxt else ".")


def pending_text(pending):
    if not pending:
        return ""
    noun = lockout.ACTION_NOUNS.get(pending.get("action"), "action")
    warn = pending.get("warn")
    how = {15: "warnings at 15 and 5 minutes", 5: "a warning at 5 minutes"}.get(warn, "")
    return f"Waiting: <b>{noun}</b> at {pending.get('at', '?')}" + (f", with {how}." if how else ".")


class DayStrip(QWidget):
    """A day from 00:00 to 24:00: allowed periods green, the rest grey."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.spans = []           # [(start minute, end minute)]
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setToolTip("Green: may log in.  Grey: locked.  Marks at 06:00, 12:00 and 18:00.")

    def sizeHint(self):
        h = self.fontMetrics().height()
        return QSize(h * 10, round(h * 0.9))

    def minimumSizeHint(self):
        h = self.fontMetrics().height()
        return QSize(h * 6, round(h * 0.9))

    def set_spans(self, spans):
        self.spans = spans
        self.update()

    def paintEvent(self, _ev):
        p = QPainter(self)
        r = QRectF(self.rect()).adjusted(0.5, 1.5, -0.5, -1.5)
        p.fillRect(r, LOCKED_COLOUR if self.isEnabled() else LOCKED_COLOUR.lighter(120))
        for a, b in self.spans:
            x1 = r.left() + r.width() * a / 1440
            x2 = r.left() + r.width() * b / 1440
            p.fillRect(QRectF(x1, r.top(), x2 - x1, r.height()),
                       ALLOWED_COLOUR if self.isEnabled() else ALLOWED_COLOUR.lighter(150))
        p.setPen(QPen(QColor(255, 255, 255, 170), 1))
        for hour in (6, 12, 18):
            x = r.left() + r.width() * hour / 24
            p.drawLine(int(x), int(r.top()), int(x), int(r.bottom()))
        p.setPen(QPen(QColor("#777777"), 1))
        p.drawRect(r)
        p.end()


class HourScale(QWidget):
    """00, 06, 12, 18, 24 above the day strips, lined up with them."""

    def sizeHint(self):
        return QSize(self.fontMetrics().height() * 10, self.fontMetrics().height())

    def minimumSizeHint(self):
        return QSize(self.fontMetrics().height() * 6, self.fontMetrics().height())

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setPen(self.palette().color(self.foregroundRole()))
        fm = self.fontMetrics()
        w = self.width() - 1
        for hour in (0, 6, 12, 18, 24):
            text = f"{hour:02d}:00"
            tw = fm.horizontalAdvance(text)
            x = w * hour / 24 - tw / 2
            x = min(max(0, x), w - tw)
            p.drawText(int(x), fm.ascent(), text)
        p.end()


class PeriodEditor:
    """One period on one day: [x] [from] to [to]."""

    def __init__(self, on_change):
        self.check = QCheckBox()
        self.start = QComboBox()
        self.start.addItems(FROM_TIMES)
        self.end = QComboBox()
        self.end.addItems(TO_TIMES)
        self.to = QLabel("to")
        for w in (self.start, self.end):
            w.setMaxVisibleItems(16)
            w.currentIndexChanged.connect(on_change)
        self.check.toggled.connect(self._toggled)
        self.check.toggled.connect(on_change)
        self._toggled(False)

    def _toggled(self, on):
        for w in (self.start, self.end, self.to):
            w.setEnabled(on)

    def set(self, period):
        self.check.setChecked(bool(period))
        a, b = period or DEFAULT_PERIOD
        self.start.setCurrentIndex(max(0, self.start.findText(a)))
        self.end.setCurrentIndex(max(0, self.end.findText(b)))

    def get(self):
        if not self.check.isChecked():
            return None
        return [self.start.currentText(), self.end.currentText()]


class ControlsTab(QWidget):
    status = Signal(str)
    control_known = Signal(str, dict)     # child id, {"state", "by", "since", "bypassed"}

    def __init__(self, remotes, parent=None):
        super().__init__(parent)
        self.remotes = remotes
        self.child = None
        self.busy = False
        self.known = None          # last control info read from the PC
        self.login = None          # last login times info read from the PC (1.4.0+)
        self.dirty = False
        self._loading = False
        self._seq = 0

        # ---- internet access
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

        # ---- login times
        self.login_box = QGroupBox("Login times")
        lb = QVBoxLayout(self.login_box)
        self.limit = QCheckBox("Limit when the child can log in")
        self.limit.toggled.connect(self._limit_toggled)
        lb.addWidget(self.limit)
        intro = QLabel("Outside the allowed times the child's account is locked: they can't log in, and if "
                       "they are logged in they are warned and then logged out.  A day with nothing "
                       "ticked is locked all day.  A period can't run past midnight - continue it on the "
                       "next day from 00:00.  Administrator accounts are never locked.")
        intro.setWordWrap(True)
        lb.addWidget(intro)

        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        grid.addWidget(QLabel("<b>Allowed</b>"), 0, 1, 1, 4)
        grid.addWidget(QLabel("<b>Also allowed</b>"), 0, 6, 1, 4)
        grid.addWidget(HourScale(), 0, 11)
        self.periods = []
        self.strips = []
        self.day_labels = []
        for row, name in enumerate(SHORT_DAYS, start=1):
            lab = QLabel(name)
            self.day_labels.append(lab)
            grid.addWidget(lab, row, 0)
            pair = []
            for k in range(2):
                ed = PeriodEditor(self._schedule_changed)
                col = 1 + k * 5
                grid.addWidget(ed.check, row, col)
                grid.addWidget(ed.start, row, col + 1)
                grid.addWidget(ed.to, row, col + 2)
                grid.addWidget(ed.end, row, col + 3)
                pair.append(ed)
            spacer = QLabel("")
            spacer.setFixedWidth(10)
            grid.addWidget(spacer, row, 5)
            grid.addWidget(QLabel(""), row, 10)
            strip = DayStrip()
            self.strips.append(strip)
            grid.addWidget(strip, row, 11)
            self.periods.append(pair)
        grid.setColumnStretch(11, 1)
        lb.addLayout(grid)

        copy = QHBoxLayout()
        self.b_copy_week = QPushButton("Copy Monday to Tue-Fri")
        self.b_copy_week.clicked.connect(lambda: self._copy(0, range(1, 5)))
        self.b_copy_end = QPushButton("Copy Saturday to Sunday")
        self.b_copy_end.clicked.connect(lambda: self._copy(5, [6]))
        copy.addWidget(self.b_copy_week)
        copy.addWidget(self.b_copy_end)
        copy.addStretch()
        lb.addLayout(copy)

        self.warn_group = QButtonGroup(self)
        self.warn_radios = {}
        wrow = QHBoxLayout()
        wrow.addWidget(QLabel("Before the lock:"))
        for value, text in WARN_LOCK:
            rb = QRadioButton(text)
            self.warn_radios[value] = rb
            self.warn_group.addButton(rb)
            rb.toggled.connect(self._schedule_changed)
            wrow.addWidget(rb)
        wrow.addStretch()
        lb.addLayout(wrow)
        self.at_group = QButtonGroup(self)
        self.at_radios = {}
        arow = QHBoxLayout()
        arow.addWidget(QLabel("At lock time, if logged in:"))
        for value, text in AT_LOCK:
            rb = QRadioButton(text)
            self.at_radios[value] = rb
            self.at_group.addButton(rb)
            rb.toggled.connect(self._schedule_changed)
            arow.addWidget(rb)
        arow.addStretch()
        lb.addLayout(arow)

        apply_row = QHBoxLayout()
        self.b_apply_login = QPushButton("Apply to PC")
        self.b_apply_login.setDefault(True)
        self.b_apply_login.clicked.connect(self._apply_login)
        self.b_undo_login = QPushButton("Undo changes")
        self.b_undo_login.clicked.connect(self._undo_login)
        apply_row.addWidget(self.b_apply_login)
        apply_row.addWidget(self.b_undo_login)
        apply_row.addStretch()
        lb.addLayout(apply_row)
        self.login_label = QLabel("")
        self.login_label.setWordWrap(True)
        lb.addWidget(self.login_label)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        lb.addWidget(line)
        xrow = QHBoxLayout()
        xrow.addWidget(QLabel("Extra time: allow logging in until"))
        self.extra_time = QComboBox()
        self.extra_time.addItems(FROM_TIMES)
        self.extra_time.setMaxVisibleItems(16)
        self.extra_time.setCurrentText("22:00")
        xrow.addWidget(self.extra_time)
        xrow.addWidget(QLabel("today"))
        self.b_extra = QPushButton("Allow")
        self.b_extra.clicked.connect(self._extend)
        self.b_extra_end = QPushButton("End extra time")
        self.b_extra_end.clicked.connect(lambda: self._extend(end=True))
        xrow.addWidget(self.b_extra)
        xrow.addWidget(self.b_extra_end)
        xrow.addStretch()
        lb.addLayout(xrow)
        xnote = QLabel("Extra time ends by itself; the schedule above is not changed.")
        xnote.setWordWrap(True)
        lb.addWidget(xnote)

        # ---- this PC
        pc = QGroupBox("This PC")
        pl = QVBoxLayout(pc)
        wsel = QHBoxLayout()
        wsel.addWidget(QLabel("When:"))
        self.action_warn = QComboBox()
        for value, text in WARN_ACTION:
            self.action_warn.addItem(text, value)
        wsel.addWidget(self.action_warn)
        wsel.addStretch()
        pl.addLayout(wsel)
        row = QHBoxLayout()
        self.action_buttons = {}
        for key in ("logout", "restart", "shutdown"):
            b = QPushButton(ACTIONS[key][0])
            b.clicked.connect(lambda _=False, k=key: self._action(k))
            self.action_buttons[key] = b
            row.addWidget(b)
        row.addStretch()
        pl.addLayout(row)
        prow = QHBoxLayout()
        self.pending_label = QLabel("")
        self.pending_label.setWordWrap(True)
        self.b_cancel = QPushButton("Cancel it")
        self.b_cancel.clicked.connect(self._cancel_action)
        prow.addWidget(self.pending_label, 1)
        prow.addWidget(self.b_cancel)
        pl.addLayout(prow)
        pnote = QLabel("Each asks you first.  Warnings appear on the child's screen; only one action can "
                       "wait at a time - a new one replaces it.")
        pnote.setWordWrap(True)
        pl.addWidget(pnote)

        self.btn_read = QPushButton("Read from PC")
        self.btn_read.setToolTip("Ask the PC what is in force now")
        self.btn_read.clicked.connect(self.refresh)
        top = QHBoxLayout()
        top.addWidget(self.btn_read)
        top.addStretch()

        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.addLayout(top)
        lay.addWidget(self.banner)
        lay.addWidget(self.state_label)
        lay.addWidget(access)
        lay.addWidget(self.login_box)
        lay.addWidget(pc)
        lay.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(inner)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
        self._show_login(None)
        self._enable()

    # ---- helpers ------------------------------------------------------------------
    def _name(self):
        return self.child.name if self.child else "the child"

    def _enable(self):
        ready = self.child is not None and not self.busy
        known = ready and self.known is not None
        has_login = known and self.login is not None
        for rb in self.radios.values():
            rb.setEnabled(known)
        for b in self.action_buttons.values():
            b.setEnabled(known)
        self.action_warn.setEnabled(has_login)
        if not has_login:
            self.action_warn.setCurrentIndex(0)
        self.btn_read.setEnabled(ready)
        self.limit.setEnabled(has_login)
        on = has_login and self.limit.isChecked()
        for pair in self.periods:
            for ed in pair:
                ed.check.setEnabled(on)
                ed._toggled(on and ed.check.isChecked())
        for w in (self.b_copy_week, self.b_copy_end, *self.warn_radios.values(), *self.at_radios.values(),
                  *self.strips, *self.day_labels):
            w.setEnabled(on)
        self.b_apply_login.setEnabled(has_login and self.dirty)
        self.b_undo_login.setEnabled(has_login and self.dirty)
        live = has_login and bool(self.login.get("limited"))
        self.extra_time.setEnabled(live)
        self.b_extra.setEnabled(live)
        self.b_extra_end.setEnabled(live and bool(self.login.get("extension")))
        pending = has_login and bool(self.login.get("pending"))
        self.b_cancel.setVisible(pending)
        self.b_cancel.setEnabled(pending and ready)

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

    # ---- login times ------------------------------------------------------------------
    def _show_login(self, login, keep_edits=False):
        """Fill the login times part from the PC's reply (None = not available)."""
        self.login = login
        if not keep_edits or not self.dirty:
            sched = (login or {}).get("schedule") or lockout.empty_schedule()
            self._loading = True
            self.limit.setChecked(bool(sched.get("enabled")))
            for pair, periods in zip(self.periods, sched.get("days", [[]] * 7)):
                for k, ed in enumerate(pair):
                    ed.set(periods[k] if k < len(periods) else None)
            self.warn_radios.get(sched.get("warn", 15), self.warn_radios[15]).setChecked(True)
            self.at_radios.get(sched.get("at_lock", "logout"), self.at_radios["logout"]).setChecked(True)
            self._loading = False
            self.dirty = False
        self.limit.setText(f"Limit when {self._name()} can log in")
        self._draw_strips()
        if login is None:
            self.login_label.setText("")
            self.pending_label.setText("")
        else:
            self.login_label.setText(describe_login(login, self._name()))
            self.pending_label.setText(pending_text(login.get("pending")))
        self._enable()

    def _edited_schedule(self):
        days = []
        for pair in self.periods:
            days.append([p for p in (ed.get() for ed in pair) if p])
        warn = next((v for v, rb in self.warn_radios.items() if rb.isChecked()), 15)
        at = next((v for v, rb in self.at_radios.items() if rb.isChecked()), "logout")
        return {"enabled": self.limit.isChecked(), "days": days, "warn": warn, "at_lock": at}

    def _draw_strips(self):
        sched = self._edited_schedule()
        for strip, periods in zip(self.strips, sched["days"]):
            spans = []
            for a, b in periods:
                x, y = lockout.parse_hhmm(a), lockout.parse_hhmm(b, True)
                if x is not None and y is not None and y > x:
                    spans.append((x, y))
            strip.set_spans(spans if sched["enabled"] else [(0, 1440)])

    def _schedule_changed(self, *_):
        if self._loading:
            return
        self.dirty = True
        self._draw_strips()
        self._enable()

    def _limit_toggled(self, on):
        if self._loading:
            return
        if on and not any(ed.check.isChecked() for pair in self.periods for ed in pair):
            # First time: a sensible starting point rather than "locked all week".
            self._loading = True
            for pair in self.periods:
                pair[0].set(DEFAULT_PERIOD)
            self._loading = False
        self._schedule_changed()

    def _copy(self, src, targets):
        self._loading = True
        for t in targets:
            for k in range(2):
                self.periods[t][k].set(self.periods[src][k].get())
        self._loading = False
        self._schedule_changed()

    def _undo_login(self):
        self.dirty = False
        self._show_login(self.login)

    def _apply_login(self):
        if not self.child or self.busy or self.login is None:
            return
        sched, errors = lockout.clean_schedule(self._edited_schedule())
        if errors:
            QMessageBox.warning(self, "Login times", "Please correct these first:\n\n" + "\n".join(errors))
            return
        if sched["enabled"] and not any(sched["days"]):
            r = QMessageBox.question(self, "Login times", f"No allowed times are ticked, so {self.child.name} "
                                     "would be locked out all week.  Apply anyway?",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if r != QMessageBox.Yes:
                return
        child = self.child
        tag = self._begin()
        self.status.emit(f"Sending login times to {child.name}'s PC…")

        def ok(res):
            mine = self._end(tag)
            self.status.emit(f"{child.name}: {res.get('message', '')}")
            if mine:
                if res.get("ok"):
                    self.dirty = False
                if res.get("login"):
                    self._show_login(res["login"], keep_edits=not res.get("ok"))
            if not res.get("ok"):
                QMessageBox.warning(self, "Login times", f"{child.name}: {res.get('message', '')}")

        def err(msg):
            self._end(tag)
            QMessageBox.critical(self, "Login times", f"{child.name}: {msg}")
            self.status.emit(msg)

        run_bg(lambda: self.remotes.get(child).set_login_times(sched), ok, err)

    def _extend(self, end=False):
        if not self.child or self.busy:
            return
        child = self.child
        until = "" if end else self.extra_time.currentText()
        tag = self._begin()

        def ok(res):
            mine = self._end(tag)
            self.status.emit(f"{child.name}: {res.get('message', '')}")
            if mine and res.get("login"):
                self._show_login(res["login"], keep_edits=True)
            if not res.get("ok"):
                QMessageBox.warning(self, "Extra time", f"{child.name}: {res.get('message', '')}")

        def err(msg):
            self._end(tag)
            QMessageBox.critical(self, "Extra time", f"{child.name}: {msg}")

        run_bg(lambda: self.remotes.get(child).extend(until), ok, err)

    # ---- public -------------------------------------------------------------------
    def set_child(self, child):
        self._seq += 1
        self.busy = False
        self.child = child
        self.known = None
        self.dirty = False
        self.group.setExclusive(False)
        for rb in self.radios.values():
            rb.setChecked(False)
        self.group.setExclusive(True)
        self.banner.hide()
        self.state_label.setText("")
        self._show_login(None)
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
                                         f"({data.get('helper_version', '?')}).  Update it to 1.4.0 to use "
                                         "these controls.")
                self._show_login(None)
                return
            info["bypassed"] = bool(data.get("bypassed"))
            self._show(child, info)
            login = data.get("login")
            self._show_login(login, keep_edits=True)
            if login is None:
                self.login_label.setText(f"Login times and warnings need Blighter child 1.4.0 on "
                                         f"{child.name}'s PC (it has {data.get('helper_version', '?')}).")

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
        warn = self.action_warn.currentData() if self.login is not None else 0
        title, question, detail = ACTIONS[key]
        when = "now" if not warn else (f"in {warn} minutes, after warning them at 15 and 5 minutes"
                                       if warn == 15 else "in 5 minutes, after warning them")
        if self.login and self.login.get("pending"):
            detail += "\n\nThis replaces the action already waiting."
        r = QMessageBox.question(self, title, question.format(name=child.name, when=when) + "\n\n" +
                                 detail.format(name=child.name),
                                 QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if r != QMessageBox.Yes:
            return
        tag = self._begin()
        self.status.emit(f"{title}: asking {child.name}'s PC…")

        def call():
            remote = self.remotes.get(child)
            if self.login is None:          # child older than 1.4.0
                return remote.log_child_out() if key == "logout" else remote.power(key)
            return remote.action(key, warn)

        def ok(res):
            mine = self._end(tag)
            self.status.emit(f"{child.name}: {res.get('message', '')}")
            if mine and res.get("login"):
                self._show_login(res["login"], keep_edits=True)
            if not res.get("ok"):
                QMessageBox.warning(self, title, f"{child.name}: {res.get('message', '')}")

        def err(msg):
            self._end(tag)
            QMessageBox.critical(self, title, f"{child.name}: {msg}")
            self.status.emit(msg)

        run_bg(call, ok, err)

    def _cancel_action(self):
        if not self.child or self.busy:
            return
        child = self.child
        tag = self._begin()

        def ok(res):
            mine = self._end(tag)
            self.status.emit(f"{child.name}: {res.get('message', '')}")
            if mine and res.get("login"):
                self._show_login(res["login"], keep_edits=True)

        def err(msg):
            self._end(tag)
            QMessageBox.critical(self, "Cancel", f"{child.name}: {msg}")

        run_bg(lambda: self.remotes.get(child).cancel_action(), ok, err)
