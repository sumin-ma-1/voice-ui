#!/usr/bin/env python3
"""
Build stage-2 CLIP training pairs from runtime dataset logs.

Why this script exists
----------------------
Stage-1 (`pairs.jsonl`) used Material icon assets with clean labels. Stage-2 should use
real runtime data from `dataset/events.jsonl` + `dataset/crops/`.

This script exports two files:
1) `pairs_stage2.jsonl`:
   - Positive pairs only (query text <-> chosen crop), compatible with `train_stage1.py`
     format (`image`, `text`, `icon_id`, ...).
2) `pairs_stage2_hard_negatives.jsonl`:
   - Optional diagnostics/training-aux file for explicit hard negatives.
   - Not consumed by `train_stage1.py` directly.

Important field meanings
------------------------
- `target.is_icon`:
    Runtime CLIP trigger for YOLO icon elements (vision path). If True, this row is a
    direct icon match candidate.
- `target.icon_like`:
    UIA-side heuristic tag for controls that *look* like icons (dataset tagging only).
    This does NOT trigger CLIP at runtime.

Positive selection rule
-----------------------
A row is exported to `pairs_stage2.jsonl` when all are true:
- `ok == true`
- has `query` text
- has readable `artifacts.crop_path`
- (`target.is_icon == true`) OR (`target.icon_like == true`)

This keeps runtime-consistent icon rows while also allowing UIA icon-like successes.
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from collections.abc import Callable
from typing import Any

import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from speech.target_text import refine_clip_query_text
DEFAULT_EVENTS = REPO_ROOT / "dataset/events.jsonl"
DEFAULT_OUT = REPO_ROOT / "training_data/icons_material/pairs_stage2.jsonl"
DEFAULT_SPLITS = REPO_ROOT / "training_data/icons_material/splits_stage2.json"
DEFAULT_NEG = REPO_ROOT / "training_data/icons_material/pairs_stage2_hard_negatives.jsonl"


def _norm_text(v: Any) -> str:
    return str(v or "").strip()


def _norm_name(v: Any) -> str:
    return _norm_text(v).lower()


def _as_bool(v: Any) -> bool:
    return bool(v) if v is not None else False


def _resolve_path(raw: str, events_path: Path) -> Path:
    p = Path(raw)
    if p.is_absolute():
        return p
    # Historical logs may be relative to repo root or events parent.
    c1 = (REPO_ROOT / p).resolve()
    if c1.exists():
        return c1
    return (events_path.parent / p).resolve()


def _iter_events(events_path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for i, line in enumerate(events_path.read_text(encoding="utf-8").splitlines(), start=1):
        s = line.strip()
        if not s:
            continue
        try:
            rows.append(json.loads(s))
        except json.JSONDecodeError:
            print(f"[warn] skip malformed JSONL line {i}")
    return rows


def _group_id_from_row(
    *,
    query: str,
    target_name: str,
    control_type: str,
    is_icon: bool,
    icon_like: bool,
) -> str:
    """
    Group key for split-by-group (avoid near-duplicate leakage across train/val/test).

    We keep this intentionally semantic/coarse:
    query + target_name + control_type + icon flags.
    """
    q = _norm_name(query).replace(" ", "_") or "_"
    tn = _norm_name(target_name).replace(" ", "_") or "_"
    ct = _norm_name(control_type).replace(" ", "_") or "_"
    return f"q:{q}|t:{tn}|ct:{ct}|i:{int(is_icon)}|l:{int(icon_like)}"


def _split_groups(
    group_ids: list[str],
    *,
    seed: int,
    train_ratio: float,
    val_ratio: float,
) -> dict[str, list[str]]:
    uniq = sorted(set(group_ids))
    rng = random.Random(seed)
    rng.shuffle(uniq)

    n = len(uniq)
    n_train = int(n * train_ratio)
    n_val = int(n * val_ratio)
    n_test = max(0, n - n_train - n_val)
    # Keep exact partitioning.
    train = uniq[:n_train]
    val = uniq[n_train : n_train + n_val]
    test = uniq[n_train + n_val : n_train + n_val + n_test]
    return {"train": train, "val": val, "test": test}


def export_stage2_pairs(
    *,
    events_path: Path,
    out_pairs: Path,
    out_splits: Path,
    out_hard_neg: Path | None,
    seed: int,
    train_ratio: float,
    val_ratio: float,
    min_score: float | None,
    event_filter: Callable[[dict[str, Any]], bool] | None = None,
    refine_query: bool = True,
) -> None:
    if not events_path.is_file():
        raise FileNotFoundError(f"Missing events file: {events_path}")

    events = _iter_events(events_path)
    out_pairs.parent.mkdir(parents=True, exist_ok=True)
    out_splits.parent.mkdir(parents=True, exist_ok=True)
    if out_hard_neg is not None:
        out_hard_neg.parent.mkdir(parents=True, exist_ok=True)

    positives: list[dict[str, Any]] = []
    hard_negs: list[dict[str, Any]] = []
    skip_stats: dict[str, int] = {
        "not_ok": 0,
        "missing_query": 0,
        "missing_crop": 0,
        "not_icon_or_icon_like": 0,
        "below_min_score": 0,
        "filtered_out": 0,
    }

    for e in events:
        if event_filter is not None and not event_filter(e):
            skip_stats["filtered_out"] += 1
            continue
        mode_used = _norm_name(e.get("mode_used"))
        target = e.get("target") or {}
        artifacts = e.get("artifacts") or {}
        meta = e.get("meta") or {}
        raw_query = _norm_text(e.get("query"))
        crop_rel = _norm_text(artifacts.get("crop_path"))
        target_name = _norm_text(target.get("name") or meta.get("target_name"))
        control_type = _norm_text(target.get("control_type"))
        if refine_query:
            query = refine_clip_query_text(
                raw_query,
                target_name=target_name,
                control_type=control_type,
            )
        else:
            query = raw_query

        # Backward compatibility:
        # Old logs may omit target.is_icon. Vision winners are icon candidates.
        is_icon = _as_bool(target.get("is_icon")) or mode_used == "vision"
        icon_like = _as_bool(target.get("icon_like"))
        score = meta.get("score")
        score_f = float(score) if isinstance(score, (int, float)) else None

        # Export hard negatives as a side file (optional).
        if out_hard_neg is not None and _norm_name(meta.get("label")) == "negative_hard":
            if query and crop_rel:
                crop_abs = _resolve_path(crop_rel, events_path)
                if crop_abs.is_file():
                    hard_negs.append(
                        {
                            "image": str(crop_abs.relative_to(REPO_ROOT)).replace("\\", "/"),
                            "text": query,
                            "raw_query": raw_query,
                            "icon_id": f"neg::{e.get('event_id', 'unknown')}",
                            "source": "dataset_hard_negative",
                            "event_id": e.get("event_id"),
                            "pair_event_id": meta.get("pair_event_id"),
                            "mode_used": mode_used,
                            "is_icon": is_icon,
                            "icon_like": icon_like,
                            "control_type": control_type,
                            "target_name": target_name,
                            "label": "negative_hard",
                        }
                    )
            continue

        # Positives: executed success only.
        if not _as_bool(e.get("ok")):
            skip_stats["not_ok"] += 1
            continue
        if not query:
            skip_stats["missing_query"] += 1
            continue
        if not crop_rel:
            skip_stats["missing_crop"] += 1
            continue
        crop_abs = _resolve_path(crop_rel, events_path)
        if not crop_abs.is_file():
            skip_stats["missing_crop"] += 1
            continue
        if not (is_icon or icon_like):
            skip_stats["not_icon_or_icon_like"] += 1
            continue
        if min_score is not None and score_f is not None and score_f < min_score:
            skip_stats["below_min_score"] += 1
            continue

        group_id = _group_id_from_row(
            query=query,
            target_name=target_name,
            control_type=control_type,
            is_icon=is_icon,
            icon_like=icon_like,
        )
        event_id = _norm_text(e.get("event_id")) or f"row{len(positives)}"
        positives.append(
            {
                # train_stage1.py reads these three keys.
                "image": str(crop_abs.relative_to(REPO_ROOT)).replace("\\", "/"),
                "text": query,
                "raw_query": raw_query,
                "icon_id": f"{group_id}::{event_id}",
                # Extra metadata for audit/debug/export iterations.
                "source": "dataset_runtime",
                "event_id": e.get("event_id"),
                "mode_used": mode_used,
                "is_icon": is_icon,
                "icon_like": icon_like,
                "control_type": control_type,
                "target_name": target_name,
                "group_id": group_id,
                "score": score_f,
            }
        )

    out_pairs.write_text("", encoding="utf-8")
    for row in positives:
        with out_pairs.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    if out_hard_neg is not None:
        out_hard_neg.write_text("", encoding="utf-8")
        for row in hard_negs:
            with out_hard_neg.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

    splits = _split_groups(
        [r["group_id"] for r in positives],
        seed=seed,
        train_ratio=train_ratio,
        val_ratio=val_ratio,
    )
    out_splits.write_text(json.dumps(splits, ensure_ascii=False, indent=2), encoding="utf-8")

    n_icon = sum(1 for r in positives if r.get("is_icon"))
    n_icon_like = sum(1 for r in positives if r.get("icon_like"))
    print(f"Wrote positives: {len(positives)} -> {out_pairs}")
    print(f"  is_icon rows:      {n_icon}")
    print(f"  icon_like rows:    {n_icon_like}")
    if out_hard_neg is not None:
        print(f"Wrote hard negatives: {len(hard_negs)} -> {out_hard_neg}")
    print(f"Wrote group splits: {out_splits}")
    print("Skip stats:")
    for k, v in skip_stats.items():
        print(f"  {k}: {v}")


def main() -> None:
    p = argparse.ArgumentParser(description="Export stage-2 CLIP pairs from dataset/events.jsonl.")
    p.add_argument("--events", type=Path, default=DEFAULT_EVENTS)
    p.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Positive pairs JSONL output.")
    p.add_argument("--splits-out", type=Path, default=DEFAULT_SPLITS, help="Group split JSON.")
    p.add_argument(
        "--hard-neg-out",
        type=Path,
        default=DEFAULT_NEG,
        help="Optional hard-negative JSONL output (empty string disables).",
    )
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--train-ratio", type=float, default=0.8)
    p.add_argument("--val-ratio", type=float, default=0.1)
    p.add_argument(
        "--min-score",
        type=float,
        default=None,
        help="Optional minimum matcher score for positives.",
    )
    args = p.parse_args()

    hard_neg_out = None if str(args.hard_neg_out).strip() == "" else args.hard_neg_out
    export_stage2_pairs(
        events_path=args.events,
        out_pairs=args.out,
        out_splits=args.splits_out,
        out_hard_neg=hard_neg_out,
        seed=args.seed,
        train_ratio=args.train_ratio,
        val_ratio=args.val_ratio,
        min_score=args.min_score,
    )


if __name__ == "__main__":
    main()
