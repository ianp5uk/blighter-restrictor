# -----------------------------------------------------------------------------
# Blighter Restrictor - tests for common/lockout.py (login times, warnings,
# delayed actions).
#
# Purpose: check the schedule rules and the PC-side engine with a pretend PC
# and a pretend clock, so every case (warnings at 15 and 5 minutes, lock at
# the end of a period, extra time, grace when the schedule is applied late,
# administrators never locked, fail-open on a bad file) runs in seconds.
# Run:  python3 -m unittest discover -s tests
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
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "common"))
import lockout  # noqa: E402

MON = dt.datetime(2026, 11, 30)   # a Monday


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += dt.timedelta(seconds=s)


class FakePC:
    def __init__(self, folder):
        self.state_dir = folder
        self.user = "kid"
        self.admin = False
        self.locked = False
        self.logged_in = True
        self.notes = []
        self.events = []
        self.off = False

    def child_user(self):
        return self.user

    def child_is_admin(self):
        return self.admin

    def set_locked(self, locked):
        # Like the real helpers: only a change is recorded.
        if locked != self.locked:
            self.events.append("lock" if locked else "unlock")
        self.locked = locked
        self.calls = getattr(self, "calls", 0) + 1
        return True, ""

    def child_logged_in(self):
        return self.logged_in

    def logout(self):
        self.logged_in = False
        self.events.append("logout")
        return True, ""

    def power(self, action):
        self.logged_in = False
        self.events.append(action)
        return True, ""

    def notify(self, title, text):
        self.notes.append(text)

    def bypassed(self):
        return self.off


def sched(days=None, warn=15, at_lock="logout", enabled=True):
    d = days if days is not None else [[["07:00", "21:00"]]] * 7
    return {"enabled": enabled, "days": d, "warn": warn, "at_lock": at_lock}


class Rules(unittest.TestCase):
    def test_validation(self):
        s, e = lockout.clean_schedule(sched())
        self.assertFalse(e)
        _, e = lockout.clean_schedule(sched(days=[[["21:00", "07:00"]]] + [[]] * 6))
        self.assertTrue(any("midnight" in x for x in e))
        _, e = lockout.clean_schedule(sched(days=[[["07:03", "08:00"]]] + [[]] * 6))
        self.assertTrue(e)
        _, e = lockout.clean_schedule(sched(days=[[["07:00", "12:00"], ["11:00", "13:00"]]] + [[]] * 6))
        self.assertTrue(any("overlap" in x for x in e))
        s, e = lockout.clean_schedule(sched(days=[[["15:00", "24:00"], ["07:00", "08:00"]]] + [[]] * 6))
        self.assertFalse(e)
        self.assertEqual(s["days"][0], [["07:00", "08:00"], ["15:00", "24:00"]])

    def test_state_and_midnight_join(self):
        days = [[["07:00", "08:00"], ["15:00", "24:00"]], [["00:00", "01:00"]]] + [[]] * 5
        s, _ = lockout.clean_schedule(sched(days=days))
        st = lockout.state_at(s, MON.replace(hour=23))
        self.assertTrue(st["allowed"])
        self.assertEqual(st["next_lock"], MON + dt.timedelta(days=1, hours=1))   # runs on past midnight
        st = lockout.state_at(s, MON.replace(hour=12))
        self.assertFalse(st["allowed"])
        self.assertEqual(st["next_unlock"], MON.replace(hour=15))
        self.assertFalse(lockout.state_at(lockout.empty_schedule(), MON)["limited"])

    def test_bad_file_fails_open(self):
        self.assertFalse(lockout.load_schedule("{not json")["enabled"])
        self.assertFalse(lockout.load_schedule('{"enabled": true, "days": []}')["enabled"])


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.pc = FakePC(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def engine(self, clock):
        return lockout.Engine(self.pc, now=clock, sleep=clock.sleep)

    def run_minutes(self, eng, clock, minutes):
        for _ in range(minutes):
            eng.tick()
            clock.t = clock.t.replace(second=0, microsecond=0) + dt.timedelta(minutes=1)

    def test_warnings_then_logout(self):
        c = Clock(MON.replace(hour=20, minute=40))
        e = self.engine(c)
        self.assertTrue(e.set_schedule(sched())[0])
        self.run_minutes(e, c, 25)          # 20:40 .. 21:05
        self.assertEqual(len(self.pc.notes), 2, self.pc.notes)
        self.assertIn("15 minutes", self.pc.notes[0])
        self.assertIn("5 minutes", self.pc.notes[1])
        self.assertIn("07:00 tomorrow", self.pc.notes[0])
        self.assertEqual(self.pc.events, ["lock", "logout"])
        self.assertTrue(self.pc.locked)
        c.t = MON.replace(hour=23)
        e.tick()
        self.assertEqual(self.pc.events, ["lock", "logout"])   # still locked, no new logout
        c.t = MON + dt.timedelta(days=1, hours=7, minutes=1)
        e.tick()
        self.assertFalse(self.pc.locked)

    def test_shutdown_at_lock(self):
        c = Clock(MON.replace(hour=20, minute=50))
        e = self.engine(c)
        e.set_schedule(sched(warn=5, at_lock="shutdown"))
        self.run_minutes(e, c, 15)
        self.assertEqual(len(self.pc.notes), 1)
        self.assertIn("shut down", self.pc.notes[0])
        self.assertIn("shutdown", self.pc.events)

    def test_applied_during_locked_time_gives_grace(self):
        c = Clock(MON.replace(hour=22))
        e = self.engine(c)
        e.set_schedule(sched(warn=15))
        e.tick()
        self.assertFalse(self.pc.locked)
        self.assertIn("15 minutes", self.pc.notes[0])
        self.run_minutes(e, c, 16)
        self.assertTrue(self.pc.locked)
        self.assertIn("logout", self.pc.events)
        self.assertEqual(len(self.pc.notes), 2)

    def test_not_logged_in_locks_at_once(self):
        self.pc.logged_in = False
        c = Clock(MON.replace(hour=22))
        e = self.engine(c)
        e.set_schedule(sched())
        e.tick()
        self.assertTrue(self.pc.locked)
        self.assertEqual(self.pc.notes, [])

    def test_no_warning_choice(self):
        c = Clock(MON.replace(hour=22))
        e = self.engine(c)
        e.set_schedule(sched(warn=0))
        e.tick()
        self.assertEqual(self.pc.events, ["lock", "logout"])

    def test_extra_time(self):
        c = Clock(MON.replace(hour=21, minute=30))
        self.pc.logged_in = False
        e = self.engine(c)
        e.set_schedule(sched())
        e.tick()
        self.assertTrue(self.pc.locked)
        self.assertTrue(e.set_extension("22:30")[0])
        e.tick()
        self.assertFalse(self.pc.locked)
        self.pc.logged_in = True
        c.t = MON.replace(hour=22, minute=15)
        e.tick()
        self.assertIn("15 minutes", self.pc.notes[-1])
        self.assertIn("22:30", self.pc.notes[-1])
        self.run_minutes(e, c, 17)
        self.assertTrue(self.pc.locked)
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, lockout.EXTENSION_FILE)))
        self.assertFalse(e.set_extension("21:00")[0])       # already passed

    def test_admin_never_locked(self):
        self.pc.admin = True
        c = Clock(MON.replace(hour=22))
        e = self.engine(c)
        self.assertFalse(e.set_schedule(sched())[0])
        e._write(lockout.SCHEDULE_FILE, sched())            # even if a schedule is there
        e.tick()
        self.assertEqual(self.pc.events, [])
        self.pc.admin = None
        e.tick()
        self.assertEqual(self.pc.events, [])

    def test_switched_off_unlocks(self):
        self.pc.logged_in = False
        c = Clock(MON.replace(hour=22))
        e = self.engine(c)
        e.set_schedule(sched())
        e.tick()
        self.assertTrue(self.pc.locked)
        self.pc.off = True
        e.tick()
        self.assertFalse(self.pc.locked)

    def test_schedule_off_unlocks_and_release(self):
        self.pc.logged_in = False
        c = Clock(MON.replace(hour=22))
        e = self.engine(c)
        e.set_schedule(sched())
        e.tick()
        e.set_schedule(sched(enabled=False))
        e.tick()
        self.assertFalse(self.pc.locked)
        e.set_schedule(sched())
        e.tick()
        self.assertTrue(e.release()[0])
        self.assertFalse(self.pc.locked)

    def test_never_unlocks_what_it_did_not_lock(self):
        c = Clock(MON.replace(hour=12))
        e = self.engine(c)
        e.tick()
        self.assertEqual(self.pc.events, [])

    def test_pending_15_and_5(self):
        c = Clock(MON.replace(hour=18))
        e = self.engine(c)
        ok, msg = e.set_pending("shutdown", 15)
        self.assertTrue(ok)
        self.assertIn("18:15", msg)
        self.assertEqual(len(self.pc.notes), 1)
        self.assertIn("15 minutes", self.pc.notes[0])
        self.run_minutes(e, c, 16)
        self.assertEqual(len(self.pc.notes), 2)
        self.assertIn("5 minutes", self.pc.notes[1])
        self.assertEqual(self.pc.events, ["shutdown"])
        self.assertIsNone(e.pending())

    def test_pending_on_time(self):
        """The action happens at its time, not up to a minute late."""
        c = Clock(MON.replace(hour=18, second=20))
        e = self.engine(c)
        e.set_pending("restart", 5)
        c.t = MON.replace(hour=18, minute=4, second=30)
        e.tick()
        self.assertEqual(self.pc.events, ["restart"])
        self.assertLessEqual(abs((c.t - MON.replace(hour=18, minute=5, second=20)).total_seconds()), 5)

    def test_pending_cancel_and_logout_not_logged_in(self):
        c = Clock(MON.replace(hour=18))
        e = self.engine(c)
        e.set_pending("logout", 5)
        ok, msg = e.cancel_pending()
        self.assertIn("cancelled", msg)
        self.assertIn("cancelled", self.pc.notes[-1])
        self.run_minutes(e, c, 7)
        self.assertEqual(self.pc.events, [])
        self.pc.logged_in = False
        ok, msg = e.set_pending("logout", 5)
        self.assertIn("not logged in", msg)
        self.assertIsNone(e.pending())

    def test_describe(self):
        c = Clock(MON.replace(hour=20))
        e = self.engine(c)
        e.set_schedule(sched())
        d = e.describe()
        self.assertTrue(d["allowed"])
        self.assertEqual(d["next_lock"], "21:00")
        self.assertTrue(d["enforced"])


if __name__ == "__main__":
    unittest.main()
