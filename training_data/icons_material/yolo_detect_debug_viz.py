#!/usr/bin/env python3
"""
Draw YOLO detections vs labeled GT bbox on eval screenshots.

Outputs (per case):
  - ``{stem}_full.jpg``  — full frame (downscaled for viewing) + all det boxes + GT
  - ``{stem}_zoom.jpg``  — crop around GT (and best det if any) for small icons

Colors (BGR):
  - Green thick: ground truth
  - Yellow thick: best IoU detection (candidate aligned to GT)
  - Cyan thin: other YOLO boxes

From repo root:
  python training_data/icons_material/yolo_detect_debug_viz.py
  python training_data/icons_material/yolo_detect_debug_viz.py --yolo-imgsz off
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_CASES = REPO_ROOT / "training_data/icons_material/eval_cases.json"
DEFAULT_OUT = REPO_ROOT / "training_data/icons_material/debug_yolo"


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


def _draw_box(
    img: np.ndarray,
    box: tuple[int, int, int, int],
    color: tuple[int, int, int],
    thickness: int,
    label: str | None = None,
) -> None:
    x1, y1, x2, y2 = box
    cv2.rectangle(img, (x1, y1), (x2, y2), color, thickness)
    if not label:
        return
    scale = max(0.45, min(1.2, img.shape[1] / 1920.0))
    font = cv2.FONT_HERSHEY_SIMPLEX
    fs = 0.55 * scale
    th = max(1, int(round(2 * scale)))
    (tw, th_text), _ = cv2.getTextSize(label, font, fs, th)
    ty = max(th_text + 4, y1 - 6)
    cv2.rectangle(img, (x1, ty - th_text - 6), (x1 + tw + 8, ty + 4), color, -1)
    cv2.putText(img, label, (x1 + 4, ty), font, fs, (0, 0, 0), th, cv2.LINE_AA)


def _fit_long_edge(img: np.ndarray, max_long: int) -> np.ndarray:
    h, w = img.shape[:2]
    long_edge = max(h, w)
    if long_edge <= max_long:
        return img
    scale = max_long / float(long_edge)
    nw, nh = int(round(w * scale)), int(round(h * scale))
    return cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA)


def _zoom_region(
    screen: np.ndarray,
    boxes: list[tuple[int, int, int, int]],
    *,
    pad_frac: float = 8.0,
    min_pad: int = 120,
) -> tuple[np.ndarray, int, int]:
    """Return crop and (ox, oy) origin in full-screen coordinates."""
    if not boxes:
        h, w = screen.shape[:2]
        return screen.copy(), 0, 0
    xs1 = [b[0] for b in boxes]
    ys1 = [b[1] for b in boxes]
    xs2 = [b[2] for b in boxes]
    ys2 = [b[3] for b in boxes]
    x1, y1, x2, y2 = min(xs1), min(ys1), max(xs2), max(ys2)
    bw, bh = max(1, x2 - x1), max(1, y2 - y1)
    pad = max(min_pad, int(max(bw, bh) * pad_frac))
    h, w = screen.shape[:2]
    ox = max(0, x1 - pad)
    oy = max(0, y1 - pad)
    cx2 = min(w, x2 + pad)
    cy2 = min(h, y2 + pad)
    return screen[oy:cy2, ox:cx2].copy(), ox, oy


def render_case(
    screen: np.ndarray,
    case: ScreenCase,
    det_boxes: list[tuple[int, int, int, int]],
    *,
    iou_threshold: float,
    eff_imgsz: int | None,
    max_full_long: int,
    max_zoom_long: int,
) -> tuple[np.ndarray, np.ndarray, dict]:
    vis = screen.copy()
    gt = case.bbox

    best_idx = -1
    best_iou = 0.0
    if det_boxes:
        ious = [bbox_iou(gt, b) for b in det_boxes]
        best_idx = int(np.argmax(ious))
        best_iou = float(ious[best_idx])

    hit = best_iou >= iou_threshold
    status = "HIT" if hit else "MISS"

    for i, box in enumerate(det_boxes):
        if i == best_idx:
            continue
        _draw_box(vis, box, (255, 200, 0), 1)  # cyan-ish thin

    if best_idx >= 0:
        _draw_box(
            vis,
            det_boxes[best_idx],
            (0, 255, 255),
            3,
            f"best IoU={best_iou:.2f}",
        )

    _draw_box(vis, gt, (0, 255, 0), 3, f"GT: {case.query!r}")

    imgsz_s = str(eff_imgsz) if eff_imgsz is not None else "640(default)"
    header = (
        f"{case.image_path.name}  query={case.query!r}  "
        f"imgsz={imgsz_s}  dets={len(det_boxes)}  {status} (IoU>={iou_threshold})"
    )
    scale = max(0.5, min(1.0, vis.shape[1] / 1920.0))
    cv2.putText(
        vis,
        header,
        (12, int(28 * scale + 8)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55 * scale,
        (255, 255, 255),
        max(1, int(2 * scale)),
        cv2.LINE_AA,
    )

    zoom_boxes = [gt]
    if best_idx >= 0:
        zoom_boxes.append(det_boxes[best_idx])
    zoom, ox, oy = _zoom_region(screen, zoom_boxes)
    zoom_vis = zoom.copy()
    zh, zw = zoom.shape[:2]

    def _shift(b: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
        return b[0] - ox, b[1] - oy, b[2] - ox, b[3] - oy

    for i, box in enumerate(det_boxes):
        if i == best_idx:
            continue
        sb = _shift(box)
        if sb[2] > 0 and sb[3] > 0 and sb[0] < zw and sb[1] < zh:
            _draw_box(zoom_vis, sb, (255, 200, 0), 1)

    if best_idx >= 0:
        sb = _shift(det_boxes[best_idx])
        _draw_box(zoom_vis, sb, (0, 255, 255), 3, f"best IoU={best_iou:.2f}")

    _draw_box(zoom_vis, _shift(gt), (0, 255, 0), 3, f"GT: {case.query!r}")

    cv2.putText(
        zoom_vis,
        f"{status} best_iou={best_iou:.2f}",
        (8, 24),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.65,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )

    full_out = _fit_long_edge(vis, max_full_long)
    zoom_out = _fit_long_edge(zoom_vis, max_zoom_long)

    meta = {
        "best_iou": best_iou,
        "hit": hit,
        "n_dets": len(det_boxes),
        "eff_imgsz": eff_imgsz,
    }
    return full_out, zoom_out, meta


def main() -> None:
    p = argparse.ArgumentParser(description="Save YOLO vs GT debug images for eval cases.")
    p.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    p.add_argument("--iou-threshold", type=float, default=0.5)
    p.add_argument(
        "--yolo-imgsz",
        type=str,
        default=None,
        help="Set VOICE_UI_YOLO_IMGSZ (auto, off, or e.g. 1280). Default: current env / auto.",
    )
    p.add_argument("--max-full-long", type=int, default=1920, help="Max long edge for _full.jpg")
    p.add_argument("--max-zoom-long", type=int, default=960, help="Max long edge for _zoom.jpg")
    args = p.parse_args()

    if args.yolo_imgsz is not None:
        os.environ["VOICE_UI_YOLO_IMGSZ"] = args.yolo_imgsz.strip()

    if not args.cases.is_file():
        print(f"Missing cases: {args.cases}")
        sys.exit(1)

    from perception.icon_utils import detect_icons, resolve_yolo_imgsz

    cases = load_cases(args.cases)
    args.out.mkdir(parents=True, exist_ok=True)

    hits = 0
    for case in cases:
        screen = cv2.imread(str(case.image_path))
        if screen is None:
            print(f"[skip] cannot read {case.image_path}")
            continue

        eff = resolve_yolo_imgsz(screen)
        icons = detect_icons(screen)
        det_boxes = [tuple(ic["bbox"]) for ic in icons]

        full, zoom, meta = render_case(
            screen,
            case,
            det_boxes,
            iou_threshold=args.iou_threshold,
            eff_imgsz=eff,
            max_full_long=args.max_full_long,
            max_zoom_long=args.max_zoom_long,
        )

        stem = case.image_path.stem
        full_path = args.out / f"{stem}_full.jpg"
        zoom_path = args.out / f"{stem}_zoom.jpg"
        cv2.imwrite(str(full_path), full, [cv2.IMWRITE_JPEG_QUALITY, 92])
        cv2.imwrite(str(zoom_path), zoom, [cv2.IMWRITE_JPEG_QUALITY, 92])

        if meta["hit"]:
            hits += 1
        print(
            f"  {stem}: {meta['n_dets']} dets  best_iou={meta['best_iou']:.2f}  "
            f"{'HIT' if meta['hit'] else 'MISS'}  -> {full_path.name} + {zoom_path.name}"
        )

    print(f"\nWrote {len(cases)} cases to {args.out}  (GT matched {hits}/{len(cases)})")
    print("Open *_zoom.jpg for icon-level detail; *_full.jpg for whole screen.")


if __name__ == "__main__":
    main()
