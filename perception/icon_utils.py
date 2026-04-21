# perception/icon_utils.py
# - YOLO detection
# - CLIP embeddings
# - cropping
# - OCR

import torch
import numpy as np
from PIL import Image
from perception.screen_capture import capture_screen
from ultralytics import YOLO

import easyocr

# ---- LOAD MODELS ONCE ----
device = "cuda" if torch.cuda.is_available() else "cpu"
is_gpu = device == "cuda"

if is_gpu:
    print(f"[GPU] Using CUDA device: {torch.cuda.get_device_name(0)}")
else:
    print("[GPU] CUDA not found. Using CPU.")

# CLIP
import clip
clip_model, preprocess = clip.load("ViT-B/32", device=device)

# YOLO (fine tuned model)
yolo_model = YOLO("epoch235.pt")
yolo_device = 0 if is_gpu else "cpu"

# ---- YOLO DETECTION ----
def detect_icons(image):

    results = yolo_model.predict(image, device=yolo_device, verbose=False)

    boxes = []

    for r in results:
        for box in r.boxes:
            cls = int(box.cls[0])
            if cls == 0:
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                boxes.append((x1, y1, x2, y2))

    # return boxes
    icons = []

    for (x1, y1, x2, y2) in boxes:

        #pad = 40 # add OCR around icon (context region)
        # ---------------------------
        # directional padding
        # ---------------------------
        pad_top = 20
        pad_bottom = 40
        pad_left = 20
        pad_right = 20

        h, w, _ = image.shape

        x1p = max(0, x1 - pad_left)
        y1p = max(0, y1 - pad_top)
        x2p = min(w, x2 + pad_right)
        y2p = min(h, y2 + pad_bottom)

        crop = image[y1p:y2p, x1p:x2p]

        text = extract_text_from_icon(crop)

        icons.append({
            "bbox": (x1, y1, x2, y2),
            # "ocr_bbox": (x1p, y1p, x2p, y2p),
            "text": text
        })

    return icons


# ---- EMBEDDINGS ----
def get_text_embedding(text):

    tokens = clip.tokenize([text]).to(device)

    with torch.no_grad():
        emb = clip_model.encode_text(tokens)

    emb = emb / emb.norm(dim=-1, keepdim=True)
    return emb

# ---- OCR ----
ocr_reader = easyocr.Reader(['en'], gpu=is_gpu)

def extract_text_from_icon(image_np):

    results = ocr_reader.readtext(image_np)

    texts = []

    for (bbox, text, conf) in results:
        if conf > 0.4:
            texts.append(text)

    return " ".join(texts)