# automation/window_focus.py
# Activate a top-level Windows window by matching its title (substring, case-insensitive).

from __future__ import annotations

import ctypes

import win32con
import win32gui
import win32process


def _bring_hwnd_to_foreground(hwnd: int) -> None:
    if not hwnd or not win32gui.IsWindow(hwnd):
        return
    try:
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    except Exception:
        pass

    foreground_hwnd = win32gui.GetForegroundWindow()
    foreground_tid = 0
    if foreground_hwnd:
        foreground_tid = win32process.GetWindowThreadProcessId(foreground_hwnd)[0]

    current_tid = ctypes.windll.kernel32.GetCurrentThreadId()
    attached = False
    if foreground_tid and foreground_tid != current_tid:
        if ctypes.windll.user32.AttachThreadInput(foreground_tid, current_tid, True):
            attached = True
    try:
        win32gui.SetForegroundWindow(hwnd)
    except Exception:
        pass
    finally:
        if attached:
            ctypes.windll.user32.AttachThreadInput(foreground_tid, current_tid, False)


def _title_match_score(title: str, needle_lower: str) -> int:
    t = title.strip().lower()
    if not t:
        return 0
    if t == needle_lower:
        return 3
    if t.startswith(needle_lower):
        return 2
    if needle_lower in t:
        return 1
    return 0


def activate_window_by_title_substring(substring: str) -> str | None:
    """
    Find a visible top-level window whose title matches ``substring`` and bring it to the foreground.

    Matching is case-insensitive. Multiple matches: best score wins (exact > prefix > contains),
    then earliest in ``EnumWindows`` order (typically higher in Z-order).

    Returns:
        ``None`` on success, or a short error message on failure.
    """
    needle = (substring or "").strip()
    if not needle:
        return "focus needs text after the word focus, e.g. focus Chrome."

    needle_lower = needle.lower()
    candidates: list[tuple[int, int, int, str]] = []  # (-score, index, hwnd, title)

    def _enum(hwnd: int, _: object) -> bool:
        if not win32gui.IsWindowVisible(hwnd):
            return True
        try:
            if win32gui.GetWindow(hwnd, win32con.GW_OWNER):
                return True
        except Exception:
            pass
        try:
            title = win32gui.GetWindowText(hwnd)
        except Exception:
            return True
        if not title.strip():
            return True
        score = _title_match_score(title, needle_lower)
        if score <= 0:
            return True
        try:
            style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
            if style & win32con.WS_EX_TOOLWINDOW:
                return True
        except Exception:
            pass
        idx = len(candidates)
        candidates.append((-score, idx, hwnd, title))
        return True

    try:
        win32gui.EnumWindows(_enum, None)
    except Exception as e:
        return f"Could not enumerate windows: {e}"

    if not candidates:
        return f"No visible window title matched {substring!r}. Try a shorter or different substring."

    candidates.sort(key=lambda row: (row[0], row[1]))
    _neg_score, _idx, hwnd, chosen_title = candidates[0]
    try:
        _bring_hwnd_to_foreground(hwnd)
    except Exception as e:
        return f"Could not activate {chosen_title!r}: {e}"

    return None
