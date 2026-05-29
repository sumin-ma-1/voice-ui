from __future__ import annotations

import json
import os
import random
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2

from dataset import runtime_overrides

_LOCK = threading.Lock()
_SESSION_ID: str | None = None


def is_dataset_logging_enabled() -> bool:
    """Each call: ``runtime_overrides`` then ``VOICE_UI_DATASET_LOG`` (change at runtime in dev)."""
    return runtime_overrides.effective_dataset_log()


def extra_negatives_cap() -> int:
    """
    Max extra hard-negative crop rows per successful grounding (same utterance + frame).
    ``VOICE_UI_DATASET_EXTRA_NEGATIVES=6`` or ``true`` (defaults to 6). ``0`` / unset = off.
    Override via ``!dataset negs …`` in text dev mode.
    """
    return runtime_overrides.effective_extra_negatives_cap()


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


def save_scan_frame(frame: Any) -> dict[str, str] | None:
    """
    Persist one full-screen capture for a single UIA scan (one ``look``).

    Returns ``{"frame_id", "frame_path"}`` for reuse across multiple targets on the
    same screen. Safe no-op when dataset logging is disabled or write fails.
    """
    if not is_dataset_logging_enabled() or frame is None:
        return None
    frame_id = str(uuid.uuid4())
    frame_path = _dataset_root() / "frames" / f"{frame_id}.png"
    if not _safe_imwrite(frame_path, frame):
        return None
    return {
        "frame_id": frame_id,
        "frame_path": str(frame_path).replace("\\", "/"),
    }


def prepare_grounding_artifacts(
    *,
    raw_text: str,
    action: str,
    query: str | None,
    mode_used: str,
    match: dict[str, Any] | None,
    score: float | int | None,
    frame: Any,
    shared_frame: dict[str, str] | None = None,
) -> dict[str, Any]:
    """
    Save optional frame/crop artifacts and return metadata to attach into command params.

    When ``shared_frame`` is set (from :func:`save_scan_frame`), only the crop is written;
    all events from that scan reference the same ``frame_path`` / ``frame_id``.

    Safe no-op when dataset logging is disabled.
    """
    if not is_dataset_logging_enabled():
        return {}

    event_id = str(uuid.uuid4())
    artifacts: dict[str, Any] = {"event_id": event_id}

    m = match or {}
    bbox = _bbox_to_int_tuple(m.get("bbox"))
    is_icon = bool(m.get("is_icon", False))
    icon_like = bool(m.get("icon_like", False))
    frame_rel: str | None = None
    frame_id: str | None = None
    crop_rel = None

    if shared_frame:
        frame_rel = shared_frame.get("frame_path")
        frame_id = shared_frame.get("frame_id")
    elif frame is not None:
        frame_id = event_id
        frame_path = _dataset_root() / "frames" / f"{frame_id}.png"
        if _safe_imwrite(frame_path, frame):
            frame_rel = str(frame_path).replace("\\", "/")

    if bbox is not None and frame is not None:
        crop = _crop_from_bbox(frame, bbox)
        if crop is not None:
            crop_path = _dataset_root() / "crops" / f"{event_id}.png"
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
            "target_name": m.get("name"),
            "is_icon": is_icon,
            "icon_like": icon_like,
            "control_type": m.get("control_type"),
            "frame_id": frame_id,
            "frame_path": frame_rel,
            "crop_path": crop_rel,
        }
    )
    return artifacts


def append_hard_negative_rows(
    *,
    parent_event_id: str,
    frame_path: str | None,
    frame_id: str | None = None,
    raw_text: str,
    action: str,
    query: str | None,
    mode_used: str,
    frame: Any,
    positive_bbox: tuple[int, int, int, int] | None,
    candidates: list[dict[str, Any]],
    positive_name: str | None,
    positive_is_icon: bool | None,
    positive_icon_like: bool | None = None,
    max_extra: int,
) -> None:
    """
    Append one JSONL row per non-chosen candidate crop (contrastive / ranking training).
    Requires ``VOICE_UI_DATASET_LOG`` on; ``max_extra`` from :func:`extra_negatives_cap`.

    ``positive_is_icon`` / ``positive_icon_like`` on ``meta`` for stage-2 export filters.
    """
    if not is_dataset_logging_enabled() or max_extra <= 0:
        return
    if frame is None or not candidates:
        return

    def _norm_bbox(b: Any) -> tuple[int, int, int, int] | None:
        t = _bbox_to_int_tuple(b)
        return t

    pos = _norm_bbox(positive_bbox)
    pool: list[dict[str, Any]] = []
    for el in candidates:
        bb = _norm_bbox(el.get("bbox"))
        if bb is None:
            continue
        if pos is not None and bb == pos:
            continue
        pool.append(el)
    if not pool:
        return
    random.shuffle(pool)
    pool = pool[:max_extra]

    for el in pool:
        bb = _norm_bbox(el.get("bbox"))
        if bb is None:
            continue
        neg_id = str(uuid.uuid4())
        crop = _crop_from_bbox(frame, bb)
        if crop is None:
            continue
        crop_path = _dataset_root() / "crops" / f"{neg_id}.png"
        if not _safe_imwrite(crop_path, crop):
            continue
        crop_rel = str(crop_path).replace("\\", "/")
        event = {
            "event_id": neg_id,
            "ts": _utc_iso_now(),
            "session_id": _get_session_id(),
            "raw_text": raw_text,
            "action": action,
            "query": query,
            "mode_used": mode_used,
            "ok": None,
            "reason": "negative_hard_sample",
            "target": {
                "name": el.get("name"),
                "bbox": list(bb),
                "center": el.get("center"),
                "is_icon": bool(el.get("is_icon", False)),
                "icon_like": bool(el.get("icon_like", False)),
                "control_type": el.get("control_type"),
            },
            "artifacts": {
                "frame_id": frame_id,
                "frame_path": frame_path,
                "crop_path": crop_rel,
            },
            "meta": {
                "label": "negative_hard",
                "pair_event_id": parent_event_id,
                "positive_name": positive_name,
                "positive_is_icon": positive_is_icon,
                "positive_icon_like": positive_icon_like,
                "positive_bbox": list(pos) if pos else None,
            },
        }
        _append_event(event)


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
            "is_icon": (
                (element or {}).get("is_icon")
                if (element or {}).get("is_icon") is not None
                else params.get("_dataset_is_icon")
            ),
            "icon_like": (
                (element or {}).get("icon_like")
                if (element or {}).get("icon_like") is not None
                else params.get("_dataset_icon_like")
            ),
            "control_type": (element or {}).get("control_type")
            or params.get("_dataset_control_type"),
        },
        "artifacts": {
            "frame_id": params.get("_dataset_frame_id"),
            "frame_path": params.get("_dataset_frame_path"),
            "crop_path": params.get("_dataset_crop_path"),
        },
        "meta": {
            "score": params.get("_dataset_score"),
            "target_name": params.get("_dataset_target_name"),
            **(params.get("_dataset_meta_extra") or {}),
        },
    }
    _append_event(event)
