# perception/icon_like.py
# Heuristic ``icon_like`` for UIA elements: dataset / stage-2 tagging only.
# Does NOT set ``is_icon`` — runtime CLIP runs only on YOLO vision elements.

from __future__ import annotations

ICON_LIKE_CONTROL_TYPES = frozenset(
    {
        "Button",
        "Image",
        "SplitButton",
        "MenuItem",
        "CheckBox",  # small toolbar toggles
    }
)

# Toolbar-style controls (px on screen; tune via env if needed).
_ICON_LIKE_MAX_LONG_EDGE = 128
_ICON_LIKE_MIN_LONG_EDGE = 10
_ICON_LIKE_ASPECT_MIN = 0.55
_ICON_LIKE_ASPECT_MAX = 1.85


def uia_icon_like(
    control_type: str,
    bbox: tuple[int, int, int, int] | None,
    name: str | None = None,
) -> bool:
    """
    True when a UIA control looks like a small, roughly square icon/button.

    ``name`` is optional (empty toolbar glyphs are still icon-like).
    """
    if not control_type or control_type not in ICON_LIKE_CONTROL_TYPES:
        return False
    if bbox is None:
        return False
    try:
        x1, y1, x2, y2 = (int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3]))
    except (TypeError, ValueError, IndexError):
        return False
    w, h = x2 - x1, y2 - y1
    if w <= 0 or h <= 0:
        return False
    long_edge = max(w, h)
    if long_edge < _ICON_LIKE_MIN_LONG_EDGE or long_edge > _ICON_LIKE_MAX_LONG_EDGE:
        return False
    aspect = w / float(h)
    if aspect < _ICON_LIKE_ASPECT_MIN or aspect > _ICON_LIKE_ASPECT_MAX:
        return False
    return True
