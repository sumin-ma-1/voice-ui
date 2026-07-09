"""Load task131 utterance list and match study events to task ids."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_TASKS = _REPO_ROOT / "task131.xlsx"


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


@lru_cache(maxsize=1)
def load_task_list(path: str | None = None) -> list[dict[str, str | int]]:
    p = Path(path) if path else _DEFAULT_TASKS
    if not p.is_file():
        return []
    try:
        import openpyxl
    except ImportError:
        return []

    wb = openpyxl.load_workbook(p, read_only=True)
    try:
        ws = wb.active
        tasks: list[dict[str, str | int]] = []
        for i, row in enumerate(ws.iter_rows(min_row=1, values_only=True), start=1):
            cell = row[0] if row else None
            text = str(cell).strip() if cell is not None else ""
            if not text:
                continue
            tasks.append({"task_id": i, "utterance": text, "utterance_norm": _norm(text)})
        return tasks
    finally:
        wb.close()


def match_task(raw_text: str, *, tasks_path: str | None = None) -> dict[str, str | int] | None:
    norm = _norm(raw_text)
    if not norm:
        return None
    tasks = load_task_list(tasks_path)
    for t in tasks:
        if t["utterance_norm"] == norm:
            return {"task_id": t["task_id"], "task_utterance": t["utterance"]}
    for t in tasks:
        u = str(t["utterance_norm"])
        if u in norm or norm in u:
            return {"task_id": t["task_id"], "task_utterance": t["utterance"], "match": "partial"}
    return None
