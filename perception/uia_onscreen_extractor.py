# perception/uia_onscreen_extractor.py
"""
Drop-in UIA extractor that prefers **native ``IsOffscreen``** (UIA 30022) and prunes
entire subtrees when the platform reports ``True``.

Why a separate module
----------------------
* **Default path:** ``ui_extractor.extract_uia_elements`` dispatches here (including
  ``run_uia_stage`` / ``--mode uia`` / cascades that start with UIA).
* **Classic tree:** set ``VOICE_UI_UIA_USE_CLASSIC=1`` in the environment to use
  ``descendants(depth=20)`` in ``ui_extractor`` instead.

Behavior
--------
* Depth-first walk (``children()`` stack) up to ``max_depth`` (default 20).
* If ``IsOffscreen`` resolves to **True**, we **do not descend** and **do not append**
  that node — same assumption as the UIA spec (off-screen subtrees are not interactable).
* If ``IsOffscreen`` cannot be read (**None**), we **do not prune** on that signal alone
  (conservative fallback so unknown backends still return elements).

This is independent of pywinauto's high-level ``descendants()`` flattening, so we avoid
enumerating descendants of nodes that are already off-screen.
"""

from __future__ import annotations

import os
from typing import Any, Optional

from pywinauto import Application

from perception.icon_like import uia_icon_like

# Microsoft UI Automation property id (UIAutomationClient.h)
UIA_IsOffscreenPropertyId = 30022

# Same exclusions as ``perception.ui_extractor`` for comparable output.
EXCLUDE_TYPES = frozenset(
    {
        "Static",
        "Groupbox",
        "ListItems",
        "ListItem",
        "GroupBox",
    }
)


def _unwrap_iui_automation_element(element_info: Any) -> Any:
    """Best-effort pointer to the underlying ``IUIAutomationElement`` COM object."""
    for attr in ("_element", "element", "iface", "native_element"):
        raw = getattr(element_info, attr, None)
        if raw is not None:
            return raw
    return None


def read_current_is_offscreen(wrapper: Any) -> Optional[bool]:
    """
    Return ``True`` / ``False`` from UIA ``CurrentIsOffscreen``, or ``None`` if unknown.

    Order:
        1. Public attributes on ``UIAElementInfo`` (newer pywinauto builds).
        2. ``IUIAutomationElement.CurrentIsOffscreen`` / ``get_CurrentIsOffscreen``.
        3. ``GetCurrentPropertyValue(UIA_IsOffscreenPropertyId)`` (VARIANT → bool).
    """
    try:
        ei = wrapper.element_info
    except Exception:
        return None

    for attr in ("is_offscreen", "current_is_offscreen"):
        if hasattr(ei, attr):
            try:
                v = getattr(ei, attr)
                if callable(v):
                    v = v()
                if isinstance(v, bool):
                    return v
            except Exception:
                continue

    raw = _unwrap_iui_automation_element(ei)
    if raw is None:
        return None

    try:
        if hasattr(raw, "CurrentIsOffscreen"):
            v = raw.CurrentIsOffscreen
            if isinstance(v, bool):
                return v
    except Exception:
        pass

    try:
        if hasattr(raw, "get_CurrentIsOffscreen"):
            v = raw.get_CurrentIsOffscreen()
            if isinstance(v, bool):
                return v
    except Exception:
        pass

    try:
        if hasattr(raw, "GetCurrentPropertyValue"):
            v = raw.GetCurrentPropertyValue(UIA_IsOffscreenPropertyId)
            # comtypes VARIANT often exposes .value
            if hasattr(v, "value"):
                inner = v.value
                if isinstance(inner, bool):
                    return inner
                # COM VT_BOOL true is often -1 (0xFFFF) as int
                if isinstance(inner, int):
                    return inner != 0
            if isinstance(v, bool):
                return v
            if isinstance(v, int):
                return v != 0
    except Exception:
        pass

    return None


def extract_uia_elements(
    *,
    max_depth: int = 20,
    max_visits: int = 50_000,
) -> list[dict]:
    """
    Collect UIA element dicts from the active top window using **IsOffscreen-pruned DFS**.

    Environment (optional):
        ``VOICE_UI_UIA_MAX_DEPTH`` — override max tree depth (integer).
    """
    depth_env = os.environ.get("VOICE_UI_UIA_MAX_DEPTH", "").strip()
    if depth_env.isdigit():
        max_depth = int(depth_env)

    app = Application(backend="uia").connect(active_only=True)
    window = app.top_window()

    elements: list[dict] = []
    visits = 0

    try:
        roots = list(window.children())
    except Exception:
        roots = []

    stack: list[tuple[Any, int]] = [(ch, 1) for ch in reversed(roots)]

    while stack:
        if visits >= max_visits:
            print(
                f"[uia_onscreen] Visit budget {max_visits} hit; "
                "stopping (raise budget or fall back to OCR/vision)."
            )
            break

        wrap, d = stack.pop()
        visits += 1

        if d > max_depth:
            continue

        try:
            off = read_current_is_offscreen(wrap)
            if off is True:
                continue

            rect = wrap.rectangle()
            control_type = wrap.friendly_class_name()
            name = wrap.window_text()
        except Exception:
            continue

        if control_type in EXCLUDE_TYPES:
            # Still descend: excluded types may wrap useful descendants.
            pass
        else:
            try:
                parent = wrap.parent()
                parent_name = ""
                parent_type = ""
                if parent:
                    parent_name = parent.window_text()
                    parent_type = parent.friendly_class_name()

                mp = rect.mid_point()
                cx, cy = int(mp.x), int(mp.y)
                bbox = (rect.left, rect.top, rect.right, rect.bottom)
                elements.append(
                    {
                        "name": name,
                        "control_type": control_type,
                        "parent_name": parent_name,
                        "parent_type": parent_type,
                        "bbox": bbox,
                        "center": (cx, cy),
                        "is_icon": False,
                        "icon_like": uia_icon_like(control_type, bbox, name),
                    }
                )
            except Exception:
                pass

        if d >= max_depth:
            continue

        try:
            kids = list(wrap.children())
        except Exception:
            continue

        for ch in reversed(kids):
            stack.append((ch, d + 1))

    return elements
