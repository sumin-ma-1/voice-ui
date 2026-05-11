# agent/process_utterance.py
# One user utterance: parse → Office / direct / grounded UI → execute.

from __future__ import annotations

import os
import time
from typing import TYPE_CHECKING, Any

from automation.action_space import (
    DIRECT_ACTIONS,
    POST_GROUNDING_CLICK_DELAY_ACTIONS,
    UNKNOWN_ACTION,
    is_office_action,
)
from automation.executor import execute
from com.office_controller import OfficeController
from dataset.data_logger import (
    append_hard_negative_rows,
    extra_negatives_cap,
    prepare_grounding_artifacts,
)
from grounding.matcher import find_best_match
from perception.debug_draw import draw_elements, draw_match, show_debug
from perception.grounding_cascade import (
    run_ocr_match_step,
    run_uia_match_step,
    run_vision_match_step,
)
from perception.grounding_highlight import show_grounding_highlight
from perception.ocr_elements import create_easyocr_reader
from perception.screen_capture import capture_screen
from perception.ui_extractor import extract_elements_by_mode
from perception.ui_filter import filter_elements
from perception.ui_fallback_pipeline import (
    STAGE_OCR,
    STAGE_UIA,
    STAGE_VISION,
    run_fullframe_ocr_stage,
    run_uia_stage,
    run_vision_icon_stage,
)
from speech.command_parser import parse_command
from speech.voice_session import contains_wake_phrase, strip_wake_phrase

if TYPE_CHECKING:
    from speech.floating_voice_widget import FloatingVoiceUI
    from speech.voice_session import VoiceSession

SCORE_THRESHOLD = {
    "uia": 31,
    "ocr": 18,
    "vision": 15,
}

EXIT_PHRASES = frozenset(
    {
        "exit",
        "quit",
        "stop agent",
        "shutdown",
    }
)


def _filtered_candidates_for_used_mode(
    used_mode: str, frame: Any, ocr_reader: Any
) -> list[dict[str, Any]]:
    """Rebuild candidate list for the stage that won (for hard-negative dataset mining)."""
    um = (used_mode or "").lower()
    if um == "uia":
        return filter_elements(run_uia_stage())
    if um == "ocr":
        if ocr_reader is None:
            return []
        return filter_elements(run_fullframe_ocr_stage(frame, ocr_reader, conf_min=0.35))
    if um == "vision":
        return filter_elements(run_vision_icon_stage(frame))
    return []


def _grace_wait(
    voice: Any | None,
    ui: Any | None,
    seconds: float,
) -> str:
    """
    Returns:
        "ok" — proceed
        "stop" — user cancelled
        "exit" — user asked to exit during grace
    """
    if voice is None:
        return "ok"

    voice.clear_abort_flags()
    voice.enter_grace()
    if ui is not None:
        ui.set_pipeline_guide('Grace: say "Stop" to cancel, or "Exit" to quit.')
    t_end = time.time() + seconds
    while time.time() < t_end:
        if voice.poll_stop() or voice.consume_stop():
            voice.exit_grace()
            return "stop"
        if voice.poll_exit() or voice.consume_exit():
            voice.exit_grace()
            return "exit"
        time.sleep(0.05)
    voice.exit_grace()
    return "ok"


def _confirm(ui: Any | None, title: str, message: str) -> bool:
    if ui is None or not ui.get_confirm_before_run():
        return True
    return ui.confirm_run(title, message)


def process_utterance(
    text: str,
    *,
    mode: str,
    ocr_reader: Any,
    office: OfficeController,
    ui: FloatingVoiceUI | None,
    voice: VoiceSession | None,
    start_timer: bool = True,
) -> str:
    """
    Returns:
        "exit" — shut down the app
        "continue" — next utterance
    """
    raw = (text or "").strip()
    t = raw.lower()
    if t in EXIT_PHRASES:
        print("Shutting down agent...")
        return "exit"
    if contains_wake_phrase(t):
        rest = strip_wake_phrase(t).lower().strip()
        if rest in EXIT_PHRASES:
            print("Shutting down agent...")
            return "exit"

    print("User utterance:", text)

    start_time = time.time() if start_timer else time.time()
    if start_timer:
        print("Timer starts.")

    parse_source = (text or "").strip()
    if contains_wake_phrase(parse_source.lower()):
        stripped = strip_wake_phrase(parse_source)
        if stripped:
            parse_source = stripped

    command = parse_command(parse_source)
    command["_raw_text"] = (text or "").strip()
    command["_mode_used"] = mode

    action = command["action"]
    print("Parsed command:", command)

    if ui is not None:
        ui.set_pipeline_guide(f"Parsed: {action}")

    if action == UNKNOWN_ACTION:
        print(
            "Could not parse that as a known command. "
            "Try examples: click Save, type hello, copy, open word, scroll down."
        )
        return "continue"

    grace_sec = float(os.getenv("VOICE_UI_GRACE_SECONDS", "0.85"))

    if is_office_action(command.get("action", "")):
        print("Office COM command detected")
        if ui is not None:
            ui.set_pipeline_guide("Running Office action…")
        g = _grace_wait(voice, ui, grace_sec)
        if g == "exit":
            return "exit"
        if g == "stop":
            print("Cancelled before Office run.")
            return "continue"
        if not _confirm(ui, "Confirm Office action", f"Run Office command?\n{command}"):
            print("Cancelled.")
            return "continue"
        success = office.execute(command)
        print(f"Execution time: {time.time() - start_time:.4f} sec")
        if not success:
            print("Office command failed")
        return "continue"

    if action in DIRECT_ACTIONS:
        print("Direct action:", action)
        if ui is not None:
            ui.set_pipeline_guide(f"Direct action: {action}")
        g = _grace_wait(voice, ui, grace_sec)
        if g == "exit":
            return "exit"
        if g == "stop":
            print("Cancelled before direct action.")
            return "continue"
        if not _confirm(ui, "Confirm action", f"Run {action}?"):
            print("Cancelled.")
            return "continue"
        result = execute(action, element=None, params=command)
        if not result.ok:
            print(result.reason)
        print(f"Execution time: {time.time() - start_time:.4f} sec")
        return "continue"

    # --- UI-grounded ---
    frame = capture_screen()
    query = command.get("query", parse_source)

    match = None
    score = 0.0
    used_mode = mode
    filtered: list[dict[str, Any]] = []

    if mode == "all":
        if ui is not None:
            ui.set_pipeline_guide("Finding target: UIA…")
        match, score, used_mode, frame = run_uia_match_step(
            frame,
            query,
            uia_threshold=SCORE_THRESHOLD[STAGE_UIA],
            heading="\n[STEP 1] Try UIA",
            no_match_fallback_message=(
                "[UIA] No confident match → fallback to full-frame OCR"
            ),
            used_mode_on_miss=mode,
        )
        if match is None:
            if ui is not None:
                ui.set_pipeline_guide("Finding target: OCR…")
            match, score, used_mode, frame = run_ocr_match_step(
                frame,
                query,
                ocr_reader,
                ocr_threshold=SCORE_THRESHOLD[STAGE_OCR],
                heading="\n[STEP 2] Try full-frame OCR",
                no_match_fallback_message=(
                    "[OCR] No confident match → fallback to vision (icons + local OCR)"
                ),
                used_mode_on_miss=mode,
            )
        if match is None:
            if ui is not None:
                ui.set_pipeline_guide("Finding target: vision (YOLO)…")
            match, score, used_mode, frame = run_vision_match_step(
                frame,
                query,
                vision_threshold=SCORE_THRESHOLD[STAGE_VISION],
                heading="\n[STEP 3] Try vision (YOLO + localized OCR)",
                used_mode_on_miss=mode,
            )

    elif mode == "both":
        if ui is not None:
            ui.set_pipeline_guide("Finding target: UIA…")
        match, score, used_mode, frame = run_uia_match_step(
            frame,
            query,
            uia_threshold=SCORE_THRESHOLD[STAGE_UIA],
            heading="\n[STEP 1] Try UIA",
            no_match_fallback_message=(
                "[UIA] No confident match → fallback to vision (YOLO + localized OCR)"
            ),
            used_mode_on_miss=mode,
        )
        if match is None:
            if ui is not None:
                ui.set_pipeline_guide("Finding target: vision (YOLO)…")
            match, score, used_mode, frame = run_vision_match_step(
                frame,
                query,
                vision_threshold=SCORE_THRESHOLD[STAGE_VISION],
                heading="\n[STEP 2] Try vision (YOLO + localized OCR)",
                used_mode_on_miss=mode,
            )

    elif mode == "ocr":
        ocr_elements = run_fullframe_ocr_stage(frame, ocr_reader, conf_min=0.35)
        filtered = filter_elements(ocr_elements)
        print(f"[ocr] {len(ocr_elements)} lines → {len(filtered)} after filter")
        if ui is not None:
            ui.set_pipeline_guide("Matching text (OCR)…")
        match, score = find_best_match(query, filtered, screen=frame)

    elif mode in ("uia", "vision"):
        elements = extract_elements_by_mode(mode)
        filtered = filter_elements(elements)
        print(f"[{mode}] {len(elements)} → {len(filtered)}")
        if ui is not None:
            ui.set_pipeline_guide(f"Matching ({mode})…")
        match, score = find_best_match(query, filtered, screen=frame)

    else:
        raise ValueError(f"Unsupported mode: {mode!r}")

    if mode in ("both", "all") and match is not None:
        filtered = _filtered_candidates_for_used_mode(used_mode, frame, ocr_reader)

    print("\nGROUNDING RESULT")
    print("Action:", action)
    print("Query:", query)
    print("Mode used:", used_mode)

    if match:
        print("Matched element:", match["name"])
        print("Score:", score)
    else:
        print("No element selected after matching.")

    if mode in ("both", "all"):
        cascade_ok = match is not None
    else:
        threshold = SCORE_THRESHOLD[mode]
        cascade_ok = bool(match) and score > threshold

    if not cascade_ok:
        print("No confident UI match")
        return "continue"

    frame_for_dataset = frame.copy() if frame is not None else None
    artifacts = prepare_grounding_artifacts(
        raw_text=text,
        action=action,
        query=query,
        mode_used=used_mode,
        match=match,
        score=score,
        frame=frame_for_dataset,
    )
    if artifacts:
        command["_dataset_event_id"] = artifacts.get("event_id")
        command["_dataset_frame_path"] = artifacts.get("frame_path")
        command["_dataset_crop_path"] = artifacts.get("crop_path")
        command["_dataset_score"] = artifacts.get("score")
        command["_dataset_target_name"] = artifacts.get("target_name")
        command["_mode_used"] = used_mode

        n_extra = extra_negatives_cap()
        if n_extra > 0 and filtered and artifacts.get("event_id") and frame_for_dataset is not None:
            append_hard_negative_rows(
                parent_event_id=str(artifacts["event_id"]),
                frame_path=artifacts.get("frame_path"),
                raw_text=text,
                action=action,
                query=query,
                mode_used=used_mode,
                frame=frame_for_dataset,
                positive_bbox=match.get("bbox"),
                candidates=filtered,
                positive_name=match.get("name"),
                max_extra=n_extra,
            )

    if ui is not None:
        ui.set_pipeline_guide("Highlighting target…")
    master = ui.root if ui is not None else None
    if master is not None:
        hl_ms = max(1200, int(grace_sec * 1000) + 400)
        show_grounding_highlight(element=match, master=master, duration_ms=hl_ms)

    g = _grace_wait(voice, ui, grace_sec)
    if g == "exit":
        return "exit"
    if g == "stop":
        print("Cancelled before execute.")
        return "continue"

    if not _confirm(
        ui,
        "Confirm UI action",
        f"{action} on “{match.get('name', '?')}”?",
    ):
        print("Cancelled.")
        return "continue"

    debug_frame = frame.copy() if frame is not None else None
    if debug_frame is not None:
        if mode == "ocr":
            debug_frame = draw_elements(debug_frame, filtered)
        elif mode in ("uia", "vision"):
            debug_frame = draw_elements(debug_frame, filtered)
        debug_frame = draw_match(debug_frame, match)

    if debug_frame is not None:
        show_debug(debug_frame)

    if ui is not None:
        ui.set_pipeline_guide("Executing…")
    result = execute(action, element=match, params=command)
    if not result.ok:
        print(result.reason)
    elif action in POST_GROUNDING_CLICK_DELAY_ACTIONS:
        time.sleep(1.5)

    print(f"Execution time: {time.time() - start_time:.4f} sec")
    return "continue"


def ensure_ocr_reader(mode: str, ocr_reader: Any) -> Any:
    if mode in ("ocr", "all") and ocr_reader is None:
        print("[Init] Loading EasyOCR for full-frame OCR (one-time, may take a while)...")
        return create_easyocr_reader()
    return ocr_reader
