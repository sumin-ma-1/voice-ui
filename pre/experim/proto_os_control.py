import speech_recognition as sr
import pyautogui
import os
import subprocess
from pywinauto import Desktop
import csv
from datetime import datetime

import torch
import numpy as np
import io
import soundfile as sf
from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor, pipeline


# -----------------------
# Log setup
# -----------------------

LOG_FILE = "proto_os_control_log.csv"

def save_research_log(voice, cmd, status):
    with open(LOG_FILE, mode='a', newline='', encoding='utf-8') as f:
        csv.writer(f).writerow([datetime.now(), voice, cmd, status])


# -----------------------
# Load Whisper Tiny
# -----------------------

print("Loading Whisper Tiny...")

device = "cuda:0" if torch.cuda.is_available() else "cpu"
dtype = torch.float16 if torch.cuda.is_available() else torch.float32

model_id = "openai/whisper-tiny"

model = AutoModelForSpeechSeq2Seq.from_pretrained(
    model_id,
    torch_dtype=dtype,
    low_cpu_mem_usage=True
)

model.to(device)

processor = AutoProcessor.from_pretrained(model_id)

pipe = pipeline(
    "automatic-speech-recognition",
    model=model,
    tokenizer=processor.tokenizer,
    feature_extractor=processor.feature_extractor,
    device=device,
)

print("Whisper ready.\n")


# -----------------------
# OS Controller
# -----------------------

class OSController:

    def __init__(self):
        self.desktop = Desktop(backend="uia")

    def open_app(self, name):

        if "notepad" in name:
            subprocess.Popen("notepad.exe")

        elif "calculator" in name:
            subprocess.Popen("calc.exe")

        elif "browser" in name or "chrome" in name:
            os.system("start chrome")

    def close_active_window(self):

        try:
            active_window = self.desktop.active_window()
            title = active_window.window_text()
            active_window.close()
            print(f"[{title}] closed")
            return True

        except:
            pyautogui.hotkey("alt", "f4")
            return False

    def show_desktop(self):
        pyautogui.hotkey("win", "d")

    def system_volume(self, direction):

        if "up" in direction or "increase" in direction:
            pyautogui.press("volumeup", presses=5)

        else:
            pyautogui.press("volumedown", presses=5)


# -----------------------
# Whisper transcription
# -----------------------

def transcribe_whisper(audio):

    # Convert SpeechRecognition audio → WAV
    wav_bytes = audio.get_wav_data()

    # Decode WAV → numpy
    audio_np, sr_rate = sf.read(io.BytesIO(wav_bytes))

    # Run Whisper
    result = pipe(
        {"array": audio_np, "sampling_rate": sr_rate},
        generate_kwargs={"language": "english"}
    )

    return result["text"].strip().lower()


# -----------------------
# Main Agent
# -----------------------

def start_agent():

    controller = OSController()

    recognizer = sr.Recognizer()
    mic = sr.Microphone()

    # speech detection tuning
    recognizer.energy_threshold = 300
    recognizer.pause_threshold = 0.8
    recognizer.dynamic_energy_threshold = True

    print("--- OS Voice Control Running ---")

    with mic as source:

        recognizer.adjust_for_ambient_noise(source, duration=1)

        while True:

            try:

                print("\n[Waiting for command...]")

                audio = recognizer.listen(
                    source,
                    timeout=5,
                    phrase_time_limit=5
                )

                command = transcribe_whisper(audio)

                print("User speech:", command)

                if "notepad" in command or "calculator" in command:

                    controller.open_app(command)
                    save_research_log(command, "OpenApp", "Success")

                elif "desktop" in command:

                    controller.show_desktop()
                    save_research_log(command, "ShowDesktop", "Success")

                elif "close" in command or "exit" in command:

                    controller.close_active_window()
                    save_research_log(command, "CloseWindow", "Success")

                elif "volume" in command:

                    controller.system_volume(command)
                    save_research_log(command, "VolumeControl", "Success")

                elif "stop" in command or "quit" in command:

                    print("Shutting down.")
                    break

            except sr.WaitTimeoutError:
                print("Listening timeout")

            except Exception as e:
                print("Error:", e)


# -----------------------

if __name__ == "__main__":
    start_agent()