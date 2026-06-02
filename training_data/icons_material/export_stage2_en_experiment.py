#!/usr/bin/env python3
"""
One-off experiment: export stage-2 pairs with Korean (Hangul) labels excluded.

Not used by tools/collect_stage2_full.ps1 or the default README flow.

From repo root:
  python training_data/icons_material/export_stage2_en_experiment.py
  python training_data/icons_material/train_stage2.py \\
    --pairs training_data/icons_material/pairs_stage2_en.jsonl \\
    --splits training_data/icons_material/splits_stage2_en.json \\
    --best-checkpoint stage2_en_best.pt \\
    --epoch-prefix stage2_en_epoch \\
    --log-file train_stage2_en.log \\
    --epochs 10 --batch-size 32
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
OUT_PAIRS = REPO_ROOT / "training_data/icons_material/pairs_stage2_en.jsonl"
OUT_SPLITS = REPO_ROOT / "training_data/icons_material/splits_stage2_en.json"
OUT_NEG = REPO_ROOT / "training_data/icons_material/pairs_stage2_en_hard_negatives.jsonl"
# Default: also write hard-neg sidecar for train_stage2_hardneg_experiment.py


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
    p = argparse.ArgumentParser(description="Export EN-only stage-2 pairs (no Hangul in labels).")
    p.add_argument("--events", type=Path, default=DEFAULT_EVENTS)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--train-ratio", type=float, default=0.8)
    p.add_argument("--val-ratio", type=float, default=0.1)
    p.add_argument(
        "--no-hard-neg",
        action="store_true",
        help="Skip hard-negative sidecar export.",
    )
    args = p.parse_args()

    print("Experiment export: excluding rows with Hangul in query or target name.")
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
    )
    print()
    print("Train CLIP-only (does not overwrite stage2_best.pt):")
    print(
        "  python training_data/icons_material/train_stage2.py "
        "--pairs training_data/icons_material/pairs_stage2_en.jsonl "
        "--splits training_data/icons_material/splits_stage2_en.json "
        "--best-checkpoint stage2_en_best.pt "
        "--epoch-prefix stage2_en_epoch "
        "--log-file train_stage2_en.log "
        "--epochs 10 --batch-size 32"
    )
    if not args.no_hard_neg:
        print()
        print("Train with hard-negative loss (experiment):")
        print(
            "  python training_data/icons_material/train_stage2_hardneg_experiment.py "
            "--pairs training_data/icons_material/pairs_stage2_en.jsonl "
            "--splits training_data/icons_material/splits_stage2_en.json "
            "--hard-neg-pairs training_data/icons_material/pairs_stage2_en_hard_negatives.jsonl "
            "--best-checkpoint stage2_en_hn_best.pt "
            "--epochs 10 --batch-size 32"
        )


if __name__ == "__main__":
    main()
