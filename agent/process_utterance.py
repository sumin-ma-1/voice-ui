# agent/process_utterance.py
# One user utterance: parse → Office / direct / grounded UI → execute.

from __future__ import annotations

import os
import time
from contextlib import nullcontext
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
    flush_study_execute_log,
    log_study_utterance,
    prepare_grounding_artifacts,
)
from dataset.study_context import StudyRecorder, maybe_start_recorder
from dataset.study_rating import prompt_study_rating
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
from speech.target_text import refine_parsed_voice_query
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


def _log_study(
    recorder: StudyRecorder | None,
    *,
    outcome: str,
    action: str | None = None,
    query: str | None = None,
    mode_used: str | None = None,
    ok: bool | None = None,
    reason: str | None = None,
    element: dict[str, Any] | None = None,
    artifacts: dict[str, Any] | None = None,
    match_score: float | None = None,
    ui: Any | None = None,
    prompt_rating: bool = False,
    raw_text: str | None = None,
) -> None:
    if recorder is None:
        return
    event_id = log_study_utterance(
        recorder=recorder,
        outcome=outcome,
        action=action,
        query=query,
        mode_used=mode_used,
        ok=ok,
        reason=reason,
        element=element,
        artifacts=artifacts,
        match_score=match_score,
    )
    if prompt_rating and outcome in {"success", "office_ok"}:
        from dataset.study_context import get_participant_id

        prompt_study_rating(
            event_id,
            participant_id=get_participant_id(),
            utterance_index=None,
            ui_root=getattr(ui, "root", None) if ui is not None else None,
            raw_text=raw_text,
        )


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

    study = maybe_start_recorder(text, mode_requested=mode)

    parse_source = (text or "").strip()
    if contains_wake_phrase(parse_source.lower()):
        stripped = strip_wake_phrase(parse_source)
        if stripped:
            parse_source = stripped

    with study.time_block("parse") if study else nullcontext():
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
        _log_study(
            study,
            outcome="parse_fail",
            action=action,
            query=command.get("query"),
            mode_used=mode,
            ok=False,
            reason="unknown_action",
        )
        return "continue"

    grace_sec = float(os.getenv("VOICE_UI_GRACE_SECONDS", "0.85"))

    if is_office_action(command.get("action", "")):
        print("Office COM command detected")
        if ui is not None:
            ui.set_pipeline_guide("Running Office action…")
        with study.time_block("grace") if study else nullcontext():
            g = _grace_wait(voice, ui, grace_sec)
        if g == "exit":
            return "exit"
        if g == "stop":
            print("Cancelled before Office run.")
            _log_study(
                study,
                outcome="cancelled_grace",
                action=action,
                query=command.get("query"),
                mode_used=mode,
                ok=False,
                reason="grace_stop",
            )
            return "continue"
        with study.time_block("confirm") if study else nullcontext():
            confirmed = _confirm(ui, "Confirm Office action", f"Run Office command?\n{command}")
        if not confirmed:
            print("Cancelled.")
            _log_study(
                study,
                outcome="cancelled_confirm",
                action=action,
                query=command.get("query"),
                mode_used=mode,
                ok=False,
                reason="confirm_cancel",
            )
            return "continue"
        with study.time_block("execute") if study else nullcontext():
            success = office.execute(command)
        print(f"Execution time: {time.time() - start_time:.4f} sec")
        if not success:
            print("Office command failed")
        _log_study(
            study,
            outcome="office_ok" if success else "office_fail",
            action=action,
            query=command.get("query"),
            mode_used=mode,
            ok=bool(success),
            reason=None if success else "office_execute_failed",
            ui=ui,
            prompt_rating=bool(success),
            raw_text=text,
        )
        return "continue"

    if action in DIRECT_ACTIONS:
        print("Direct action:", action)
        if ui is not None:
            ui.set_pipeline_guide(f"Direct action: {action}")
        with study.time_block("grace") if study else nullcontext():
            g = _grace_wait(voice, ui, grace_sec)
        if g == "exit":
            return "exit"
        if g == "stop":
            print("Cancelled before direct action.")
            _log_study(
                study,
                outcome="cancelled_grace",
                action=action,
                query=command.get("query"),
                mode_used=mode,
                ok=False,
                reason="grace_stop",
            )
            return "continue"
        with study.time_block("confirm") if study else nullcontext():
            confirmed = _confirm(ui, "Confirm action", f"Run {action}?")
        if not confirmed:
            print("Cancelled.")
            _log_study(
                study,
                outcome="cancelled_confirm",
                action=action,
                query=command.get("query"),
                mode_used=mode,
                ok=False,
                reason="confirm_cancel",
            )
            return "continue"
        if study:
            study.attach_to_command(command)
        with study.time_block("execute") if study else nullcontext():
            result = execute(action, element=None, params=command)
        if study and study.has_pending_execute():
            flush_study_execute_log(
                study,
                query=command.get("query"),
                mode_used=mode,
            )
        if not result.ok:
            print(result.reason)
        print(f"Execution time: {time.time() - start_time:.4f} sec")
        if study is not None and result.ok:
            from dataset.study_context import get_participant_id

            prompt_study_rating(
                study.event_id,
                participant_id=get_participant_id(),
                utterance_index=None,
                ui_root=getattr(ui, "root", None) if ui is not None else None,
                raw_text=text,
            )
        return "continue"

    # --- UI-grounded ---
    capture_ctx = study.time_block("capture") if study else nullcontext()
    with capture_ctx:
        frame = capture_screen()
    query = refine_parsed_voice_query(command.get("query", parse_source) or "")

    match = None
    score = 0.0
    used_mode = mode
    filtered: list[dict[str, Any]] = []

    if mode == "all":
        if ui is not None:
            ui.set_pipeline_guide("Finding target: UIA…")
        with study.time_block("uia") if study else nullcontext():
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
            with study.time_block("ocr") if study else nullcontext():
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
            with study.time_block("vision") if study else nullcontext():
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
        with study.time_block("uia") if study else nullcontext():
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
            with study.time_block("vision") if study else nullcontext():
                match, score, used_mode, frame = run_vision_match_step(
                    frame,
                    query,
                    vision_threshold=SCORE_THRESHOLD[STAGE_VISION],
                    heading="\n[STEP 2] Try vision (YOLO + localized OCR)",
                    used_mode_on_miss=mode,
                )

    elif mode == "ocr":
        with study.time_block("ocr") if study else nullcontext():
            ocr_elements = run_fullframe_ocr_stage(frame, ocr_reader, conf_min=0.35)
        filtered = filter_elements(ocr_elements)
        print(f"[ocr] {len(ocr_elements)} lines → {len(filtered)} after filter")
        if ui is not None:
            ui.set_pipeline_guide("Matching text (OCR)…")
        with study.time_block("match") if study else nullcontext():
            match, score = find_best_match(query, filtered, screen=frame)
        used_mode = "ocr"

    elif mode in ("uia", "vision"):
        stage_key = mode
        with study.time_block(stage_key) if study else nullcontext():
            elements = extract_elements_by_mode(mode)
        filtered = filter_elements(elements)
        print(f"[{mode}] {len(elements)} → {len(filtered)}")
        if ui is not None:
            ui.set_pipeline_guide(f"Matching ({mode})…")
        with study.time_block("match") if study else nullcontext():
            match, score = find_best_match(query, filtered, screen=frame)
        used_mode = mode

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

    if study is not None:
        study.set_grounding_path(used_mode if match else None)

    if mode in ("both", "all"):
        cascade_ok = match is not None
    else:
        threshold = SCORE_THRESHOLD[mode]
        cascade_ok = bool(match) and score > threshold

    if not cascade_ok:
        print("No confident UI match")
        _log_study(
            study,
            outcome="no_match",
            action=action,
            query=query,
            mode_used=used_mode,
            ok=False,
            reason="below_threshold_or_no_candidate",
            element=match,
            match_score=float(score) if score is not None else None,
        )
        return "continue"

    frame_for_dataset = frame.copy() if frame is not None else None
    with study.time_block("artifacts") if study else nullcontext():
        artifacts = prepare_grounding_artifacts(
            raw_text=text,
            action=action,
            query=query,
            mode_used=used_mode,
            match=match,
            score=score,
            frame=frame_for_dataset,
            event_id=study.event_id if study is not None else None,
        )
    if artifacts:
        command["_dataset_event_id"] = artifacts.get("event_id")
        command["_dataset_frame_id"] = artifacts.get("frame_id")
        command["_dataset_frame_path"] = artifacts.get("frame_path")
        command["_dataset_crop_path"] = artifacts.get("crop_path")
        command["_dataset_score"] = artifacts.get("score")
        command["_dataset_target_name"] = artifacts.get("target_name")
        command["_dataset_is_icon"] = artifacts.get("is_icon")
        command["_dataset_icon_like"] = artifacts.get("icon_like")
        command["_dataset_control_type"] = artifacts.get("control_type")
        command["_mode_used"] = used_mode

        n_extra = extra_negatives_cap()
        if n_extra > 0 and filtered and artifacts.get("event_id") and frame_for_dataset is not None:
            append_hard_negative_rows(
                parent_event_id=str(artifacts["event_id"]),
                frame_path=artifacts.get("frame_path"),
                frame_id=artifacts.get("frame_id"),
                raw_text=text,
                action=action,
                query=query,
                mode_used=used_mode,
                frame=frame_for_dataset,
                positive_bbox=match.get("bbox"),
                candidates=filtered,
                positive_name=match.get("name"),
                positive_is_icon=bool(match.get("is_icon", False)),
                positive_icon_like=bool(match.get("icon_like", False)),
                max_extra=n_extra,
            )

    if ui is not None:
        ui.set_pipeline_guide("Highlighting target…")
    master = ui.root if ui is not None else None
    if master is not None:
        hl_ms = max(1200, int(grace_sec * 1000) + 400)
        with study.time_block("highlight") if study else nullcontext():
            show_grounding_highlight(element=match, master=master, duration_ms=hl_ms)

    with study.time_block("grace") if study else nullcontext():
        g = _grace_wait(voice, ui, grace_sec)
    if g == "exit":
        return "exit"
    if g == "stop":
        print("Cancelled before execute.")
        _log_study(
            study,
            outcome="cancelled_grace",
            action=action,
            query=query,
            mode_used=used_mode,
            ok=False,
            reason="grace_stop",
            element=match,
            artifacts=artifacts,
            match_score=float(score) if score is not None else None,
        )
        return "continue"

    with study.time_block("confirm") if study else nullcontext():
        confirmed = _confirm(
            ui,
            "Confirm UI action",
            f"{action} on “{match.get('name', '?')}”?",
        )
    if not confirmed:
        print("Cancelled.")
        _log_study(
            study,
            outcome="cancelled_confirm",
            action=action,
            query=query,
            mode_used=used_mode,
            ok=False,
            reason="confirm_cancel",
            element=match,
            artifacts=artifacts,
            match_score=float(score) if score is not None else None,
        )
        return "continue"

    debug_frame = frame.copy() if frame is not None else None
    with study.time_block("debug") if study else nullcontext():
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
    if study:
        study.attach_to_command(command)
    with study.time_block("execute") if study else nullcontext():
        result = execute(action, element=match, params=command)
    if study and study.has_pending_execute():
        flush_study_execute_log(
            study,
            query=query,
            mode_used=used_mode,
        )
    if not result.ok:
        print(result.reason)
    elif action in POST_GROUNDING_CLICK_DELAY_ACTIONS:
        time.sleep(1.5)

    if study is not None and result.ok:
        from dataset.study_context import get_participant_id

        prompt_study_rating(
            study.event_id,
            participant_id=get_participant_id(),
            utterance_index=None,
            ui_root=getattr(ui, "root", None) if ui is not None else None,
            raw_text=text,
        )

    print(f"Execution time: {time.time() - start_time:.4f} sec")
    return "continue"


def ensure_ocr_reader(mode: str, ocr_reader: Any) -> Any:
    if mode in ("ocr", "all") and ocr_reader is None:
        print("[Init] Loading EasyOCR for full-frame OCR (one-time, may take a while)...")
        return create_easyocr_reader()
    return ocr_reader
