# speech/voice_session.py
# Wake phrase + WebRTC VAD + Whisper. Hands-free: listen for "hey voice ui" then command.

from __future__ import annotations

import os
import queue
import re
import threading
import time
from collections import deque
from typing import TYPE_CHECKING, Any, Callable

import numpy as np

try:
    import webrtcvad  # type: ignore
except ImportError:
    webrtcvad = None

import pyaudio

from speech.whisper_engine import WhisperEngine

if TYPE_CHECKING:
    pass

SAMPLE_RATE = 16000
FRAME_MS = 30
FRAME_SAMPLES = int(SAMPLE_RATE * FRAME_MS / 1000)  # 480
FRAME_BYTES = FRAME_SAMPLES * 2

# ~300 ms trailing silence to end an utterance
END_SILENCE_FRAMES = 10
# Ignore very short noise bursts
MIN_SPEECH_FRAMES = 5

WAKE_PATTERNS = (
    r"hey\s+voice\s+ui",
    r"hey\s+voice",
)


def _norm_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip())


def contains_wake_phrase(text: str) -> bool:
    t = _norm_ws(text.lower())
    for pat in WAKE_PATTERNS:
        if re.search(pat, t):
            return True
    return "hey voice ui" in t.replace(" ", "")


def strip_wake_phrase(text: str) -> str:
    t = _norm_ws(text)
    for pat in WAKE_PATTERNS:
        t = re.sub(pat, "", t, flags=re.IGNORECASE).strip()
        t = re.sub(r"^[\s,:-]+", "", t)
    return _norm_ws(t)


class VoiceSession:
    """
    Background thread: mic → VAD → Whisper.

    Puts command strings on ``out_queue``. Wake phrase required before each command
    (except optional grace abort phrases handled via :meth:`poll_abort` / :meth:`enter_grace`).
    """

    def __init__(
        self,
        out_queue: "queue.Queue[str | None]",
        *,
        on_status: Callable[[str], None] | None = None,
        on_partial_line: Callable[[str], None] | None = None,
        model_size: str | None = None,
    ) -> None:
        self.out_queue = out_queue
        self._on_status = on_status
        self._on_partial = on_partial_line

        self._run = False
        self._thread: threading.Thread | None = None

        self._main_busy = threading.Event()
        self._grace = threading.Event()
        self._abort_stop = threading.Event()
        self._abort_exit = threading.Event()

        size = model_size or os.getenv("VOICE_UI_WHISPER_MODEL", "tiny")
        self._whisper = WhisperEngine(model_size=size)

        self._vad: Any = None
        if webrtcvad is not None:
            aggressiveness = int(os.getenv("VOICE_UI_VAD_AGGRESSIVENESS", "2"))
            aggressiveness = max(0, min(3, aggressiveness))
            self._vad = webrtcvad.Vad(aggressiveness)
        else:
            self._status("WebRTC VAD unavailable (pip install webrtcvad). Using energy gate.")

        self._await_command = False

    def _status(self, msg: str) -> None:
        if self._on_status:
            try:
                self._on_status(msg)
            except Exception:
                pass

    def start(self) -> None:
        if self._run:
            return
        self._run = True
        self._thread = threading.Thread(target=self._loop, name="VoiceSession", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._run = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def set_main_busy(self, busy: bool) -> None:
        if busy:
            self._main_busy.set()
        else:
            self._main_busy.clear()

    def enter_grace(self) -> None:
        self._grace.set()

    def exit_grace(self) -> None:
        self._grace.clear()

    def clear_abort_flags(self) -> None:
        self._abort_stop.clear()
        self._abort_exit.clear()

    def poll_stop(self) -> bool:
        return self._abort_stop.is_set()

    def poll_exit(self) -> bool:
        return self._abort_exit.is_set()

    def consume_stop(self) -> bool:
        if self._abort_stop.is_set():
            self._abort_stop.clear()
            return True
        return False

    def consume_exit(self) -> bool:
        if self._abort_exit.is_set():
            self._abort_exit.clear()
            return True
        return False

    def _energy_is_loud(self, frame_i16: np.ndarray) -> bool:
        rms = float(np.sqrt(np.mean(frame_i16.astype(np.float64) ** 2)))
        thr = float(os.getenv("VOICE_UI_ENERGY_GATE", "280"))
        return rms >= thr

    def _is_speech_frame(self, frame_bytes: bytes) -> bool:
        if self._vad is not None:
            try:
                return bool(self._vad.is_speech(frame_bytes, SAMPLE_RATE))
            except Exception:
                pass
        pcm = np.frombuffer(frame_bytes, dtype=np.int16)
        return self._energy_is_loud(pcm)

    def _transcribe(self, pcm: np.ndarray) -> str:
        return self._whisper.transcribe_pcm16(pcm, language=None)

    def _check_grace_abort(self, text: str) -> None:
        t = _norm_ws(text.lower())
        if not t:
            return
        if re.search(r"\bstop\b", t) or "중지" in t:
            self._abort_stop.set()
        if re.search(r"\bexit\b", t) or re.search(r"\bquit\b", t):
            self._abort_exit.set()

    def _handle_utterance_text(self, text: str) -> None:
        text = _norm_ws(text)
        if not text:
            return

        if self._grace.is_set():
            self._check_grace_abort(text)
            return

        if self._main_busy.is_set():
            return

        if self._await_command:
            t2 = strip_wake_phrase(text) if contains_wake_phrase(text) else text
            self.out_queue.put(t2)
            self._await_command = False
            return

        if not contains_wake_phrase(text):
            self._status("Wake phrase not detected; say 'Hey Voice UI' …")
            return

        cmd = strip_wake_phrase(text)
        if cmd:
            self.out_queue.put(cmd)
        else:
            self._await_command = True
            self._status("Listening for command…")

    def _loop(self) -> None:
        pa = pyaudio.PyAudio()
        try:
            stream = pa.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=SAMPLE_RATE,
                input=True,
                frames_per_buffer=FRAME_SAMPLES,
            )
        except Exception as e:
            self._status(f"Microphone open failed: {e}")
            return

        buf = bytearray()
        speech_frames = 0
        silence_run = 0
        in_speech = False
        last_partial = 0.0

        try:
            while self._run:
                try:
                    data = stream.read(FRAME_SAMPLES, exception_on_overflow=False)
                except Exception:
                    time.sleep(0.05)
                    continue

                is_voice = self._is_speech_frame(data)

                if self._main_busy.is_set() and not self._grace.is_set():
                    buf.clear()
                    in_speech = False
                    speech_frames = 0
                    silence_run = 0
                    time.sleep(0.01)
                    continue

                if is_voice:
                    in_speech = True
                    silence_run = 0
                    buf.extend(data)
                    speech_frames += 1

                    now = time.monotonic()
                    if (
                        self._on_partial
                        and (now - last_partial) > 0.45
                        and len(buf) >= FRAME_BYTES * 15
                    ):
                        chunk = np.frombuffer(bytes(buf), dtype=np.int16)
                        snap = self._transcribe(chunk)
                        if snap:
                            try:
                                self._on_partial(snap)
                            except Exception:
                                pass
                        last_partial = now
                else:
                    if in_speech:
                        silence_run += 1
                        buf.extend(data)

                    if in_speech and silence_run >= END_SILENCE_FRAMES:
                        pcm = np.frombuffer(bytes(buf), dtype=np.int16)
                        buf.clear()
                        in_speech = False
                        speech_frames = 0
                        silence_run = 0

                        if len(pcm) < SAMPLE_RATE * 0.12:
                            continue

                        text = self._transcribe(pcm)
                        if self._on_partial:
                            try:
                                self._on_partial("")
                            except Exception:
                                pass
                        self._handle_utterance_text(text)
        finally:
            try:
                stream.stop_stream()
                stream.close()
            except Exception:
                pass
            pa.terminate()
