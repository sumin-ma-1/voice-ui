# How to run
# 1. static image: python demos/explorer_icon_label_demo.py --image path/to/explorer.png --out demo_out.png
# 2. live capture: python demos/explorer_icon_label_demo.py --capture --out demo_out.png
"""
Demo: Explorer-style list — many identical folder icons with names on the RIGHT.

  - Full-frame EasyOCR (geometry preserved)
  - YOLO icon boxes (class 0), same weights as perception/icon_utils.py
  - Pair scoring: right-of-icon, vertical overlap / center alignment, OCR confidence
  - One-to-one assignment: scipy linear_sum_assignment if available, else greedy

Usage (from repo root, with epoch235.pt present):
  python demos/explorer_icon_label_demo.py --image path/to/explorer.png --out demo_out.png
  python demos/explorer_icon_label_demo.py --capture --out demo_out.png

Optional: pip install scipy  (better global matching when labels compete)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

# Repo root (parent of demos/)
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from scipy.optimize import linear_sum_assignment
except ImportError:
    linear_sum_assignment = None


def _quad_to_aabb(quad: list | np.ndarray) -> tuple[int, int, int, int]:
    pts = np.asarray(quad, dtype=np.float32).reshape(-1, 2)
    x1 = int(np.floor(pts[:, 0].min()))
    y1 = int(np.floor(pts[:, 1].min()))
    x2 = int(np.ceil(pts[:, 0].max()))
    y2 = int(np.ceil(pts[:, 1].max()))
    return x1, y1, x2, y2


def yolo_icon_boxes(image: np.ndarray, weights: Path, device: str | int) -> list[tuple[int, int, int, int]]:
    from ultralytics import YOLO

    if not weights.is_file():
        raise FileNotFoundError(
            f"YOLO weights not found: {weights}\n"
            "Place epoch235.pt at the repo root (same as main.py) or pass --weights."
        )
    model = YOLO(str(weights))
    results = model.predict(image, device=device, verbose=False)
    boxes: list[tuple[int, int, int, int]] = []
    for r in results:
        for box in r.boxes:
            if int(box.cls[0]) != 0:
                continue
            x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
            boxes.append((x1, y1, x2, y2))
    return boxes


def ocr_lines(image: np.ndarray, langs: list[str], gpu: bool) -> list[dict]:
    import easyocr

    reader = easyocr.Reader(langs, gpu=gpu)
    raw = reader.readtext(image)
    lines: list[dict] = []
    for bbox, text, conf in raw:
        t = (text or "").strip()
        if conf < 0.25 or len(t) < 1:
            continue
        x1, y1, x2, y2 = _quad_to_aabb(bbox)
        h, w = image.shape[:2]
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)
        if x2 <= x1 or y2 <= y1:
            continue
        cx = (x1 + x2) / 2.0
        cy = (y1 + y2) / 2.0
        lines.append(
            {
                "text": t,
                "conf": float(conf),
                "bbox": (x1, y1, x2, y2),
                "cx": cx,
                "cy": cy,
            }
        )
    return lines


def vertical_overlap_fraction(
    iy1: int, iy2: int, ty1: int, ty2: int
) -> float:
    inter = max(0, min(iy2, ty2) - max(iy1, ty1))
    ih = max(1, iy2 - iy1)
    th = max(1, ty2 - ty1)
    return inter / float(min(ih, th))


def pair_score(
    icon: tuple[int, int, int, int],
    line: dict,
    *,
    max_right_gap: int,
    min_v_overlap: float,
) -> float | None:
    ix1, iy1, ix2, iy2 = icon
    tx1, ty1, tx2, ty2 = line["bbox"]
    icx = (ix1 + ix2) / 2.0
    icy = (iy1 + iy2) / 2.0

    # Name on the RIGHT: text box should start near or right of icon's right edge
    gap = tx1 - ix2
    if gap < -8:
        return None
    if gap > max_right_gap:
        return None

    v_ov = vertical_overlap_fraction(iy1, iy2, ty1, ty2)
    if v_ov < min_v_overlap:
        dy = abs(line["cy"] - icy)
        if dy > max(iy2 - iy1, ty2 - ty1) * 0.85:
            return None

    dy = abs(line["cy"] - icy)
    gap_n = max(0.0, float(gap))
    geo = 100.0 / (1.0 + gap_n / 40.0) + 80.0 / (1.0 + dy / 12.0)
    conf_part = line["conf"] * 120.0
    align = v_ov * 60.0
    return geo + conf_part + align


def assign_greedy(
    icons: list[tuple[int, int, int, int]],
    lines: list[dict],
    score_fn,
) -> list[int | None]:
    """Return for each icon index the assigned line index or None."""
    used_text: set[int] = set()
    order = sorted(range(len(icons)), key=lambda i: (icons[i][1] + icons[i][3]) / 2.0)
    out: list[int | None] = [None] * len(icons)
    for i in order:
        best_j: int | None = None
        best_s = -1.0
        for j, line in enumerate(lines):
            if j in used_text:
                continue
            s = score_fn(icons[i], line)
            if s is None:
                continue
            if s > best_s:
                best_s = s
                best_j = j
        if best_j is not None and best_s > 0:
            out[i] = best_j
            used_text.add(best_j)
    return out


def assign_hungarian(
    icons: list[tuple[int, int, int, int]],
    lines: list[dict],
    score_fn,
) -> list[int | None]:
    n, m = len(icons), len(lines)
    if n == 0:
        return []
    BIG = 1e9
    cost = np.full((n, m), BIG, dtype=np.float64)
    for i in range(n):
        for j in range(m):
            s = score_fn(icons[i], lines[j])
            if s is not None:
                cost[i, j] = BIG - s
    row_ind, col_ind = linear_sum_assignment(cost)
    out: list[int | None] = [None] * n
    for r, c in zip(row_ind, col_ind):
        if cost[r, c] < BIG - 1.0:
            out[r] = int(c)
    return out


def hue_color(idx: int, n: int) -> tuple[int, int, int]:
    if n <= 0:
        return (0, 255, 255)
    h = int(180 * idx / max(n, 1)) % 180
    c = np.zeros((1, 1, 3), dtype=np.uint8)
    c[0, 0, 0] = h
    c[0, 0, 1] = 220
    c[0, 0, 2] = 255
    bgr = cv2.cvtColor(c, cv2.COLOR_HSV2BGR)[0, 0]
    return int(bgr[0]), int(bgr[1]), int(bgr[2])


def annotate(
    image: np.ndarray,
    icons: list[tuple[int, int, int, int]],
    lines: list[dict],
    assignment: list[int | None],
    title: str,
) -> np.ndarray:
    out = image.copy()
    h, w = out.shape[:2]
    n = len(icons)

    for idx, box in enumerate(icons):
        color = hue_color(idx, n)
        x1, y1, x2, y2 = box
        cv2.rectangle(out, (x1, y1), (x2, y2), color, 3)
        tag = f"[{idx}]"
        cv2.putText(
            out,
            tag,
            (x1, max(0, y1 - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            color,
            2,
            cv2.LINE_AA,
        )

    for j, line in enumerate(lines):
        tx1, ty1, tx2, ty2 = line["bbox"]
        cv2.rectangle(out, (tx1, ty1), (tx2, ty2), (180, 180, 180), 1)

    for idx, box in enumerate(icons):
        color = hue_color(idx, n)
        j = assignment[idx] if idx < len(assignment) else None
        if j is None:
            continue
        line = lines[j]
        tx1, ty1, tx2, ty2 = line["bbox"]
        cv2.rectangle(out, (tx1, ty1), (tx2, ty2), color, 2)
        ix1, iy1, ix2, iy2 = box
        p0 = (ix2, (iy1 + iy2) // 2)
        p1 = (tx1, (ty1 + ty2) // 2)
        cv2.line(out, p0, p1, color, 2, cv2.LINE_AA)
        cv2.circle(out, p0, 5, color, -1, cv2.LINE_AA)
        cv2.circle(out, p1, 5, color, -1, cv2.LINE_AA)
        cap = f"{idx}: {line['text'][:60]}"
        cv2.putText(
            out,
            cap,
            (min(w - 10, tx1), max(22, ty1 - 6)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            color,
            2,
            cv2.LINE_AA,
        )

    legend_y = 24
    cv2.rectangle(out, (8, 8), (min(w - 8, 520), 110), (30, 30, 30), -1)
    cv2.rectangle(out, (8, 8), (min(w - 8, 520), 110), (200, 200, 200), 1)
    for t, dy in [
        (title, 0),
        ("Icon: thick color box + [index]", 22),
        ("Name: same-color rect + link line", 44),
        ("Gray: all OCR boxes (unmatched too)", 66),
    ]:
        cv2.putText(
            out,
            t,
            (16, legend_y + dy),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (240, 240, 240),
            1,
            cv2.LINE_AA,
        )
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--image", type=Path, help="BGR screenshot (e.g. Explorer window)")
    src.add_argument("--capture", action="store_true", help="Capture full screen via pyautogui")
    ap.add_argument("--out", type=Path, default=Path("explorer_icon_label_demo_out.png"))
    ap.add_argument("--weights", type=Path, default=ROOT / "epoch235.pt")
    ap.add_argument("--max-right-gap", type=int, default=420, help="Max px from icon right to text left")
    ap.add_argument("--min-v-overlap", type=float, default=0.2, help="Min vertical overlap (looser for misaligned YOLO)")
    ap.add_argument("--show", action="store_true", help="Open cv2.imshow (press any key to close)")
    ap.add_argument("--lang", nargs="+", default=["en"], help="EasyOCR languages, e.g. en ko")
    args = ap.parse_args()

    import torch

    gpu = torch.cuda.is_available()
    dev = 0 if gpu else "cpu"

    if args.capture:
        from perception.screen_capture import capture_screen

        image = capture_screen()
    else:
        image = cv2.imread(str(args.image))
        if image is None:
            raise SystemExit(f"Could not read image: {args.image}")

    icons = yolo_icon_boxes(image, args.weights, dev)
    lines = ocr_lines(image, list(args.lang), gpu)

    def score_fn(icon, line):
        return pair_score(
            icon,
            line,
            max_right_gap=args.max_right_gap,
            min_v_overlap=args.min_v_overlap,
        )

    if linear_sum_assignment is not None and len(icons) > 0:
        assignment = assign_hungarian(icons, lines, score_fn)
    else:
        if linear_sum_assignment is None:
            print("[info] scipy not installed — using greedy assignment (pip install scipy for Hungarian).")
        assignment = assign_greedy(icons, lines, score_fn)

    matched = sum(1 for x in assignment if x is not None)
    print(f"Icons (YOLO cls0): {len(icons)} | OCR lines: {len(lines)} | Matched: {matched}")
    for i, box in enumerate(icons):
        j = assignment[i] if i < len(assignment) else None
        if j is None:
            print(f"  [{i}] {box} -> (no label)")
        else:
            print(f"  [{i}] {box} -> {lines[j]['text']!r} (conf={lines[j]['conf']:.2f})")

    title = f"Explorer-style demo | icons={len(icons)} ocr={len(lines)} matched={matched}"
    vis = annotate(image, icons, lines, assignment, title)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(args.out), vis)
    print(f"Wrote: {args.out.resolve()}")

    if args.show:
        cv2.imshow(title[:80], vis)
        print("Press any key in the image window to exit.")
        cv2.waitKey(0)
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
