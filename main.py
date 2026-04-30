# main.py
# Main script: UI grounding modes via --mode
# How to run:
#   python main.py --mode {uia|ocr|vision|both|all}
#
#   uia     — accessibility tree only
#   ocr     — full-frame EasyOCR only
#   vision  — YOLO icons + localized OCR only
#   both    — UIA then vision (two-step fallback)
#   all     — UIA then full-frame OCR then vision (three-step fallback)
#
#   To escape the running agent, press Ctrl+C
#   To exit the agent, type "exit", "quit", "stop agent", "shutdown"
#   UIA defaults to native on-screen extraction (``IsOffscreen`` + DFS prune); see
#   ``perception.uia_onscreen_extractor``. To use classic ``descendants`` instead, set
#   ``VOICE_UI_UIA_USE_CLASSIC`` to 1 / true / yes / on. Remove the variable (or any other
#   value) to use on-screen UIA again.
#   PowerShell classic: ``$env:VOICE_UI_UIA_USE_CLASSIC = "1"``
#   See ``perception.ui_extractor`` for details.

import argparse
import time

from speech.text_input_gui import TextInputGUI
from speech.command_parser import parse_command

from perception.ui_extractor import extract_elements_by_mode
from perception.ui_filter import filter_elements
from perception.ui_fallback_pipeline import (
    run_fullframe_ocr_stage,
    STAGE_UIA,
    STAGE_OCR,
    STAGE_VISION,
)
from perception.grounding_cascade import (
    run_ocr_match_step,
    run_uia_match_step,
    run_vision_match_step,
)
from perception.ocr_elements import create_easyocr_reader
from grounding.matcher import find_best_match
from automation.executor import execute
from automation.action_space import (
    DIRECT_ACTIONS,
    POST_GROUNDING_CLICK_DELAY_ACTIONS,
    UNKNOWN_ACTION,
)

from perception.screen_capture import capture_screen
from perception.debug_draw import draw_elements, draw_match, show_debug

from com.office_controller import OfficeController
from com.office_dispatcher import OfficeDispatcher

# ---- MODE-specific THRESHOLDS ----
# Single modes (uia / ocr / vision) use the key matching --mode.
# Cascades (both / all) apply STAGE_UIA / STAGE_OCR / STAGE_VISION inside the loop.
SCORE_THRESHOLD = {
    "uia": 31,
    "ocr": 18,
    "vision": 15,
}

def main(mode):

    text_input = TextInputGUI()

    # ---- OFFICE COM ----
    office = OfficeController()
    office_dispatcher = OfficeDispatcher()

    # EasyOCR is only needed for full-frame OCR (single ``ocr`` mode or ``all`` cascade).
    ocr_reader = None
    if mode in ("ocr", "all"):
        print("[Init] Loading EasyOCR for full-frame OCR (one-time, may take a while)...")
        ocr_reader = create_easyocr_reader()

    print(f"Experiment agent started  [mode={mode}]")

    while True:

        frame = None

        try:

            text = text_input.get_input()

            if not text:
                continue

            if text.lower() in ["exit", "quit", "stop agent", "shutdown"]:
                print("Shutting down agent...")
                break

            print("User typed:", text)

            # ---- START TIMER ----
            start_time = time.time()
            print(f"Timer starts.")

            command = parse_command(text)

            action = command["action"]

            print("Parsed command:", command)

            # ---- NO ACTION DETECTED ----
            if action == UNKNOWN_ACTION:
                # Parser could not map text → known action (distinct from executor / Office failures).
                print(
                    "Could not parse that as a known command. "
                    "Try examples: click Save, type hello, copy, open word, scroll down."
                )
                continue

            # ---- OFFICE COM ----

            if office_dispatcher.is_office_command(command):

                print("Office COM command detected")

                success = office.execute(command)

                # ---- END TIMER ----
                print(f"Execution time: {time.time() - start_time:.4f} sec")

                if not success:
                    print("Office command failed")

                continue

            # ---- DIRECT ACTIONS (NO UI MATCHING) ----
            if action in DIRECT_ACTIONS:

                print("Direct action:", action)

                result = execute(
                    action,
                    element=None,
                    params=command,
                )
                if not result.ok:
                    print(result.reason)

                continue

            # ----------------------------------------
            # UI-GROUNDED ACTIONS (click, hover, etc.)
            # ----------------------------------------

            # ---- IMAGE LOAD or SCREEN CAPTURE 대체 ----
            frame = capture_screen()
            # image_path = 'Screenshot.png' # path to the image file to load
            # frame = cv2.imread(image_path)
            # if frame is None:
            #     print(f"Error: Couldn't find the directory({image_path}).")

            # ---- SEMANTIC MATCHING ----
            query = command.get("query", text)

            match = None
            score = 0.0
            used_mode = mode

            # =========================
            # Cascade modes: all = UIA → OCR → vision; both = UIA → vision
            # =========================
            if mode == "all":
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
                    match, score, used_mode, frame = run_vision_match_step(
                        frame,
                        query,
                        vision_threshold=SCORE_THRESHOLD[STAGE_VISION],
                        heading="\n[STEP 3] Try vision (YOLO + localized OCR)",
                        used_mode_on_miss=mode,
                    )

            elif mode == "both":
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
                    match, score, used_mode, frame = run_vision_match_step(
                        frame,
                        query,
                        vision_threshold=SCORE_THRESHOLD[STAGE_VISION],
                        heading="\n[STEP 2] Try vision (YOLO + localized OCR)",
                        used_mode_on_miss=mode,
                    )

            # =========================
            # Single modes: uia, ocr, vision
            # =========================
            elif mode == "ocr":

                ocr_elements = run_fullframe_ocr_stage(frame, ocr_reader, conf_min=0.35)
                filtered = filter_elements(ocr_elements)

                print(f"[ocr] {len(ocr_elements)} lines → {len(filtered)} after filter")

                frame = draw_elements(frame, filtered)

                match, score = find_best_match(query, filtered, screen=frame)

            elif mode in ("uia", "vision"):

                elements = extract_elements_by_mode(mode)
                filtered = filter_elements(elements)

                print(f"[{mode}] {len(elements)} → {len(filtered)}")

                frame = draw_elements(frame, filtered)

                match, score = find_best_match(query, filtered, screen=frame)

            else:
                raise ValueError(f"Unsupported mode: {mode!r}")

            # ---- RESULT ----
            print("\nGROUNDING RESULT")
            print("Action:", action)
            print("Query:", query)
            print("Mode used:", used_mode)

            if match:
                print("Matched element:", match["name"])
                print("Score:", score)
            else:
                print("No element selected after matching.")

            # Cascades apply thresholds per stage; single modes use SCORE_THRESHOLD[mode].
            if mode in ("both", "all"):
                cascade_ok = match is not None
            else:
                threshold = SCORE_THRESHOLD[mode]
                cascade_ok = bool(match) and score > threshold

            if cascade_ok:

                frame = draw_match(frame, match)

                if frame is not None:
                    show_debug(frame)

                result = execute(
                    action,
                    element=match,
                    params=command,
                )
                if not result.ok:
                    print(result.reason)
                elif action in POST_GROUNDING_CLICK_DELAY_ACTIONS:
                    time.sleep(1.5)

                # ---- END TIMER ----
                print(f"Execution time: {time.time() - start_time:.4f} sec")

            else:

                print("No confident UI match")

        except KeyboardInterrupt:

            print("\nCommand cancelled. Waiting for next command...")
            continue

        except Exception as e:

            print("Error:", e)


if __name__ == "__main__":

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=["uia", "ocr", "vision", "both", "all"],
        default="uia",
        help=(
            "uia / ocr / vision = single source; "
            "both = UIA→vision; "
            "all = UIA→OCR→vision"
        ),
    )
    args = parser.parse_args()

    main(args.mode)
