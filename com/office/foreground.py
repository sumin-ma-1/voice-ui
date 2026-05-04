# com/office/foreground.py
# Bring Excel / Word / PowerPoint COM main windows to the foreground on Windows.

from __future__ import annotations

import ctypes
from typing import Any

import win32con
import win32gui
import win32process


def office_application_hwnd(app: Any) -> int:
    """Return a top-level HWND for an Office ``Application`` COM object, or 0."""
    if app is None:
        return 0
    for name in ("Hwnd", "HWND", "hWnd"):
        if hasattr(app, name):
            try:
                v = int(getattr(app, name))
                if v:
                    return v
            except (TypeError, ValueError):
                continue
    try:
        w = getattr(app, "ActiveWindow", None)
        if w is not None and hasattr(w, "Hwnd"):
            return int(w.Hwnd)
    except Exception:
        pass
    return 0


def bring_com_application_to_foreground(app: Any) -> None:
    """
    Raise the Office application's main window so it is not stuck behind the agent UI.

    Uses ``ShowWindow`` + ``SetForegroundWindow`` with ``AttachThreadInput`` so the call
    works more reliably when our process is not the foreground app (common for COM).
    """
    if app is None:
        return
    try:
        if hasattr(app, "Activate"):
            app.Activate()
    except Exception:
        pass

    hwnd = office_application_hwnd(app)
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
