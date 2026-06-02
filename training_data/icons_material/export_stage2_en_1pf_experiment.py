#!/usr/bin/env python3
"""
Experiment: EN-only pairs + at most **one positive per frame_id**.

Why (vs "drop hard_neg jsonl")
------------------------------
``train_stage2.py`` never reads ``pairs_stage2_hard_negatives.jsonl``. Re-export
without that file does **not** change training.

Collection with ``--add-hard-negs`` still logs many **positive** rows per screen
frame. In CLIP contrastive training, other positives from the **same frame** in
the same batch act as implicit hard negatives. This script keeps the highest-score
positive per ``frame_id`` to reduce that effect.

Not wired into tools/collect_stage2_full.ps1.

From repo root:
  python training_data/icons_material/export_stage2_en_1pf_experiment.py
  python training_data/icons_material/train_stage2.py \\
    --pairs training_data/icons_material/pairs_stage2_en_1pf.jsonl \\
    --splits training_data/icons_material/splits_stage2_en_1pf.json \\
    --best-checkpoint stage2_en_1pf_best.pt \\
    --epoch-prefix stage2_en_1pf_epoch \\
    --log-file train_stage2_en_1pf.log \\
    --epochs 10 --batch-size 32
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from export_stage2_pairs import (  # noqa: E402
    DEFAULT_EVENTS,
    REPO_ROOT,
    _split_groups,
    export_stage2_pairs,
)

HANGUL_RE = re.compile(r"[\uac00-\ud7a3]")
OUT_PAIRS = REPO_ROOT / "training_data/icons_material/pairs_stage2_en_1pf.jsonl"
OUT_SPLITS = REPO_ROOT / "training_data/icons_material/splits_stage2_en_1pf.json"


def _english_only_event(e: dict[str, Any]) -> bool:
    target = e.get("target") or {}
    meta = e.get("meta") or {}
    for t in (
        str(e.get("query") or ""),
        str(target.get("name") or ""),
        str(meta.get("target_name") or ""),
    ):
        if t and HANGUL_RE.search(t):
            return False
    return True


def _load_event_meta(events_path: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for line in events_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        o = json.loads(line)
        eid = str(o.get("event_id") or "")
        if eid:
            out[eid] = o
    return out


def _frame_id_and_score(e: dict[str, Any]) -> tuple[str, float]:
    art = e.get("artifacts") or {}
    fid = str(art.get("frame_id") or "")
    score = (e.get("meta") or {}).get("score")
    try:
        sc = float(score) if score is not None else 0.0
    except (TypeError, ValueError):
        sc = 0.0
    return fid, sc


def _dedupe_one_per_frame(
    pairs: list[dict[str, Any]],
    events_by_id: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """Keep highest meta.score positive per frame_id; skip rows with no frame_id."""
    best: dict[str, tuple[dict[str, Any], float]] = {}
    no_frame = 0
    for row in pairs:
        eid = str(row.get("event_id") or "")
        ev = events_by_id.get(eid)
        if not ev:
            no_frame += 1
            continue
        fid, sc = _frame_id_and_score(ev)
        if not fid:
            no_frame += 1
            continue
        prev = best.get(fid)
        if prev is None or sc >= prev[1]:
            best[fid] = (row, sc)
    kept = [t[0] for t in best.values()]
    removed = len(pairs) - len(kept)
    return kept, removed


def main() -> None:
    p = argparse.ArgumentParser(
        description="EN-only export + one positive per frame_id (experiment)."
    )
    p.add_argument("--events", type=Path, default=DEFAULT_EVENTS)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--train-ratio", type=float, default=0.8)
    p.add_argument("--val-ratio", type=float, default=0.1)
    args = p.parse_args()

    print(
        "Experiment: EN labels only, then dedupe to 1 positive per frame_id "
        "(reduces in-batch hard negatives; does not read hard_neg JSONL)."
    )

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".jsonl", delete=False, encoding="utf-8"
    ) as tmp:
        tmp_path = Path(tmp.name)

    try:
        export_stage2_pairs(
            events_path=args.events,
            out_pairs=tmp_path,
            out_splits=tmp_path.with_suffix(".splits.json"),
            out_hard_neg=None,
            seed=args.seed,
            train_ratio=args.train_ratio,
            val_ratio=args.val_ratio,
            min_score=None,
            event_filter=_english_only_event,
        )

        pairs = [
            json.loads(line)
            for line in tmp_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        before = len(pairs)
        events_by_id = _load_event_meta(args.events)
        pairs, removed = _dedupe_one_per_frame(pairs, events_by_id)

        OUT_PAIRS.write_text("", encoding="utf-8")
        for row in pairs:
            with OUT_PAIRS.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

        splits = _split_groups(
            [r["group_id"] for r in pairs],
            seed=args.seed,
            train_ratio=args.train_ratio,
            val_ratio=args.val_ratio,
        )
        OUT_SPLITS.write_text(
            json.dumps(splits, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        print(f"EN positives before frame dedupe: {before}")
        print(f"After 1-per-frame:             {len(pairs)} (removed {removed})")
        print(f"Wrote {OUT_PAIRS}")
        print(f"Wrote {OUT_SPLITS}")
    finally:
        tmp_path.unlink(missing_ok=True)
        tmp_splits = tmp_path.with_suffix(".splits.json")
        tmp_splits.unlink(missing_ok=True)

    print()
    print("Train:")
    print(
        "  python training_data/icons_material/train_stage2.py "
        "--pairs training_data/icons_material/pairs_stage2_en_1pf.jsonl "
        "--splits training_data/icons_material/splits_stage2_en_1pf.json "
        "--best-checkpoint stage2_en_1pf_best.pt "
        "--epoch-prefix stage2_en_1pf_epoch "
        "--log-file train_stage2_en_1pf.log "
        "--epochs 10 --batch-size 32"
    )


if __name__ == "__main__":
    main()
