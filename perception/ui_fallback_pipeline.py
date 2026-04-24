# perception/ui_fallback_pipeline.py
"""
UIA → (optional full-frame OCR) → vision (YOLO icons + local OCR) helpers.

Stage runners are composed by ``main.py``: ``--mode both`` uses UIA then vision;
``--mode all`` inserts full-frame OCR between UIA and vision. Each stage returns raw element dicts (before
perception.ui_filter.filter_elements) so the caller can log counts, draw debug
overlays, and run grounding.matcher.find_best_match with a per-stage score
threshold.

Rationale
---------
- UIA is fast and precise when the target app exposes good accessibility names.
- When UIA names are missing or mismatched, full-frame OCR often still exposes
  visible text (menus, web content, dialog labels).
- When OCR is still insufficient (icons, sparse text), YOLO icon boxes plus
  localized OCR around each box (see perception.icon_utils.detect_icons) feeds
  the CLIP-heavy branch in the matcher for icon-like targets.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from perception.ui_extractor import extract_uia_elements, extract_vision_elements_from_image
from perception.ocr_elements import extract_ocr_elements_from_image


def run_uia_stage() -> list[dict]:
    """
    Collect UIA-backed control elements from the foreground desktop window.

    Implementation is ``perception.ui_extractor.extract_uia_elements()``:

    * Default: classic ``descendants(depth=20)``.
    * If env ``VOICE_UI_UIA_NATIVE_ONSCREEN=1``: ``perception.uia_onscreen_extractor``
      (native ``IsOffscreen`` / UIA property 30022 + DFS subtree prune). Unset to revert.

    Returns:
        Raw element dicts (may be empty if the tree is sparse or pywinauto cannot attach).

    Raises:
        May propagate pywinauto exceptions; main.py typically catches and falls back.
    """
    return extract_uia_elements()


def run_fullframe_ocr_stage(
    screen_bgr: np.ndarray,
    ocr_reader: Any,
    *,
    conf_min: float = 0.35,
) -> list[dict]:
    """
    Run EasyOCR over the entire screenshot and convert lines to element dicts.

    Args:
        screen_bgr: Fresh screenshot without debug drawings overlaid.
        ocr_reader: Shared easyocr.Reader (constructed once in main for latency).
        conf_min: Minimum per-line OCR confidence (see demos/ocr_grounded_agent_demo).

    Returns:
        Element dicts suitable for filter_elements / find_best_match.
    """
    return extract_ocr_elements_from_image(screen_bgr, ocr_reader, conf_min=conf_min)


def run_vision_icon_stage(screen_bgr: np.ndarray) -> list[dict]:
    """
    YOLO class-0 icon boxes plus localized OCR crops (perception.icon_utils).

    Args:
        screen_bgr: Same-resolution capture as used for OCR; must align with bbox
            coordinates produced by YOLO on this tensor.

    Returns:
        Raw vision elements (is_icon=True entries carry OCR text in ``name`` / ``text``).
    """
    return extract_vision_elements_from_image(screen_bgr)


# Human-readable labels for logging in main.py when stepping through the cascade.
STAGE_UIA = "uia"
STAGE_OCR = "ocr"
STAGE_VISION = "vision"
