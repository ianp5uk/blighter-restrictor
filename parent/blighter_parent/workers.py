# -----------------------------------------------------------------------------
# Blighter Restrictor - background jobs.
#
# Purpose: run slow network work (SSH, log downloads, reachability checks) on
# a thread pool so the window never freezes, and deliver the result or error
# back on the GUI thread through a Qt signal.
# Usage:  run_bg(function, on_ok=callback(result), on_err=callback(message),
#                quiet=False)
# Every job that is not "quiet" counts as the app being busy: busy_signal()
# reports how many are running, so the main window can show "Working…".
# (Background polling - reachability, Live log refresh - is quiet.)
#
# Copyright (C) 2026 Ways Property
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version.  It is distributed WITHOUT ANY WARRANTY; see the
# LICENSE file or <https://www.gnu.org/licenses/> for details.
# -----------------------------------------------------------------------------

import traceback

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot


class _Dispatcher(QObject):
    """Lives on the GUI thread; calls callbacks there."""
    deliver = Signal(object, object)
    busy_changed = Signal(int)

    def __init__(self):
        super().__init__()
        self.deliver.connect(self._call)

    @Slot(object, object)
    def _call(self, callback, value):
        if callback:
            callback(value)


_dispatcher = None
_busy = 0


def _get_dispatcher():
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = _Dispatcher()
    return _dispatcher


def busy_signal():
    """Signal(int): number of non-quiet jobs running (0 = idle)."""
    return _get_dispatcher().busy_changed


class _Job(QRunnable):
    def __init__(self, fn, on_ok, on_err):
        super().__init__()
        self.fn, self.on_ok, self.on_err = fn, on_ok, on_err

    def run(self):
        try:
            result = self.fn()
        except Exception as e:  # report every failure to the GUI
            msg = str(e) or e.__class__.__name__
            if not getattr(e, "user_facing", False) and e.__class__.__name__ != "RemoteError":
                traceback.print_exc()
            _dispatcher.deliver.emit(self.on_err, msg)
            return
        _dispatcher.deliver.emit(self.on_ok, result)


def run_bg(fn, on_ok=None, on_err=None, quiet=False):
    d = _get_dispatcher()
    if not quiet:
        global _busy
        _busy += 1
        d.busy_changed.emit(_busy)

        def finished(callback):
            def call(value):
                global _busy
                _busy = max(0, _busy - 1)
                d.busy_changed.emit(_busy)
                if callback:
                    callback(value)
            return call
        on_ok, on_err = finished(on_ok), finished(on_err)
    QThreadPool.globalInstance().start(_Job(fn, on_ok, on_err))
