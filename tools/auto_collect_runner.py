#!/usr/bin/env python3
"""
Scenario-driven automatic dataset collector (safe-by-default, no real clicks).

What this tool does
-------------------
1) Read `configs/collect_targets.json` (window title whitelist + collection plan)
2) Optionally launch whitelisted apps if not already open (`--auto-launch` / config)
3) Focus each whitelisted window **or** open Chrome/Edge history URLs and collect per page
4) Extract UIA candidates
5) Keep icon candidates (`is_icon` or `icon_like`)
6) Save frame/crop artifacts and append `dataset/events.jsonl` rows

Important safety behavior
-------------------------
- Default mode is **NO EXECUTION**: it does not call `automation.executor.execute`.
- It only logs synthetic "collection probe" events for training data.
- Window scope is restricted by explicit title substrings in config.
- Browser history mode opens real URLs from local history; use domain filters and a test VM
  when possible.

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

from automation.window_focus import (
    activate_window_by_title_substring,
    window_exists_by_title_substring,
)
from dataset.data_logger import (
    append_hard_negative_rows,
    extra_negatives_cap,
    is_dataset_logging_enabled,
    log_execute_event,
    prepare_grounding_artifacts,
    save_scan_frame,
)
from perception.screen_capture import capture_screen
from perception.ui_fallback_pipeline import run_uia_stage
from perception.ui_filter import filter_elements
from tools.app_launcher import ensure_app_for_target
from tools.browser_history import (
    HistoryEntry,
    browser_window_substring,
    foreground_window_title,
    open_url_in_browser,
    read_recent_history,
    wait_for_page,
)
from tools.browser_ui_filter import (
    filter_icon_candidates_for_browser_ui,
    is_blank_browser_tab,
    resolve_browser_ui_settings,
)

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


def _collect_probes_on_current_screen(
    *,
    title_label: str,
    run_id: str,
    loops: int,
    per_screen_cap: int,
    sleep_between_samples_ms: int,
    score_value: float,
    seed: int,
    add_hard_negs: bool,
    dry_run: bool,
    fallback_queries: list[str],
    randomize_query: bool,
    context_meta: dict[str, Any] | None = None,
    browser_ui_mode: str = "both",
    chrome_band_ratio: float = 0.16,
) -> dict[str, int]:
    """Sample UIA icon-like elements on the currently focused window."""
    stats = {"probes_logged": 0, "candidates_seen": 0}
    rng = random.Random(seed ^ hash(title_label))

    for loop_idx in range(max(1, loops)):
        frame = capture_screen()
        raw = run_uia_stage()
        filtered = filter_elements(raw)
        icon_candidates = [
            e
            for e in filtered
            if bool(e.get("is_icon", False)) or bool(e.get("icon_like", False))
        ]
        icon_candidates = filter_icon_candidates_for_browser_ui(
            icon_candidates,
            mode=browser_ui_mode,
            frame=frame,
            chrome_band_ratio=chrome_band_ratio,
        )
        stats["candidates_seen"] += len(icon_candidates)
        if not icon_candidates:
            if browser_ui_mode != "both":
                print(
                    f"[browser-ui] no {browser_ui_mode} candidates on {title_label!r} "
                    f"(loop {loop_idx + 1})"
                )
            continue

        rng.shuffle(icon_candidates)
        picks = icon_candidates[: max(1, per_screen_cap)]

        shared_frame = None if dry_run else save_scan_frame(frame)

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
                    f"[dry-run] {title_label!r} loop={loop_idx + 1} "
                    f"query={query!r} icon_like={bool(el.get('icon_like'))}"
                )
                continue

            action = "left_click"
            artifacts = prepare_grounding_artifacts(
                raw_text=f"[auto_collect {run_id}] click {query}",
                action=action,
                query=query,
                mode_used="uia",
                match=el,
                score=score_value,
                frame=frame,
                shared_frame=shared_frame,
            )
            if not artifacts:
                continue

            params: dict[str, Any] = {
                "query": query,
                "_raw_text": f"[auto_collect {run_id}] click {query}",
                "_mode_used": "uia",
                "_dataset_event_id": artifacts.get("event_id"),
                "_dataset_frame_id": artifacts.get("frame_id"),
                "_dataset_frame_path": artifacts.get("frame_path"),
                "_dataset_crop_path": artifacts.get("crop_path"),
                "_dataset_score": artifacts.get("score"),
                "_dataset_target_name": artifacts.get("target_name"),
                "_dataset_is_icon": artifacts.get("is_icon"),
                "_dataset_icon_like": artifacts.get("icon_like"),
                "_dataset_control_type": artifacts.get("control_type"),
            }
            if context_meta:
                params["_dataset_meta_extra"] = dict(context_meta)

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
                        frame_id=artifacts.get("frame_id"),
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


def _auto_launch_settings(cfg: dict[str, Any]) -> dict[str, Any]:
    ac = cfg.get("auto_launch") or {}
    return {
        "presets": ac.get("presets") if isinstance(ac.get("presets"), dict) else {},
        "launch_wait_ms": int(ac.get("launch_wait_ms", 10000)),
        "skip_if_window_open": bool(ac.get("skip_if_window_open", True)),
    }


def _auto_launch_enabled(args: argparse.Namespace, cfg: dict[str, Any]) -> bool:
    if args.auto_launch:
        return True
    return bool((cfg.get("auto_launch") or {}).get("enabled", False))


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
    auto_launch: bool,
    launch_settings: dict[str, Any],
    cfg: dict[str, Any],
) -> dict[str, int]:
    """
    Collect probes from one target window definition.

    target JSON keys:
      - title_substring (required)
      - enabled (optional, default true)
      - launch (optional path or alias: chrome, edge, vscode, powerpoint, …)
      - launch_args (optional list[str])
      - fallback_queries (optional list[str])
      - randomize_query (optional bool, default true)
    """
    stats = {
        "windows_focused": 0,
        "probes_logged": 0,
        "candidates_seen": 0,
        "pages_visited": 0,
        "apps_launched": 0,
    }

    if not bool(target.get("enabled", True)):
        return stats

    title = str(target.get("title_substring") or "").strip()
    if not title:
        return stats

    if auto_launch:
        had_window = window_exists_by_title_substring(title) if launch_settings["skip_if_window_open"] else False
        ready = ensure_app_for_target(
            target,
            presets=launch_settings["presets"],
            launch_wait_ms=int(
                target.get("launch_wait_ms") or launch_settings["launch_wait_ms"]
            ),
            skip_if_window_open=bool(launch_settings["skip_if_window_open"]),
            dry_run=dry_run,
        )
        if not ready:
            print(f"[skip] no window for {title!r} after auto-launch")
            return stats
        if not had_window and not dry_run:
            stats["apps_launched"] += 1

    err = activate_window_by_title_substring(title)
    if err:
        print(f"[skip] focus failed for {title!r}: {err}")
        return stats

    stats["windows_focused"] += 1
    time.sleep(max(0.05, dwell_ms / 1000.0))

    browser_ui = resolve_browser_ui_settings(target, cfg=cfg, history=False)
    if browser_ui["require_blank_tab"]:
        tab_title = foreground_window_title()
        if not is_blank_browser_tab(tab_title):
            print(
                f"[skip] {title!r}: require blank/new tab for chrome-only collection "
                f"(title={tab_title!r})"
            )
            return stats

    fallback_queries = [
        _normalize_query(str(q))
        for q in (target.get("fallback_queries") or [])
        if _normalize_query(str(q))
    ]
    randomize_query = bool(target.get("randomize_query", True))

    s = _collect_probes_on_current_screen(
        title_label=title,
        run_id=run_id,
        loops=loops,
        per_screen_cap=per_screen_cap,
        sleep_between_samples_ms=sleep_between_samples_ms,
        score_value=score_value,
        seed=seed,
        add_hard_negs=add_hard_negs,
        dry_run=dry_run,
        fallback_queries=fallback_queries,
        randomize_query=randomize_query,
        context_meta={
            "collect_mode": "static",
            "window_title_substring": title,
            "browser_ui_mode": browser_ui["mode"],
        },
        browser_ui_mode=browser_ui["mode"],
        chrome_band_ratio=browser_ui["chrome_band_ratio"],
    )
    stats["probes_logged"] += s["probes_logged"]
    stats["candidates_seen"] += s["candidates_seen"]
    return stats


def _collect_from_history_entry(
    entry: HistoryEntry,
    *,
    run_id: str,
    loops: int,
    page_load_ms: int,
    dwell_ms: int,
    per_screen_cap: int,
    sleep_between_samples_ms: int,
    score_value: float,
    seed: int,
    add_hard_negs: bool,
    dry_run: bool,
    fallback_queries: list[str],
    randomize_query: bool,
    cfg: dict[str, Any],
) -> dict[str, int]:
    """Open one history URL in the browser and collect UIA probes on that page."""
    stats = {"windows_focused": 0, "probes_logged": 0, "candidates_seen": 0, "pages_visited": 0}
    label = f"{entry.browser}:{entry.domain}"

    if dry_run:
        print(
            f"[dry-run] history {label} url={entry.url!r} title={entry.title!r}"
        )
        return stats

    if not open_url_in_browser(entry.browser, entry.url):
        return stats

    stats["pages_visited"] += 1
    page_title = wait_for_page(
        entry.browser,
        page_load_ms=page_load_ms,
        expected_title_hint=entry.title,
    )
    time.sleep(max(0.05, dwell_ms / 1000.0))

    title_sub = browser_window_substring(entry.browser)
    err = activate_window_by_title_substring(title_sub)
    if err:
        print(f"[skip] browser focus failed after opening {entry.url!r}: {err}")
        return stats

    stats["windows_focused"] += 1
    browser_ui = resolve_browser_ui_settings(None, cfg=cfg, history=True)
    context_meta = {
        "collect_mode": "browser_history",
        "browser": entry.browser,
        "source_url": entry.url,
        "page_title": page_title or entry.title,
        "domain": entry.domain,
        "browser_ui_mode": browser_ui["mode"],
    }
    s = _collect_probes_on_current_screen(
        title_label=label,
        run_id=run_id,
        loops=loops,
        per_screen_cap=per_screen_cap,
        sleep_between_samples_ms=sleep_between_samples_ms,
        score_value=score_value,
        seed=seed ^ hash(entry.url),
        add_hard_negs=add_hard_negs,
        dry_run=dry_run,
        fallback_queries=fallback_queries,
        randomize_query=randomize_query,
        context_meta=context_meta,
        browser_ui_mode=browser_ui["mode"],
        chrome_band_ratio=browser_ui["chrome_band_ratio"],
    )
    stats["probes_logged"] += s["probes_logged"]
    stats["candidates_seen"] += s["candidates_seen"]
    return stats


def _resolve_history_browsers(args: argparse.Namespace, cfg: dict[str, Any]) -> list[str]:
    hist_cfg = cfg.get("browser_history") or {}
    if args.from_history:
        raw = args.from_history.strip().lower()
        if raw == "both":
            return ["chrome", "edge"]
        return [raw]
    if bool(hist_cfg.get("enabled", False)):
        browsers = hist_cfg.get("browsers") or ["chrome"]
        return [str(b).strip().lower() for b in browsers if str(b).strip()]
    return []


def _run_history_collection(
    browsers: list[str],
    *,
    cfg: dict[str, Any],
    args: argparse.Namespace,
    run_id: str,
) -> dict[str, int]:
    hist_cfg = cfg.get("browser_history") or {}
    total = {"windows_focused": 0, "probes_logged": 0, "candidates_seen": 0, "pages_visited": 0}

    limit = args.history_limit if args.history_limit is not None else int(hist_cfg.get("history_limit", 25))
    days = args.history_days if args.history_days is not None else hist_cfg.get("history_days", 14)
    page_load_ms = (
        args.page_load_ms if args.page_load_ms is not None else int(hist_cfg.get("page_load_ms", 3000))
    )
    allow = hist_cfg.get("domain_allowlist") or []
    block = hist_cfg.get("domain_blocklist") or []
    one_per_domain = bool(hist_cfg.get("one_per_domain", True))
    loops = int(hist_cfg.get("loops_per_page", args.loops))
    per_screen_cap = int(hist_cfg.get("per_screen_cap", args.per_screen_cap))
    fallback_queries = [
        _normalize_query(str(q))
        for q in (hist_cfg.get("fallback_queries") or ["menu", "search", "settings"])
        if _normalize_query(str(q))
    ]
    randomize_query = bool(hist_cfg.get("randomize_query", True))

    seen_urls: set[str] = set()
    entries: list[HistoryEntry] = []
    per_browser = max(1, limit // max(1, len(browsers)))

    for browser in browsers:
        rows = read_recent_history(
            browser,
            limit=per_browser,
            days=days if days is not None else None,
            domain_allowlist=allow if allow else None,
            domain_blocklist=block if block else None,
            one_per_domain=one_per_domain,
        )
        print(f"[history] {browser}: {len(rows)} URL(s) from local history")
        for row in rows:
            if row.url in seen_urls:
                continue
            seen_urls.add(row.url)
            entries.append(row)
            if len(entries) >= limit:
                break
        if len(entries) >= limit:
            break

    if not entries:
        print("[history] no URLs to visit (empty history or all filtered)")
        return total

    print(f"[history] visiting {len(entries)} page(s)")
    for i, entry in enumerate(entries):
        print(f"[history] ({i + 1}/{len(entries)}) {entry.browser} {entry.domain} — {entry.url}")
        s = _collect_from_history_entry(
            entry,
            run_id=run_id,
            loops=loops,
            page_load_ms=page_load_ms,
            dwell_ms=args.dwell_ms,
            per_screen_cap=per_screen_cap,
            sleep_between_samples_ms=args.sleep_between_samples_ms,
            score_value=args.score_value,
            seed=args.seed,
            add_hard_negs=args.add_hard_negs,
            dry_run=args.dry_run,
            fallback_queries=fallback_queries,
            randomize_query=randomize_query,
            cfg=cfg,
        )
        for k in total:
            total[k] += s[k]
        if args.sleep_between_pages_ms > 0 and i + 1 < len(entries):
            time.sleep(args.sleep_between_pages_ms / 1000.0)

    return total


def main() -> None:
    p = argparse.ArgumentParser(description="Automatic UIA icon-like dataset collector.")
    p.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    p.add_argument("--run-id", type=str, default="")
    p.add_argument("--loops", type=int, default=3, help="Screens to sample per target or history page.")
    p.add_argument("--dwell-ms", type=int, default=700, help="Wait after focusing a window or page load.")
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
    p.add_argument(
        "--from-history",
        choices=("chrome", "edge", "both"),
        default="",
        help="Visit recent Chrome/Edge history URLs and collect on each page.",
    )
    p.add_argument(
        "--history-only",
        action="store_true",
        help="Skip static config targets; only run browser history traversal.",
    )
    p.add_argument("--history-limit", type=int, default=None, help="Max distinct history pages to visit.")
    p.add_argument(
        "--history-days",
        type=int,
        default=None,
        help="Only URLs visited within this many days (config default if omitted).",
    )
    p.add_argument(
        "--page-load-ms",
        type=int,
        default=None,
        help="Wait after opening each history URL before UIA capture.",
    )
    p.add_argument(
        "--sleep-between-pages-ms",
        type=int,
        default=400,
        help="Pause between history page visits.",
    )
    p.add_argument(
        "--auto-launch",
        action="store_true",
        help="Start apps from launch/presets when no matching window is open.",
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
    if not isinstance(targets, list):
        raise RuntimeError("Config targets must be a list.")

    history_browsers = _resolve_history_browsers(args, cfg)
    run_static = not args.history_only and bool(targets)
    run_history = bool(history_browsers)

    if not run_static and not run_history:
        raise RuntimeError(
            "Nothing to collect: enable config targets, set browser_history.enabled, "
            "or pass --from-history chrome|edge|both."
        )

    auto_launch = _auto_launch_enabled(args, cfg)
    launch_settings = _auto_launch_settings(cfg)

    run_id = args.run_id.strip() or time.strftime("%Y%m%d_%H%M%S")
    print(
        f"[auto-collect] run_id={run_id}  static_targets={len(targets) if run_static else 0}  "
        f"history={history_browsers or 'off'}  auto_launch={auto_launch}  dry_run={args.dry_run}"
    )

    total = {
        "windows_focused": 0,
        "probes_logged": 0,
        "candidates_seen": 0,
        "pages_visited": 0,
        "apps_launched": 0,
    }

    if run_static:
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
                auto_launch=auto_launch,
                launch_settings=launch_settings,
                cfg=cfg,
            )
            for k in total:
                total[k] += s[k]

    if run_history:
        h = _run_history_collection(history_browsers, cfg=cfg, args=args, run_id=run_id)
        for k in total:
            total[k] += h[k]

    print(
        "[auto-collect] done: "
        f"focused={total['windows_focused']} "
        f"apps_launched={total['apps_launched']} "
        f"pages_visited={total['pages_visited']} "
        f"candidates_seen={total['candidates_seen']} "
        f"probes_logged={total['probes_logged']}"
    )


if __name__ == "__main__":
    main()
