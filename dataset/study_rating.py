"""Optional 1–5 satisfaction prompt after each study utterance."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dataset.study_context import _dataset_root, is_study_ratings_enabled


def _ratings_path() -> Path:
    return _dataset_root() / "study_ratings.jsonl"


def append_study_rating(
    *,
    event_id: str,
    rating: int,
    participant_id: str | None,
    utterance_index: int | None,
) -> None:
    row: dict[str, Any] = {
        "event_id": event_id,
        "rating": int(rating),
        "participant_id": participant_id,
        "utterance_index": utterance_index,
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
) -> None:
    if not is_study_ratings_enabled():
        return

    def _ask() -> None:
        try:
            import tkinter as tk
            from tkinter import simpledialog

            root = ui_root
            created = False
            if root is None:
                root = tk.Tk()
                root.withdraw()
                created = True
            rating = simpledialog.askinteger(
                "Study rating",
                "How well did this command work? (1=poor, 5=excellent)\nLeave Cancel to skip.",
                parent=root,
                minvalue=1,
                maxvalue=5,
            )
            if created:
                root.destroy()
            if rating is None:
                return
            append_study_rating(
                event_id=event_id,
                rating=int(rating),
                participant_id=participant_id,
                utterance_index=utterance_index,
            )
            print(f"[study] Rating saved: event={event_id} rating={rating}")
        except Exception as e:
            print(f"[study] Rating prompt skipped: {e}")

    threading.Thread(target=_ask, daemon=True).start()
