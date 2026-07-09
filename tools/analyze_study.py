#!/usr/bin/env python3
"""
Summarize user-study logs from participant zip files (es.zip, sb.zip, sm.zip).

Usage (repo root):
  python tools/analyze_study.py
  python tools/analyze_study.py --zips es.zip sb.zip sm.zip
  python tools/analyze_study.py --out study_import/report
"""

from __future__ import annotations

import argparse
import json
import statistics
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ZIPS = ("es.zip", "sb.zip", "sm.zip")
OUTLIER_MS = 60_000


def _extract_zip(zip_path: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(dest)


def _find_dataset_dirs(root: Path) -> list[Path]:
    dirs: list[Path] = []
    for p in root.rglob("events.jsonl"):
        dirs.append(p.parent)
    return sorted(set(dirs))


def _load_ratings(path: Path) -> dict[str, int]:
    if not path.is_file():
        return {}
    out: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        o = json.loads(line)
        if o.get("event_id") and o.get("rating") is not None:
            out[str(o["event_id"])] = int(o["rating"])
    return out


def _load_events(dataset_dir: Path, *, zip_label: str) -> list[dict[str, Any]]:
    path = dataset_dir / "events.jsonl"
    ratings = _load_ratings(dataset_dir / "study_ratings.jsonl")
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        o = json.loads(line)
        if (o.get("meta") or {}).get("label") == "negative_hard":
            continue
        s = o.get("study") or (o.get("meta") or {}).get("study") or {}
        lat = s.get("latency_ms") or {}
        pipeline = lat.get("pipeline") or lat.get("total")
        wall = lat.get("wall_clock") or lat.get("total")
        rows.append(
            {
                "zip": zip_label,
                "dataset_dir": dataset_dir.name,
                "participant_id": s.get("participant_id") or dataset_dir.name,
                "event_id": o.get("event_id"),
                "raw_text": o.get("raw_text"),
                "outcome": s.get("outcome")
                or ("success" if o.get("ok") else "fail"),
                "route": s.get("route"),
                "grounding": s.get("grounding_path") or o.get("mode_used"),
                "surface": (s.get("surface") or {}).get("surface_class"),
                "web_category": (s.get("surface") or {}).get("web_category"),
                "vision_used": bool(s.get("vision_used")),
                "pipeline_ms": pipeline,
                "wall_ms": wall,
                "rating": ratings.get(o.get("event_id")),
                "task_id": (s.get("task") or {}).get("task_id"),
            }
        )
    return rows


def _match_tasks_posthoc(rows: list[dict[str, Any]]) -> None:
    try:
        from dataset.study_tasks import match_task
    except ImportError:
        return
    for r in rows:
        if r.get("task_id"):
            continue
        m = match_task(str(r.get("raw_text") or ""))
        if m:
            r["task_id"] = m.get("task_id")
            r["task_match"] = m.get("match", "exact")


def _summarize(label: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"label": label, "events": 0}
    outcomes = Counter(r["outcome"] for r in rows)
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
    ratings = [r["rating"] for r in rows if r.get("rating") is not None]
    task_ids = {r["task_id"] for r in rows if r.get("task_id")}

    summary: dict[str, Any] = {
        "label": label,
        "events": len(rows),
        "success": len(success),
        "success_rate_pct": round(100 * len(success) / len(rows), 1),
        "outcomes": dict(outcomes),
        "unique_task_ids": len(task_ids),
        "latency_outliers_ge_60s": len(outliers),
        "ratings_n": len(ratings),
        "rating_mean": round(statistics.mean(ratings), 2) if ratings else None,
        "grounding_success": dict(
            Counter(r["grounding"] for r in success if r.get("grounding"))
        ),
        "surface": dict(Counter(r["surface"] for r in rows if r.get("surface"))),
        "vision_used_n": sum(1 for r in rows if r.get("vision_used")),
    }
    if pipes:
        summary["pipeline_ms_median"] = round(statistics.median(pipes))
        summary["pipeline_ms_mean"] = round(statistics.mean(pipes))
        summary["pipeline_ms_p90"] = round(
            sorted(pipes)[max(0, int(len(pipes) * 0.9) - 1)]
        )
    return summary


def _load_manifest(dataset_dir: Path) -> dict[str, Any] | None:
    p = dataset_dir / "study_manifest.json"
    if not p.is_file():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def main() -> None:
    p = argparse.ArgumentParser(description="Analyze es/sb/sm study zip exports.")
    p.add_argument(
        "--zips",
        nargs="*",
        default=list(DEFAULT_ZIPS),
        help="Zip files under repo root (default: es.zip sb.zip sm.zip)",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=REPO_ROOT / "study_import" / "report",
    )
    p.add_argument("--extract-dir", type=Path, default=REPO_ROOT / "study_import")
    p.add_argument(
        "--dirs",
        nargs="*",
        default=[],
        help="Local dataset dirs, e.g. dataset_sm (label=sm/dataset_sm)",
    )
    args = p.parse_args()

    all_rows: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    manifests: list[dict[str, Any]] = []
    missing: list[str] = []

    for dir_name in args.dirs:
        d = REPO_ROOT / dir_name
        if not d.is_dir():
            print(f"[warn] --dirs {dir_name}: not found")
            continue
        zip_label = d.name.removeprefix("dataset_") if d.name.startswith("dataset_") else d.name
        label = f"{zip_label}/{d.name}"
        rows = _load_events(d, zip_label=zip_label)
        _match_tasks_posthoc(rows)
        all_rows.extend(rows)
        summaries.append(_summarize(label, rows))
        mf = _load_manifest(d)
        if mf:
            mf["_source"] = label
            manifests.append(mf)

    for zip_name in args.zips:
        zip_path = REPO_ROOT / zip_name
        zip_label = Path(zip_name).stem  # es | sb | sm
        if not zip_path.is_file():
            missing.append(zip_name)
            continue
        extract_root = args.extract_dir / zip_label
        _extract_zip(zip_path, extract_root)
        dataset_dirs = _find_dataset_dirs(extract_root)
        if not dataset_dirs:
            print(f"[warn] {zip_name}: no events.jsonl found")
            continue
        for d in dataset_dirs:
            label = f"{zip_label}/{d.name}"
            rows = _load_events(d, zip_label=zip_label)
            _match_tasks_posthoc(rows)
            all_rows.extend(rows)
            summaries.append(_summarize(label, rows))
            mf = _load_manifest(d)
            if mf:
                mf["_source"] = label
                manifests.append(mf)

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "events_flat.json").write_text(
        json.dumps(all_rows, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (args.out / "summary.json").write_text(
        json.dumps(summaries, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (args.out / "manifests.json").write_text(
        json.dumps(manifests, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("=== User study report ===\n")
    if missing:
        print("Missing zips:", ", ".join(missing))
        print()
    for s in summaries:
        print(f"## {s['label']}")
        if s.get("events", 0) == 0:
            print("  (no events)\n")
            continue
        print(f"  events={s['events']}  success_rate={s['success_rate_pct']}%")
        print(f"  outcomes={s.get('outcomes')}")
        print(f"  task_ids_matched={s.get('unique_task_ids')}")
        if s.get("rating_mean") is not None:
            print(f"  ratings: n={s['ratings_n']} mean={s['rating_mean']}")
        if s.get("pipeline_ms_median") is not None:
            print(
                f"  pipeline_ms (<60s): median={s['pipeline_ms_median']} "
                f"mean={s['pipeline_ms_mean']} p90={s['pipeline_ms_p90']} "
                f"outliers={s['latency_outliers_ge_60s']}"
            )
        print(f"  grounding={s.get('grounding_success')}")
        print(f"  surface={s.get('surface')}")
        print(f"  vision_used={s.get('vision_used_n')}\n")

    for m in manifests:
        sysinfo = m.get("system") or {}
        print(
            f"Manifest {m.get('_source')}: "
            f"RAM={sysinfo.get('ram_gb')}GB CPU={sysinfo.get('cpu_count')} "
            f"CUDA={sysinfo.get('cuda_available')} "
            f"session={m.get('session_id')}"
        )

    print(f"\nWrote: {args.out / 'summary.json'}")


if __name__ == "__main__":
    main()
