# perception/ui_extractor.py
# UIA tree, vision (YOLO + local OCR on an image or live capture), and legacy ``both`` concat.
#
# Optional native on-screen UIA (``IsOffscreen`` / property 30022 + pruned DFS):
#   set environment variable ``VOICE_UI_UIA_NATIVE_ONSCREEN=1``
#   → ``extract_uia_elements()`` delegates to ``perception.uia_onscreen_extractor``.
#   Unset to restore classic ``descendants()`` behavior.

import os

from pywinauto import Application
from perception.screen_capture import capture_screen
from perception.icon_utils import detect_icons


def _native_onscreen_uia_enabled() -> bool:
    return os.environ.get("VOICE_UI_UIA_NATIVE_ONSCREEN", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def extract_uia_elements():
    """
    Walk the active window UIA tree and return raw element dicts.

    When ``VOICE_UI_UIA_NATIVE_ONSCREEN`` is set (see module doc), uses
    ``uia_onscreen_extractor`` (``IsOffscreen`` + DFS prune). Otherwise uses the
    classic ``descendants(depth=20)`` walk.
    """
    if _native_onscreen_uia_enabled():
        from perception.uia_onscreen_extractor import extract_uia_elements as _native_extract

        return _native_extract()

    return _extract_uia_elements_classic()


def _extract_uia_elements_classic():
    """Classic pywinauto ``descendants`` flattening (full tree up to depth 20)."""

    app = Application(backend="uia").connect(active_only=True)
    window = app.top_window()

    elements = []

    EXCLUDE_TYPES = {
        "Static",
        "Groupbox",
        "ListItems",
        "ListItem",
        "GroupBox",
    }

    for element in window.descendants(depth=20):

        try:
            rect = element.rectangle()
            parent = element.parent()

            name = element.window_text()
            control_type = element.friendly_class_name()

            if control_type in EXCLUDE_TYPES:
                continue

            parent_name = ""
            parent_type = ""

            if parent:
                parent_name = parent.window_text()
                parent_type = parent.friendly_class_name()

            mp = rect.mid_point()
            # mid_point() returns a pywinauto POINT, not a tuple — use plain ints for the rest of the stack.
            cx, cy = int(mp.x), int(mp.y)
            elements.append(
                {
                    "name": name,
                    "control_type": control_type,
                    "parent_name": parent_name,
                    "parent_type": parent_type,
                    "bbox": (rect.left, rect.top, rect.right, rect.bottom),
                    "center": (cx, cy),
                    "is_icon": False,
                }
            )

        except Exception:
            continue

    return elements


def extract_vision_elements_from_image(screen):
    """
    YOLO icon detection + localized OCR around each box on a provided BGR image.

    This lets main.py reuse one fresh ``capture_screen()`` for OCR and vision
    without a second full-screen grab.

    Args:
        screen: numpy BGR array (HxWx3).

    Returns:
        List of element dicts with ``is_icon`` set True for CLIP matching.
    """
    icons = detect_icons(screen)

    print("YOLO boxes:", len(icons))

    elements = []

    for icon in icons:

        x1, y1, x2, y2 = icon["bbox"]
        text = icon["text"]

        elements.append(
            {
                "name": text,
                "control_type": "icon",
                "parent_name": "",
                "parent_type": "",
                "bbox": (x1, y1, x2, y2),
                "center": ((x1 + x2) // 2, (y1 + y2) // 2),
                "is_icon": True,
            }
        )

    return elements


def extract_vision_elements():
    """Live full-screen capture, then YOLO + localized OCR (wrapper)."""

    screen = capture_screen()
    return extract_vision_elements_from_image(screen)


def extract_elements_by_mode(mode: str):
    """
    Dispatch **single-source** extraction used by ``main.py`` for ``--mode uia`` and
    ``--mode vision`` only.

    Do **not** pass ``ocr``, ``both``, or ``all`` here:

    * ``ocr`` needs an ``easyocr.Reader`` and is implemented in
      ``perception.ocr_elements.extract_ocr_elements_from_image`` (see ``main.py``).
    * ``both`` / ``all`` are **sequential fallbacks**, implemented in ``main.py``
      via ``perception.ui_fallback_pipeline``.

    Args:
        mode: Exactly ``"uia"`` or ``"vision"``.

    Returns:
        Raw element dicts before ``perception.ui_filter.filter_elements``.
    """
    if mode == "uia":
        return extract_uia_elements()

    if mode == "vision":
        return extract_vision_elements()

    if mode == "both":
        try:
            uia = extract_uia_elements()
        except Exception:
            print("[both] UIA failed → vision only")
            uia = []
            vision = extract_vision_elements()
            return uia + vision

        vision = []
        return uia + vision

    if mode in ("ocr", "all"):
        raise ValueError(
            f"extract_elements_by_mode({mode!r}) is not supported. "
            f"Use main.py --mode {mode}, or perception.ocr_elements / "
            f"perception.ui_fallback_pipeline for cascade steps."
        )

    raise ValueError(
        f"Unknown mode: {mode!r}. extract_elements_by_mode only accepts "
        "'uia', 'vision', or legacy 'both' (concatenated lists)."
    )
