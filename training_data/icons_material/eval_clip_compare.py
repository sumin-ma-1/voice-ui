#!/usr/bin/env python3
"""
Compare baseline CLIP ViT-B/32 vs stage1 fine-tuned checkpoint.

Modes:
  gallery  — Material pairs.jsonl retrieval (icon-level, no YOLO).
  screen   — Screenshot -> YOLO (detect_icons) -> CLIP pick best icon crop.
  oracle   — GT bbox crops only (no YOLO): query vs all labeled crops (CLIP-only).
  all      — gallery + screen + oracle

Screen cases JSON (copy eval_cases.example.json -> eval_cases.json):
  [{"image": "path.png", "query": "close", "bbox": [x1, y1, x2, y2]}]

Run from repo root (venv):
  python training_data/icons_material/eval_clip_compare.py --mode all
  python training_data/icons_material/eval_clip_compare.py --mode screen --cases training_data/icons_material/eval_cases.json
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

PAIRS_PATH = REPO_ROOT / "training_data/icons_material/pairs.jsonl"
SPLITS_PATH = REPO_ROOT / "training_data/icons_material/splits.json"
DEFAULT_CKPT = REPO_ROOT / "training_data/icons_material/checkpoints/stage1_best.pt"
DEFAULT_CASES = REPO_ROOT / "training_data/icons_material/eval_cases.json"


@dataclass(frozen=True)
class PairRecord:
    icon_id: str
    text: str
    image_path: Path


@dataclass(frozen=True)
class ScreenCase:
    image_path: Path
    query: str
    bbox: tuple[int, int, int, int]


def load_pairs(path: Path) -> list[PairRecord]:
    out: list[PairRecord] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        o = json.loads(line)
        out.append(
            PairRecord(
                icon_id=str(o["icon_id"]),
                text=str(o["text"]),
                image_path=(REPO_ROOT / o["image"]).resolve(),
            )
        )
    return out


def load_screen_cases(path: Path) -> list[ScreenCase]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    cases: list[ScreenCase] = []
    for i, o in enumerate(raw):
        bb = o.get("bbox") or []
        if len(bb) != 4:
            raise ValueError(f"Case {i}: bbox must be [x1,y1,x2,y2]")
        x1, y1, x2, y2 = (int(bb[0]), int(bb[1]), int(bb[2]), int(bb[3]))
        if x2 <= x1 or y2 <= y1:
            raise ValueError(
                f"Case {i}: invalid bbox {bb} (set real pixel coords; see eval_cases.example.json)"
            )
        cases.append(
            ScreenCase(
                image_path=(REPO_ROOT / o["image"]).resolve(),
                query=str(o["query"]).strip(),
                bbox=(x1, y1, x2, y2),
            )
        )
    return cases


def load_clip(checkpoint: Path | None, device: torch.device):
    import clip as clip_module

    model, preprocess = clip_module.load("ViT-B/32", device=device, jit=False)
    model.float()
    model.eval()
    tag = "baseline"
    if checkpoint is not None:
        ckpt = torch.load(checkpoint, map_location=device, weights_only=False)
        model.load_state_dict(ckpt["model_state_dict"], strict=True)
        tag = checkpoint.stem
    return model, preprocess, tag, clip_module


@torch.no_grad()
def encode_text(model, clip_module, device: torch.device, texts: list[str]) -> torch.Tensor:
    tokens = clip_module.tokenize(texts, truncate=True).to(device)
    return F.normalize(model.encode_text(tokens), dim=-1)


@torch.no_grad()
def encode_images(model, preprocess, device: torch.device, images: list[Image.Image]) -> torch.Tensor:
    if not images:
        return torch.empty(0, 512, device=device)
    batch = torch.stack([preprocess(im) for im in images]).to(device)
    return F.normalize(model.encode_image(batch), dim=-1)


def rgba_file_to_rgb(path: Path) -> Image.Image:
    im = Image.open(path).convert("RGBA")
    bg = Image.new("RGB", im.size, (255, 255, 255))
    bg.paste(im, mask=im.split()[3])
    return bg


@torch.no_grad()
def gallery_metrics(
    model,
    preprocess,
    clip_module,
    records: list[PairRecord],
    device: torch.device,
) -> dict[str, float]:
    if not records:
        return {"r1": 0.0, "r5": 0.0, "n": 0}

    texts = [r.text for r in records]
    rgb_images = [rgba_file_to_rgb(r.image_path) for r in records]
    txt_emb = encode_text(model, clip_module, device, texts)
    img_emb = encode_images(model, preprocess, device, rgb_images)
    sims = img_emb @ txt_emb.T
    n = sims.shape[0]
    r1 = r5 = 0
    for i in range(n):
        topk = torch.topk(sims[i], k=min(5, n)).indices.tolist()
        if i == topk[0]:
            r1 += 1
        if i in topk:
            r5 += 1
    return {"r1": r1 / n, "r5": r5 / n, "n": float(n)}


def crop_screen_bbox(screen_bgr: np.ndarray, bbox: tuple[int, int, int, int]) -> Image.Image | None:
    h, w = screen_bgr.shape[:2]
    x1, y1, x2, y2 = bbox
    x1, y1 = max(0, min(x1, w)), max(0, min(y1, h))
    x2, y2 = max(0, min(x2, w)), max(0, min(y2, h))
    if x2 <= x1 or y2 <= y1:
        return None
    patch = screen_bgr[y1:y2, x1:x2]
    return Image.fromarray(cv2.cvtColor(patch, cv2.COLOR_BGR2RGB))


@torch.no_grad()
def oracle_metrics(
    model,
    preprocess,
    clip_module,
    device: torch.device,
    cases: list[ScreenCase],
    *,
    verbose: bool = False,
) -> dict[str, float]:
    """
    Each case: one GT crop + query. Build N x N similarity (query_i vs crop_j).
    R@1 / R@5: diagonal should win (CLIP-only, no YOLO).
    """
    labels: list[str] = []
    crops: list[Image.Image] = []
    texts: list[str] = []

    for case in cases:
        screen = cv2.imread(str(case.image_path))
        if screen is None:
            print(f"[warn] cannot read: {case.image_path}")
            continue
        pil = crop_screen_bbox(screen, case.bbox)
        if pil is None:
            print(f"[warn] empty GT crop: {case.image_path.name} bbox={case.bbox}")
            continue
        labels.append(case.image_path.name)
        crops.append(pil)
        texts.append(case.query)

    n = len(crops)
    if n == 0:
        return {"r1": 0.0, "r5": 0.0, "n": 0.0}

    img_emb = encode_images(model, preprocess, device, crops)
    txt_emb = encode_text(model, clip_module, device, texts)
    sims = (txt_emb @ img_emb.T).cpu()

    r1 = r5 = 0
    for i in range(n):
        row = sims[i]
        topk = torch.topk(row, k=min(5, n)).indices.tolist()
        if i == topk[0]:
            r1 += 1
        if i in topk:
            r5 += 1
        if verbose and i != topk[0]:
            j = topk[0]
            print(
                f"  miss R@1: query={texts[i]!r} ({labels[i]}) "
                f"-> top={labels[j]} score={row[j]:.3f} vs gt={row[i]:.3f}"
            )

    return {"r1": r1 / n, "r5": r5 / n, "n": float(n)}


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


@torch.no_grad()
def rank_icons_for_query(
    model,
    preprocess,
    clip_module,
    device: torch.device,
    screen_bgr: np.ndarray,
    query: str,
    icon_bboxes: list[tuple[int, int, int, int]],
) -> tuple[list[int], list[float]]:
    crops: list[Image.Image] = []
    for x1, y1, x2, y2 in icon_bboxes:
        patch = screen_bgr[y1:y2, x1:x2]
        crops.append(Image.fromarray(cv2.cvtColor(patch, cv2.COLOR_BGR2RGB)))
    img_emb = encode_images(model, preprocess, device, crops)
    txt_emb = encode_text(model, clip_module, device, [query])
    sims = (img_emb @ txt_emb.T).squeeze(-1).cpu()
    order = torch.argsort(sims, descending=True).tolist()
    scores = [float(sims[i].item()) for i in order]
    return order, scores


@torch.no_grad()
def screen_metrics(
    model,
    preprocess,
    clip_module,
    device: torch.device,
    cases: list[ScreenCase],
    *,
    iou_threshold: float = 0.5,
) -> dict[str, float]:
    from perception.icon_utils import detect_icons

    top1 = top5 = detected = 0
    n = len(cases)

    for case in cases:
        screen = cv2.imread(str(case.image_path))
        if screen is None:
            print(f"[warn] cannot read: {case.image_path}")
            continue
        icons = detect_icons(screen)
        boxes = [tuple(ic["bbox"]) for ic in icons]
        if not boxes:
            print(f"[warn] no YOLO icons: {case.image_path.name} query={case.query!r}")
            continue

        ious = [bbox_iou(case.bbox, b) for b in boxes]
        gt_idx = int(np.argmax(ious))
        if ious[gt_idx] < iou_threshold:
            print(
                f"[warn] GT not detected IoU>={iou_threshold}: {case.image_path.name} "
                f"query={case.query!r} best_iou={ious[gt_idx]:.2f}"
            )
            continue
        detected += 1

        order, _scores = rank_icons_for_query(
            model, preprocess, clip_module, device, screen, case.query, boxes
        )
        rank_gt = order.index(gt_idx)
        if rank_gt == 0:
            top1 += 1
        if rank_gt < min(5, len(boxes)):
            top5 += 1

    return {
        "top1": top1 / detected if detected else 0.0,
        "top5": top5 / detected if detected else 0.0,
        "detected": float(detected),
        "n": float(n),
    }


def filter_by_icon_ids(records: list[PairRecord], ids: set[str]) -> list[PairRecord]:
    return [r for r in records if r.icon_id in ids]


def run_gallery(
    checkpoint: Path | None,
    device: torch.device,
    *,
    split_name: str | None,
) -> dict[str, float]:
    records = load_pairs(PAIRS_PATH)
    if split_name and SPLITS_PATH.is_file():
        split = json.loads(SPLITS_PATH.read_text(encoding="utf-8"))
        if split_name in split:
            records = filter_by_icon_ids(records, set(split[split_name]))
    model, preprocess, tag, clip_module = load_clip(checkpoint, device)
    m = gallery_metrics(model, preprocess, clip_module, records, device)
    m["tag"] = tag
    del model
    if device.type == "cuda":
        torch.cuda.empty_cache()
    return m


def run_oracle(
    checkpoint: Path | None,
    device: torch.device,
    cases: list[ScreenCase],
    *,
    verbose: bool,
) -> dict[str, float]:
    model, preprocess, tag, clip_module = load_clip(checkpoint, device)
    m = oracle_metrics(
        model, preprocess, clip_module, device, cases, verbose=verbose
    )
    m["tag"] = tag
    del model
    if device.type == "cuda":
        torch.cuda.empty_cache()
    return m


def run_screen(
    checkpoint: Path | None,
    device: torch.device,
    cases: list[ScreenCase],
    *,
    iou_threshold: float,
) -> dict[str, float]:
    model, preprocess, tag, clip_module = load_clip(checkpoint, device)
    m = screen_metrics(
        model, preprocess, clip_module, device, cases, iou_threshold=iou_threshold
    )
    m["tag"] = tag
    del model
    if device.type == "cuda":
        torch.cuda.empty_cache()
    return m


def print_compare(title: str, base: dict, tuned: dict, keys: list[str]) -> None:
    print(f"\n=== {title} ===")
    for k in keys:
        b = base.get(k, 0)
        t = tuned.get(k, 0)
        if k in ("n", "detected"):
            print(f"  {k}: {int(b)} cases")
            continue
        delta = t - b
        print(f"  {k}: baseline={b:.4f}  stage1={t:.4f}  (delta {delta:+.4f})")


def main() -> None:
    p = argparse.ArgumentParser(description="Compare baseline vs stage1 CLIP.")
    p.add_argument(
        "--mode",
        choices=("gallery", "screen", "oracle", "all"),
        default="all",
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        help="oracle: print each R@1 miss (wrong top crop)",
    )
    p.add_argument("--checkpoint", type=Path, default=DEFAULT_CKPT)
    p.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    p.add_argument(
        "--gallery-split",
        choices=("all", "test", "val"),
        default="test",
        help="Material records for gallery eval",
    )
    p.add_argument("--iou-threshold", type=float, default=0.5)
    p.add_argument("--device", choices=("cuda", "cpu"), default="cuda")
    args = p.parse_args()

    device = torch.device(
        "cuda" if args.device == "cuda" and torch.cuda.is_available() else "cpu"
    )
    print(f"Device: {device}")

    ckpt = args.checkpoint.resolve() if args.checkpoint.is_file() else None
    if ckpt is None:
        print(f"[warn] checkpoint not found: {args.checkpoint} (gallery/screen tuned arm skipped)")

    if args.mode in ("gallery", "all"):
        split = None if args.gallery_split == "all" else args.gallery_split
        base_g = run_gallery(None, device, split_name=split)
        tuned_g = run_gallery(ckpt, device, split_name=split) if ckpt else {}
        label = f"Material gallery ({args.gallery_split}, n={int(base_g.get('n', 0))})"
        if ckpt:
            print_compare(label, base_g, tuned_g, ["r1", "r5"])
        else:
            print(f"\n=== {label} ===\n  baseline R@1={base_g['r1']:.4f} R@5={base_g['r5']:.4f}")

    cases: list[ScreenCase] | None = None
    if args.mode in ("screen", "oracle", "all"):
        if not args.cases.is_file():
            print(
                f"\n[{args.mode}] Skip: cases file missing: {args.cases}\n"
                f"  Copy eval_cases.example.json -> eval_cases.json and label bbox/query."
            )
        else:
            cases = load_screen_cases(args.cases)

    if args.mode in ("oracle", "all") and cases is not None:
        print(
            "\n[oracle] GT bbox crops only: each query ranked against all "
            f"{len(cases)} labeled crops (no YOLO)."
        )
        base_o = run_oracle(None, device, cases, verbose=False)
        tuned_o = (
            run_oracle(ckpt, device, cases, verbose=args.verbose) if ckpt else {}
        )
        label = f"Screen oracle GT crops (n={int(base_o.get('n', 0))})"
        if ckpt:
            print_compare(label, base_o, tuned_o, ["r1", "r5"])
        else:
            print(f"\n=== {label} ===\n  baseline R@1={base_o['r1']:.4f} R@5={base_o['r5']:.4f}")

    if args.mode in ("screen", "all") and cases is not None:
        base_s = run_screen(None, device, cases, iou_threshold=args.iou_threshold)
        tuned_s = (
            run_screen(ckpt, device, cases, iou_threshold=args.iou_threshold)
            if ckpt
            else {}
        )
        if ckpt:
            print_compare(
                f"Screen YOLO+CLIP (labeled cases, detected={int(base_s.get('detected', 0))}/{int(base_s.get('n', 0))})",
                base_s,
                tuned_s,
                ["top1", "top5"],
            )
        else:
            print(
                f"\n  baseline top1={base_s['top1']:.4f} top5={base_s['top5']:.4f} "
                f"(detected {int(base_s['detected'])}/{int(base_s['n'])})"
            )


if __name__ == "__main__":
    main()
