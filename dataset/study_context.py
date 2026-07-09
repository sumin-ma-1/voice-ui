"""User-study helpers: participant context, surface labels, timings, system manifest."""

from __future__ import annotations

import json
import os
import platform
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import win32gui
except ImportError:  # pragma: no cover
    win32gui = None  # type: ignore

_MANIFEST_WRITTEN = False
_UTTERANCE_INDEX = 0
_INDEX_LOCK = threading.Lock()

_BROWSER_TOKENS = (
    "google chrome",
    "microsoft edge",
    "mozilla firefox",
    "brave",
    "opera",
    "vivaldi",
)
_NATIVE_APP_TOKENS: tuple[tuple[str, str], ...] = (
    ("word", "Word"),
    ("excel", "Excel"),
    ("powerpoint", "PowerPoint"),
    ("outlook", "Outlook"),
    ("visual studio code", "VS Code"),
    ("한글", "Hancom"),
    ("hwp", "Hancom"),
    ("notepad", "Notepad"),
)
_SHOPPING_HINTS = (
    "amazon",
    "ebay",
    "coupang",
    "gmarket",
    "11st",
    "shop",
    "shopping",
    "store",
    "cart",
)
_YOUTUBE_HINTS = ("youtube", "youtu.be")

_PIPELINE_KEYS = ("stt", "parse", "capture", "uia", "ocr", "vision", "match", "execute")
_UX_KEYS = ("grace", "highlight", "confirm", "debug", "artifacts")

# Set by speech.voice_session after final Whisper pass (voice input only).
_LAST_VOICE_STT_MS: float | None = None


def is_study_mode() -> bool:
    if _truthy(os.getenv("VOICE_UI_STUDY")):
        return True
    return bool((os.getenv("VOICE_UI_STUDY_USER") or "").strip())


def is_study_ratings_enabled() -> bool:
    return _truthy(os.getenv("VOICE_UI_STUDY_RATINGS"))


def _truthy(v: str | None) -> bool:
    return (v or "").strip().lower() in {"1", "true", "yes", "on"}


def get_participant_id() -> str | None:
    pid = (os.getenv("VOICE_UI_STUDY_USER") or "").strip()
    return pid or None


def get_input_mode() -> str:
    return (os.getenv("VOICE_UI_INPUT_MODE") or "text").strip().lower()


def _dataset_root() -> Path:
    root = os.getenv("VOICE_UI_DATASET_DIR", "dataset")
    p = Path(root)
    p.mkdir(parents=True, exist_ok=True)
    return p


def next_utterance_index() -> int:
    global _UTTERANCE_INDEX
    with _INDEX_LOCK:
        _UTTERANCE_INDEX += 1
        return _UTTERANCE_INDEX


def get_foreground_window_title() -> str:
    if win32gui is None:
        return ""
    try:
        hwnd = win32gui.GetForegroundWindow()
        if not hwnd:
            return ""
        return str(win32gui.GetWindowText(hwnd) or "").strip()
    except Exception:
        return ""


def _strip_browser_suffix(title: str) -> str:
    t = title.strip()
    for token in _BROWSER_TOKENS:
        suffix = f" - {token}"
        if t.lower().endswith(suffix):
            return t[: -len(suffix)].strip()
        suffix2 = f" — {token.title()}"
        if t.lower().endswith(suffix2.lower()):
            return t[: -len(suffix2)].strip()
    return t


def _infer_web_category(title_lower: str) -> str | None:
    if any(h in title_lower for h in _YOUTUBE_HINTS):
        return "youtube"
    if any(h in title_lower for h in _SHOPPING_HINTS):
        return "shopping"
    return None


def infer_surface_context(window_title: str | None = None) -> dict[str, Any]:
    title = (window_title if window_title is not None else get_foreground_window_title()).strip()
    lower = title.lower()

    surface_class = "unknown"
    app_name: str | None = None
    domain_hint: str | None = None
    web_category: str | None = None

    browser = next((b for b in _BROWSER_TOKENS if b in lower), None)
    if browser:
        surface_class = "web_in_browser"
        app_name = browser.title()
        page_title = _strip_browser_suffix(title)
        web_category = _infer_web_category(page_title.lower())
        domain_hint = web_category
    else:
        for needle, label in _NATIVE_APP_TOKENS:
            if needle in lower:
                surface_class = "native_app"
                app_name = label
                break
        if surface_class == "unknown" and title:
            surface_class = "native_app"
            app_name = title.split(" - ")[0].strip() or title

    return {
        "window_title": title or None,
        "surface_class": surface_class,
        "app_name": app_name,
        "domain_hint": domain_hint,
        "web_category": web_category,
    }


def target_meta_flags(element: dict[str, Any] | None) -> dict[str, bool]:
    el = element or {}
    name = el.get("name")
    bbox = el.get("bbox")
    control_type = el.get("control_type")
    return {
        "has_name": bool(name and str(name).strip()),
        "has_bbox": bbox is not None and len(bbox) == 4,
        "has_control_type": bool(control_type and str(control_type).strip()),
    }


def set_last_voice_stt_ms(ms: float | None) -> None:
    global _LAST_VOICE_STT_MS
    _LAST_VOICE_STT_MS = ms


def consume_last_voice_stt_ms() -> float | None:
    global _LAST_VOICE_STT_MS
    ms = _LAST_VOICE_STT_MS
    _LAST_VOICE_STT_MS = None
    return ms


def _system_specs() -> dict[str, Any]:
    specs: dict[str, Any] = {
        "platform": platform.platform(),
        "processor": platform.processor() or platform.machine(),
        "python": platform.python_version(),
        "machine": platform.machine(),
    }
    try:
        import psutil  # optional

        vm = psutil.virtual_memory()
        specs["ram_gb"] = round(vm.total / (1024**3), 1)
        specs["ram_available_gb"] = round(vm.available / (1024**3), 1)
        specs["cpu_count_logical"] = psutil.cpu_count(logical=True)
        specs["cpu_count_physical"] = psutil.cpu_count(logical=False)
        specs["disk_free_gb"] = round(
            psutil.disk_usage(str(Path.cwd().anchor or "C:\\")).free / (1024**3), 1
        )
    except Exception:
        pass

    try:
        import torch

        specs["cuda_available"] = bool(torch.cuda.is_available())
        if torch.cuda.is_available():
            specs["gpu_name"] = torch.cuda.get_device_name(0)
            specs["gpu_vram_gb"] = round(
                torch.cuda.get_device_properties(0).total_memory / (1024**3), 1
            )
    except Exception:
        specs["cuda_available"] = False

    clip_ckpt = os.getenv("VOICE_UI_CLIP_CHECKPOINT", "").strip()
    if not clip_ckpt:
        default = Path("training_data/icons_material/checkpoints/stage1_best.pt")
        clip_ckpt = str(default) if default.is_file() else "default"
    specs["clip_checkpoint"] = clip_ckpt
    return specs


def study_hardware_notes(specs: dict[str, Any]) -> dict[str, Any]:
    """Reboot / environment recommendations from one-time manifest specs."""
    ram = float(specs.get("ram_gb") or 0)
    disk = float(specs.get("disk_free_gb") or 0)
    reboot_recommended = ram < 16 or disk < 10
    return {
        "min_ram_gb_recommended": 16,
        "min_disk_free_gb_recommended": 10,
        "gpu_optional_for_vision": True,
        "reboot_before_session_recommended": reboot_recommended,
        "reboot_reason": (
            "RAM<16GB or disk<10GB free at session start"
            if reboot_recommended
            else None
        ),
        "close_heavy_apps_recommended": True,
    }


def _task_list_manifest() -> dict[str, Any]:
    from dataset.study_tasks import load_task_list

    tasks = load_task_list()
    return {"file": "task131.xlsx", "count": len(tasks)}


def ensure_study_manifest(*, mode: str, input_kind: str) -> None:
    global _MANIFEST_WRITTEN
    if not is_study_mode() or _MANIFEST_WRITTEN:
        return
    path = _dataset_root() / "study_manifest.json"
    if path.is_file():
        _MANIFEST_WRITTEN = True
        return

    system = _system_specs()
    session_type = (os.getenv("VOICE_UI_STUDY_SESSION_TYPE") or "user_study").strip()
    manifest = {
        "participant_id": get_participant_id(),
        "session_id": datetime_session_id(),
        "session_type": session_type,
        "mode": mode,
        "input_mode": input_kind,
        "system": system,
        "hardware_guidance": study_hardware_notes(system),
        "latency_metrics": {
            "primary": "latency_ms.pipeline",
            "definition": (
                "pipeline = parse + screen capture + grounding (uia/ocr/vision/match) "
                "+ execute (automation). Excludes grace/highlight/confirm UI delays."
            ),
            "wall_clock_includes_ux": "latency_ms.wall_clock",
        },
        "task_list": _task_list_manifest(),
        "notes": (
            "surface_class: native_app = local Win32/UIA apps; "
            "web_in_browser = pages rendered inside Chrome/Edge (e.g. YouTube, shopping)."
        ),
    }
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    _MANIFEST_WRITTEN = True
    print(f"[study] Wrote manifest -> {path}")


def datetime_session_id() -> str:
    from datetime import datetime

    return datetime.now().strftime("%Y%m%d_%H%M%S")


@dataclass
class StudyRecorder:
    """Collect per-utterance study metadata and timings."""

    raw_text: str
    mode_requested: str
    input_mode: str
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    t0: float = field(default_factory=time.perf_counter)
    timings_ms: dict[str, float] = field(default_factory=dict)
    grounding_path: str | None = None
    vision_used: bool = False
    surface: dict[str, Any] = field(default_factory=dict)
    _pending_execute: dict[str, Any] | None = field(default=None, repr=False)
    _wall_clock_ms: float | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        stt = consume_last_voice_stt_ms()
        if stt is not None:
            self.timings_ms["stt"] = round(stt, 2)
        self.surface = infer_surface_context()

    def mark_ms(self, key: str, elapsed_ms: float) -> None:
        self.timings_ms[key] = round(float(elapsed_ms), 2)

    def time_block(self, key: str):
        return _TimingBlock(self, key)

    def set_grounding_path(self, used_mode: str | None) -> None:
        if used_mode:
            self.grounding_path = used_mode
            self.vision_used = used_mode == "vision"

    def total_ms(self) -> float:
        return round((time.perf_counter() - self.t0) * 1000.0, 2)

    def freeze_wall_clock(self) -> None:
        """Call immediately before logging (avoids heavy imports inflating wall_clock)."""
        self._wall_clock_ms = self.total_ms()

    def wall_clock_ms(self) -> float:
        return self._wall_clock_ms if self._wall_clock_ms is not None else self.total_ms()

    def pipeline_ms(self) -> float:
        return round(
            sum(self.timings_ms.get(k, 0.0) for k in _PIPELINE_KEYS),
            2,
        )

    def ux_overhead_ms(self) -> float:
        return round(sum(self.timings_ms.get(k, 0.0) for k in _UX_KEYS), 2)

    def refresh_surface(self) -> None:
        self.surface = infer_surface_context()

    def set_pending_execute(
        self,
        *,
        action: str,
        ok: bool,
        reason: str | None,
        element: dict[str, Any] | None,
        artifacts: dict[str, Any] | None,
        match_score: float | None,
    ) -> None:
        self._pending_execute = {
            "action": action,
            "ok": ok,
            "reason": reason,
            "element": element,
            "artifacts": artifacts or {},
            "match_score": match_score,
        }

    def has_pending_execute(self) -> bool:
        return self._pending_execute is not None

    def build_study_block(
        self,
        *,
        outcome: str,
        route: str | None,
        ok: bool | None,
        reason: str | None,
        action: str | None,
        query: str | None,
        mode_used: str | None,
        match_score: float | None,
        element: dict[str, Any] | None,
    ) -> dict[str, Any]:
        gpu_used = False
        gpu_name: str | None = None
        if self.vision_used:
            try:
                import torch

                gpu_used = bool(torch.cuda.is_available())
                if gpu_used:
                    gpu_name = torch.cuda.get_device_name(0)
            except Exception:
                pass

        flags = target_meta_flags(element)
        from dataset.study_tasks import match_task

        task = match_task(self.raw_text)
        return {
            "participant_id": get_participant_id(),
            "utterance_index": next_utterance_index(),
            "input_mode": self.input_mode,
            "outcome": outcome,
            "route": route,
            "ok": ok,
            "reason": reason,
            "action": action,
            "query": query,
            "mode_requested": self.mode_requested,
            "mode_used": mode_used,
            "grounding_path": self.grounding_path or mode_used,
            "vision_used": self.vision_used,
            "gpu_used": gpu_used,
            "gpu_name": gpu_name,
            "match_score": match_score,
            "task": task,
            "latency_ms": {
                "pipeline": self.pipeline_ms(),
                "wall_clock": self.wall_clock_ms(),
                "ux_overhead": self.ux_overhead_ms(),
                **self.timings_ms,
            },
            "surface": self.surface,
            "target_meta": flags,
        }

    def attach_to_command(self, command: dict[str, Any]) -> None:
        command["_study_recorder"] = self


class _TimingBlock:
    def __init__(self, recorder: StudyRecorder, key: str) -> None:
        self.recorder = recorder
        self.key = key
        self.t0 = 0.0

    def __enter__(self) -> _TimingBlock:
        self.t0 = time.perf_counter()
        return self

    def __exit__(self, *args: object) -> None:
        self.recorder.mark_ms(self.key, (time.perf_counter() - self.t0) * 1000.0)


def route_for_action(action: str | None) -> str | None:
    if not action:
        return None
    from automation.action_space import DIRECT_ACTIONS, is_office_action

    if is_office_action(action):
        return "office"
    if action in DIRECT_ACTIONS:
        return "direct"
    return "grounded"


def maybe_start_recorder(
    raw_text: str,
    *,
    mode_requested: str,
) -> StudyRecorder | None:
    if not is_study_mode():
        return None
    os.environ.setdefault("VOICE_UI_DATASET_LOG", "1")
    return StudyRecorder(
        raw_text=raw_text,
        mode_requested=mode_requested,
        input_mode=get_input_mode(),
    )
