#!/usr/bin/env python3
"""
Click two corners on a screenshot to get eval bbox [x1, y1, x2, y2].

Folder mode (10 images in eval_screenshots/):
  python training_data/icons_material/label_bbox.py training_data/icons_material/eval_screenshots

Controls:
  1st / 2nd left-click  = bbox (on icon; top bar ignored)
  s                     = save to JSON (stay on this image)
  Enter or n            = next image
  r                     = reset clicks
  q / ESC               = quit

Large screenshots are shown scaled down; bbox is stored in original pixel coords.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
MAX_DISPLAY_W = 1600
MAX_DISPLAY_H = 900


def _rel_image_path(image: Path) -> str:
    try:
        return image.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return image.resolve().as_posix()


def resolve_path(p: Path) -> Path:
    if p.is_file() or p.is_dir():
        return p.resolve()
    alt = REPO_ROOT / p
    if alt.is_file() or alt.is_dir():
        return alt.resolve()
    raise FileNotFoundError(p)


def list_images(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    files = [
        p
        for p in sorted(path.iterdir())
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS
    ]
    if not files:
        raise SystemExit(f"No images (*{', *'.join(IMAGE_EXTS)}) in {path}")
    return files


def load_cases(path: Path | None) -> list[dict]:
    if path is None or not path.is_file():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def save_cases(path: Path, cases: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cases, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def labeled_image_paths(cases: list[dict]) -> set[str]:
    return {str(c.get("image", "")).replace("\\", "/") for c in cases}


def label_images(
    images: list[Path],
    *,
    default_query: str,
    append_path: Path | None,
    skip_labeled: bool,
) -> None:
    cases = load_cases(append_path)
    done_paths = labeled_image_paths(cases) if skip_labeled else set()

    todo = images
    if skip_labeled:
        todo = [im for im in images if _rel_image_path(im) not in done_paths]
        skipped = len(images) - len(todo)
        if skipped:
            print(f"Skipping {skipped} already in {append_path}")

    if not todo:
        print("Nothing to label (all done?).")
        return

    win = "label_bbox"
    clicks: list[tuple[int, int]] = []
    bbox: list[int] | None = None
    screen: np.ndarray | None = None
    display_img: np.ndarray | None = None
    display_scale: float = 1.0
    image_path: Path | None = None
    index = 0

    def load_current() -> bool:
        nonlocal screen, image_path, clicks, bbox, display_img, display_scale
        clicks = []
        bbox = None
        image_path = todo[index]
        screen = cv2.imread(str(image_path))
        if screen is None:
            print(f"[warn] cannot read: {image_path}")
            return False
        h, w = screen.shape[:2]
        display_scale = min(1.0, MAX_DISPLAY_W / w, MAX_DISPLAY_H / h)
        if display_scale < 1.0:
            display_img = cv2.resize(
                screen,
                (int(w * display_scale), int(h * display_scale)),
                interpolation=cv2.INTER_AREA,
            )
            print(f"  display scale {display_scale:.3f} ({w}x{h} -> {display_img.shape[1]}x{display_img.shape[0]})")
        else:
            display_img = screen
        return True

    def to_orig(px: int, py: int) -> tuple[int, int]:
        if display_scale <= 0:
            return px, py
        return int(round(px / display_scale)), int(round(py / display_scale))

    bar = 40

    def redraw() -> None:
        if display_img is None:
            return
        dh, dw = display_img.shape[:2]
        view = np.zeros((dh + bar, dw, 3), dtype=np.uint8)
        view[:bar] = (40, 40, 40)
        view[bar:] = display_img
        title = f"{index + 1}/{len(todo)}  {image_path.name}  (s=save, Enter/n=next, q=quit)"
        cv2.putText(
            view,
            title[:100],
            (8, 26),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (240, 240, 240),
            2,
        )
        if bbox is not None and screen is not None:
            x1, y1, x2, y2 = bbox
            sx1, sy1 = int(x1 * display_scale), int(y1 * display_scale) + bar
            sx2, sy2 = int(x2 * display_scale), int(y2 * display_scale) + bar
            cv2.rectangle(view, (sx1, sy1), (sx2, sy2), (0, 255, 0), 2)
        for i, (px, py) in enumerate(clicks):
            cv2.circle(view, (px, py), 5, (0, 0, 255), -1)
        try:
            cv2.imshow(win, view)
        except cv2.error as e:
            print(f"[warn] imshow failed: {e}")

    def on_mouse(event: int, x: int, y: int, _flags: int, _param) -> None:
        nonlocal bbox
        if event != cv2.EVENT_LBUTTONDOWN or screen is None:
            return
        if y < bar:
            return
        clicks.append((x, y))
        if len(clicks) >= 2:
            (x1, y1), (x2, y2) = clicks[0], clicks[1]
            ox1, oy1 = to_orig(x1, y1 - bar)
            ox2, oy2 = to_orig(x2, y2 - bar)
            bbox = [min(ox1, ox2), min(oy1, oy2), max(ox1, ox2), max(oy1, oy2)]
            print(f"  bbox = {bbox}")
            clicks.clear()
        redraw()

    def go_next() -> bool:
        nonlocal index
        if index + 1 >= len(todo):
            return False
        index += 1
        while index < len(todo):
            if load_current():
                return True
            print(f"[warn] skip unreadable: {todo[index].name}")
            index += 1
        return False

    def save_current() -> None:
        nonlocal cases, bbox, clicks
        if bbox is None or image_path is None:
            print("  No bbox — click two corners on the icon first.")
            return
        query = default_query.strip() or input("  query (e.g. close): ").strip()
        if not query:
            print("  Empty query — not saved.")
            return
        entry = {
            "image": _rel_image_path(image_path),
            "query": query,
            "bbox": bbox,
        }
        print("  saved:", json.dumps(entry, ensure_ascii=False))
        if append_path is not None:
            cases.append(entry)
            save_cases(append_path, cases)
            print(f"  -> {append_path} ({len(cases)} total)")
        bbox = None
        clicks.clear()
        redraw()

    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    cv2.setMouseCallback(win, on_mouse)

    while index < len(todo) and not load_current():
        print(f"[warn] skip unreadable: {todo[index].name}")
        index += 1
    if index >= len(todo):
        print("No readable images.")
        return

    print(
        f"Label {len(todo)} image(s). Two clicks -> bbox. "
        f"s=save (stay), Enter/n=next image, q=quit."
    )
    redraw()

    while True:
        try:
            if cv2.getWindowProperty(win, cv2.WND_PROP_VISIBLE) < 1:
                print("Window closed. Run again with --skip-labeled to continue.")
                break
        except cv2.error:
            break

        key = cv2.waitKey(50) & 0xFF
        if key in (ord("q"), 27):
            break
        if key == ord("r"):
            clicks.clear()
            bbox = None
            redraw()
        if key in (ord("n"), 13):  # n or Enter
            if not go_next():
                print("All images done.")
                break
            redraw()
        if key == ord("s"):
            save_current()

    cv2.destroyAllWindows()
    print(f"Stopped at image {index + 1}/{len(todo)}. Run again with --skip-labeled to resume.")


def main() -> None:
    p = argparse.ArgumentParser(description="Label icon bbox for eval_cases.json")
    p.add_argument(
        "path",
        type=Path,
        help="Screenshot file or folder",
    )
    p.add_argument("--query", type=str, default="", help="Default query; empty = prompt on save")
    p.add_argument(
        "--append",
        type=Path,
        default=REPO_ROOT / "training_data/icons_material/eval_cases.json",
    )
    p.add_argument(
        "--skip-labeled",
        action="store_true",
        default=True,
        help="Skip images already in JSON (default: on)",
    )
    p.add_argument(
        "--no-skip-labeled",
        action="store_false",
        dest="skip_labeled",
        help="Show all images even if already labeled",
    )
    args = p.parse_args()

    root = resolve_path(args.path)
    images = list_images(root)
    append = args.append
    if append is not None and not append.is_absolute():
        append = (REPO_ROOT / append).resolve()

    print(f"Found {len(images)} image(s) in {root}")
    label_images(
        images,
        default_query=args.query,
        append_path=append,
        skip_labeled=args.skip_labeled,
    )


if __name__ == "__main__":
    main()
