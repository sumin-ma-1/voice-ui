#!/usr/bin/env python3
"""
Preview Material icon augmentation (before / after) for one icon.

From repo root:
  python training_data/icons_material/preview_augment.py
  python training_data/icons_material/preview_augment.py --icon settings --samples 5
"""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from augment import augment_icon_patch, material_to_baseline_rgb  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
IMAGES_DIR = REPO_ROOT / "training_data/icons_material/images"
PREVIEW_DIR = REPO_ROOT / "training_data/icons_material/previews"


def _load_icon(icon_id: str) -> Image.Image:
    path = IMAGES_DIR / f"{icon_id}.png"
    if not path.is_file():
        raise FileNotFoundError(f"Icon not found: {path}")
    return Image.open(path).convert("RGBA")


def _label(img: Image.Image, title: str, width: int) -> Image.Image:
    bar_h = 28
    out = Image.new("RGB", (width, img.height + bar_h), (48, 48, 48))
    out.paste(img, (0, bar_h))
    draw = ImageDraw.Draw(out)
    try:
        font = ImageFont.truetype("arial.ttf", 14)
    except OSError:
        font = ImageFont.load_default()
    draw.text((6, 6), title, fill=(240, 240, 240), font=font)
    return out


def build_montage(
    icon_id: str,
    *,
    n_aug: int,
    seed: int,
    cell_size: int = 224,
) -> Image.Image:
    icon = _load_icon(icon_id)
    rng = random.Random(seed)

    panels: list[tuple[str, Image.Image]] = []

    # Before: large icon (Material-like)
    baseline = material_to_baseline_rgb(icon).resize(
        (cell_size, cell_size), Image.Resampling.LANCZOS
    )
    panels.append(("before (tight / runtime-like)", baseline))

    raw_rgb = Image.new("RGB", (cell_size, cell_size), (255, 255, 255))
    thumb = icon.copy()
    thumb.thumbnail((cell_size, cell_size), Image.Resampling.LANCZOS)
    ox = (cell_size - thumb.width) // 2
    oy = (cell_size - thumb.height) // 2
    if thumb.mode == "RGBA":
        raw_rgb.paste(thumb, (ox, oy), thumb.split()[3])
    else:
        raw_rgb.paste(thumb, (ox, oy))
    panels.append(("source png (thumb)", raw_rgb))

    for i in range(n_aug):
        aug = augment_icon_patch(icon, rng=rng)
        aug = aug.resize((cell_size, cell_size), Image.Resampling.LANCZOS)
        panels.append((f"aug {i + 1}", aug))

    labeled = [_label(im, title, cell_size) for title, im in panels]
    w = sum(im.width for im in labeled) + 8 * (len(labeled) - 1)
    h = max(im.height for im in labeled)
    montage = Image.new("RGB", (w, h), (32, 32, 32))
    x = 0
    for im in labeled:
        montage.paste(im, (x, 0))
        x += im.width + 8
    return montage


def main() -> None:
    p = argparse.ArgumentParser(description="Preview icon augmentation for CLIP stage-1.")
    p.add_argument("--icon", default="delete", help="icon_id (filename without .png)")
    p.add_argument("--samples", type=int, default=4, help="number of augmented panels")
    p.add_argument("--seed", type=int, default=42, help="RNG seed for reproducible aug")
    p.add_argument(
        "--out",
        type=Path,
        default=None,
        help="output PNG path (default: previews/<icon>_augment_preview.png)",
    )
    args = p.parse_args()

    out = args.out
    if out is None:
        PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
        out = PREVIEW_DIR / f"{args.icon}_augment_preview.png"
    else:
        out = out.resolve()
        out.parent.mkdir(parents=True, exist_ok=True)

    montage = build_montage(args.icon, n_aug=max(1, args.samples), seed=args.seed)
    montage.save(out)
    print(f"Saved: {out}")
    print(f"  icon: {args.icon}")
    print(f"  panels: before, source thumb, {max(1, args.samples)} aug sample(s)")


if __name__ == "__main__":
    main()
