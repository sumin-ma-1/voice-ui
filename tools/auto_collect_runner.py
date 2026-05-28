#!/usr/bin/env python3
"""
Scenario-driven automatic dataset collector (safe-by-default, no real clicks).

What this tool does
-------------------
1) Read `configs/collect_targets.json` (window title whitelist + collection plan)
2) Focus each whitelisted window title
3) Extract UIA candidates
4) Keep icon candidates (`is_icon` or `icon_like`)
5) Save frame/crop artifacts and append `dataset/events.jsonl` rows

Important safety behavior
-------------------------
- Default mode is **NO EXECUTION**: it does not call `automation.executor.execute`.
- It only logs synthetic "collection probe" events for training data.
- Window scope is restricted by explicit title substrings in config.

This is intended for building stage-2 CLIP data quickly with low manual effort.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from automation.window_focus import activate_window_by_title_substring
from dataset.data_logger import (
    append_hard_negative_rows,
    extra_negatives_cap,
    is_dataset_logging_enabled,
    log_execute_event,
    prepare_grounding_artifacts,
)
from perception.screen_capture import capture_screen
from perception.ui_fallback_pipeline import run_uia_stage
from perception.ui_filter import filter_elements

DEFAULT_CONFIG = REPO_ROOT / "configs/collect_targets.json"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _normalize_query(s: str) -> str:
    q = (s or "").strip().lower()
    q = " ".join(q.split())
    return q


def _candidate_query(
    element: dict[str, Any],
    *,
    fallback_queries: list[str],
    randomize: bool,
    rng: random.Random,
) -> str:
    """
    Pick training query text for this element.

    Priority:
    1) element name (best, when non-empty)
    2) target-level fallback queries from config
    3) empty string (caller skips)
    """
    name_q = _normalize_query(str(element.get("name") or ""))
    if name_q:
        return name_q
    if fallback_queries:
        return rng.choice(fallback_queries) if randomize else fallback_queries[0]
    return ""


def _collect_from_target(
    target: dict[str, Any],
    *,
    run_id: str,
    loops: int,
    dwell_ms: int,
    per_screen_cap: int,
    sleep_between_samples_ms: int,
    score_value: float,
    seed: int,
    add_hard_negs: bool,
    dry_run: bool,
) -> dict[str, int]:
    """
    Collect probes from one target window definition.

    target JSON keys:
      - title_substring (required)
      - enabled (optional, default true)
      - fallback_queries (optional list[str])
      - randomize_query (optional bool, default true)
    """
    stats = {"windows_focused": 0, "probes_logged": 0, "candidates_seen": 0}

    if not bool(target.get("enabled", True)):
        return stats

    title = str(target.get("title_substring") or "").strip()
    if not title:
        return stats

    err = activate_window_by_title_substring(title)
    if err:
        print(f"[skip] focus failed for {title!r}: {err}")
        return stats

    stats["windows_focused"] += 1
    time.sleep(max(0.05, dwell_ms / 1000.0))

    fallback_queries = [
        _normalize_query(str(q))
        for q in (target.get("fallback_queries") or [])
        if _normalize_query(str(q))
    ]
    randomize_query = bool(target.get("randomize_query", True))
    rng = random.Random(seed ^ hash(title))

    for loop_idx in range(max(1, loops)):
        frame = capture_screen()
        raw = run_uia_stage()
        filtered = filter_elements(raw)
        icon_candidates = [
            e
            for e in filtered
            if bool(e.get("is_icon", False)) or bool(e.get("icon_like", False))
        ]
        stats["candidates_seen"] += len(icon_candidates)
        if not icon_candidates:
            continue

        rng.shuffle(icon_candidates)
        picks = icon_candidates[: max(1, per_screen_cap)]

        for i, el in enumerate(picks):
            query = _candidate_query(
                el,
                fallback_queries=fallback_queries,
                randomize=randomize_query,
                rng=rng,
            )
            if not query:
                continue

            if dry_run:
                print(
                    f"[dry-run] {title!r} loop={loop_idx + 1} "
                    f"query={query!r} icon_like={bool(el.get('icon_like'))}"
                )
                continue

            # Use the same logger path as normal runtime, but do not execute clicks.
            action = "left_click"
            artifacts = prepare_grounding_artifacts(
                raw_text=f"[auto_collect {run_id}] click {query}",
                action=action,
                query=query,
                mode_used="uia",
                match=el,
                score=score_value,
                frame=frame,
            )
            if not artifacts:
                continue

            params = {
                "query": query,
                "_raw_text": f"[auto_collect {run_id}] click {query}",
                "_mode_used": "uia",
                "_dataset_event_id": artifacts.get("event_id"),
                "_dataset_frame_path": artifacts.get("frame_path"),
                "_dataset_crop_path": artifacts.get("crop_path"),
                "_dataset_score": artifacts.get("score"),
                "_dataset_target_name": artifacts.get("target_name"),
                "_dataset_is_icon": artifacts.get("is_icon"),
                "_dataset_icon_like": artifacts.get("icon_like"),
                "_dataset_control_type": artifacts.get("control_type"),
            }
            log_execute_event(
                action=action,
                params=params,
                element=el,
                ok=True,
                reason=f"auto_collect_probe:{run_id}",
            )
            stats["probes_logged"] += 1

            if add_hard_negs:
                n_extra = extra_negatives_cap()
                if n_extra > 0:
                    append_hard_negative_rows(
                        parent_event_id=str(artifacts["event_id"]),
                        frame_path=artifacts.get("frame_path"),
                        raw_text=f"[auto_collect {run_id}] click {query}",
                        action=action,
                        query=query,
                        mode_used="uia",
                        frame=frame,
                        positive_bbox=el.get("bbox"),
                        candidates=icon_candidates,
                        positive_name=el.get("name"),
                        positive_is_icon=bool(el.get("is_icon", False)),
                        positive_icon_like=bool(el.get("icon_like", False)),
                        max_extra=n_extra,
                    )

            if sleep_between_samples_ms > 0 and i + 1 < len(picks):
                time.sleep(sleep_between_samples_ms / 1000.0)

    return stats


def main() -> None:
    p = argparse.ArgumentParser(description="Automatic UIA icon-like dataset collector.")
    p.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    p.add_argument("--run-id", type=str, default="")
    p.add_argument("--loops", type=int, default=3, help="Screens to sample per target.")
    p.add_argument("--dwell-ms", type=int, default=700, help="Wait after focusing a window.")
    p.add_argument(
        "--per-screen-cap",
        type=int,
        default=6,
        help="Max icon-like candidates to log from one screen sample.",
    )
    p.add_argument("--sleep-between-samples-ms", type=int, default=120)
    p.add_argument(
        "--score-value",
        type=float,
        default=55.0,
        help="Synthetic score written to events.meta.score for export filtering.",
    )
    p.add_argument("--seed", type=int, default=42)
    p.add_argument(
        "--add-hard-negs",
        action="store_true",
        help="Also append negative_hard rows from non-chosen icon-like candidates.",
    )
    p.add_argument(
        "--force-enable-dataset-log",
        action="store_true",
        help="Set VOICE_UI_DATASET_LOG=1 in this process.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview focus + candidate/query picks without writing dataset rows.",
    )
    args = p.parse_args()

    if not args.config.is_file():
        raise FileNotFoundError(f"Missing config: {args.config}")

    if args.force_enable_dataset_log:
        os.environ["VOICE_UI_DATASET_LOG"] = "1"

    if not args.dry_run and not is_dataset_logging_enabled():
        raise RuntimeError(
            "Dataset logging is OFF. Set VOICE_UI_DATASET_LOG=1 or pass --force-enable-dataset-log."
        )

    cfg = _load_json(args.config)
    targets = cfg.get("targets") or []
    if not isinstance(targets, list) or not targets:
        raise RuntimeError("Config has no targets list.")

    run_id = args.run_id.strip() or time.strftime("%Y%m%d_%H%M%S")
    print(f"[auto-collect] run_id={run_id}  targets={len(targets)}  dry_run={args.dry_run}")

    total = {"windows_focused": 0, "probes_logged": 0, "candidates_seen": 0}
    for t in targets:
        s = _collect_from_target(
            t,
            run_id=run_id,
            loops=args.loops,
            dwell_ms=args.dwell_ms,
            per_screen_cap=args.per_screen_cap,
            sleep_between_samples_ms=args.sleep_between_samples_ms,
            score_value=args.score_value,
            seed=args.seed,
            add_hard_negs=args.add_hard_negs,
            dry_run=args.dry_run,
        )
        for k in total:
            total[k] += s[k]

    print(
        "[auto-collect] done: "
        f"focused={total['windows_focused']} "
        f"candidates_seen={total['candidates_seen']} "
        f"probes_logged={total['probes_logged']}"
    )


if __name__ == "__main__":
    main()
