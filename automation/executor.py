# automation/executor.py
from __future__ import annotations

from typing import Any, Callable, NamedTuple

import pyautogui

from automation.action_space import GROUNDED_ACTIONS, PYAUTOGUI_ACTIONS

MOVE_DURATION = 0.15
TYPE_INTERVAL = 0.02

# Disable the fail-safe
# pyautogui.FAILSAFE = False


class ExecuteResult(NamedTuple):
    """Outcome of ``execute`` — use ``reason`` for user-facing or log lines when ``ok`` is False."""

    ok: bool
    reason: str | None = None


def _pair_xy_from_center(center: Any) -> tuple[int, int] | None:
    """
    Normalize ``center`` to ``(x, y)``.

    UIA extractors historically passed pywinauto ``POINT`` from ``rect.mid_point()``;
    those objects have ``.x`` / ``.y`` but no ``len()`` — tuples/lists use indexing.
    """
    if center is None:
        return None
    if hasattr(center, "x") and hasattr(center, "y"):
        try:
            return int(center.x), int(center.y)
        except (TypeError, ValueError):
            return None
    try:
        return int(center[0]), int(center[1])
    except (TypeError, ValueError, IndexError):
        return None


def _move_to_element(element: dict[str, Any] | None) -> ExecuteResult | None:
    """Move cursor to element center. Returns ``ExecuteResult`` on bad shape; ``None`` if ok or no element."""
    if not element:
        return None
    pair = _pair_xy_from_center(element.get("center"))
    if pair is None:
        return ExecuteResult(
            False,
            "Matched UI element has no valid center coordinates; cannot move the cursor.",
        )
    x, y = pair
    pyautogui.moveTo(x, y, duration=MOVE_DURATION)
    return None


def _validate(action: str, params: dict[str, Any], element: dict | None) -> ExecuteResult | None:
    if action not in PYAUTOGUI_ACTIONS:
        return ExecuteResult(
            False,
            f"Unsupported automation action {action!r}. "
            "This usually means a routing bug (action is not in automation.action_space.PYAUTOGUI_ACTIONS).",
        )
    if action in GROUNDED_ACTIONS and not element:
        return ExecuteResult(
            False,
            f"Action {action!r} needs a matched on-screen target. No element was provided after UI matching.",
        )
    if action == "press_key":
        key = params.get("key")
        if not key or not str(key).strip():
            return ExecuteResult(
                False,
                "press_key needs a key name after 'press' (e.g. press f5).",
            )
    if action == "hotkey":
        keys = params.get("keys") or []
        if not keys:
            return ExecuteResult(
                False,
                "hotkey needs key names after the word hotkey (e.g. hotkey ctrl s).",
            )
    if action == "scroll":
        direction = params.get("direction", "down")
        if direction not in ("up", "down", "left", "right"):
            return ExecuteResult(
                False,
                f"scroll direction must be up, down, left, or right; got {direction!r}.",
            )
    return None


def _run_left_click(_params: dict[str, Any]) -> None:
    pyautogui.click()


def _run_right_click(_params: dict[str, Any]) -> None:
    pyautogui.rightClick()


def _run_double_click(_params: dict[str, Any]) -> None:
    pyautogui.doubleClick()


def _run_hover(_params: dict[str, Any]) -> None:
    pass


def _run_scroll(params: dict[str, Any]) -> None:
    direction = params.get("direction", "down")
    amount = int(params.get("amount", 500))
    if direction == "up":
        pyautogui.scroll(amount)
    elif direction == "down":
        pyautogui.scroll(-amount)
    elif direction == "left":
        pyautogui.hscroll(-amount)
    else:
        pyautogui.hscroll(amount)


def _run_press_key(params: dict[str, Any]) -> None:
    pyautogui.press(params["key"])


def _run_hotkey(params: dict[str, Any]) -> None:
    keys = params.get("keys", [])
    pyautogui.hotkey(*keys)


def _run_enter(_params: dict[str, Any]) -> None:
    pyautogui.press("enter")


def _run_esc(_params: dict[str, Any]) -> None:
    pyautogui.press("esc")


def _run_tab(_params: dict[str, Any]) -> None:
    pyautogui.press("tab")


def _run_backspace(_params: dict[str, Any]) -> None:
    pyautogui.press("backspace")


def _run_delete(_params: dict[str, Any]) -> None:
    pyautogui.press("delete")


def _run_type(params: dict[str, Any]) -> None:
    text = params.get("text", "")
    pyautogui.write(text, interval=TYPE_INTERVAL)


def _run_select_all(_params: dict[str, Any]) -> None:
    pyautogui.hotkey("ctrl", "a")


def _run_copy(_params: dict[str, Any]) -> None:
    pyautogui.hotkey("ctrl", "c")


def _run_paste(_params: dict[str, Any]) -> None:
    pyautogui.hotkey("ctrl", "v")


def _run_cut(_params: dict[str, Any]) -> None:
    pyautogui.hotkey("ctrl", "x")


def _run_undo(_params: dict[str, Any]) -> None:
    pyautogui.hotkey("ctrl", "z")


def _run_redo(_params: dict[str, Any]) -> None:
    pyautogui.hotkey("ctrl", "y")


def _run_save(_params: dict[str, Any]) -> None:
    pyautogui.hotkey("ctrl", "s")


def _run_new_tab(_params: dict[str, Any]) -> None:
    pyautogui.hotkey("ctrl", "t")


def _run_close_tab(_params: dict[str, Any]) -> None:
    pyautogui.hotkey("ctrl", "w")


def _run_switch_tab(params: dict[str, Any]) -> None:
    direction = params.get("direction", "next")
    if direction == "next":
        pyautogui.hotkey("ctrl", "tab")
    else:
        pyautogui.hotkey("ctrl", "shift", "tab")


def _run_refresh(_params: dict[str, Any]) -> None:
    pyautogui.press("f5")


_RUNNERS: dict[str, Callable[[dict[str, Any]], None]] = {
    "left_click": _run_left_click,
    "right_click": _run_right_click,
    "double_click": _run_double_click,
    "hover": _run_hover,
    "scroll": _run_scroll,
    "press_key": _run_press_key,
    "hotkey": _run_hotkey,
    "enter": _run_enter,
    "esc": _run_esc,
    "tab": _run_tab,
    "backspace": _run_backspace,
    "delete": _run_delete,
    "type": _run_type,
    "select_all": _run_select_all,
    "copy": _run_copy,
    "paste": _run_paste,
    "cut": _run_cut,
    "undo": _run_undo,
    "redo": _run_redo,
    "save": _run_save,
    "new_tab": _run_new_tab,
    "close_tab": _run_close_tab,
    "switch_tab": _run_switch_tab,
    "refresh": _run_refresh,
}


def execute(action: str, element=None, params=None) -> ExecuteResult:
    """
    Run a PyAutoGUI automation. Returns :class:`ExecuteResult` instead of failing silently.

    Callers should print ``result.reason`` when ``not result.ok`` so users see parser failures
    vs unsupported actions vs missing parameters vs runtime errors distinctly.
    """
    params = dict(params or {})

    err = _validate(action, params, element)
    if err is not None:
        return err

    move_err = _move_to_element(element)
    if move_err is not None:
        return move_err

    runner = _RUNNERS.get(action)
    if runner is None:
        return ExecuteResult(
            False,
            f"No runner registered for action {action!r} (add it to _RUNNERS and action_space).",
        )

    try:
        runner(params)
    except Exception as e:
        return ExecuteResult(
            False,
            f"Automation failed while running {action!r}: {type(e).__name__}: {e}",
        )

    return ExecuteResult(True, None)
