#!/usr/bin/env python3
"""
EN-only stage-2 export without refine_clip_query_text (UIA query as CLIP text).

Use with LoRA fine-tune so Stage-1 weights stay mostly frozen.

From repo root:
  python training_data/icons_material/export_stage2_en_raw_experiment.py
  python training_data/icons_material/train_stage2_lora_experiment.py
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from export_stage2_pairs import (  # noqa: E402
    DEFAULT_EVENTS,
    REPO_ROOT,
    export_stage2_pairs,
)

HANGUL_RE = re.compile(r"[\uac00-\ud7a3]")
OUT_PAIRS = REPO_ROOT / "training_data/icons_material/pairs_stage2_en_raw.jsonl"
OUT_SPLITS = REPO_ROOT / "training_data/icons_material/splits_stage2_en_raw.json"
OUT_NEG = REPO_ROOT / "training_data/icons_material/pairs_stage2_en_raw_hard_negatives.jsonl"


def _row_texts(e: dict[str, Any]) -> list[str]:
    target = e.get("target") or {}
    meta = e.get("meta") or {}
    return [
        str(e.get("query") or ""),
        str(target.get("name") or ""),
        str(meta.get("target_name") or ""),
    ]


def _has_hangul(e: dict[str, Any]) -> bool:
    return any(HANGUL_RE.search(t) for t in _row_texts(e) if t)


def _english_only_event(e: dict[str, Any]) -> bool:
    return not _has_hangul(e)


def main() -> None:
    p = argparse.ArgumentParser(
        description="Export EN-only stage-2 pairs (no Hangul, no text refinement)."
    )
    p.add_argument("--events", type=Path, default=DEFAULT_EVENTS)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--train-ratio", type=float, default=0.8)
    p.add_argument("--val-ratio", type=float, default=0.1)
    p.add_argument("--no-hard-neg", action="store_true")
    args = p.parse_args()

    print("Export: EN-only, text = raw UIA query (refine_clip_query_text skipped).")
    export_stage2_pairs(
        events_path=args.events,
        out_pairs=OUT_PAIRS,
        out_splits=OUT_SPLITS,
        out_hard_neg=None if args.no_hard_neg else OUT_NEG,
        seed=args.seed,
        train_ratio=args.train_ratio,
        val_ratio=args.val_ratio,
        min_score=None,
        event_filter=_english_only_event,
        refine_query=False,
    )
    print()
    print("LoRA train (merged checkpoint compatible with eval_clip_compare.py):")
    print("  python training_data/icons_material/train_stage2_lora_experiment.py")


if __name__ == "__main__":
    main()
