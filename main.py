# main.py
# Main script: UI grounding modes via --mode
# Input: --input text (default, dev) | voice (wake phrase + floating UI)

import argparse
import os
import queue
import threading

from agent.process_utterance import ensure_ocr_reader, process_utterance
from com.office_controller import OfficeController
from dataset.runtime_overrides import handle_dev_command
from dataset.study_context import ensure_study_manifest, is_study_mode
from speech.floating_voice_widget import FloatingVoiceUI
from speech.text_input_gui import TextInputGUI
from speech.voice_session import VoiceSession


def main(mode: str, input_kind: str) -> None:

    os.environ["VOICE_UI_INPUT_MODE"] = input_kind
    if is_study_mode():
        os.environ.setdefault("VOICE_UI_DATASET_LOG", "1")
        ensure_study_manifest(mode=mode, input_kind=input_kind)

    office = OfficeController()

    ocr_reader = None
    ocr_reader = ensure_ocr_reader(mode, ocr_reader)

    print(f"Experiment agent started  [mode={mode}]  [input={input_kind}]")

    if input_kind == "text":
        text_input = TextInputGUI()

        while True:
            try:
                text = text_input.get_input()

                if not text:
                    continue

                if handle_dev_command(text) == "handled":
                    continue

                r = process_utterance(
                    text,
                    mode=mode,
                    ocr_reader=ocr_reader,
                    office=office,
                    ui=None,
                    voice=None,
                )
                if r == "exit":
                    break

            except KeyboardInterrupt:
                print("\nCommand cancelled. Waiting for next command...")
                continue

            except Exception as e:
                print("Error:", e)

        return

    # ---- Voice + floating UI ----
    cmd_queue: queue.Queue[str | None] = queue.Queue()
    shutdown = threading.Event()

    ui = FloatingVoiceUI(on_close=lambda: shutdown.set())

    def pump_commands() -> None:
        if shutdown.is_set():
            try:
                ui.root.quit()
            except Exception:
                pass
            return

        voice_session.set_main_busy(False)
        ui.set_mic_active(False)
        ui.set_led("idle")
        ui.set_pipeline_guide('Say: "Hey Voice UI", then ask your command.')

        try:
            while True:
                text = cmd_queue.get_nowait()
                if text is None:
                    shutdown.set()
                    ui.root.quit()
                    return

                ui.set_led("processing")
                ui.set_transcript_line(text)
                voice_session.set_main_busy(True)

                try:
                    r = process_utterance(
                        text,
                        mode=mode,
                        ocr_reader=ocr_reader,
                        office=office,
                        ui=ui,
                        voice=voice_session,
                    )
                    if r == "exit":
                        shutdown.set()
                        ui.root.quit()
                        return
                finally:
                    voice_session.set_main_busy(False)

                ui.clear_transcript()

        except queue.Empty:
            pass

        if not shutdown.is_set():
            ui.root.after(120, pump_commands)

    voice_session = VoiceSession(
        cmd_queue,
        on_status=lambda m: ui.root.after(
            0, lambda mm=m: ui.set_pipeline_guide(mm)
        ),
        on_partial_line=lambda p: ui.root.after(
            0, lambda pp=p: ui.set_transcript_line(pp)
        ),
        on_mic_activity=lambda active: ui.root.after(
            0, lambda a=active: ui.set_mic_active(a)
        ),
    )

    voice_session.start()
    ui.root.after(150, pump_commands)

    try:
        ui.run()
    finally:
        voice_session.stop()
        shutdown.set()


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
    parser.add_argument(
        "--input",
        choices=["text", "voice"],
        default="text",
        help='text = floating prompt (dev); voice = wake phrase + minimal floating UI',
    )
    args = parser.parse_args()

    main(args.mode, args.input)
