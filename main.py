# main.py
# Main script: switch between UIA / Vision / Both modes with --mode
# How to run:
#   python main.py --mode {uia|vision|both}
#   To escape the running agent, press Ctrl+C
#   To exit the agent, type "exit", "quit", "stop agent", "shutdown"

import argparse
import time

from speech.text_input_gui import TextInputGUI
from speech.command_parser import parse_command

from perception.ui_extractor import extract_elements_by_mode
from perception.ui_filter import filter_elements
from grounding.matcher import find_best_match
from automation.executor import execute

from perception.screen_capture import capture_screen
from perception.debug_draw import draw_elements, draw_match, show_debug

from com.office_controller import OfficeController
from com.office_dispatcher import OfficeDispatcher

import cv2

# ---- MODE-specific THRESHOLDS ----
SCORE_THRESHOLD = {
    "uia":    31,
    "vision": 15,
    "both":   15,
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
            # BOTH MODE (UIA → Vision fallback)
            # 1. when an extracted uia element doesn't exist
            # 2. when match not found
            # =========================
            if mode == "both":

                print("\n[STEP 1] Try UIA")

                try:
                    uia_elements = extract_elements_by_mode("uia")
                    uia_filtered = filter_elements(uia_elements)

                    print(f"[UIA] {len(uia_elements)} → {len(uia_filtered)}")

                    for i, el in enumerate(uia_filtered):
                        # Print index and main info in one line using f-string (debugging)
                        print(f"  [{i+1}] Name: {el['name']}, Type: {el['type']} | P Name: {el['parent_name']} Type: {el['parent_type']}")

                    match, score = find_best_match(
                        query,
                        uia_filtered,
                        screen=frame
                    )

                    if match and score > SCORE_THRESHOLD["uia"]:
                        used_mode = "uia"
                        frame = draw_elements(frame, uia_filtered)

                    else:
                        print("Matched element:", match["name"]) # debug
                        print("Score:", score) # debug
                        print("[UIA] No confident match → fallback to Vision")
                        frame = draw_elements(frame, uia_filtered) # to compare
                        show_debug(frame) # to compare
                        frame = capture_screen() # reset
                        match = None

                except Exception as e:
                    print("[UIA] Failed:", e)
                    match = None


                # ---------- Vision fallback ----------
                if match is None:

                    print("\n[STEP 2] Try Vision")

                    vision_elements = extract_elements_by_mode("vision")
                    vision_filtered = filter_elements(vision_elements)

                    print(f"[Vision] {len(vision_elements)} → {len(vision_filtered)}")

                    match, score = find_best_match(
                        query,
                        vision_filtered,
                        screen=frame
                    )

                    if match and score > SCORE_THRESHOLD["vision"]:
                        used_mode = "vision"
                        frame = draw_elements(frame, vision_filtered)
                    else:
                        match = None


            # =========================
            # UIA or Vision single mode
            # =========================
            else:

                elements = extract_elements_by_mode(mode)
                filtered = filter_elements(elements)

                print(f"[{mode}] {len(elements)} → {len(filtered)}")

                frame = draw_elements(frame, filtered)

                match, score = find_best_match(
                    query,
                    filtered,
                    screen=frame
                )

            # ---- RESULT ----
            print("\nMATCH FOUND")
            print("Action:", action)
            print("Query:", query)
            print("Mode used:", used_mode)

            if match:
                print("Matched element:", match["name"])

            print("Score:", score)

            threshold = SCORE_THRESHOLD[mode]

            if match and score > threshold:

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
        choices=["uia", "vision", "both"],
        default="uia",
        help="Extraction mode: uia / vision / both"
    )
    args = parser.parse_args()

    main(args.mode)
