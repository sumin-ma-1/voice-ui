#!/usr/bin/env python3
"""
Stage-2 CLIP fine-tune on runtime screen crops (pairs_stage2.jsonl).

- Init weights: stage1_best.pt (Material icons stage-1).
- Saves: stage2_best.pt / stage2_epoch*.pt (does NOT overwrite stage1_best.pt).
- Split: uses splits_stage2.json group ids from export_stage2_pairs.py.

From repo root:
  python training_data/icons_material/export_stage2_pairs.py
  python training_data/icons_material/train_stage2.py
  python training_data/icons_material/train_stage2.py --epochs 10 --batch-size 32
"""

from __future__ import annotations

import argparse
import io
import json
import random
import sys
from dataclasses import dataclass
from pathlib import Path

import torch
import torch.nn.functional as F
from PIL import Image, ImageEnhance, ImageFilter
from torch.utils.data import DataLoader, Dataset

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

REPO_ROOT = Path(__file__).resolve().parents[2]
PAIRS_PATH = REPO_ROOT / "training_data/icons_material/pairs_stage2.jsonl"
SPLITS_PATH = REPO_ROOT / "training_data/icons_material/splits_stage2.json"
CHECKPOINT_DIR = REPO_ROOT / "training_data/icons_material/checkpoints"
DEFAULT_INIT = CHECKPOINT_DIR / "stage1_best.pt"


@dataclass(frozen=True)
class PairRecord:
    icon_id: str
    group_id: str
    text: str
    image_path: Path


def _group_id_from_icon_id(icon_id: str) -> str:
    if "::" in icon_id:
        return icon_id.rsplit("::", 1)[0]
    return icon_id


def load_pairs(path: Path) -> list[PairRecord]:
    rows: list[PairRecord] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        o = json.loads(line)
        icon_id = str(o["icon_id"])
        rel = Path(o["image"])
        img = (REPO_ROOT / rel).resolve()
        rows.append(
            PairRecord(
                icon_id=icon_id,
                group_id=str(o.get("group_id") or _group_id_from_icon_id(icon_id)),
                text=str(o["text"]),
                image_path=img,
            )
        )
    return rows


def load_splits(path: Path) -> dict[str, list[str]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        "train": list(data.get("train") or []),
        "val": list(data.get("val") or []),
        "test": list(data.get("test") or []),
    }


def filter_records(records: list[PairRecord], group_ids: set[str]) -> list[PairRecord]:
    return [r for r in records if r.group_id in group_ids]


def augment_screen_crop(im: Image.Image, *, rng: random.Random) -> Image.Image:
    """Light photometric aug for real UI crops (no random invert)."""
    out = im.convert("RGB")
    if rng.random() < 0.85:
        out = ImageEnhance.Brightness(out).enhance(rng.uniform(0.85, 1.15))
        out = ImageEnhance.Contrast(out).enhance(rng.uniform(0.90, 1.10))
    if rng.random() < 0.4:
        buf = io.BytesIO()
        out.save(buf, format="JPEG", quality=rng.randint(70, 92))
        buf.seek(0)
        out = Image.open(buf).convert("RGB")
    if rng.random() < 0.2:
        out = out.filter(ImageFilter.GaussianBlur(radius=rng.uniform(0.2, 0.5)))
    return out


class ScreenCropDataset(Dataset):
    def __init__(
        self,
        records: list[PairRecord],
        preprocess,
        *,
        augment: bool,
    ) -> None:
        self.records = records
        self.preprocess = preprocess
        self.augment = augment

    def __len__(self) -> int:
        return len(self.records)

    def __getitem__(self, index: int):
        r = self.records[index]
        im = Image.open(r.image_path).convert("RGB")
        if self.augment:
            im = augment_screen_crop(im, rng=random.Random())
        image = self.preprocess(im)
        return image, r.text, r.icon_id


def collate_batch(batch, clip_module):
    images, texts, icon_ids = zip(*batch)
    image_t = torch.stack(images, dim=0)
    text_t = clip_module.tokenize(list(texts), truncate=True)
    return image_t, text_t, list(icon_ids)


def clip_contrastive_loss(
    model,
    image_features: torch.Tensor,
    text_features: torch.Tensor,
) -> torch.Tensor:
    image_features = F.normalize(image_features, dim=-1)
    text_features = F.normalize(text_features, dim=-1)
    logit_scale = model.logit_scale.exp()
    logits = logit_scale * image_features @ text_features.T
    n = logits.shape[0]
    labels = torch.arange(n, device=logits.device)
    loss_i = F.cross_entropy(logits, labels)
    loss_t = F.cross_entropy(logits.T, labels)
    return (loss_i + loss_t) / 2


@torch.no_grad()
def recall_at_k(
    model,
    preprocess,
    records: list[PairRecord],
    device: torch.device,
    clip_module,
    k: int = 1,
) -> float:
    if not records:
        return 0.0
    ds = ScreenCropDataset(records, preprocess, augment=False)
    loader = DataLoader(
        ds,
        batch_size=64,
        shuffle=False,
        num_workers=0,
        collate_fn=lambda b: collate_batch(b, clip_module),
    )
    all_img: list[torch.Tensor] = []
    all_txt: list[torch.Tensor] = []
    model.eval()
    for image_t, text_t, _ in loader:
        image_t = image_t.to(device)
        text_t = text_t.to(device)
        img_f = model.encode_image(image_t)
        txt_f = model.encode_text(text_t)
        all_img.append(F.normalize(img_f, dim=-1).cpu())
        all_txt.append(F.normalize(txt_f, dim=-1).cpu())
    img_mat = torch.cat(all_img, dim=0)
    txt_mat = torch.cat(all_txt, dim=0)
    sims = img_mat @ txt_mat.T
    n = sims.shape[0]
    hits = 0
    for i in range(n):
        row = sims[i]
        topk = torch.topk(row, k=min(k, n)).indices
        if i in topk:
            hits += 1
    return hits / n


def load_init_checkpoint(model, path: Path, device: torch.device) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"Init checkpoint not found: {path}")
    ckpt = torch.load(path, map_location=device, weights_only=False)
    state = ckpt.get("model_state_dict") or ckpt
    model.load_state_dict(state, strict=False)
    print(f"Loaded init weights from {path}")


def train(args: argparse.Namespace) -> None:
    import clip as clip_module

    pairs_path = Path(args.pairs)
    splits_path = Path(args.splits)
    if not pairs_path.is_file():
        raise FileNotFoundError(f"Missing {pairs_path}; run export_stage2_pairs.py first.")
    if not splits_path.is_file():
        raise FileNotFoundError(f"Missing {splits_path}; run export_stage2_pairs.py first.")

    records = load_pairs(pairs_path)
    split = load_splits(splits_path)
    train_recs = filter_records(records, set(split["train"]))
    val_recs = filter_records(records, set(split["val"]))
    test_recs = filter_records(records, set(split["test"]))

    print(
        f"Stage-2 pairs: total={len(records)}  train={len(train_recs)}  "
        f"val={len(val_recs)}  test={len(test_recs)}"
    )
    if len(train_recs) < 8:
        raise RuntimeError("Too few training pairs; collect/export more data first.")

    device = torch.device(
        "cuda" if args.device == "cuda" and torch.cuda.is_available() else "cpu"
    )
    if device.type == "cuda":
        print(f"Device: cuda ({torch.cuda.get_device_name(0)})", flush=True)
    else:
        print("Device: cpu", flush=True)

    model, preprocess = clip_module.load("ViT-B/32", device=device, jit=False)
    model.float()
    init_path = Path(args.init_checkpoint)
    load_init_checkpoint(model, init_path, device)

    model.train()
    if hasattr(model, "logit_scale"):
        model.logit_scale.requires_grad = False

    train_ds = ScreenCropDataset(train_recs, preprocess, augment=True)
    train_loader = DataLoader(
        train_ds,
        batch_size=args.batch_size,
        shuffle=True,
        num_workers=0,
        drop_last=len(train_ds) > args.batch_size,
        collate_fn=lambda b: collate_batch(b, clip_module),
    )

    opt = torch.optim.AdamW(
        model.parameters(),
        lr=args.lr,
        weight_decay=args.weight_decay,
    )

    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    log_path = CHECKPOINT_DIR / args.log_file
    best_path = CHECKPOINT_DIR / args.best_checkpoint
    epoch_prefix = args.epoch_prefix
    best_val = -1.0

    def log(msg: str) -> None:
        print(msg, flush=True)
        with log_path.open("a", encoding="utf-8") as lf:
            lf.write(msg + "\n")

    log(
        f"=== train_stage2 start epochs={args.epochs} batch={args.batch_size} "
        f"lr={args.lr} init={init_path} ==="
    )

    for epoch in range(1, args.epochs + 1):
        model.train()
        total_loss = 0.0
        n_batches = 0
        for image_t, text_t, _ in train_loader:
            image_t = image_t.to(device)
            text_t = text_t.to(device)
            opt.zero_grad(set_to_none=True)
            img_f = model.encode_image(image_t)
            txt_f = model.encode_text(text_t)
            loss = clip_contrastive_loss(model, img_f, txt_f)
            if not torch.isfinite(loss):
                raise RuntimeError("Non-finite loss; try lower --lr or --batch-size")
            loss.backward()
            if args.max_grad_norm > 0:
                torch.nn.utils.clip_grad_norm_(model.parameters(), args.max_grad_norm)
            opt.step()
            total_loss += float(loss.item())
            n_batches += 1
            if args.log_every > 0 and n_batches % args.log_every == 0:
                log(f"  epoch {epoch}/{args.epochs}  batch {n_batches}  loss={loss.item():.4f}")

        avg_loss = total_loss / max(n_batches, 1)
        if device.type == "cuda":
            torch.cuda.empty_cache()
        val_r1 = recall_at_k(model, preprocess, val_recs, device, clip_module, k=1)
        if device.type == "cuda":
            torch.cuda.empty_cache()
        test_r1 = recall_at_k(model, preprocess, test_recs, device, clip_module, k=1)

        log(
            f"epoch {epoch}/{args.epochs}  loss={avg_loss:.4f}  "
            f"val_R@1={val_r1:.4f}  test_R@1={test_r1:.4f}"
        )

        ckpt = {
            "model_state_dict": model.state_dict(),
            "epoch": epoch,
            "val_recall_at_1": val_r1,
            "test_recall_at_1": test_r1,
            "args": vars(args),
            "init_checkpoint": str(init_path),
            "stage": 2,
        }
        torch.save(ckpt, CHECKPOINT_DIR / f"{epoch_prefix}{epoch:02d}.pt")

        if val_r1 >= best_val:
            best_val = val_r1
            torch.save(ckpt, best_path)
            log(f"  -> best checkpoint {best_path} (val_R@1={best_val:.4f})")

    log("Done.")
    log(f"Best: {best_path} (stage1 preserved at {init_path})")


def main() -> None:
    p = argparse.ArgumentParser(description="Stage-2 runtime crop CLIP fine-tune.")
    p.add_argument("--pairs", type=Path, default=PAIRS_PATH)
    p.add_argument("--splits", type=Path, default=SPLITS_PATH)
    p.add_argument("--init-checkpoint", type=Path, default=DEFAULT_INIT)
    p.add_argument("--epochs", type=int, default=10)
    p.add_argument("--batch-size", type=int, default=32, help="32 for 6GB GPU; lower if OOM")
    p.add_argument("--lr", type=float, default=5e-7, help="Lower than stage-1 (fine-tune)")
    p.add_argument("--max-grad-norm", type=float, default=1.0)
    p.add_argument("--weight-decay", type=float, default=0.01)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--device", choices=("cuda", "cpu"), default="cuda")
    p.add_argument("--log-every", type=int, default=10)
    p.add_argument(
        "--best-checkpoint",
        type=Path,
        default=CHECKPOINT_DIR / "stage2_best.pt",
        help="Best weights filename under checkpoints/ (experiment: stage2_en_best.pt).",
    )
    p.add_argument(
        "--epoch-prefix",
        default="stage2_epoch",
        help="Per-epoch checkpoint prefix (experiment: stage2_en_epoch).",
    )
    p.add_argument(
        "--log-file",
        default="train_stage2.log",
        help="Log filename under checkpoints/ (experiment: train_stage2_en.log).",
    )
    args = p.parse_args()
    args.best_checkpoint = Path(args.best_checkpoint).name
    args.log_file = str(args.log_file)
    torch.manual_seed(args.seed)
    train(args)


if __name__ == "__main__":
    main()
