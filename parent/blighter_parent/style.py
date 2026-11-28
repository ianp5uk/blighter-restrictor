# -----------------------------------------------------------------------------
# Blighter Restrictor - look and feel.
#
# Purpose: one place for the parent app's styling, using only Qt's built-in
# palette, style sheet and cursor features (plus one Windows call for the
# title bar colour).  Mostly applied in light mode only - in dark mode the
# system look is left alone so nothing becomes unreadable, except the Linux
# check boxes and radio buttons (see below).
#   * the grey around the white panels is made slightly darker
#   * Windows 11: the title bar ("Blighter Restrictor x.y.z") is tinted a
#     little darker so it stands apart (not possible on Linux - GNOME draws
#     the title bar itself; Windows 10 ignores the request)
#   * buttons get a clear border; the border turns blue on hover and the
#     button darkens and its text nudges down when pressed.  The default
#     button (Apply to PC, Save) keeps a blue border
#   * a pointing-finger cursor over buttons, check boxes, radio buttons,
#     drop-downs and tabs
#   * Linux: a Segoe UI-like font, and Windows-style check boxes / radio
#     buttons (blue with a white tick / dot when on) that grow with the text
#     size from View > Larger / Smaller text.  Since 1.4.0 they are a little
#     larger and have a 2-pixel border, and dark mode gets its own colours
#     (a light border on a dark box), because GNOME's dark-mode ones are
#     hard to see - especially when not ticked
# The colours are constants below so they can be adjusted easily.
#
# Copyright (C) 2026 Ian Packer
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
IND_BORDER = "#5f5f5f"   # Linux check box / radio button border (light mode)
# Linux check boxes / radio buttons in dark mode
DARK_IND_BORDER = "#d0d0d0"
DARK_IND_BG = "#1e1e1e"
DARK_ACCENT = "#3d9be9"
DARK_ACCENT_HOVER = "#62b0f0"
DARK_DISABLED_BORDER = "#6a6a6a"
DARK_DISABLED_BG = "#2e2e2e"
DARK_DISABLED_ON = "#3c5a75"

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


def _indicator_css(h, light):
    """Linux check boxes and radio buttons, sized from the text height h."""
    s = max(16, round(h * 0.95))
    if light:
        border, bg, accent, hover = IND_BORDER, "white", ACCENT, ACCENT_HOVER
        dis_border, dis_bg, dis_on = "#b8b8b8", "#f0f0f0", "#a6c8e8"
    else:
        border, bg, accent, hover = DARK_IND_BORDER, DARK_IND_BG, DARK_ACCENT, DARK_ACCENT_HOVER
        dis_border, dis_bg, dis_on = DARK_DISABLED_BORDER, DARK_DISABLED_BG, DARK_DISABLED_ON
    return f"""
QCheckBox, QRadioButton {{ spacing: {max(6, round(h * 0.4))}px; }}
QCheckBox::indicator, QRadioButton::indicator {{
    width: {s}px; height: {s}px; border: 2px solid {border}; background: {bg};
}}
QCheckBox::indicator {{ border-radius: 3px; }}
QRadioButton::indicator {{ border-radius: {s // 2 + 2}px; }}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{ border-color: {accent}; }}
QCheckBox::indicator:checked {{
    background: {accent}; border-color: {accent}; image: url("{CHECK_SVG}");
}}
QCheckBox::indicator:checked:hover {{ background: {hover}; border-color: {hover}; }}
QRadioButton::indicator:checked {{
    border-color: {accent};
    background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5,
        stop:0 white, stop:0.36 white, stop:0.44 {accent}, stop:1 {accent});
}}
QCheckBox::indicator:disabled, QRadioButton::indicator:disabled {{
    border-color: {dis_border}; background: {dis_bg};
}}
QCheckBox::indicator:checked:disabled {{ background: {dis_on}; border-color: {dis_on}; }}
QRadioButton::indicator:checked:disabled {{
    border-color: {dis_on};
    background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5,
        stop:0 white, stop:0.36 white, stop:0.44 {dis_on}, stop:1 {dis_on});
}}
"""


def apply_stylesheet(app):
    """(Re)build the style sheet for the current text size; called again when
    the text size changes so check boxes and buttons grow with the text."""
    h = QFontMetrics(app.font()).height()
    if not _is_light(app):
        app.setStyleSheet("" if IS_WINDOWS else _indicator_css(h, light=False))
        return
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
        css += _indicator_css(h, light=True)
    app.setStyleSheet(css)
