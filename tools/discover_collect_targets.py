#!/usr/bin/env python3
"""Print or write auto-collect targets discovered from installed Windows apps."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.installed_apps import discover_installed_apps


def main() -> None:
    p = argparse.ArgumentParser(description="Discover installed apps for auto-collect whitelist.")
    p.add_argument("--max-apps", type=int, default=30)
    p.add_argument("--out", type=Path, default=None, help="Write JSON list of target entries.")
    p.add_argument("--json", action="store_true", help="Print full discovery rows as JSON.")
    args = p.parse_args()

    rows = discover_installed_apps(max_apps=args.max_apps)
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        for r in rows:
            print(
                f"{r['display_name']!r}  title={r['title_substring']!r}  "
                f"launch={r['launch']}  ({r['source']})"
            )
        print(f"\n[{len(rows)} app(s)]")

    if args.out:
        targets = [r["target"] for r in rows]
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(targets, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
