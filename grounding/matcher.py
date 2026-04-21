# grounding/matcher.py (revised.ver)
# Optimized matcher:
#   1. 스크린샷 1회만 찍고 재사용
#   2. CLIP 이미지 인코딩을 배치로 처리
#   3. 아이콘별 개별 capture_screen() 제거

from sentence_transformers import SentenceTransformer
import numpy as np
import torch
from PIL import Image

from perception.icon_utils import (
    clip_model,
    preprocess,
    device,
    get_text_embedding #,
    #clip_similarity
)
from perception.screen_capture import capture_screen

# ---- TEXT MODEL ----
text_model = SentenceTransformer("all-MiniLM-L6-v2", device=device)


def cosine_similarity_matrix(query_vec, matrix):

    query_norm = np.linalg.norm(query_vec)
    matrix_norm = np.linalg.norm(matrix, axis=1)

    return (matrix @ query_vec) / (matrix_norm * query_norm)


def build_element_description(e):

    name = e.get("name", "")
    parent_name = e.get("parent_name", "")
    parent_type = e.get("parent_type", "")

    return f"{name} {parent_name} {parent_type}"


def batch_image_embeddings(crops):
    """여러 crop을 한 번에 CLIP 인코딩"""

    if not crops:
        return None

    batch = torch.stack([
        preprocess(Image.fromarray(c)) for c in crops
    ]).to(device)

    with torch.no_grad():
        embs = clip_model.encode_image(batch)

    embs = embs / embs.norm(dim=-1, keepdim=True)

    return embs


def find_best_match(query, elements, screen=None):

    if not elements:
        return None, 0

    best_element = None
    best_score = -1

    # ---- TEXT ELEMENTS ----
    text_elements = [e for e in elements if not e.get("is_icon")]
    icon_elements = [e for e in elements if e.get("is_icon")]

    # ---- TEXT MATCHING (SentenceTransformer) ----
    if text_elements:

        descriptions = [build_element_description(e) for e in text_elements]

        query_vec = text_model.encode(query)
        element_vecs = text_model.encode(descriptions)

        sims = cosine_similarity_matrix(query_vec, element_vecs)

        idx = int(np.argmax(sims))
        score = float(sims[idx]) * 100

        if score > best_score:
            best_score = score
            best_element = text_elements[idx]

    # ---- ICON MATCHING (CLIP, 배치) ----
    if icon_elements:

        # 스크린샷 1회만
        if screen is None:
            screen = capture_screen()

        # 모든 아이콘 crop을 한 번에 수집
        crops = []
        valid_icons = []
        ocr_texts = []

        for e in icon_elements:

            try:
                x1, y1, x2, y2 = e["bbox"]
                crop = screen[y1:y2, x1:x2]

                if crop.size == 0:
                    continue

                crops.append(crop)
                valid_icons.append(e)
                ocr_texts.append(e.get("text", "") or e.get("name", ""))

            except Exception:
                continue

        if crops:

            # 배치 이미지 인코딩 (1회 GPU 호출)
            img_embs = batch_image_embeddings(crops)

            # OCR 텍스트가 있는 아이콘은 텍스트 임베딩도 합산
            text_emb_cache = {}

            for i, ocr_text in enumerate(ocr_texts):

                if ocr_text and ocr_text not in text_emb_cache:
                    text_emb_cache[ocr_text] = get_text_embedding(ocr_text)

                if ocr_text and ocr_text in text_emb_cache:
                    combined = (img_embs[i] + text_emb_cache[ocr_text]) / 2
                    img_embs[i] = combined / combined.norm(dim=-1, keepdim=True)

            # 쿼리 CLIP 텍스트 임베딩
            clip_query_emb = get_text_embedding(query)

            # 배치 유사도 (행렬 곱 한 번)
            sims = (img_embs @ clip_query_emb.T).squeeze(-1).cpu()

            best_icon_idx = int(torch.argmax(sims))
            best_icon_score = float(sims[best_icon_idx]) * 100

            if best_icon_score > best_score:
                best_score = best_icon_score
                best_element = valid_icons[best_icon_idx]

    return best_element, best_score
