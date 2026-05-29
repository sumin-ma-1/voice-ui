"""
Split browser collection into window chrome vs in-page UI.

- ``chrome_only``: toolbar / window controls (back, reload, minimize, …)
- ``page_only``: candidates that are not classified as browser chrome (for history URLs)
- ``both``: no extra filter (default)
"""

from __future__ import annotations

from typing import Any

# Substrings in UIA ``name`` typical of Chromium window chrome (EN UI).
_CHROME_NAME_FRAGMENTS: tuple[str, ...] = (
    "minimize",
    "maximize",
    "close",
    "restore",
    "back",
    "forward",
    "reload",
    "refresh",
    "home",
    "extensions",
    "bookmark",
    "new tab",
    "tab search",
    "menu",
    "zoom:",
    "zoom ",
    "pan up",
    "pan down",
    "view site information",
    "settings and more",
    "customize and control",
    "profile",
    "install ",
    "chrome ",
    "microsoft edge",
)

_VALID_MODES = frozenset({"both", "chrome_only", "page_only"})


def normalize_browser_ui_mode(mode: str | None) -> str:
    m = (mode or "both").strip().lower()
    return m if m in _VALID_MODES else "both"


def _name_suggests_browser_chrome(name: str) -> bool:
    n = (name or "").strip().lower()
    if not n:
        return False
    return any(frag in n for frag in _CHROME_NAME_FRAGMENTS)


def _bbox_center_y(bbox: Any) -> float | None:
    try:
        x1, y1, x2, y2 = bbox
        return (float(y1) + float(y2)) / 2.0
    except Exception:
        return None


def _bbox_in_chrome_band(bbox: Any, *, frame_h: int, chrome_band_ratio: float) -> bool:
    try:
        _x1, y1, _x2, y2 = bbox
        band = max(40, int(frame_h * chrome_band_ratio))
        # Control mostly in the top band (title bar + tabs + toolbar on Windows)
        return float(y2) <= band or float(y1) < band * 0.85
    except Exception:
        return False


def is_browser_chrome_control(
    element: dict[str, Any],
    *,
    frame_h: int,
    chrome_band_ratio: float = 0.16,
) -> bool:
    """True if element looks like browser window chrome, not page content."""
    name = str(element.get("name") or "")
    if _name_suggests_browser_chrome(name):
        return True
    bbox = element.get("bbox")
    if bbox and _bbox_in_chrome_band(bbox, frame_h=frame_h, chrome_band_ratio=chrome_band_ratio):
        # Top band alone is weak; require short label or empty name (icon-only toolbar)
        cy = _bbox_center_y(bbox)
        band = max(40, int(frame_h * chrome_band_ratio))
        if cy is not None and cy <= band:
            if not name.strip() or len(name) < 48:
                return True
    return False


def filter_icon_candidates_for_browser_ui(
    candidates: list[dict[str, Any]],
    *,
    mode: str,
    frame: Any,
    chrome_band_ratio: float = 0.16,
    strict_top_band: bool = False,
) -> list[dict[str, Any]]:
    mode = normalize_browser_ui_mode(mode)
    if mode == "both" or not candidates:
        return candidates

    h = 1080
    if frame is not None:
        try:
            h = int(frame.shape[0])
        except Exception:
            pass

    if mode == "chrome_only":
        return [
            e
            for e in candidates
            if is_browser_chrome_control(e, frame_h=h, chrome_band_ratio=chrome_band_ratio)
        ]
    # page_only
    out = [
        e
        for e in candidates
        if not is_browser_chrome_control(e, frame_h=h, chrome_band_ratio=chrome_band_ratio)
    ]
    if strict_top_band:
        # History pages: drop any icon_like still in the tab/toolbar band (repeats every URL).
        out = [
            e
            for e in out
            if not _bbox_in_chrome_band(e.get("bbox"), frame_h=h, chrome_band_ratio=chrome_band_ratio)
        ]
    return out


def is_blank_browser_tab(window_title: str) -> bool:
    """Heuristic: new tab / about:blank — good time to snapshot browser chrome once."""
    t = (window_title or "").strip().lower()
    if not t:
        return False
    if "about:blank" in t:
        return True
    if "new tab" in t:
        return True
    if t in ("google chrome", "chrome", "microsoft edge", "edge"):
        return True
    # Localized Edge/Chrome sometimes: title ends with browser name only
    for suffix in (" - google chrome", " - microsoft edge"):
        if t.endswith(suffix) and len(t) < len(suffix) + 40:
            inner = t[: -len(suffix)].strip()
            if not inner or inner in ("new tab", "about:blank", "새 탭", "새 탭 -"):
                return True
    return False


def resolve_browser_ui_settings(
    target: dict[str, Any] | None,
    *,
    cfg: dict[str, Any],
    history: bool = False,
) -> dict[str, Any]:
    """
    Merge per-target ``browser_ui``, ``browser_defaults``, and ``browser_history.browser_ui``.
    """
    defaults = cfg.get("browser_defaults") if isinstance(cfg.get("browser_defaults"), dict) else {}
    ratio = float(defaults.get("chrome_band_ratio", 0.16))

    mode = "both"
    require_blank = False
    strict_top_band = False
    dedupe_across_pages = False

    if history:
        hist = cfg.get("browser_history") if isinstance(cfg.get("browser_history"), dict) else {}
        bu = hist.get("browser_ui") if isinstance(hist.get("browser_ui"), dict) else {}
        mode = bu.get("mode", hist.get("ui_mode", "page_only"))
        ratio = float(bu.get("chrome_band_ratio", ratio))
        strict_top_band = bool(bu.get("strict_top_band", True))
        dedupe_across_pages = bool(bu.get("dedupe_across_pages", True))
    elif target:
        bu = target.get("browser_ui") if isinstance(target.get("browser_ui"), dict) else {}
        if bu:
            mode = bu.get("mode", mode)
            require_blank = bool(bu.get("require_blank_tab", False))
            ratio = float(bu.get("chrome_band_ratio", ratio))
            strict_top_band = bool(bu.get("strict_top_band", False))
        else:
            title = str(target.get("title_substring") or "").lower()
            if "chrome" in title or "edge" in title:
                mode = str(defaults.get("mode_for_browsers", "chrome_only"))
                require_blank = bool(defaults.get("require_blank_tab_for_browsers", True))

    return {
        "mode": normalize_browser_ui_mode(str(mode)),
        "require_blank_tab": require_blank,
        "chrome_band_ratio": ratio,
        "strict_top_band": strict_top_band,
        "dedupe_across_pages": dedupe_across_pages,
    }
