#!/usr/bin/env python3
"""
Export Google Material Design Icons (Apache 2.0) from the official zip into
training_data/icons_material/images/ + pairs.jsonl.

Does not require full zip extraction (avoids Windows long-path issues).

Default filter: png/.../materialicons/24dp/1x/ (baseline filled, one size per icon).

Run from repo root:
  python training_data/icons_material/build_pairs.py
"""

from __future__ import annotations

import argparse
import json
import re
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ZIP = REPO_ROOT / "training_data/icons_material/material-design-icons-4.0.0.zip"
OUT_DIR = REPO_ROOT / "training_data/icons_material"
IMAGES_DIR = OUT_DIR / "images"
PAIRS_PATH = OUT_DIR / "pairs.jsonl"

# material-design-icons-4.0.0/png/{category}/{icon}/materialicons/24dp/1x/*.png
ZIP_ENTRY_RE = re.compile(
    r"^material-design-icons-4\.0\.0/png/[^/]+/([^/]+)/materialicons/24dp/1x/[^/]+\.png$"
)


def _human_name(icon_id: str) -> str:
    return icon_id.replace("_", " ").strip()


def captions_for_icon(icon_id: str) -> list[str]:
    human = _human_name(icon_id)
    out: list[str] = []
    for t in (icon_id, human, f"click {human}", f"press {human}", f"icon {human}"):
        if t and t not in out:
            out.append(t)
    return out


def find_zip_entries(zf: zipfile.ZipFile) -> dict[str, str]:
    """icon_id -> zip member path (first match per icon)."""
    found: dict[str, str] = {}
    for name in zf.namelist():
        m = ZIP_ENTRY_RE.match(name)
        if not m:
            continue
        icon_id = m.group(1)
        found.setdefault(icon_id, name)
    return found


def export(
    zip_path: Path,
    *,
    images_dir: Path,
    pairs_path: Path,
    dry_run: bool = False,
) -> tuple[int, int]:
    if not zip_path.is_file():
        raise FileNotFoundError(f"Zip not found: {zip_path}\nDownload tag 4.0.0 from GitHub material-design-icons.")

    with zipfile.ZipFile(zip_path) as zf:
        entries = find_zip_entries(zf)
        if not entries:
            raise RuntimeError("No matching PNG entries in zip (expected png/.../materialicons/24dp/1x/).")

        if not dry_run:
            images_dir.mkdir(parents=True, exist_ok=True)

        pair_rows = 0
        for icon_id in sorted(entries):
            member = entries[icon_id]
            rel_image = images_dir.relative_to(REPO_ROOT) / f"{icon_id}.png"
            image_path = images_dir / f"{icon_id}.png"

            if not dry_run:
                with zf.open(member) as src, open(image_path, "wb") as dst:
                    dst.write(src.read())

            for text in captions_for_icon(icon_id):
                row = {
                    "image": str(rel_image).replace("\\", "/"),
                    "text": text,
                    "icon_id": icon_id,
                    "source": "material_design_icons",
                    "license": "Apache-2.0",
                    "zip_member": member,
                }
                pair_rows += 1
                if not dry_run:
                    with pairs_path.open("a", encoding="utf-8") as f:
                        f.write(json.dumps(row, ensure_ascii=False) + "\n")

        return len(entries), pair_rows


def main() -> None:
    p = argparse.ArgumentParser(description="Build Material Icons pairs.jsonl from official zip.")
    p.add_argument("--zip", type=Path, default=DEFAULT_ZIP, help="Path to material-design-icons-4.0.0.zip")
    p.add_argument("--dry-run", action="store_true", help="Count only; do not write files")
    args = p.parse_args()

    if not args.dry_run and PAIRS_PATH.exists():
        PAIRS_PATH.unlink()

    n_icons, n_pairs = export(
        args.zip.resolve(),
        images_dir=IMAGES_DIR,
        pairs_path=PAIRS_PATH,
        dry_run=args.dry_run,
    )

    print(f"Icons: {n_icons}")
    print(f"Pairs (image,text rows): {n_pairs}")
    if not args.dry_run:
        print(f"Images: {IMAGES_DIR}")
        print(f"JSONL:  {PAIRS_PATH}")


if __name__ == "__main__":
    main()
