from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2

_LOCK = threading.Lock()
_SESSION_ID: str | None = None


def _is_true(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def is_dataset_logging_enabled() -> bool:
    return _is_true(os.getenv("VOICE_UI_DATASET_LOG"))


def _utc_iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_session_id() -> str:
    global _SESSION_ID
    if _SESSION_ID is not None:
        return _SESSION_ID
    with _LOCK:
        if _SESSION_ID is None:
            _SESSION_ID = datetime.now().strftime("%Y%m%d_%H%M%S")
    return _SESSION_ID


def _dataset_root() -> Path:
    root = os.getenv("VOICE_UI_DATASET_DIR", "dataset")
    p = Path(root)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _events_path() -> Path:
    return _dataset_root() / "events.jsonl"


def _append_event(event: dict[str, Any]) -> None:
    path = _events_path()
    line = json.dumps(event, ensure_ascii=False)
    with _LOCK:
        with path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")


def _safe_imwrite(path: Path, image: Any) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        return bool(cv2.imwrite(str(path), image))
    except Exception:
        return False


def _bbox_to_int_tuple(bbox: Any) -> tuple[int, int, int, int] | None:
    try:
        x1, y1, x2, y2 = bbox
        return int(x1), int(y1), int(x2), int(y2)
    except Exception:
        return None


def _crop_from_bbox(frame: Any, bbox: tuple[int, int, int, int]) -> Any | None:
    if frame is None:
        return None
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = bbox
    x1 = max(0, min(x1, w))
    x2 = max(0, min(x2, w))
    y1 = max(0, min(y1, h))
    y2 = max(0, min(y2, h))
    if x2 <= x1 or y2 <= y1:
        return None
    return frame[y1:y2, x1:x2].copy()


def prepare_grounding_artifacts(
    *,
    raw_text: str,
    action: str,
    query: str | None,
    mode_used: str,
    match: dict[str, Any] | None,
    score: float | int | None,
    frame: Any,
) -> dict[str, Any]:
    """
    Save optional frame/crop artifacts and return metadata to attach into command params.
    Safe no-op when dataset logging is disabled.
    """
    if not is_dataset_logging_enabled():
        return {}

    event_id = str(uuid.uuid4())
    artifacts: dict[str, Any] = {"event_id": event_id}

    bbox = _bbox_to_int_tuple((match or {}).get("bbox"))
    frame_rel = None
    crop_rel = None

    if frame is not None:
        frame_name = f"{event_id}.png"
        frame_path = _dataset_root() / "frames" / frame_name
        if _safe_imwrite(frame_path, frame):
            frame_rel = str(frame_path).replace("\\", "/")

    if bbox is not None and frame is not None:
        crop = _crop_from_bbox(frame, bbox)
        if crop is not None:
            crop_name = f"{event_id}.png"
            crop_path = _dataset_root() / "crops" / crop_name
            if _safe_imwrite(crop_path, crop):
                crop_rel = str(crop_path).replace("\\", "/")

    artifacts.update(
        {
            "raw_text": raw_text,
            "action": action,
            "query": query,
            "mode_used": mode_used,
            "score": float(score) if score is not None else None,
            "bbox": list(bbox) if bbox is not None else None,
            "target_name": (match or {}).get("name"),
            "frame_path": frame_rel,
            "crop_path": crop_rel,
        }
    )
    return artifacts


def log_execute_event(
    *,
    action: str,
    params: dict[str, Any],
    element: dict[str, Any] | None,
    ok: bool,
    reason: str | None,
) -> None:
    if not is_dataset_logging_enabled():
        return

    event_id = params.get("_dataset_event_id") or str(uuid.uuid4())
    bbox = _bbox_to_int_tuple((element or {}).get("bbox"))

    event = {
        "event_id": event_id,
        "ts": _utc_iso_now(),
        "session_id": _get_session_id(),
        "raw_text": params.get("_raw_text"),
        "action": action,
        "query": params.get("query"),
        "mode_used": params.get("_mode_used"),
        "ok": bool(ok),
        "reason": reason,
        "target": {
            "name": (element or {}).get("name"),
            "bbox": list(bbox) if bbox is not None else None,
            "center": (element or {}).get("center"),
        },
        "artifacts": {
            "frame_path": params.get("_dataset_frame_path"),
            "crop_path": params.get("_dataset_crop_path"),
        },
        "meta": {
            "score": params.get("_dataset_score"),
            "target_name": params.get("_dataset_target_name"),
        },
    }
    _append_event(event)
