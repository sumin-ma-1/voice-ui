#!/usr/bin/env python3
"""
Experiment: Stage-2 CLIP fine-tune with explicit hard-negative loss.

Hard negatives (wrong crop + query from auto-collect) are exported to
``pairs_stage2_*_hard_negatives.jsonl``. Standard ``train_stage2.py`` ignores them;
this script adds a term that **pushes apart** image/text features on those pairs.

  loss = loss_clip_positives + hard_neg_weight * mean(cosine(img, text))

Not part of the main collect/train pipeline.

From repo root (after export_stage2_en_experiment.py without --no-hard-neg):
  python training_data/icons_material/train_stage2_hardneg_experiment.py \\
    --pairs training_data/icons_material/pairs_stage2_en.jsonl \\
    --splits training_data/icons_material/splits_stage2_en.json \\
    --hard-neg-pairs training_data/icons_material/pairs_stage2_en_hard_negatives.jsonl \\
    --best-checkpoint stage2_en_hn_best.pt \\
    --epoch-prefix stage2_en_hn_epoch \\
    --log-file train_stage2_en_hn.log
"""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

import torch
import torch.nn.functional as F
from torch.utils.data import DataLoader

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from train_stage2 import (  # noqa: E402
    CHECKPOINT_DIR,
    DEFAULT_INIT,
    PAIRS_PATH,
    SPLITS_PATH,
    ScreenCropDataset,
    clip_contrastive_loss,
    collate_batch,
    filter_records,
    load_init_checkpoint,
    load_pairs,
    load_splits,
    recall_at_k,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EN_PAIRS = REPO_ROOT / "training_data/icons_material/pairs_stage2_en.jsonl"
DEFAULT_EN_SPLITS = REPO_ROOT / "training_data/icons_material/splits_stage2_en.json"
DEFAULT_HARD_NEG = (
    REPO_ROOT / "training_data/icons_material/pairs_stage2_en_hard_negatives.jsonl"
)


def hard_negative_loss(
    image_features: torch.Tensor,
    text_features: torch.Tensor,
    *,
    margin: float,
) -> torch.Tensor:
    """Penalize high cosine similarity on misaligned (hard neg) pairs."""
    image_features = F.normalize(image_features, dim=-1)
    text_features = F.normalize(text_features, dim=-1)
    cos = (image_features * text_features).sum(dim=-1)
    return F.relu(cos + margin).mean()


def train(args: argparse.Namespace) -> None:
    import clip as clip_module

    pairs_path = Path(args.pairs)
    splits_path = Path(args.splits)
    hard_neg_path = Path(args.hard_neg_pairs)

    records = load_pairs(pairs_path)
    split = load_splits(splits_path)
    train_recs = filter_records(records, set(split["train"]))
    val_recs = filter_records(records, set(split["val"]))
    test_recs = filter_records(records, set(split["test"]))

    hard_train: list = []
    if hard_neg_path.is_file():
        hard_all = load_pairs(hard_neg_path)
        rng = random.Random(args.seed)
        hard_train = list(hard_all)
        rng.shuffle(hard_train)
        if args.hard_neg_cap > 0 and len(hard_train) > args.hard_neg_cap:
            hard_train = hard_train[: args.hard_neg_cap]
    else:
        print(f"[warn] hard-neg file missing: {hard_neg_path} (CLIP-only training)")

    print(
        f"Stage-2 pairs: total={len(records)}  train={len(train_recs)}  "
        f"val={len(val_recs)}  test={len(test_recs)}"
    )
    print(f"Hard negatives for training: {len(hard_train)}  weight={args.hard_neg_weight}")

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
    hard_ds = (
        ScreenCropDataset(hard_train, preprocess, augment=True) if hard_train else None
    )
    hard_loader = (
        DataLoader(
            hard_ds,
            batch_size=args.batch_size,
            shuffle=True,
            num_workers=0,
            drop_last=len(hard_ds) > args.batch_size,
            collate_fn=lambda b: collate_batch(b, clip_module),
        )
        if hard_ds
        else None
    )
    hard_iter = iter(hard_loader) if hard_loader else None

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
        f"=== train_stage2_hardneg start epochs={args.epochs} batch={args.batch_size} "
        f"lr={args.lr} hard_weight={args.hard_neg_weight} init={init_path} ==="
    )

    for epoch in range(1, args.epochs + 1):
        model.train()
        total_loss = 0.0
        total_pos = 0.0
        total_hn = 0.0
        n_batches = 0
        for image_t, text_t, _ in train_loader:
            image_t = image_t.to(device)
            text_t = text_t.to(device)
            opt.zero_grad(set_to_none=True)
            img_f = model.encode_image(image_t)
            txt_f = model.encode_text(text_t)
            loss_pos = clip_contrastive_loss(model, img_f, txt_f)
            loss = loss_pos

            loss_hn_val = 0.0
            if (
                hard_iter is not None
                and args.hard_neg_weight > 0
                and len(hard_train) >= args.batch_size
            ):
                try:
                    hn_img, hn_txt, _ = next(hard_iter)
                except StopIteration:
                    hard_iter = iter(hard_loader)
                    hn_img, hn_txt, _ = next(hard_iter)
                hn_img = hn_img.to(device)
                hn_txt = hn_txt.to(device)
                hn_img_f = model.encode_image(hn_img)
                hn_txt_f = model.encode_text(hn_txt)
                loss_hn = hard_negative_loss(
                    hn_img_f, hn_txt_f, margin=args.hard_neg_margin
                )
                loss = loss + args.hard_neg_weight * loss_hn
                loss_hn_val = float(loss_hn.item())

            if not torch.isfinite(loss):
                raise RuntimeError("Non-finite loss; try lower --lr or --hard-neg-weight")
            loss.backward()
            if args.max_grad_norm > 0:
                torch.nn.utils.clip_grad_norm_(model.parameters(), args.max_grad_norm)
            opt.step()
            total_loss += float(loss.item())
            total_pos += float(loss_pos.item())
            total_hn += loss_hn_val
            n_batches += 1
            if args.log_every > 0 and n_batches % args.log_every == 0:
                log(
                    f"  epoch {epoch}/{args.epochs}  batch {n_batches}  "
                    f"loss={loss.item():.4f}  pos={loss_pos.item():.4f}  hn={loss_hn_val:.4f}"
                )

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
            "stage": "2_hardneg_experiment",
        }
        torch.save(ckpt, CHECKPOINT_DIR / f"{epoch_prefix}{epoch:02d}.pt")

        if val_r1 >= best_val:
            best_val = val_r1
            torch.save(ckpt, best_path)
            log(f"  -> best checkpoint {best_path} (val_R@1={best_val:.4f})")

    log("Done.")
    log(f"Best: {best_path} (stage1 preserved at {init_path})")


def main() -> None:
    p = argparse.ArgumentParser(description="Stage-2 + hard-negative loss (experiment).")
    p.add_argument("--pairs", type=Path, default=DEFAULT_EN_PAIRS)
    p.add_argument(
        "--splits",
        type=Path,
        default=DEFAULT_EN_SPLITS,
        help="Group splits JSON (not .jsonl): splits_stage2_en.json",
    )
    p.add_argument("--hard-neg-pairs", type=Path, default=DEFAULT_HARD_NEG)
    p.add_argument("--init-checkpoint", type=Path, default=DEFAULT_INIT)
    p.add_argument("--epochs", type=int, default=10)
    p.add_argument("--batch-size", type=int, default=32)
    p.add_argument("--lr", type=float, default=5e-7)
    p.add_argument("--hard-neg-weight", type=float, default=0.25)
    p.add_argument(
        "--hard-neg-margin",
        type=float,
        default=0.0,
        help="Penalize cos(img,text) > -margin on hard-neg pairs.",
    )
    p.add_argument(
        "--hard-neg-cap",
        type=int,
        default=0,
        help="Max hard-neg rows per run (0 = use all exported).",
    )
    p.add_argument("--max-grad-norm", type=float, default=1.0)
    p.add_argument("--weight-decay", type=float, default=0.01)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--device", choices=("cuda", "cpu"), default="cuda")
    p.add_argument("--log-every", type=int, default=10)
    p.add_argument("--best-checkpoint", type=Path, default="stage2_en_hn_best.pt")
    p.add_argument("--epoch-prefix", default="stage2_en_hn_epoch")
    p.add_argument("--log-file", default="train_stage2_en_hn.log")
    args = p.parse_args()
    args.best_checkpoint = Path(args.best_checkpoint).name
    args.log_file = str(args.log_file)
    torch.manual_seed(args.seed)
    train(args)


if __name__ == "__main__":
    main()
