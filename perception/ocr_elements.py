# perception/ocr_elements.py
"""
Full-frame OCR helpers for UI grounding.

These utilities convert EasyOCR line detections into the same element dictionary
shape used by UIA / vision extractors (name, bbox, center, control_type, etc.)
so downstream code (filter_elements, find_best_match) can treat them uniformly.

Design notes
------------
- EasyOCR returns quadrilateral polygons; we axis-align them to integer AABBs
  clipped to the image bounds.
- Short or low-confidence lines are dropped early to reduce noise for semantic
  matching (SentenceTransformer in grounding.matcher).
"""

from __future__ import annotations

from typing import Any

import numpy as np


def quad_to_axis_aligned_bbox(quad: list | np.ndarray) -> tuple[int, int, int, int]:
    """
    Convert an EasyOCR quadrilateral (4 corner points) to an integer axis-aligned box.

    Args:
        quad: Array-like of shape (4, 2) with (x, y) corners in image coordinates.

    Returns:
        (x1, y1, x2, y2) inclusive-min / exclusive-max style consistent with the rest
        of this repo (same convention as UIA rectangles: left, top, right, bottom).
    """
    pts = np.asarray(quad, dtype=np.float32).reshape(-1, 2)
    x1 = int(np.floor(pts[:, 0].min()))
    y1 = int(np.floor(pts[:, 1].min()))
    x2 = int(np.ceil(pts[:, 0].max()))
    y2 = int(np.ceil(pts[:, 1].max()))
    return x1, y1, x2, y2


def extract_ocr_elements_from_image(
    image: np.ndarray,
    reader: Any,
    *,
    conf_min: float = 0.35,
) -> list[dict]:
    """
    Run full-frame OCR and emit element dicts compatible with perception.ui_filter.

    Each element roughly mirrors UIA entries so matcher.build_element_description
    can concatenate name / parent fields the same way.

    Args:
        image: BGR screenshot (numpy HxWx3), same format as capture_screen().
        reader: Initialized easyocr.Reader instance (reused across commands for speed).
        conf_min: Per-line confidence cutoff from EasyOCR (0–1). Lines below this are
            discarded before matching.

    Returns:
        List of dicts with keys: name, control_type, parent_name, parent_type, bbox,
        center, is_icon, ocr_conf.
    """
    if image is None or image.size == 0:
        return []

    h, w = image.shape[:2]
    raw = reader.readtext(image)
    elements: list[dict] = []

    for bbox, text, conf in raw:
        # Normalize text; skip empty strings after stripping whitespace.
        t = (text or "").strip()
        if not t or float(conf) < float(conf_min):
            continue

        x1, y1, x2, y2 = quad_to_axis_aligned_bbox(bbox)
        # Clip to valid image rectangle to avoid negative indices downstream.
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)
        if x2 <= x1 or y2 <= y1:
            continue

        cx = (x1 + x2) // 2
        cy = (y1 + y2) // 2

        elements.append(
            {
                # Primary label for semantic matching (SentenceTransformer path).
                "name": t,
                # Distinguishes OCR-derived rows from UIA control types / YOLO icons.
                "control_type": "ocr_text",
                # Full-frame OCR has no explicit accessibility parent; keep empty strings
                # so build_element_description still concatenates cleanly.
                "parent_name": "",
                "parent_type": "",
                "bbox": (x1, y1, x2, y2),
                "center": (cx, cy),
                # Not a YOLO icon crop; icon matching in matcher uses is_icon=True.
                "is_icon": False,
                # Preserve raw OCR confidence for debugging / optional future gating.
                "ocr_conf": float(conf),
            }
        )

    return elements


def create_easyocr_reader(langs: list[str] | None = None, gpu: bool | None = None) -> Any:
    """
    Construct a single EasyOCR reader for the agent process.

    Kept as a small factory so main.py does not import easyocr/torch at module import
    time when running unrelated demos.

    Args:
        langs: BCP-like language tags EasyOCR understands, e.g. ["en"], ["en", "ko"].
        gpu: If None, auto-detect CUDA via torch.cuda.is_available().

    Returns:
        easyocr.Reader instance.
    """
    import easyocr
    import torch

    if langs is None:
        langs = ["en"]
    if gpu is None:
        gpu = bool(torch.cuda.is_available())
    return easyocr.Reader(list(langs), gpu=gpu)
