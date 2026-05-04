#!/usr/bin/env python3
"""
OCR-grounded agent demo (same interaction style as main.py).

  - Floating prompt (TextInputGUI) for commands
  - Full-screen capture → EasyOCR with per-line bbox + confidence
  - Elements shaped like UIA/vision entries → filter_elements → find_best_match
  - execute() for click / hover / double_click and direct actions

Examples:
  click Save
  hover Downloads
  double click Documents

Run from repo root:
  python demos/ocr_grounded_agent_demo.py
  python demos/ocr_grounded_agent_demo.py --lang en ko --debug # debug mode will save the annotated screenshot to the test_screen_img folder

Exit: type exit, quit, stop agent, or shutdown (same as main.py).
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from speech.text_input_gui import TextInputGUI
from speech.command_parser import parse_command
from perception.ui_filter import filter_elements
from grounding.matcher import find_best_match
from automation.executor import execute
from automation.action_space import (
    DIRECT_ACTIONS,
    GROUNDED_ACTIONS,
    POST_GROUNDING_CLICK_DELAY_ACTIONS,
    UNKNOWN_ACTION,
    is_office_action,
)
from perception.screen_capture import capture_screen
from perception.debug_draw import draw_elements, draw_match, show_debug

from com.office_controller import OfficeController

# SentenceTransformer cosine * 100; short OCR strings often score lower than UIA names
OCR_SCORE_THRESHOLD = 18.0


def _quad_to_aabb(quad: list | np.ndarray) -> tuple[int, int, int, int]:
    pts = np.asarray(quad, dtype=np.float32).reshape(-1, 2)
    x1 = int(np.floor(pts[:, 0].min()))
    y1 = int(np.floor(pts[:, 1].min()))
    x2 = int(np.ceil(pts[:, 0].max()))
    y2 = int(np.ceil(pts[:, 1].max()))
    return x1, y1, x2, y2


def extract_ocr_elements(
    image: np.ndarray,
    reader,
    conf_min: float = 0.35,
) -> list[dict]:
    """Full-frame OCR → UI-shaped element dicts (bbox, center, name)."""
    h, w = image.shape[:2]
    raw = reader.readtext(image)
    elements: list[dict] = []
    for bbox, text, conf in raw:
        t = (text or "").strip()
        if not t or float(conf) < conf_min:
            continue
        x1, y1, x2, y2 = _quad_to_aabb(bbox)
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)
        if x2 <= x1 or y2 <= y1:
            continue
        cx = (x1 + x2) // 2
        cy = (y1 + y2) // 2
        elements.append(
            {
                "name": t,
                "control_type": "ocr_text",
                "parent_name": "",
                "parent_type": "",
                "bbox": (x1, y1, x2, y2),
                "center": (cx, cy),
                "is_icon": False,
                "ocr_conf": float(conf),
            }
        )
    return elements


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--lang",
        nargs="+",
        default=["en"],
        help="EasyOCR language list, e.g. en ko",
    )
    ap.add_argument(
        "--ocr-conf",
        type=float,
        default=0.35,
        help="Minimum EasyOCR confidence per line",
    )
    ap.add_argument(
        "--threshold",
        type=float,
        default=OCR_SCORE_THRESHOLD,
        help="Min match score (SentenceTransformer path, 0–100 scale)",
    )
    ap.add_argument(
        "--debug",
        action="store_true",
        help="After a grounded action, save annotated screenshot via show_debug",
    )
    args = ap.parse_args()

    import easyocr
    import torch

    gpu = torch.cuda.is_available()
    reader = easyocr.Reader(list(args.lang), gpu=gpu)

    text_input = TextInputGUI()
    office = OfficeController()

    print("OCR-grounded agent demo (EasyOCR + semantic match + execute)")
    print(f"Languages: {args.lang} | match threshold: {args.threshold}")
    print('Commands like main.py, e.g. "click Save". Exit: exit / quit / stop agent / shutdown')

    while True:
        frame = None
        try:
            text = text_input.get_input()
            if not text:
                continue

            if text.lower() in ["exit", "quit", "stop agent", "shutdown"]:
                print("Shutting down...")
                break

            print("User typed:", text)
            start = time.time()

            command = parse_command(text)
            action = command["action"]
            print("Parsed:", command)

            if action == UNKNOWN_ACTION:
                print(
                    "Could not parse that as a known command. "
                    "Try: click <OCR text>, type hello, or copy."
                )
                continue

            if is_office_action(command.get("action", "")):
                print("Office COM command")
                ok = office.execute(command)
                print(f"Office ok={ok} | {time.time() - start:.2f}s")
                continue

            if action in DIRECT_ACTIONS:
                result = execute(action, element=None, params=command)
                if not result.ok:
                    print(result.reason)
                else:
                    print(f"Direct action done | {time.time() - start:.2f}s")
                continue

            if action not in GROUNDED_ACTIONS:
                print(f"Action {action!r} not wired for OCR grounding in this demo.")
                continue

            frame = capture_screen()
            elements = extract_ocr_elements(frame, reader, conf_min=args.ocr_conf)
            filtered = filter_elements(elements)

            print(f"[OCR] lines: {len(elements)} → after filter: {len(filtered)}")
            for i, el in enumerate(elements[:40]):
                x1, y1, x2, y2 = el["bbox"]
                print(
                    f"  [{i}] {el['name']!r} bbox=({x1},{y1},{x2},{y2}) "
                    f"conf={el.get('ocr_conf', 0):.2f}"
                )
            if len(elements) > 40:
                print(f"  ... +{len(elements) - 40} more (pre-filter)")

            query = command.get("query", text)
            match, score = find_best_match(query, filtered, screen=frame)

            print(f"Query: {query!r} | best: {match['name'] if match else None} | score: {score:.1f}")

            if match and score > args.threshold:
                vis = draw_elements(frame, filtered)
                vis = draw_match(vis, match)
                if args.debug:
                    show_debug(vis)
                result = execute(action, element=match, params=command)
                if not result.ok:
                    print(result.reason)
                else:
                    if action in POST_GROUNDING_CLICK_DELAY_ACTIONS:
                        time.sleep(1.0)
                    print(f"Executed {action} | {time.time() - start:.2f}s")
            else:
                print("No confident OCR text match (lower --threshold or fix wording).")
                if args.debug and filtered:
                    show_debug(draw_elements(frame.copy(), filtered))

        except KeyboardInterrupt:
            print("\nCancelled; waiting for next command...")
            continue
        except Exception as e:
            print("Error:", e)


if __name__ == "__main__":
    main()
