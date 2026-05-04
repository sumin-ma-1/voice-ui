# automation/win32_scroll.py
# Reliable mouse wheel scrolling on Windows (PyAutoGUI's ``hscroll`` uses vertical wheel only).
#
# MSDN: ``MOUSEEVENTF_WHEEL`` / ``MOUSEEVENTF_HWHEEL`` with ``dwData`` in multiples of 120 (WHEEL_DELTA).

from __future__ import annotations

import ctypes
import sys

import pyautogui

MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_HWHEEL = 0x01000
WHEEL_DELTA = 120


def _screen_size() -> tuple[int, int]:
    w = int(ctypes.windll.user32.GetSystemMetrics(0))
    h = int(ctypes.windll.user32.GetSystemMetrics(1))
    return max(1, w), max(1, h)


def _mouse_wheel_event(flags: int, x: int, y: int, dw_data: int) -> None:
    width, height = _screen_size()
    cx = max(0, min(width - 1, int(x)))
    cy = max(0, min(height - 1, int(y)))
    converted_x = 65536 * cx // width + 1
    converted_y = 65536 * cy // height + 1
    ctypes.windll.user32.mouse_event(
        flags,
        ctypes.c_long(converted_x),
        ctypes.c_long(converted_y),
        int(dw_data),
        0,
    )


def _amount_to_notches(amount: int) -> int:
    """Map legacy ``amount`` (often 500) to a small number of wheel detents."""
    a = abs(int(amount))
    if a <= 30:
        return max(1, a // 10)
    return max(3, min(25, a // 100))


def scroll_at_cursor(direction: str, amount: int = 500) -> None:
    """
    Vertical or horizontal wheel at the **current** cursor (same as PyAutoGUI).

    ``direction``: ``up`` | ``down`` | ``left`` | ``right``.
    """
    if sys.platform != "win32":
        raise OSError("win32_scroll.scroll_at_cursor is Windows-only")

    x, y = pyautogui.position()
    notches = _amount_to_notches(amount)

    if direction == "up":
        for _ in range(notches):
            _mouse_wheel_event(MOUSEEVENTF_WHEEL, x, y, WHEEL_DELTA)
    elif direction == "down":
        for _ in range(notches):
            _mouse_wheel_event(MOUSEEVENTF_WHEEL, x, y, -WHEEL_DELTA)
    elif direction == "right":
        for _ in range(notches):
            _mouse_wheel_event(MOUSEEVENTF_HWHEEL, x, y, WHEEL_DELTA)
    elif direction == "left":
        for _ in range(notches):
            _mouse_wheel_event(MOUSEEVENTF_HWHEEL, x, y, -WHEEL_DELTA)
    else:
        raise ValueError(f"Unknown scroll direction: {direction!r}")
