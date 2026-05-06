# perception/grounding_cascade.py
"""
Shared UIA → (optional OCR) → vision grounding steps for ``main.py`` cascade modes.

Keeps logging, thresholds, and frame refresh behavior identical to the former inlined blocks.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from grounding.matcher import find_best_match
from perception.debug_draw import draw_elements, show_debug
from perception.screen_capture import capture_screen
from perception.ui_filter import filter_elements
from perception.ui_fallback_pipeline import (
    run_fullframe_ocr_stage,
    run_uia_stage,
    run_vision_icon_stage,
    STAGE_OCR,
    STAGE_UIA,
    STAGE_VISION,
)


def _print_uia_listing(uia_filtered: list[dict]) -> None:
    for i, el in enumerate(uia_filtered):
        print(
            f"  [{i + 1}] Name: {el['name']}, Type: {el['type']} | "
            f"P Name: {el['parent_name']} Type: {el['parent_type']}"
        )


def run_uia_match_step(
    frame: np.ndarray,
    query: str,
    *,
    uia_threshold: int,
    heading: str,
    no_match_fallback_message: str,
    used_mode_on_miss: str,
) -> tuple[dict | None, float, str, np.ndarray]:
    """
    Try UIA extraction + semantic match. On confident match, keep ``frame`` raw and
    return ``used_mode`` = ``STAGE_UIA``. Otherwise refresh ``frame`` from screen,
    optionally save debug of UIA candidates, and return ``match`` is None.
    """
    print(heading)

    try:
        uia_elements = run_uia_stage()
        uia_filtered = filter_elements(uia_elements)

        print(f"[UIA] {len(uia_elements)} → {len(uia_filtered)}")

        _print_uia_listing(uia_filtered)

        match, score = find_best_match(query, uia_filtered, screen=frame)

        if match and score > uia_threshold:
            return match, score, STAGE_UIA, frame

        if match:
            print("[UIA] Best candidate:", match["name"], "| score:", score)
        print(no_match_fallback_message)
        if uia_filtered:
            show_debug(draw_elements(frame.copy(), uia_filtered))
        return None, float(score), used_mode_on_miss, capture_screen()

    except Exception as e:
        print("[UIA] Failed:", e)
        return None, 0.0, used_mode_on_miss, capture_screen()


def run_ocr_match_step(
    frame: np.ndarray,
    query: str,
    ocr_reader: Any,
    *,
    ocr_threshold: int,
    heading: str,
    no_match_fallback_message: str,
    used_mode_on_miss: str,
) -> tuple[dict | None, float, str, np.ndarray]:
    """Full-frame OCR stage (``all`` cascade only)."""
    print(heading)

    ocr_elements = run_fullframe_ocr_stage(frame, ocr_reader, conf_min=0.35)
    ocr_filtered = filter_elements(ocr_elements)

    print(f"[OCR] {len(ocr_elements)} lines → {len(ocr_filtered)} after filter")

    match, score = find_best_match(query, ocr_filtered, screen=frame)

    if match and score > ocr_threshold:
        return match, score, STAGE_OCR, frame

    if match:
        print("[OCR] Best candidate:", match["name"], "| score:", score)
    print(no_match_fallback_message)
    return None, float(score), used_mode_on_miss, frame


def run_vision_match_step(
    frame: np.ndarray,
    query: str,
    *,
    vision_threshold: int,
    heading: str,
    used_mode_on_miss: str,
) -> tuple[dict | None, float, str, np.ndarray]:
    """YOLO icons + localized OCR stage."""
    print(heading)

    vision_elements = run_vision_icon_stage(frame)
    vision_filtered = filter_elements(vision_elements)

    print(f"[Vision] {len(vision_elements)} → {len(vision_filtered)}")

    match, score = find_best_match(query, vision_filtered, screen=frame)

    if match and score > vision_threshold:
        return match, score, STAGE_VISION, frame

    if match:
        print("[Vision] Best candidate:", match["name"], "| score:", score)
    return None, float(score), used_mode_on_miss, frame
