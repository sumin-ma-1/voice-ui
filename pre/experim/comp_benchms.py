# Records 7 seconds of audio once
# Feeds the same audio into all models
# Measures processing time only
import pyaudio
import numpy as np
import time
import wave
import torch
from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor, pipeline
from faster_whisper import WhisperModel
from vosk import Model, KaldiRecognizer
# import speech_recognition as sr
import json

RATE = 16000
CHUNK = 1024
SECONDS = 7

print("Recording... Speak now")

p = pyaudio.PyAudio()

stream = p.open(
    format=pyaudio.paInt16,
    channels=1,
    rate=RATE,
    input=True,
    frames_per_buffer=CHUNK
)

frames = []

for _ in range(int(RATE / CHUNK * SECONDS)):
    data = stream.read(CHUNK)
    frames.append(data)

stream.stop_stream()
stream.close()
p.terminate()

audio_bytes = b''.join(frames)
audio_np = np.frombuffer(audio_bytes, np.int16).astype(np.float32) / 32768.0

print("Recording complete\n")

# ----------------------
# WHISPER
# ----------------------

print("Loading Whisper Base...")

device = "cuda:0" if torch.cuda.is_available() else "cpu"
torch_dtype = torch.float16 if torch.cuda.is_available() else torch.float32

model_id = "openai/whisper-tiny"

model = AutoModelForSpeechSeq2Seq.from_pretrained(
    model_id,
    torch_dtype=torch_dtype,
    low_cpu_mem_usage=True
)

model.to(device)

processor = AutoProcessor.from_pretrained(model_id)

pipe = pipeline(
    "automatic-speech-recognition",
    model=model,
    tokenizer=processor.tokenizer,
    feature_extractor=processor.feature_extractor,
    # torch_dtype=torch_dtype,
    chunk_length_s=30,
    device=device,
)

print("Model ready.\n")

# Convert microphone bytes → float waveform
audio_np = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0

audio_input = {
    "array": audio_np,
    "sampling_rate": RATE
}

start = time.time()

result = pipe(audio_input)

end = time.time()

print("Whisper text:", result["text"])
print("Whisper time:", end - start, "seconds\n")


# ----------------------
# FASTER WHISPER
# ----------------------

model_fw = WhisperModel("base", compute_type="int8")

start = time.time()

segments, _ = model_fw.transcribe(audio_np)
text = " ".join([seg.text for seg in segments])

end = time.time()

print("Faster Whisper text:", text)
print("Faster Whisper time:", end - start, "seconds\n")


# ----------------------
# VOSK
# ----------------------

vosk_model = Model("vosk-model-small-en-us-0.15")
rec = KaldiRecognizer(vosk_model, RATE)

start = time.time()

rec.AcceptWaveform(audio_bytes)
result = json.loads(rec.Result())

end = time.time()

print("Vosk text:", result.get("text", ""))
print("Vosk time:", end - start, "seconds\n")


# # ----------------------
# # GOOGLE WEB SPEECH API
# # ----------------------

# recognizer = sr.Recognizer()

# with wave.open("temp.wav", "wb") as wf:
#     wf.setnchannels(1)
#     wf.setsampwidth(2)
#     wf.setframerate(RATE)
#     wf.writeframes(audio_bytes)

# with sr.AudioFile("temp.wav") as source:
#     audio_data = recognizer.record(source)

# start = time.time()

# try:
#     text = recognizer.recognize_google(audio_data, language="en-US")
# except Exception as e:
#     text = f"[ERROR: {e}]"

# end = time.time()

# print("Google text:", text)
# print("Google time:", end - start, "seconds\n")