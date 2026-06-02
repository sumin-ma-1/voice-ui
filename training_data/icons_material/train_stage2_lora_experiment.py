#!/usr/bin/env python3
"""
Stage-2 CLIP LoRA fine-tune on EN-only, pre-refinement screen crops.

- Init: stage1_best.pt (base frozen; only LoRA adapters trained).
- Saves merged weights (LoRA folded into Linear) for existing eval/runtime loaders.
- Default data: pairs_stage2_en_raw.jsonl from export_stage2_en_raw_experiment.py

From repo root:
  python training_data/icons_material/export_stage2_en_raw_experiment.py
  python training_data/icons_material/train_stage2_lora_experiment.py
  python training_data/icons_material/train_stage2_lora_experiment.py --epochs 15 --lr 1e-4
"""

from __future__ import annotations

import argparse
import copy
import sys
from pathlib import Path

import torch
import torch.nn.functional as F
from torch.utils.data import DataLoader

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from clip_lora import (  # noqa: E402
    count_lora_parameters,
    inject_clip_lora,
    lora_trainable_parameters,
    merge_and_unwrap_lora,
)
from train_stage2 import (  # noqa: E402
    CHECKPOINT_DIR,
    DEFAULT_INIT,
    REPO_ROOT,
    ScreenCropDataset,
    clip_contrastive_loss,
    collate_batch,
    filter_records,
    load_init_checkpoint,
    load_pairs,
    load_splits,
    recall_at_k,
)

PAIRS_PATH = REPO_ROOT / "training_data/icons_material/pairs_stage2_en_raw.jsonl"
SPLITS_PATH = REPO_ROOT / "training_data/icons_material/splits_stage2_en_raw.json"


def _save_merged_checkpoint(model: torch.nn.Module, path: Path, meta: dict) -> int:
    snap = copy.deepcopy(model).cpu()
    merged_layers = merge_and_unwrap_lora(snap)
    torch.save({**meta, "model_state_dict": snap.state_dict(), "lora_merged": True}, path)
    del snap
    return merged_layers


def train(args: argparse.Namespace) -> None:
    import clip as clip_module

    pairs_path = Path(args.pairs)
    splits_path = Path(args.splits)
    if not pairs_path.is_file():
        raise FileNotFoundError(
            f"Missing {pairs_path}; run export_stage2_en_raw_experiment.py first."
        )
    if not splits_path.is_file():
        raise FileNotFoundError(
            f"Missing {splits_path}; run export_stage2_en_raw_experiment.py first."
        )

    records = load_pairs(pairs_path)
    split = load_splits(splits_path)
    train_recs = filter_records(records, set(split["train"]))
    val_recs = filter_records(records, set(split["val"]))
    test_recs = filter_records(records, set(split["test"]))

    print(
        f"Stage-2 LoRA: total={len(records)}  train={len(train_recs)}  "
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

    lora_names = inject_clip_lora(
        model,
        r=args.lora_r,
        alpha=args.lora_alpha,
        visual_only=args.visual_only,
        text_only=args.text_only,
    )
    if not lora_names:
        raise RuntimeError("No LoRA layers injected; check target module names.")
    print(f"LoRA layers: {len(lora_names)}  trainable params: {count_lora_parameters(model):,}")

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
        lora_trainable_parameters(model),
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
        f"=== train_stage2_lora start epochs={args.epochs} batch={args.batch_size} "
        f"lr={args.lr} r={args.lora_r} alpha={args.lora_alpha} init={init_path} ==="
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
                torch.nn.utils.clip_grad_norm_(
                    lora_trainable_parameters(model), args.max_grad_norm
                )
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

        meta = {
            "epoch": epoch,
            "val_recall_at_1": val_r1,
            "test_recall_at_1": test_r1,
            "args": vars(args),
            "init_checkpoint": str(init_path),
            "stage": "2_lora",
        }
        epoch_path = CHECKPOINT_DIR / f"{epoch_prefix}{epoch:02d}.pt"
        merged_layers = _save_merged_checkpoint(model, epoch_path, meta)
        log(f"  saved merged epoch ckpt ({merged_layers} layers) -> {epoch_path.name}")

        if val_r1 >= best_val:
            best_val = val_r1
            _save_merged_checkpoint(model, best_path, meta)
            log(f"  -> best checkpoint {best_path} (val_R@1={best_val:.4f})")

    log("Done.")
    log(f"Best merged checkpoint: {best_path} (stage1 preserved at {init_path})")


def main() -> None:
    p = argparse.ArgumentParser(description="Stage-2 LoRA CLIP fine-tune (EN raw labels).")
    p.add_argument("--pairs", type=Path, default=PAIRS_PATH)
    p.add_argument("--splits", type=Path, default=SPLITS_PATH)
    p.add_argument("--init-checkpoint", type=Path, default=DEFAULT_INIT)
    p.add_argument("--epochs", type=int, default=12)
    p.add_argument("--batch-size", type=int, default=32)
    p.add_argument("--lr", type=float, default=1e-4, help="LoRA typically needs higher LR than full FT")
    p.add_argument("--lora-r", type=int, default=8)
    p.add_argument("--lora-alpha", type=float, default=16.0)
    p.add_argument("--visual-only", action="store_true", help="LoRA on visual tower only")
    p.add_argument("--text-only", action="store_true", help="LoRA on text tower only")
    p.add_argument("--max-grad-norm", type=float, default=1.0)
    p.add_argument("--weight-decay", type=float, default=0.0)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--device", choices=("cuda", "cpu"), default="cuda")
    p.add_argument("--log-every", type=int, default=10)
    p.add_argument(
        "--best-checkpoint",
        type=Path,
        default=CHECKPOINT_DIR / "stage2_en_lora_best.pt",
    )
    p.add_argument("--epoch-prefix", default="stage2_en_lora_epoch")
    p.add_argument("--log-file", default="train_stage2_en_lora.log")
    args = p.parse_args()
    args.best_checkpoint = Path(args.best_checkpoint).name
    args.log_file = str(args.log_file)
    torch.manual_seed(args.seed)
    train(args)


if __name__ == "__main__":
    main()
