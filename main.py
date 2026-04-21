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

import argparse
import time

from speech.text_input_gui import TextInputGUI
from speech.command_parser import parse_command

from perception.ui_extractor import extract_elements_by_mode
from perception.ui_filter import filter_elements
from perception.ui_fallback_pipeline import (
    run_uia_stage,
    run_fullframe_ocr_stage,
    run_vision_icon_stage,
    STAGE_UIA,
    STAGE_OCR,
    STAGE_VISION,
)
from perception.ocr_elements import create_easyocr_reader
from grounding.matcher import find_best_match
from automation.executor import execute

from perception.screen_capture import capture_screen
from perception.debug_draw import draw_elements, draw_match, show_debug

from com.office_controller import OfficeController
from com.office_dispatcher import OfficeDispatcher

import cv2

# ---- MODE-specific THRESHOLDS ----
# Single modes (uia / ocr / vision) use the key matching --mode.
# Cascades (both / all) apply STAGE_UIA / STAGE_OCR / STAGE_VISION inside the loop.
SCORE_THRESHOLD = {
    "uia": 31,
    "ocr": 18,
    "vision": 15,
}

# actions that DO NOT require UI grounding
DIRECT_ACTIONS = {
    "type",
    "scroll",
    "enter",
    "esc",
    "tab",
    "backspace",
    "delete",
    "copy",
    "paste",
    "cut",
    "undo",
    "redo",
    "save",
    "select_all",
    "new_tab",
    "close_tab",
    "refresh",
    "press_key",
    "hotkey"
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
            if action == "unknown":

                print("No Action detected. Please try again.")

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

                execute(
                    action,
                    element=None,
                    params=command
                )

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
            score = 0
            used_mode = mode

            # =========================
            # ALL MODE — UIA → full-frame OCR → vision
            # =========================
            if mode == "all":

                match = None
                score = 0.0
                used_mode = mode

                print("\n[STEP 1] Try UIA")

                try:
                    uia_elements = run_uia_stage()
                    uia_filtered = filter_elements(uia_elements)

                    print(f"[UIA] {len(uia_elements)} → {len(uia_filtered)}")

                    for i, el in enumerate(uia_filtered):
                        print(
                            f"  [{i+1}] Name: {el['name']}, Type: {el['type']} | "
                            f"P Name: {el['parent_name']} Type: {el['parent_type']}"
                        )

                    match, score = find_best_match(query, uia_filtered, screen=frame)

                    if match and score > SCORE_THRESHOLD[STAGE_UIA]:
                        used_mode = STAGE_UIA
                        frame = draw_elements(frame, uia_filtered)
                    else:
                        if match:
                            print("[UIA] Best candidate:", match["name"], "| score:", score)
                        print("[UIA] No confident match → fallback to full-frame OCR")
                        if uia_filtered:
                            show_debug(draw_elements(frame.copy(), uia_filtered))
                        frame = capture_screen()
                        match = None

                except Exception as e:
                    print("[UIA] Failed:", e)
                    match = None
                    frame = capture_screen()

                if match is None:

                    print("\n[STEP 2] Try full-frame OCR")

                    ocr_elements = run_fullframe_ocr_stage(frame, ocr_reader, conf_min=0.35)
                    ocr_filtered = filter_elements(ocr_elements)

                    print(f"[OCR] {len(ocr_elements)} lines → {len(ocr_filtered)} after filter")

                    match, score = find_best_match(query, ocr_filtered, screen=frame)

                    if match and score > SCORE_THRESHOLD[STAGE_OCR]:
                        used_mode = STAGE_OCR
                        frame = draw_elements(frame, ocr_filtered)
                    else:
                        if match:
                            print("[OCR] Best candidate:", match["name"], "| score:", score)
                        print("[OCR] No confident match → fallback to vision (icons + local OCR)")
                        match = None

                if match is None:

                    print("\n[STEP 3] Try vision (YOLO + localized OCR)")

                    vision_elements = run_vision_icon_stage(frame)
                    vision_filtered = filter_elements(vision_elements)

                    print(f"[Vision] {len(vision_elements)} → {len(vision_filtered)}")

                    match, score = find_best_match(query, vision_filtered, screen=frame)

                    if match and score > SCORE_THRESHOLD[STAGE_VISION]:
                        used_mode = STAGE_VISION
                        frame = draw_elements(frame, vision_filtered)
                    else:
                        if match:
                            print("[Vision] Best candidate:", match["name"], "| score:", score)
                        match = None

            # =========================
            # BOTH MODE — UIA → vision (skip full-frame OCR)
            # =========================
            elif mode == "both":

                match = None
                score = 0.0
                used_mode = mode

                print("\n[STEP 1] Try UIA")

                try:
                    uia_elements = run_uia_stage()
                    uia_filtered = filter_elements(uia_elements)

                    print(f"[UIA] {len(uia_elements)} → {len(uia_filtered)}")

                    for i, el in enumerate(uia_filtered):
                        print(
                            f"  [{i+1}] Name: {el['name']}, Type: {el['type']} | "
                            f"P Name: {el['parent_name']} Type: {el['parent_type']}"
                        )

                    match, score = find_best_match(query, uia_filtered, screen=frame)

                    if match and score > SCORE_THRESHOLD[STAGE_UIA]:
                        used_mode = STAGE_UIA
                        frame = draw_elements(frame, uia_filtered)
                    else:
                        if match:
                            print("[UIA] Best candidate:", match["name"], "| score:", score)
                        print("[UIA] No confident match → fallback to vision (YOLO + localized OCR)")
                        if uia_filtered:
                            show_debug(draw_elements(frame.copy(), uia_filtered))
                        frame = capture_screen()
                        match = None

                except Exception as e:
                    print("[UIA] Failed:", e)
                    match = None
                    frame = capture_screen()

                if match is None:

                    print("\n[STEP 2] Try vision (YOLO + localized OCR)")

                    vision_elements = run_vision_icon_stage(frame)
                    vision_filtered = filter_elements(vision_elements)

                    print(f"[Vision] {len(vision_elements)} → {len(vision_filtered)}")

                    match, score = find_best_match(query, vision_filtered, screen=frame)

                    if match and score > SCORE_THRESHOLD[STAGE_VISION]:
                        used_mode = STAGE_VISION
                        frame = draw_elements(frame, vision_filtered)
                    else:
                        if match:
                            print("[Vision] Best candidate:", match["name"], "| score:", score)
                        match = None

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

                execute(
                    action,
                    element=match,
                    params=command
                )

                # ---- END TIMER ----
                print(f"Execution time: {time.time() - start_time:.4f} sec")

                # Wait for app to open after click/double click
                if action in ("left_click", "double_click", "right_click"):
                    time.sleep(1.5)

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
