#!/usr/bin/env python3
"""
Automated task131 benchmark: hardware manifest + latency + success rate.

NOT a user-satisfaction study — no ratings. Use run_study.ps1 for free-form sm/es/sb.

Usage (repo root):
  python tools/run_study_batch.py
  python tools/run_study_batch.py --dataset-dir dataset_sm_task131 --fresh
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent.process_utterance import ensure_ocr_reader, process_utterance
from com.office_controller import OfficeController
from dataset.study_context import ensure_study_manifest
from dataset.study_tasks import load_task_list

DEFAULT_BENCH_DIR = "dataset_sm_task131"
OUTLIER_MS = 60_000


def _configure_bench(*, participant: str, dataset_dir: str, mode: str) -> Path:
    os.environ["VOICE_UI_STUDY"] = "1"
    os.environ["VOICE_UI_STUDY_USER"] = participant
    os.environ["VOICE_UI_STUDY_SESSION_TYPE"] = "task131_bench"
    os.environ["VOICE_UI_DATASET_LOG"] = "1"
    os.environ["VOICE_UI_DATASET_DIR"] = dataset_dir
    os.environ["VOICE_UI_DATASET_EXTRA_NEGATIVES"] = "0"
    os.environ["VOICE_UI_INPUT_MODE"] = "text"
    os.environ["VOICE_UI_GRACE_SECONDS"] = "0"
    os.environ["VOICE_UI_STUDY_QUIET"] = "1"
    os.environ.pop("VOICE_UI_STUDY_RATINGS", None)
    os.environ.pop("VOICE_UI_STUDY_RATINGS_SYNC", None)
    ensure_study_manifest(mode=mode, input_kind="text")
    return REPO_ROOT / dataset_dir


def _bench_summary(events_path: Path) -> dict:
    rows: list[dict] = []
    for line in events_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        o = json.loads(line)
        if (o.get("meta") or {}).get("label") == "negative_hard":
            continue
        s = o.get("study") or (o.get("meta") or {}).get("study") or {}
        lat = s.get("latency_ms") or {}
        pipeline = lat.get("pipeline") or lat.get("total")
        rows.append(
            {
                "outcome": s.get("outcome") or ("success" if o.get("ok") else "fail"),
                "pipeline_ms": pipeline,
            }
        )
    success = [r for r in rows if r["outcome"] in ("success", "office_ok")]
    pipes = [
        float(r["pipeline_ms"])
        for r in success
        if isinstance(r["pipeline_ms"], (int, float)) and r["pipeline_ms"] < OUTLIER_MS
    ]
    outliers = [
        r
        for r in success
        if isinstance(r["pipeline_ms"], (int, float)) and r["pipeline_ms"] >= OUTLIER_MS
    ]
    summary = {
        "events": len(rows),
        "success": len(success),
        "success_rate_pct": round(100 * len(success) / len(rows), 1) if rows else 0,
        "latency_outliers_ge_60s": len(outliers),
    }
    if pipes:
        summary["pipeline_ms_median"] = round(statistics.median(pipes))
        summary["pipeline_ms_mean"] = round(statistics.mean(pipes))
        summary["pipeline_ms_p90"] = round(sorted(pipes)[max(0, int(len(pipes) * 0.9) - 1)])
    return summary


def main() -> None:
    p = argparse.ArgumentParser(description="Automated task131 benchmark (no ratings).")
    p.add_argument("--participant", default="sm", help="Logged participant_id")
    p.add_argument(
        "--dataset-dir",
        default=DEFAULT_BENCH_DIR,
        help=f"Output folder under repo root (default: {DEFAULT_BENCH_DIR})",
    )
    p.add_argument("--mode", default="all", choices=["uia", "ocr", "vision", "both", "all"])
    p.add_argument("--limit", type=int, default=0, help="Max tasks (0 = all)")
    p.add_argument("--start", type=int, default=1, help="1-based task_id to start from")
    p.add_argument("--delay", type=float, default=0.3, help="Seconds between commands")
    p.add_argument("--fresh", action="store_true", help="Remove existing dataset dir first")
    p.add_argument(
        "--tasks",
        type=Path,
        default=REPO_ROOT / "task131.xlsx",
        help="Task list xlsx",
    )
    args = p.parse_args()

    tasks = load_task_list(str(args.tasks))
    if not tasks:
        raise SystemExit(f"No tasks loaded from {args.tasks}")

    tasks = [t for t in tasks if int(t["task_id"]) >= args.start]
    if args.limit > 0:
        tasks = tasks[: args.limit]

    out_dir = REPO_ROOT / args.dataset_dir
    if args.fresh and out_dir.is_dir():
        import shutil

        shutil.rmtree(out_dir)
        print(f"Removed previous {out_dir}")

    out_dir = _configure_bench(
        participant=args.participant, dataset_dir=args.dataset_dir, mode=args.mode
    )
    office = OfficeController()
    ocr_reader = ensure_ocr_reader(args.mode, None)

    print("=== task131 benchmark (automated, no ratings) ===")
    print(f"participant : {args.participant}")
    print(f"dataset     : {out_dir}")
    print(f"tasks       : {len(tasks)}")
    print()

    t0 = time.perf_counter()
    for i, task in enumerate(tasks, start=1):
        utterance = str(task["utterance"])
        tid = int(task["task_id"])
        banner = f"[{i}/{len(tasks)}] task_id={tid}: {utterance}"
        os.environ["VOICE_UI_STUDY_CURRENT_TASK"] = banner
        print("\n" + "=" * 72, flush=True)
        print(f"  NOW RUNNING  {banner}", flush=True)
        print("=" * 72, flush=True)
        try:
            r = process_utterance(
                utterance,
                mode=args.mode,
                ocr_reader=ocr_reader,
                office=office,
                ui=None,
                voice=None,
            )
            print(f"  RESULT -> {r}", flush=True)
        except Exception as exc:
            print(f"  RESULT -> ERROR: {exc}", flush=True)
        if args.delay > 0 and i < len(tasks):
            time.sleep(args.delay)

    elapsed = time.perf_counter() - t0
    events_path = out_dir / "events.jsonl"
    summary = _bench_summary(events_path) if events_path.is_file() else {}

    print()
    print(f"Done in {elapsed:.1f}s")
    print(f"Manifest: {out_dir / 'study_manifest.json'}")
    if summary:
        print(
            f"Success rate: {summary['success']}/{summary['events']} "
            f"({summary['success_rate_pct']}%)"
        )
        if summary.get("pipeline_ms_median") is not None:
            print(
                f"Pipeline ms (<60s): median={summary['pipeline_ms_median']} "
                f"mean={summary['pipeline_ms_mean']} p90={summary['pipeline_ms_p90']} "
                f"outliers={summary['latency_outliers_ge_60s']}"
            )

    report_path = out_dir / "bench_summary.json"
    report_path.write_text(
        json.dumps({**summary, "elapsed_s": round(elapsed, 1)}, indent=2),
        encoding="utf-8",
    )
    print(f"Wrote: {report_path}")


if __name__ == "__main__":
    main()
