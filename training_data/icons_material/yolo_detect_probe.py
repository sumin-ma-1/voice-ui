#!/usr/bin/env python3
"""
YOLO-only check on labeled screen cases: box count + best IoU vs GT bbox.

Use to compare default imgsz (640) vs larger (1280) on big desktops.

From repo root:
  python training_data/icons_material/yolo_detect_probe.py
  python training_data/icons_material/yolo_detect_probe.py --compare auto 640 1280
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_CASES = REPO_ROOT / "training_data/icons_material/eval_cases.json"


@dataclass(frozen=True)
class ScreenCase:
    image_path: Path
    query: str
    bbox: tuple[int, int, int, int]


def load_cases(path: Path) -> list[ScreenCase]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    out: list[ScreenCase] = []
    for row in raw:
        img = REPO_ROOT / row["image"] if not Path(row["image"]).is_absolute() else Path(row["image"])
        if not img.is_file():
            img = path.parent / row["image"]
        out.append(
            ScreenCase(
                image_path=img,
                query=str(row.get("query", "")),
                bbox=tuple(int(x) for x in row["bbox"]),
            )
        )
    return out


def bbox_iou(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0
    inter = (ix2 - ix1) * (iy2 - iy1)
    union = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - inter
    return inter / union if union > 0 else 0.0


def run_probe(
    cases: list[ScreenCase],
    imgsz: int | str | None,
    *,
    iou_threshold: float,
) -> dict[str, float]:
    import os

    from perception.icon_utils import detect_icons, yolo_imgsz_for_frame

    if imgsz == "auto":
        os.environ["VOICE_UI_YOLO_IMGSZ"] = "auto"
        predict_imgsz: int | None = None
    elif isinstance(imgsz, int):
        predict_imgsz = imgsz
    else:
        predict_imgsz = None

    hit = 0
    total_boxes = 0
    for case in cases:
        screen = cv2.imread(str(case.image_path))
        if screen is None:
            print(f"  [skip] cannot read {case.image_path}")
            continue
        h, w = screen.shape[:2]
        if imgsz == "auto":
            eff = yolo_imgsz_for_frame(h, w)
            icons = detect_icons(screen)
        else:
            eff = predict_imgsz if predict_imgsz is not None else 640
            icons = detect_icons(screen, imgsz=predict_imgsz)
        boxes = [tuple(ic["bbox"]) for ic in icons]
        total_boxes += len(boxes)
        if not boxes:
            print(
                f"  {case.image_path.name}  query={case.query!r}  "
                f"size={screen.shape[1]}x{screen.shape[0]}  boxes=0  best_iou=—"
            )
            continue
        ious = [bbox_iou(case.bbox, b) for b in boxes]
        best = float(max(ious))
        ok = best >= iou_threshold
        if ok:
            hit += 1
        mark = "OK" if ok else "miss"
        print(
            f"  {case.image_path.name}  query={case.query!r}  "
            f"size={w}x{h} imgsz={eff}  boxes={len(boxes)}  "
            f"best_iou={best:.2f}  [{mark}]"
        )

    n = len(cases)
    print(
        f"  => GT matched (IoU>={iou_threshold}): {hit}/{n}  "
        f"avg_boxes_per_image={total_boxes / n:.1f}"
    )
    return {"hit": float(hit), "n": float(n)}


def main() -> None:
    p = argparse.ArgumentParser(description="YOLO detection probe on labeled screen cases.")
    p.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    p.add_argument("--iou-threshold", type=float, default=0.5)
    p.add_argument(
        "--compare",
        nargs="+",
        metavar="IMGSZ",
        help="Run side by side: auto, off, or integers (e.g. --compare auto 640 1280).",
    )
    p.add_argument(
        "--imgsz",
        type=int,
        default=None,
        help="Single imgsz run; omit for Ultralytics default (640).",
    )
    args = p.parse_args()

    if not args.cases.is_file():
        print(f"Missing cases file: {args.cases}")
        sys.exit(1)

    cases = load_cases(args.cases)
    sizes: list[int | None]
    def _parse_size(token: str) -> int | str | None:
        t = token.strip().lower()
        if t in ("auto", "off", "default"):
            return t
        return int(t)

    if args.compare:
        sizes = [_parse_size(t) for t in args.compare]
    else:
        sizes = [args.imgsz]

    for sz in sizes:
        if sz == "off" or sz == "default":
            import os

            os.environ["VOICE_UI_YOLO_IMGSZ"] = "off"
            label = "off (640)"
            run_sz: int | str | None = None
        elif sz == "auto":
            label = "auto"
            run_sz = "auto"
        elif sz is None:
            label = "off (640)"
            run_sz = None
        else:
            label = str(sz)
            run_sz = int(sz)
        print(f"\n=== YOLO imgsz={label} ===")
        run_probe(cases, run_sz, iou_threshold=args.iou_threshold)


if __name__ == "__main__":
    main()
