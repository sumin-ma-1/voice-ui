# perception/icon_utils.py
# - YOLO detection
# - CLIP embeddings
# - cropping
# - OCR

import os
from pathlib import Path

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

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_CLIP_CHECKPOINT = (
    _REPO_ROOT / "training_data/icons_material/checkpoints/stage1_best.pt"
)


def _resolve_clip_checkpoint_path(raw: str) -> Path | None:
    """Absolute path, or relative to cwd, then repo root."""
    s = raw.strip()
    if not s:
        return None
    if s.lower() in ("off", "baseline", "none"):
        return None
    p = Path(s)
    candidates = [p.resolve()] if p.is_absolute() else [Path.cwd() / p, _REPO_ROOT / p]
    for c in candidates:
        if c.is_file():
            return c.resolve()
    return None


def _clip_checkpoint_to_load() -> tuple[Path | None, str]:
    """
    Env ``VOICE_UI_CLIP_CHECKPOINT`` overrides default.
    If unset, use ``training_data/icons_material/checkpoints/stage1_best.pt`` when present.
  """
    env_raw = os.getenv("VOICE_UI_CLIP_CHECKPOINT", "").strip()
    if env_raw:
        p = _resolve_clip_checkpoint_path(env_raw)
        if p is not None:
            return p, "env"
        return None, "env_missing"
    if _DEFAULT_CLIP_CHECKPOINT.is_file():
        return _DEFAULT_CLIP_CHECKPOINT.resolve(), "default"
    return None, "baseline"


# CLIP (optional fine-tuned weights from train_stage1.py)
import clip

clip_model, preprocess = clip.load("ViT-B/32", device=device, jit=False)
clip_model.float()
clip_model.eval()

_clip_ckpt_path, _clip_ckpt_source = _clip_checkpoint_to_load()
if _clip_ckpt_path is not None:
    try:
        _sd = torch.load(
            _clip_ckpt_path, map_location=device, weights_only=False
        )
    except TypeError:
        _sd = torch.load(_clip_ckpt_path, map_location=device)
    clip_model.load_state_dict(_sd["model_state_dict"], strict=True)
    clip_model.eval()
    if _clip_ckpt_source == "default":
        print(
            f"[CLIP] loaded {_clip_ckpt_path.name} (default: {_clip_ckpt_path.relative_to(_REPO_ROOT)})"
        )
    else:
        print(f"[CLIP] loaded {_clip_ckpt_path.name} ({_clip_ckpt_path})")
elif _clip_ckpt_source == "env_missing":
    print(
        f"[CLIP] VOICE_UI_CLIP_CHECKPOINT={os.getenv('VOICE_UI_CLIP_CHECKPOINT', '')!r} "
        "not found — using ViT-B/32 baseline"
    )
else:
    print("[CLIP] ViT-B/32 baseline (no stage1_best.pt at default path)")

# YOLO (fine tuned model)
yolo_model = YOLO("epoch235.pt")
yolo_device = 0 if is_gpu else "cpu"


_YOLO_IMGSZ_MIN = 640
_YOLO_IMGSZ_MAX = 1536
_yolo_imgsz_last_logged: int | None = None


def yolo_imgsz_for_frame(height: int, width: int) -> int:
    """
    Pick YOLO ``imgsz`` from capture size so small icons on large desktops stay visible.

    Rule: ~one third of the long edge, snapped to 32px, clamped to [640, 1536].
    (3840px wide -> 1280; 1920px -> 640.)
    """
    long_edge = max(int(height), int(width))
    raw = long_edge / 3.0
    snapped = int(round(raw / 32)) * 32
    return max(_YOLO_IMGSZ_MIN, min(_YOLO_IMGSZ_MAX, snapped))


def _yolo_imgsz_env_mode() -> str:
    """``auto`` (default), ``off``, or ``fixed``."""
    raw = os.getenv("VOICE_UI_YOLO_IMGSZ", "auto").strip().lower()
    if raw in ("", "auto"):
        return "auto"
    if raw in ("off", "default"):
        return "off"
    try:
        if int(raw) > 0:
            return "fixed"
    except ValueError:
        pass
    return "auto"


def _yolo_imgsz_env_fixed() -> int | None:
    raw = os.getenv("VOICE_UI_YOLO_IMGSZ", "auto").strip()
    try:
        v = int(raw)
        return v if v > 0 else None
    except ValueError:
        return None


def resolve_yolo_imgsz(image, *, override: int | None = None) -> int | None:
    """
    Resolve Ultralytics ``imgsz`` for this frame.

    Priority: per-call ``override`` > fixed env int > auto from frame > ``off`` (YOLO default 640).
    """
    if override is not None:
        return override
    mode = _yolo_imgsz_env_mode()
    if mode == "fixed":
        return _yolo_imgsz_env_fixed()
    if mode == "off":
        return None
    h, w = image.shape[:2]
    return yolo_imgsz_for_frame(h, w)


def _log_yolo_imgsz_startup() -> None:
    mode = _yolo_imgsz_env_mode()
    if mode == "off":
        print("[YOLO] imgsz=off (Ultralytics default 640; set VOICE_UI_YOLO_IMGSZ=auto to scale)")
    elif mode == "fixed":
        print(f"[YOLO] imgsz={_yolo_imgsz_env_fixed()} (fixed, VOICE_UI_YOLO_IMGSZ)")
    else:
        print(
            f"[YOLO] imgsz=auto (long_edge/3, snap 32, clamp {_YOLO_IMGSZ_MIN}–{_YOLO_IMGSZ_MAX})"
        )


_log_yolo_imgsz_startup()


# ---- YOLO DETECTION ----
def detect_icons(image, *, imgsz: int | None = None):
    global _yolo_imgsz_last_logged

    predict_kw: dict = {"device": yolo_device, "verbose": False}
    sz = resolve_yolo_imgsz(image, override=imgsz)
    if sz is not None:
        predict_kw["imgsz"] = sz
        if _yolo_imgsz_env_mode() == "auto" and sz != _yolo_imgsz_last_logged:
            h, w = image.shape[:2]
            print(f"[YOLO] predict imgsz={sz} for {w}x{h}")
            _yolo_imgsz_last_logged = sz

    results = yolo_model.predict(image, **predict_kw)

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