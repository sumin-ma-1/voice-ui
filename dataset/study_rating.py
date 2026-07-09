"""Optional 1–5 satisfaction prompt after each study utterance."""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dataset.study_context import _dataset_root, is_study_ratings_enabled


def _sync_ratings() -> bool:
    return (os.getenv("VOICE_UI_STUDY_RATINGS_SYNC") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _ratings_path() -> Path:
    return _dataset_root() / "study_ratings.jsonl"


def append_study_rating(
    *,
    event_id: str,
    rating: int,
    participant_id: str | None,
    utterance_index: int | None,
    raw_text: str | None = None,
    task_id: int | None = None,
) -> None:
    row: dict[str, Any] = {
        "event_id": event_id,
        "rating": int(rating),
        "participant_id": participant_id,
        "utterance_index": utterance_index,
        "raw_text": raw_text,
        "task_id": task_id,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    path = _ratings_path()
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def prompt_study_rating(
    event_id: str,
    *,
    participant_id: str | None,
    utterance_index: int | None,
    ui_root: Any | None = None,
    raw_text: str | None = None,
    task_id: int | None = None,
) -> None:
    if not is_study_ratings_enabled():
        return

    def _ask() -> None:
        try:
            import tkinter as tk
            from tkinter import simpledialog

            label = (os.getenv("VOICE_UI_STUDY_CURRENT_TASK") or "").strip()
            if not label and raw_text:
                prefix = f"task_id={task_id}  " if task_id is not None else ""
                label = f"{prefix}{raw_text}"
            if label:
                print(f"[study] Rate this command: {label}", flush=True)

            root = ui_root
            created = False
            if root is None:
                root = tk.Tk()
                root.withdraw()
                created = True
            body = "How well did this command work? (1=poor, 5=excellent)\nCancel = skip."
            if label:
                body = f"Command:\n{label}\n\n{body}"
            rating = simpledialog.askinteger(
                "Study rating",
                body,
                parent=root,
                minvalue=1,
                maxvalue=5,
            )
            if created:
                root.destroy()
            if rating is None:
                print("[study] Rating skipped", flush=True)
                return
            append_study_rating(
                event_id=event_id,
                rating=int(rating),
                participant_id=participant_id,
                utterance_index=utterance_index,
                raw_text=raw_text,
                task_id=task_id,
            )
            print(f"[study] Rating saved: {label or event_id} -> {rating}", flush=True)
        except Exception as e:
            print(f"[study] Rating prompt skipped: {e}", flush=True)

    if _sync_ratings():
        _ask()
    else:
        threading.Thread(target=_ask, daemon=True).start()
