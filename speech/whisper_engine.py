# NumPy buffer ver.
import os

import numpy as np
import torch
import whisper


class WhisperEngine:

    def __init__(self, model_size="tiny"):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"

        print(f"Loading Whisper model on {self.device}...")
        self.model = whisper.load_model(model_size, device=self.device)
        print(f"Whisper ready on {self.device}.")

    def transcribe(self, audio, language: str | None = None):

        # get raw PCM audio
        raw = audio.get_raw_data(convert_rate=16000, convert_width=2)

        # convert to numpy int16
        audio_np = np.frombuffer(raw, np.int16)

        return self.transcribe_pcm16(audio_np, language=language)

    def transcribe_pcm16(
        self,
        pcm_int16: np.ndarray,
        *,
        language: str | None = None,
        sample_rate: int = 16000,
    ) -> str:
        """PCM int16 mono → transcript (lowercase stripped)."""
        if pcm_int16 is None or len(pcm_int16) < int(sample_rate * 0.12):
            return ""

        audio_np = np.asarray(pcm_int16, dtype=np.int16).astype(np.float32) / 32768.0

        lang = language
        if lang is None and os.getenv("VOICE_UI_WHISPER_LANG"):
            lang = os.getenv("VOICE_UI_WHISPER_LANG") or None
            if lang and lang.lower() in ("auto", "none"):
                lang = None

        kwargs = {"fp16": (self.device == "cuda")}
        if lang:
            kwargs["language"] = lang

        result = self.model.transcribe(audio_np, **kwargs)
        return result["text"].lower().strip()
