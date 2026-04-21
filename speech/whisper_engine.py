# NumPy buffer ver.
import whisper
import numpy as np
import torch

class WhisperEngine:

    def __init__(self, model_size="tiny"):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"

        print(f"Loading Whisper model on {self.device}...")
        self.model = whisper.load_model(model_size, device=self.device)
        print(f"Whisper ready on {self.device}.")

    def transcribe(self, audio):

        # get raw PCM audio
        raw = audio.get_raw_data(convert_rate=16000, convert_width=2)

        # convert to numpy int16
        audio_np = np.frombuffer(raw, np.int16)

        # normalize to float32
        audio_np = audio_np.astype(np.float32) / 32768.0

        result = self.model.transcribe(
            audio_np,
            language="en",
            fp16=(self.device == "cuda")
        )

        return result["text"].lower().strip()
