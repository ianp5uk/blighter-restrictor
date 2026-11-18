# -----------------------------------------------------------------------------
# Blighter Restrictor - look and feel.
#
# Purpose: one place for the parent app's styling, using only Qt's built-in
# palette, style sheet and cursor features (plus one Windows call for the
# title bar colour).  Applied in light mode only - in dark mode the system
# look is left alone so nothing becomes unreadable.
#   * the grey around the white panels is made slightly darker
#   * Windows 11: the title bar ("Blighter Restrictor x.y.z") is tinted a
#     little darker so it stands apart (not possible on Linux - GNOME draws
#     the title bar itself; Windows 10 ignores the request)
#   * buttons get a clear border; the border turns blue on hover and the
#     button darkens and its text nudges down when pressed.  The default
#     button (Apply to laptop, Save) keeps a blue border
#   * a pointing-finger cursor over buttons, check boxes, radio buttons,
#     drop-downs and tabs
#   * Linux: a Segoe UI-like font, and Windows-style check boxes / radio
#     buttons (blue with a white tick / dot when on) that grow with the text
#     size from View > Larger / Smaller text
# The colours are constants below so they can be adjusted easily.
#
# Copyright (C) 2026 Ways Property
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version.  It is distributed WITHOUT ANY WARRANTY; see the
# LICENSE file or <https://www.gnu.org/licenses/> for details.
# -----------------------------------------------------------------------------

import os
import sys

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QFont, QFontMetrics, QPalette
from PySide6.QtWidgets import (QAbstractButton, QApplication, QCheckBox, QComboBox,
                               QPushButton, QRadioButton, QTabBar)

IS_WINDOWS = sys.platform.startswith("win")
CHECK_SVG = os.path.join(os.path.dirname(__file__), "check.svg").replace("\\", "/")

# ---- adjustable shades -----------------------------------------------------------
WINDOW_DARKER = 104      # grey around the panels: 100 = unchanged, larger = darker
TITLE_DARKER = 106       # title bar, relative to that grey (Windows 11 only)
ACCENT = "#0078d4"       # Windows blue
ACCENT_HOVER = "#106ebe"
ACCENT_PRESSED = "#005a9e"
BTN_BG = "#fdfdfd"
BTN_BORDER = "#8a8a8a"
BTN_HOVER_BG = "#e5f1fb"
BTN_PRESSED_BG = "#cce4f7"
IND_BORDER = "#5f5f5f"   # Linux check box / radio button border

# Nearest freely available fonts to Windows' Segoe UI, in order of preference
# (the first one installed is used).
LINUX_FONTS = ["Segoe UI", "Selawik", "Noto Sans", "Ubuntu Sans", "Ubuntu", "DejaVu Sans"]

_POINTER_TYPES = (QAbstractButton, QComboBox, QTabBar)


def _is_light(app):
    return app.palette().color(QPalette.Window).lightness() > 128


class _Polisher(QObject):
    """Sets the pointing-finger cursor on clickable controls as they are
    created, and tints the title bar of each window as it is shown."""

    def __init__(self, title_colour=None):
        super().__init__()
        self.title_colour = title_colour

    def eventFilter(self, obj, ev):
        t = ev.type()
        if t == QEvent.Polish and isinstance(obj, _POINTER_TYPES):
            obj.setCursor(Qt.PointingHandCursor)
        elif t == QEvent.Show and self.title_colour is not None and obj.isWidgetType() and obj.isWindow():
            _tint_title_bar(obj, self.title_colour)
        return False


def _tint_title_bar(window, colour):
    """Windows 11 only (DWMWA_CAPTION_COLOR); earlier Windows ignores it."""
    try:
        import ctypes
        ref = ctypes.c_uint(colour.red() | (colour.green() << 8) | (colour.blue() << 16))
        ctypes.windll.dwmapi.DwmSetWindowAttribute(ctypes.c_void_p(int(window.winId())), 35,
                                                   ctypes.byref(ref), ctypes.sizeof(ref))
    except Exception:
        pass


def setup(app):
    """Call once, after QApplication is created and before any window."""
    if not IS_WINDOWS:
        f = QFont(app.font())
        f.setFamilies(LINUX_FONTS)
        app.setFont(f)
    title = None
    if _is_light(app):
        pal = app.palette()
        window = pal.color(QPalette.Window).darker(WINDOW_DARKER)
        pal.setColor(QPalette.Window, window)
        app.setPalette(pal)
        if IS_WINDOWS:
            title = window.darker(TITLE_DARKER)
    app._blighter_polisher = _Polisher(title)     # kept alive with the app
    app.installEventFilter(app._blighter_polisher)
    apply_stylesheet(app)


def apply_stylesheet(app):
    """(Re)build the style sheet for the current text size; called again when
    the text size changes so check boxes and buttons grow with the text."""
    if not _is_light(app):
        app.setStyleSheet("")
        return
    h = QFontMetrics(app.font()).height()
    pad_v = max(3, round(h * 0.22))
    pad_h = max(10, round(h * 0.7))
    css = f"""
QPushButton {{
    background: {BTN_BG}; border: 1px solid {BTN_BORDER}; border-radius: 4px;
    padding: {pad_v}px {pad_h}px; color: palette(button-text);
}}
QPushButton:default {{ border: 1px solid {ACCENT}; }}
QPushButton:hover {{ background: {BTN_HOVER_BG}; border: 1px solid {ACCENT}; }}
QPushButton:pressed {{
    background: {BTN_PRESSED_BG}; border: 1px solid {ACCENT_PRESSED};
    padding-top: {pad_v + 1}px; padding-bottom: {max(0, pad_v - 1)}px;
}}
QPushButton:disabled {{ background: #f3f3f3; border: 1px solid #c6c6c6; color: #a0a0a0; }}
"""
    if not IS_WINDOWS:
        s = max(14, round(h * 0.85))
        css += f"""
QCheckBox, QRadioButton {{ spacing: {max(5, round(h * 0.35))}px; }}
QCheckBox::indicator, QRadioButton::indicator {{
    width: {s}px; height: {s}px; border: 1px solid {IND_BORDER}; background: white;
}}
QCheckBox::indicator {{ border-radius: 3px; }}
QRadioButton::indicator {{ border-radius: {s // 2 + 1}px; }}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{ border-color: {ACCENT}; }}
QCheckBox::indicator:checked {{
    background: {ACCENT}; border-color: {ACCENT}; image: url("{CHECK_SVG}");
}}
QCheckBox::indicator:checked:hover {{ background: {ACCENT_HOVER}; border-color: {ACCENT_HOVER}; }}
QRadioButton::indicator:checked {{
    border-color: {ACCENT};
    background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5,
        stop:0 white, stop:0.36 white, stop:0.44 {ACCENT}, stop:1 {ACCENT});
}}
QCheckBox::indicator:disabled, QRadioButton::indicator:disabled {{
    border-color: #b8b8b8; background: #f0f0f0;
}}
QCheckBox::indicator:checked:disabled {{ background: #a6c8e8; border-color: #a6c8e8; }}
QRadioButton::indicator:checked:disabled {{
    border-color: #a6c8e8;
    background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5,
        stop:0 white, stop:0.36 white, stop:0.44 #a6c8e8, stop:1 #a6c8e8);
}}
"""
    app.setStyleSheet(css)
