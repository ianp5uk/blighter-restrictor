# -----------------------------------------------------------------------------
# Blighter Restrictor - wrapping row of controls.
#
# Purpose: a layout that places widgets left to right like a line of text and
# moves the rest onto the next line when the space runs out.  The Filters and
# Activity tabs use it for their rows of switches, so those tabs no longer
# demand a wide window: at large text sizes the rows wrap instead, and the
# divider between the children list and the tabs can still be moved.
# Based on Qt's "Flow Layout" example.  hbox() builds a small non-wrapping
# group (e.g. a label with its box) to keep together on one line.
#
# Copyright (C) 2026 Ian Packer
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version.  It is distributed WITHOUT ANY WARRANTY; see the
# LICENSE file or <https://www.gnu.org/licenses/> for details.
# -----------------------------------------------------------------------------

from PySide6.QtCore import QMargins, QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QHBoxLayout, QLayout, QSizePolicy, QWidget


class FlowLayout(QLayout):
    def __init__(self, parent=None, hspacing=12, vspacing=6):
        super().__init__(parent)
        self._items = []
        self._h, self._v = hspacing, vspacing
        self._stretchy = set()        # items that take the rest of their line
        self.setContentsMargins(QMargins(0, 0, 0, 0))

    # ---- QLayout plumbing -------------------------------------------------
    def addItem(self, item):
        self._items.append(item)

    def addWidget(self, w, stretch=False):
        super().addWidget(w)
        if stretch:
            self._stretchy.add(id(self._items[-1]))

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for it in self._items:
            size = size.expandedTo(it.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    # ---- placing ------------------------------------------------------------
    def _do_layout(self, rect, test_only):
        m = self.contentsMargins()
        eff = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        visible = [it for it in self._items if not (it.widget() and it.widget().isHidden())]
        lines, line, used = [], [], 0
        for it in visible:
            w = it.sizeHint().width()
            if line and used + self._h + w > eff.width():
                lines.append(line)
                line, used = [], 0
            used += (self._h if line else 0) + w
            line.append(it)
        if line:
            lines.append(line)
        y = eff.y()
        for line in lines:
            hint = [min(it.sizeHint().width(), eff.width()) for it in line]
            spare = eff.width() - sum(hint) - self._h * (len(line) - 1)
            grow = [it for it in line if id(it) in self._stretchy]
            if grow and spare > 0:
                extra = spare // len(grow)
                hint = [h + (extra if id(it) in self._stretchy else 0) for h, it in zip(hint, line)]
            height = max(it.sizeHint().height() for it in line)
            x = eff.x()
            for it, w in zip(line, hint):
                if not test_only:
                    h = it.sizeHint().height()
                    it.setGeometry(QRect(QPoint(x, y + (height - h) // 2), QSize(w, h)))
                x += w + self._h
            y += height + self._v
        return y - self._v - rect.y() + m.bottom() if lines else 0


def hbox(*widgets, stretch_index=None):
    """A small group kept together on one line (e.g. a label and its box)."""
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    for i, x in enumerate(widgets):
        lay.addWidget(x, 1 if i == stretch_index else 0)
    w.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
    return w
