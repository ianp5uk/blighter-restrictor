# -----------------------------------------------------------------------------
# Blighter Restrictor - login times, warnings and delayed actions (since 1.4.0).
#
# Purpose: the rules behind the Controls tab's "Login times" and the warned
# Log out / Restart / Shut down buttons, shared by the parent app (checking
# and drawing a schedule) and both PC helpers (enforcing it), so all three
# agree exactly.  Nothing here touches the operating system directly: the
# helpers pass in a small "platform" object (see Engine) that knows how to
# lock the child's account, see whether the child is logged in, log them
# out, switch the PC off and show a warning on the child's screen.
#
# The schedule (schedule.json on the PC):
#   {"enabled": true,
#    "days": [[["07:00", "08:15"], ["15:30", "21:00"]], ...],   7 lists, Monday first;
#            each day has 0, 1 or 2 allowed periods "HH:MM" to "HH:MM"
#            (5-minute steps, "24:00" allowed as an end, no period past midnight)
#    "warn": 15 | 5 | 0,          minutes of warning before the lock (15 = 15 and 5)
#    "at_lock": "logout" | "shutdown"}
#   Outside the allowed periods the child's account is locked (no new logins);
#   a day with no periods is locked all day.  enabled false = no limit.
# Extra time ("Allow until [time] today", extension.json): {"until": "YYYY-MM-DD HH:MM"}.
#   Until then the child may log in whatever the schedule says.  It expires by itself.
# A delayed action (pending.json): {"action", "at", "warn", "sent", "created"}.
#   One at a time; a new one replaces it.  Warnings at 15 and/or 5 minutes.
# lock state (lockstate.json): {"locked", "grace_until", "sent"} - whether THIS
#   program locked the account (it never unlocks one it did not lock), and the
#   warnings already shown.
#
# Safety rules (Engine.tick):
#   * only the recorded child account is ever locked, never an administrator
#     (if the child's account is an administrator the schedule is not enforced)
#   * a child who is logged in is never locked out without the chosen
#     warnings: if lock time arrives unannounced (the schedule was just
#     applied, or the PC was asleep) the warnings start then
#   * an unreadable schedule means "no limit", never "locked"
#
# Copyright (C) 2026 Ian Packer
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version.  It is distributed WITHOUT ANY WARRANTY; see the
# LICENSE file or <https://www.gnu.org/licenses/> for details.
# -----------------------------------------------------------------------------

import datetime as dt
import json
import math
import os
import time

DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
STEP = 5                      # minutes
MAX_PERIODS = 2
WARN_CHOICES = (15, 5, 0)     # 15 = warnings at 15 and 5 minutes; 5 = at 5 only; 0 = none
AT_LOCK = ("logout", "shutdown")
ACTIONS = ("logout", "restart", "shutdown")
ACTION_WORDS = {"logout": "log you out", "restart": "restart", "shutdown": "shut down"}
ACTION_NOUNS = {"logout": "log out", "restart": "restart", "shutdown": "shut down"}

SCHEDULE_FILE = "schedule.json"
EXTENSION_FILE = "extension.json"
PENDING_FILE = "pending.json"
LOCKSTATE_FILE = "lockstate.json"


def empty_schedule():
    return {"enabled": False, "days": [[] for _ in DAYS], "warn": 15, "at_lock": "logout"}


def thresholds(warn):
    """Warning points in seconds before the event."""
    return {15: [900, 300], 5: [300], 0: []}.get(warn, [])


# ---- times ----------------------------------------------------------------------
def parse_hhmm(text, allow_24=False):
    """"HH:MM" -> minutes since midnight, or None.  Must be on a 5-minute step."""
    if not isinstance(text, str) or len(text) != 5 or text[2] != ":":
        return None
    h, m = text[:2], text[3:]
    if not (h.isdigit() and m.isdigit()):
        return None
    h, m = int(h), int(m)
    if m >= 60 or m % STEP:
        return None
    total = h * 60 + m
    if total > 24 * 60 or (total == 24 * 60 and not allow_24):
        return None
    return total


def hhmm(minutes):
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def all_times(include_24=False):
    """Every 5-minute time of day as "HH:MM" (for the parent app's drop-downs)."""
    last = 24 * 60 if include_24 else 24 * 60 - STEP
    return [hhmm(m) for m in range(0, last + 1, STEP)]


# ---- checking -------------------------------------------------------------------
def clean_schedule(data):
    """Validate a schedule from the parent app.  Returns (schedule, errors)."""
    errors = []
    if not isinstance(data, dict):
        return empty_schedule(), ["The schedule is not in the expected form."]
    days = data.get("days")
    if not isinstance(days, list) or len(days) != 7:
        return empty_schedule(), ["The schedule must have seven days."]
    clean_days = []
    for name, periods in zip(DAYS, days):
        if not isinstance(periods, list) or len(periods) > MAX_PERIODS:
            errors.append(f"{name}: at most {MAX_PERIODS} periods.")
            clean_days.append([])
            continue
        spans = []
        for p in periods:
            if not (isinstance(p, (list, tuple)) and len(p) == 2):
                errors.append(f"{name}: a period is not in the expected form.")
                continue
            a, b = parse_hhmm(p[0]), parse_hhmm(p[1], allow_24=True)
            if a is None or b is None:
                errors.append(f"{name}: {p[0]} to {p[1]} is not a valid time (use 5-minute steps).")
                continue
            if b <= a:
                errors.append(f"{name}: {p[0]} to {p[1]} ends before it starts.  A period can't "
                              "run past midnight - add the rest to the next day, starting 00:00.")
                continue
            spans.append((a, b))
        spans.sort()
        if len(spans) == 2 and spans[1][0] < spans[0][1]:
            errors.append(f"{name}: the two periods overlap.")
        clean_days.append([[hhmm(a), hhmm(b)] for a, b in spans])
    warn = data.get("warn", 15)
    if warn not in WARN_CHOICES:
        errors.append("Unknown warning choice.")
        warn = 15
    at_lock = data.get("at_lock", "logout")
    if at_lock not in AT_LOCK:
        errors.append("Unknown choice for lock time.")
        at_lock = "logout"
    return ({"enabled": bool(data.get("enabled")), "days": clean_days, "warn": warn,
             "at_lock": at_lock}, errors)


def load_schedule(text):
    """Schedule from the file's text.  Anything unreadable = no limit (fail open)."""
    try:
        sched, errors = clean_schedule(json.loads(text))
    except (ValueError, TypeError):
        return empty_schedule()
    if errors:
        sched["enabled"] = False
    return sched


# ---- allowed time ------------------------------------------------------------------
def _day_spans(sched, day):
    """[(start datetime, end datetime)] of allowed periods on one date."""
    out = []
    base = dt.datetime.combine(day, dt.time())
    for a, b in sched["days"][day.weekday()]:
        out.append((base + dt.timedelta(minutes=parse_hhmm(a)),
                    base + dt.timedelta(minutes=parse_hhmm(b, True))))
    return out


def allowed_spans(sched, now, extension=None, days_ahead=8):
    """Merged allowed periods from yesterday to days_ahead days on (local, naive datetimes)."""
    spans = []
    start = now.date() - dt.timedelta(days=1)
    for i in range(days_ahead + 2):
        spans += _day_spans(sched, start + dt.timedelta(days=i))
    if extension and extension > now:
        spans.append((now.replace(second=0, microsecond=0), extension))
    spans.sort()
    merged = []
    for a, b in spans:
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return merged


def state_at(sched, now, extension=None):
    """{"limited", "allowed", "next_lock", "next_unlock"} (datetimes or None).
    next_lock: when the current allowed period ends; next_unlock: when the
    current locked time ends."""
    if not sched.get("enabled"):
        return {"limited": False, "allowed": True, "next_lock": None, "next_unlock": None}
    spans = allowed_spans(sched, now, extension)
    for a, b in spans:
        if a <= now < b:
            return {"limited": True, "allowed": True, "next_lock": b, "next_unlock": None}
    nxt = next((a for a, _ in spans if a > now), None)
    return {"limited": True, "allowed": False, "next_lock": None, "next_unlock": nxt}


def when_text(moment, now):
    """"21:00", "07:00 tomorrow" or "07:00 on Monday"."""
    if moment is None:
        return ""
    t = moment.strftime("%H:%M")
    if moment.date() == now.date():
        return t
    if moment.date() == now.date() + dt.timedelta(days=1):
        return t + " tomorrow"
    if moment.date() < now.date() + dt.timedelta(days=7):
        return f"{t} on {DAYS[moment.weekday()]}"
    return t + moment.strftime(" on %d %b")


def parse_extension(text, now):
    """extension.json text -> datetime it ends, or None if absent / over / unreadable."""
    try:
        until = dt.datetime.strptime(json.loads(text)["until"], "%Y-%m-%d %H:%M")
    except (ValueError, TypeError, KeyError):
        return None
    return until if until > now else None


# ---- the PC side -------------------------------------------------------------------
class Engine:
    """Enforces the schedule and delayed actions on the PC.

    platform must provide:
      state_dir                  folder for the four files
      child_user()               the child's account name ("" if none)
      child_is_admin()           True / False / None (unknown)
      set_locked(locked)         (ok, message) - lock / unlock the child's account
      child_logged_in()          bool
      logout()                   (ok, message)
      power(action)              (ok, message) - "restart" / "shutdown"
      notify(title, text)        show a warning on the child's screen (best effort)
      bypassed()                 True if Blighter is switched off completely
      log(text)                  optional record
    """

    def __init__(self, platform, now=None, sleep=None):
        self.p = platform
        self.now = now or dt.datetime.now
        self.sleep = sleep or time.sleep

    # files
    def _path(self, name):
        return os.path.join(self.p.state_dir, name)

    def _read(self, name):
        try:
            with open(self._path(name), encoding="utf-8") as f:
                return f.read()
        except (FileNotFoundError, PermissionError):
            return ""

    def _write(self, name, obj):
        os.makedirs(self.p.state_dir, exist_ok=True)
        path = self._path(name)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f)
        os.replace(tmp, path)

    def _remove(self, name):
        try:
            os.remove(self._path(name))
        except FileNotFoundError:
            pass

    def _json(self, name):
        try:
            v = json.loads(self._read(name) or "{}")
            return v if isinstance(v, dict) else {}
        except ValueError:
            return {}

    def schedule(self):
        text = self._read(SCHEDULE_FILE)
        return load_schedule(text) if text else empty_schedule()

    def extension(self, now):
        return parse_extension(self._read(EXTENSION_FILE), now)

    def pending(self):
        p = self._json(PENDING_FILE)
        if p.get("action") in ACTIONS and isinstance(p.get("at"), (int, float)):
            return p
        return None

    def _log(self, text):
        log = getattr(self.p, "log", None)
        if log:
            log(text)

    # what the parent app sees
    def describe(self):
        now = self.now()
        sched = self.schedule()
        ext = self.extension(now)
        ls = self._json(LOCKSTATE_FILE)
        st = state_at(sched, now, ext)
        grace = ls.get("grace_until")
        if st["limited"] and not st["allowed"] and grace and grace > now.timestamp():
            st = dict(st, allowed=True, next_lock=dt.datetime.fromtimestamp(grace))
        admin = self.p.child_is_admin()
        pend = self.pending()
        info = {
            "schedule": sched,
            "extension": ext.strftime("%H:%M") if ext else "",
            "now": now.strftime("%Y-%m-%d %H:%M"),
            "limited": st["limited"],
            "allowed": st["allowed"],
            "locked": bool(ls.get("locked")),
            "next_lock": when_text(st["next_lock"], now),
            "next_unlock": when_text(st["next_unlock"], now),
            "child_is_admin": admin,
            "enforced": st["limited"] and admin is False and not self.p.bypassed(),
            "pending": None,
        }
        if pend:
            at = dt.datetime.fromtimestamp(pend["at"])
            info["pending"] = {"action": pend["action"], "at": when_text(at, now),
                               "warn": pend.get("warn", 0)}
        return info

    # parent requests
    def set_schedule(self, data):
        sched, errors = clean_schedule(data)
        if errors:
            return False, "The login times were not changed: " + " ".join(errors)
        if sched["enabled"]:
            admin = self.p.child_is_admin()
            if admin:
                return False, ("The child's account is an administrator, so login times can't be "
                               "enforced - they could simply undo them.  Make it a standard account first.")
            if admin is None:
                return False, "The child's account could not be checked, so login times were not switched on."
        self._write(SCHEDULE_FILE, sched)
        if not sched["enabled"]:
            self._remove(EXTENSION_FILE)
        return True, ("Login times saved and in force." if sched["enabled"] else "Login times switched off.")

    def set_extension(self, until_hhmm):
        """"HH:MM" today, or "" to end extra time now."""
        now = self.now()
        if not until_hhmm:
            self._remove(EXTENSION_FILE)
            return True, "Extra time ended."
        if not self.schedule()["enabled"]:
            return False, "Login times are off, so there is no need for extra time."
        m = parse_hhmm(until_hhmm)
        if m is None:
            return False, f"{until_hhmm} is not a valid time."
        until = dt.datetime.combine(now.date(), dt.time()) + dt.timedelta(minutes=m)
        if until <= now:
            return False, f"{until_hhmm} has already passed today."
        self._write(EXTENSION_FILE, {"until": until.strftime("%Y-%m-%d %H:%M")})
        return True, f"Extra time: allowed until {until_hhmm} today."

    def set_pending(self, action, warn):
        """A warned action.  (Immediate ones are done by the helper directly.)"""
        if action not in ACTIONS or warn not in (5, 15):
            return False, "Unknown action."
        now = self.now().timestamp()
        if action == "logout" and not self.p.child_logged_in():
            return True, f"{self.p.child_user()} is not logged in."
        pend = {"action": action, "at": now + warn * 60, "warn": warn, "sent": [], "created": now}
        self._write(PENDING_FILE, pend)
        self._warn_pending(pend, self.now())
        at = dt.datetime.fromtimestamp(pend["at"]).strftime("%H:%M")
        who = "" if self.p.child_logged_in() else "  The child is not logged in now, so no warning was shown."
        return True, f"{ACTION_NOUNS[action].capitalize()} at {at}, after a {warn}-minute warning.{who}"

    def cancel_pending(self):
        pend = self.pending()
        self._remove(PENDING_FILE)
        if not pend:
            return True, "Nothing was waiting."
        if pend.get("sent") and self.p.child_logged_in():
            self.p.notify("Blighter Restrictor", f"The planned {ACTION_NOUNS[pend['action']]} has been cancelled.")
        return True, f"The planned {ACTION_NOUNS[pend['action']]} was cancelled."

    def release(self):
        """Unlock the account if this program locked it (setup removal, switch-off)."""
        ls = self._json(LOCKSTATE_FILE)
        if ls.get("locked"):
            ok, msg = self.p.set_locked(False)
            if not ok:
                return False, msg
        self._write(LOCKSTATE_FILE, {"locked": False})
        return True, "The child's account is not locked."

    # warnings
    def _due_warning(self, remaining, warn, sent):
        """The warning to show now (seconds point), or None."""
        pts = thresholds(warn)
        current = [t for t in pts if remaining <= t + 30]
        if not current:
            return None
        t = min(current)
        return None if t in sent else t

    def _warn_pending(self, pend, now):
        if not self.p.child_logged_in():
            return
        remaining = pend["at"] - now.timestamp()
        t = self._due_warning(remaining, pend.get("warn", 0), pend.get("sent", []))
        if t is None:
            return
        mins = max(1, math.ceil((remaining - 1) / 60))
        at = dt.datetime.fromtimestamp(pend["at"]).strftime("%H:%M")
        verb = ACTION_WORDS[pend["action"]]
        what = (f"This PC will {verb} in {mins} minute{'s' if mins != 1 else ''} (at {at})."
                if pend["action"] != "logout" else
                f"Blighter will log you out in {mins} minute{'s' if mins != 1 else ''} (at {at}).")
        self.p.notify("Blighter Restrictor", what + "  Save your work now.")
        pend["sent"] = sorted(set(pend.get("sent", [])) | {p for p in thresholds(pend.get("warn", 0)) if p >= t})
        self._write(PENDING_FILE, pend)

    def _warn_lock(self, ls, key, remaining, sched, unlock_text):
        sent = ls.get("sent", {}).get(key, [])
        t = self._due_warning(remaining, sched["warn"], sent)
        if t is None:
            return
        mins = max(1, math.ceil((remaining - 1) / 60))
        at = (self.now() + dt.timedelta(seconds=remaining)).strftime("%H:%M")
        then = "the PC will shut down" if sched["at_lock"] == "shutdown" else "you will be logged out"
        again = f"  You can log in again at {unlock_text}." if unlock_text else ""
        self.p.notify("Blighter Restrictor",
                      f"Login time ends in {mins} minute{'s' if mins != 1 else ''} (at {at}).  "
                      f"Save your work - {then}.{again}")
        ls["sent"] = {key: sorted(set(sent) | {p for p in thresholds(sched["warn"]) if p >= t})}
        ls["announced"] = self.now().timestamp() + remaining

    # the minute check
    def tick(self, max_seconds=58):
        """Run by the PC's timer every minute (and when the parent changes
        something).  Keeps going for up to max_seconds when an event is due
        within the minute, so warnings and actions happen on time."""
        started = time.monotonic()
        while True:
            wait = self._once()
            left = max_seconds - (time.monotonic() - started)
            if wait is None or wait > left:
                return
            self.sleep(max(1.0, min(wait, 5.0)))

    def _once(self):
        """One pass.  Returns seconds until the next thing due, or None."""
        now = self.now()
        ts = now.timestamp()
        due = []
        sched = self.schedule()
        ext = self.extension(now)
        if not ext and os.path.exists(self._path(EXTENSION_FILE)):
            self._remove(EXTENSION_FILE)
        ls = self._json(LOCKSTATE_FILE)
        ls.setdefault("locked", False)
        before = json.dumps(ls, sort_keys=True)
        st = state_at(sched, now, ext)
        admin = self.p.child_is_admin()
        enforce = st["limited"] and admin is False and bool(self.p.child_user()) and not self.p.bypassed()
        logged_in = self.p.child_logged_in() if (enforce or self.pending()) else False

        if enforce and not st["allowed"]:
            grace = ls.get("grace_until")
            ann = ls.get("announced")
            announced = bool(ann) and ts - 3600 <= ann <= ts + 1
            if not ls["locked"] and logged_in and sched["warn"] and not grace and not announced:
                # Lock time arrived without the warnings (just applied, or the PC was asleep).
                grace = ts + sched["warn"] * 60
                ls["grace_until"] = grace
                self._log("lock time reached unannounced - warnings start now")
            if grace and grace > ts and logged_in:
                st = dict(st, allowed=True, next_lock=dt.datetime.fromtimestamp(grace))
        else:
            ls.pop("grace_until", None)

        if enforce and not st["allowed"]:
            was_locked = ls["locked"]
            ok, msg = self.p.set_locked(True)
            if ok:
                ls["locked"] = True
            else:
                self._log("could not lock: " + msg)
            ls.pop("grace_until", None)
            ls.pop("sent", None)
            ls.pop("announced", None)
            if logged_in:
                if not was_locked and sched["at_lock"] == "shutdown":
                    self._write(LOCKSTATE_FILE, ls)
                    self._log("lock time: shutting down")
                    self.p.power("shutdown")
                    return None
                self._log("lock time: logging the child out")
                self.p.logout()
        else:
            if ls["locked"]:
                ok, msg = self.p.set_locked(False)
                if ok:
                    ls["locked"] = False
                else:
                    self._log("could not unlock: " + msg)
            if enforce and st["next_lock"] and logged_in:
                remaining = (st["next_lock"] - now).total_seconds()
                key = st["next_lock"].strftime("%Y-%m-%d %H:%M")
                after = state_at(sched, st["next_lock"] + dt.timedelta(seconds=1), None)
                self._warn_lock(ls, key, remaining, sched, when_text(after["next_unlock"], now))
                due.append(remaining)
                due += [remaining - t for t in thresholds(sched["warn"]) if remaining - t > 0]
        if json.dumps(ls, sort_keys=True) != before:      # only when something changed
            self._write(LOCKSTATE_FILE, ls)

        pend = self.pending()
        if pend:
            remaining = pend["at"] - ts
            if remaining <= 0:
                self._remove(PENDING_FILE)
                self._log(f"delayed {pend['action']} now")
                if pend["action"] == "logout":
                    if self.p.child_logged_in():
                        self.p.logout()
                else:
                    self.p.power(pend["action"])
                    return None
            else:
                self._warn_pending(pend, now)
                due.append(remaining)
                due += [remaining - t for t in thresholds(pend.get("warn", 0)) if remaining - t > 0]
        due = [d for d in due if d > 0]
        return min(due) if due else None
