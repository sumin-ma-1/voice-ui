# training_data/icons_material/augment.py
# UI-like crops for stage-1 CLIP training (single icon patch, not full screen).
#
# Tuned for tight YOLO bboxes (icon fills most of the crop). Emphasis: background
# tone, brightness, invert (dark mode), mild grayscale, JPEG/blur.

from __future__ import annotations

import io
import random
from typing import Sequence

from PIL import Image, ImageEnhance, ImageFilter, ImageOps

CANVAS_SIZE = 224

# Toolbar / panel backgrounds (RGB)
BG_COLORS: Sequence[tuple[int, int, int]] = (
    (255, 255, 255),
    (245, 245, 245),
    (240, 240, 240),
    (232, 232, 232),
    (43, 43, 43),
    (32, 32, 32),
    (250, 250, 250),
)

# Tight bbox: icon occupies most of the patch (matches epoch235-style boxes).
ICON_SCALE_MIN = 0.78
ICON_SCALE_MAX = 0.96
OFFSET_MIN = 0.42
OFFSET_MAX = 0.58

# Theme / monochrome (same icon_id, different toolbar colors)
P_INVERT = 0.45
P_GRAYSCALE_BLEND = 0.25
GRAYSCALE_BLEND_MIN = 0.20
GRAYSCALE_BLEND_MAX = 0.40


def _rng(rng: random.Random | None) -> random.Random:
    return rng if rng is not None else random.Random()


def composite_on_rgb(icon: Image.Image, bg: tuple[int, int, int]) -> Image.Image:
    """RGBA (or RGB) icon → RGB on solid background."""
    if icon.mode != "RGBA":
        return icon.convert("RGB")
    base = Image.new("RGB", icon.size, bg)
    base.paste(icon, mask=icon.split()[3])
    return base


def place_on_canvas(
    icon_rgb: Image.Image,
    *,
    canvas_size: int = CANVAS_SIZE,
    icon_scale: float = 0.90,
    offset_xy: tuple[float, float] = (0.5, 0.5),
    bg: tuple[int, int, int] = (240, 240, 240),
) -> Image.Image:
    """
    Resize icon on a square canvas (tight bbox: icon_scale usually 0.78–0.96).

    offset_xy: normalized top-left paste position (0=left/top, 1=right/bottom).
    """
    side = max(icon_rgb.width, icon_rgb.height, 1)
    target = max(8, int(canvas_size * icon_scale))
    scale = target / side
    nw = max(1, int(icon_rgb.width * scale))
    nh = max(1, int(icon_rgb.height * scale))
    small = icon_rgb.resize((nw, nh), Image.Resampling.LANCZOS)

    canvas = Image.new("RGB", (canvas_size, canvas_size), bg)
    max_x = canvas_size - nw
    max_y = canvas_size - nh
    ox = int(max_x * offset_xy[0])
    oy = int(max_y * offset_xy[1])
    canvas.paste(small, (ox, oy))
    return canvas


def _maybe_invert(im: Image.Image, r: random.Random) -> Image.Image:
    """Simulate light vs dark UI (black glyph ↔ white glyph)."""
    if r.random() < P_INVERT:
        return ImageOps.invert(im)
    return im


def _maybe_grayscale_blend(im: Image.Image, r: random.Random) -> Image.Image:
    """Slight desaturation; keeps shape, downplays accidental hue cues."""
    if r.random() < P_GRAYSCALE_BLEND:
        gray = im.convert("L").convert("RGB")
        alpha = r.uniform(GRAYSCALE_BLEND_MIN, GRAYSCALE_BLEND_MAX)
        return Image.blend(im, gray, alpha)
    return im


def augment_icon_patch(
    icon: Image.Image,
    *,
    rng: random.Random | None = None,
    canvas_size: int = CANVAS_SIZE,
) -> Image.Image:
    """
    One training-time view of a Material icon (single patch for CLIP).

    Geometry: near-tight crop. Photometric: bg, brightness, invert, mild grayscale, JPEG.
    """
    r = _rng(rng)
    bg = r.choice(BG_COLORS)
    rgb = composite_on_rgb(icon, bg)

    scale = r.uniform(ICON_SCALE_MIN, ICON_SCALE_MAX)
    ox = r.uniform(OFFSET_MIN, OFFSET_MAX)
    oy = r.uniform(OFFSET_MIN, OFFSET_MAX)
    out = place_on_canvas(
        rgb, canvas_size=canvas_size, icon_scale=scale, offset_xy=(ox, oy), bg=bg
    )

    if r.random() < 0.9:
        out = ImageEnhance.Brightness(out).enhance(r.uniform(0.82, 1.18))
        out = ImageEnhance.Contrast(out).enhance(r.uniform(0.90, 1.10))

    out = _maybe_invert(out, r)
    out = _maybe_grayscale_blend(out, r)

    if r.random() < 0.55:
        buf = io.BytesIO()
        out.save(buf, format="JPEG", quality=r.randint(65, 92))
        buf.seek(0)
        out = Image.open(buf).convert("RGB")

    if r.random() < 0.3:
        out = out.filter(ImageFilter.GaussianBlur(radius=r.uniform(0.2, 0.55)))

    if r.random() < 0.35:
        dx = int(r.uniform(-3, 3))
        dy = int(r.uniform(-3, 3))
        if dx or dy:
            shifted = Image.new("RGB", out.size, bg)
            shifted.paste(out, (dx, dy))
            out = shifted

    return out


def material_to_baseline_rgb(icon: Image.Image, bg: tuple[int, int, int] = (255, 255, 255)) -> Image.Image:
    """Tight-crop style: icon fills most of the canvas (runtime-like)."""
    rgb = composite_on_rgb(icon, bg)
    return place_on_canvas(rgb, icon_scale=0.94, offset_xy=(0.5, 0.5), bg=bg)
