#!/usr/bin/env python3
"""
Stage-1 CLIP fine-tune on Material icon pairs (target selector, not action parser).

- Train: random augment per step (augment_icon_patch).
- Val / test: no random aug (fixed material_to_baseline_rgb view).
- Split by icon_id (no leakage): default 80% / 10% / 10%.

From repo root (venv recommended):
  python training_data/icons_material/train_stage1.py
  python training_data/icons_material/train_stage1.py --epochs 20 --batch-size 128
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import torch
import torch.nn.functional as F
from PIL import Image
from torch.utils.data import DataLoader, Dataset

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from augment import augment_icon_patch, material_to_baseline_rgb  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
PAIRS_PATH = REPO_ROOT / "training_data/icons_material/pairs.jsonl"
SPLITS_PATH = REPO_ROOT / "training_data/icons_material/splits.json"
CHECKPOINT_DIR = REPO_ROOT / "training_data/icons_material/checkpoints"


@dataclass(frozen=True)
class PairRecord:
    icon_id: str
    text: str
    image_path: Path


def load_pairs(path: Path) -> list[PairRecord]:
    rows: list[PairRecord] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        o = json.loads(line)
        rel = Path(o["image"])
        img = (REPO_ROOT / rel).resolve()
        rows.append(
            PairRecord(
                icon_id=str(o["icon_id"]),
                text=str(o["text"]),
                image_path=img,
            )
        )
    return rows


def split_by_icon_id(
    records: list[PairRecord],
    *,
    seed: int,
    train_ratio: float = 0.8,
    val_ratio: float = 0.1,
) -> dict[str, list[str]]:
    ids = sorted({r.icon_id for r in records})
    rng = torch.Generator().manual_seed(seed)
    perm = torch.randperm(len(ids), generator=rng).tolist()
    shuffled = [ids[i] for i in perm]
    n = len(shuffled)
    n_train = int(n * train_ratio)
    n_val = int(n * val_ratio)
    n_test = n - n_train - n_val
    if n_test < 1 and n_val > 1:
        n_val -= 1
        n_test = 1
    train_ids = shuffled[:n_train]
    val_ids = shuffled[n_train : n_train + n_val]
    test_ids = shuffled[n_train + n_val :]
    return {"train": train_ids, "val": val_ids, "test": test_ids}


def write_splits(split: dict[str, list[str]], path: Path) -> None:
    path.write_text(json.dumps(split, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def filter_records(records: list[PairRecord], icon_ids: set[str]) -> list[PairRecord]:
    return [r for r in records if r.icon_id in icon_ids]


class IconPairDataset(Dataset):
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
        self._icon_cache: dict[str, Image.Image] = {}

    def __len__(self) -> int:
        return len(self.records)

    def _load_rgba(self, icon_id: str, path: Path) -> Image.Image:
        if icon_id not in self._icon_cache:
            self._icon_cache[icon_id] = Image.open(path).convert("RGBA")
        return self._icon_cache[icon_id]

    def __getitem__(self, index: int):
        r = self.records[index]
        icon = self._load_rgba(r.icon_id, r.image_path)
        if self.augment:
            rgb = augment_icon_patch(icon)
        else:
            rgb = material_to_baseline_rgb(icon)
        image = self.preprocess(rgb)
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
    ds = IconPairDataset(records, preprocess, augment=False)
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


def train(args: argparse.Namespace) -> None:
    import clip as clip_module

    if not PAIRS_PATH.is_file():
        raise FileNotFoundError(f"Missing {PAIRS_PATH}; run build_pairs.py first.")

    records = load_pairs(PAIRS_PATH)
    split = split_by_icon_id(records, seed=args.seed)
    write_splits(split, SPLITS_PATH)

    train_recs = filter_records(records, set(split["train"]))
    val_recs = filter_records(records, set(split["val"]))
    test_recs = filter_records(records, set(split["test"]))

    print(
        f"Split (by icon_id): train={len(train_recs)} val={len(val_recs)} test={len(test_recs)} "
        f"(total icons={len(records)})"
    )
    print(f"Wrote {SPLITS_PATH}")

    device = torch.device(
        "cuda" if args.device == "cuda" and torch.cuda.is_available() else "cpu"
    )
    if device.type == "cuda":
        print(f"Device: cuda ({torch.cuda.get_device_name(0)})", flush=True)
    else:
        print("Device: cpu", flush=True)

    model, preprocess = clip_module.load("ViT-B/32", device=device, jit=False)
    model.float()
    model.train()
    if hasattr(model, "logit_scale"):
        model.logit_scale.requires_grad = False

    train_ds = IconPairDataset(train_recs, preprocess, augment=True)
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
    log_path = CHECKPOINT_DIR / "train.log"
    best_val = -1.0
    best_path = CHECKPOINT_DIR / "stage1_best.pt"

    def log(msg: str) -> None:
        print(msg, flush=True)
        with log_path.open("a", encoding="utf-8") as lf:
            lf.write(msg + "\n")

    log(f"=== train_stage1 start epochs={args.epochs} batch={args.batch_size} lr={args.lr} ===")

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
        }
        torch.save(ckpt, CHECKPOINT_DIR / f"stage1_epoch{epoch:02d}.pt")

        if val_r1 >= best_val:
            best_val = val_r1
            torch.save(ckpt, best_path)
            log(f"  -> best checkpoint {best_path} (val_R@1={best_val:.4f})")

    log("Done.")
    log(f"Best: {best_path}")
    log(f"Log file: {log_path}")


def main() -> None:
    p = argparse.ArgumentParser(description="Stage-1 Material icons CLIP fine-tune.")
    p.add_argument("--epochs", type=int, default=20)
    p.add_argument("--batch-size", type=int, default=16, help="16 recommended for 6GB GPU (RTX 2060)")
    p.add_argument("--lr", type=float, default=1e-6)
    p.add_argument("--max-grad-norm", type=float, default=1.0)
    p.add_argument("--weight-decay", type=float, default=0.01)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--device", choices=("cuda", "cpu"), default="cuda")
    p.add_argument(
        "--log-every",
        type=int,
        default=10,
        help="print running loss every N batches (0=epoch summary only)",
    )
    args = p.parse_args()
    torch.manual_seed(args.seed)
    train(args)


if __name__ == "__main__":
    main()
