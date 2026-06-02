# CLIP 학습 모델 실험 기록

Material Stage-1 및 Stage-2 (runtime crop) fine-tune 실험 총정리.  
기준일: **2026-06-02** (체크포인트·eval 재측정 시점)

---

## 배포 권장

| 용도 | 권장 checkpoint | 이유 |
|------|-----------------|------|
| **런타임 (voice-ui vision)** | `checkpoints/stage1_best.pt` | screen eval top1 **55.6%** — Stage-2 계열 최고 |
| Stage-2 in-domain split | `stage2_en_hn_best.pt` 등 | 1203 test R@1 ↑ (39.7%) but screen eval ↓ |
| OpenAI baseline | `VOICE_UI_CLIP_CHECKPOINT=off` | screen top1 0% |

```powershell
# 기본 (stage1 자동 로드)
Remove-Item Env:VOICE_UI_CLIP_CHECKPOINT -ErrorAction SilentlyContinue

# 명시적
$env:VOICE_UI_CLIP_CHECKPOINT = "training_data/icons_material/checkpoints/stage1_best.pt"
```

**핵심:** train/val/test split 지표가 올라도 **eval 10장 (YOLO+CLIP)과 반드시 일치하지 않음.**  
Stage-2 full fine-tune은 Material/eval에서 Stage-1을 깎는 경우가 반복됨.

---

## 체크포인트 목록

| 파일 | 저장 시각 | init | 학습 스크립트 | 학습 데이터 | 비고 |
|------|-----------|------|---------------|-------------|------|
| `stage1_best.pt` | 2026-05-19 | OpenAI ViT-B/32 | `train_stage1.py` | Material `pairs.jsonl` (1,503) | **공식 런타임 default** |
| `stage2_best.pt` | 2026-06-02 11:27 | stage1 | `train_stage2.py` | `pairs_stage2.jsonl` (1,203) | 508 run 가중치 **덮어씀** (복구 불가) |
| `stage2_en_best.pt` | 2026-06-02 12:39 | stage1 | `train_stage2.py` | `pairs_stage2_en.jsonl` (845, EN-only) | 실험 |
| `stage2_en_hn_best.pt` | 2026-06-02 13:17 | stage1 | `train_stage2_hardneg_experiment.py` | EN 845 + hard neg 3,853 | 실험 |

로그: `checkpoints/train.log`, `train_stage2.log`, `train_stage2_en.log`, `train_stage2_en_hn.log`

---

## 모델별 학습 설정

### Stage-1 — Material Icons

| 항목 | 값 |
|------|-----|
| 스크립트 | `train_stage1.py` |
| 데이터 | `pairs.jsonl`, split `splits.json` (icon_id, 80/10/10) |
| 하이퍼 | 20 epoch, batch 16, lr `1e-6` |
| aug | train: `augment_icon_patch`, val/test: 고정 view |
| best 선정 | val R@1 최고 epoch |

**split (pairs):** train 1,202 / val 150 / test 151

**best (`stage1_best.pt`, epoch 19):**

| | val R@1 | test R@1 | train loss |
|--|---------|----------|------------|
| best | **43.3%** | 37.8% | 0.041 |
| last (ep 20) | 41.3% | 37.8% | 0.043 |

---

### Stage-2 — 508 pairs (1차 run, **소실**)

| 항목 | 값 |
|------|-----|
| 스크립트 | `train_stage2.py` |
| 하이퍼 | 10 epoch, batch 32, lr `5e-7`, init stage1 |
| split (pairs) | train 371 / val 56 / test 81 |

**best (당시 `stage2_best.pt`, epoch 2·4·6):** val R@1 **10.71%**, test R@1 **6.17%** (ep 6)

동일 508 test — Stage-1 R@1 2.47% vs Stage-2 **6.17%** (in-domain 소폭 ↑)

1203 re-export 후 **같은 파일명으로 덮어써서 가중치 복구 불가.**

---

### Stage-2 — 1,203 pairs (한·영, 현재 `stage2_best.pt`)

| 항목 | 값 |
|------|-----|
| export | `export_stage2_pairs.py` → 1,203 positives |
| split (groups / pairs) | train 360 / 939 — val 45 / 196 — test 46 / 68 |

**best (val R@1 기준, epoch 7·9):** val **9.18%**, test @ ep10 **33.82%**

| epoch | val R@1 | test R@1 |
|-------|---------|----------|
| 7 (best) | **9.18%** | 32.35% |
| 10 (last) | 8.67% | **33.82%** |

---

### Stage-2 EN-only (실험, `stage2_en_best.pt`)

| 항목 | 값 |
|------|-----|
| export | `export_stage2_en_experiment.py` (한글 358 제외) |
| split (groups / pairs) | train 220 / 745 — val 27 / 50 — test 29 / 50 |

**best (epoch 8):** val R@1 **30.0%**, test R@1 **26.0%**

---

### Stage-2 EN + Hard Negative (실험, `stage2_en_hn_best.pt`)

| 항목 | 값 |
|------|-----|
| 스크립트 | `train_stage2_hardneg_experiment.py` |
| hard neg | `pairs_stage2_en_hard_negatives.jsonl` (3,853), `hard_weight=0.25` |
| split | EN과 동일 (745 / 50 / 50) |

**best (epoch 7–8):** val R@1 **30.0%**, test R@1 **28.0%**

---

## Split 성능 — R@1 / R@5 (2026-06-02 재측정)

학습 시 로그는 R@1만 출력. 아래는 각 checkpoint를 동일 split에 재평가한 값.

### Material (`pairs.jsonl`, icon_id split)

| checkpoint | val R@1 | val R@5 | test R@1 | test R@5 |
|------------|---------|---------|----------|----------|
| OpenAI baseline | — | — | 7.3% | 20.5% |
| **stage1_best** | **43.3%** | **64.7%** | **37.8%** | **66.2%** |
| stage2_best | 42.0% | 58.7% | 35.8% | 64.2% |
| stage2_en_best | 40.7% | 61.3% | 37.1% | 62.9% |
| stage2_en_hn_best | 39.3% | 58.7% | 36.4% | 62.3% |

### Stage-2 full (`pairs_stage2.jsonl`, 1,203)

| checkpoint | val R@1 | val R@5 | test R@1 | test R@5 |
|------------|---------|---------|----------|----------|
| stage1_best | 6.63% | 12.24% | 27.94% | 39.71% |
| stage2_best | 9.18% | 15.82% | 33.82% | 52.94% |
| stage2_en_best | 10.71% | 20.92% | 38.24% | 50.00% |
| stage2_en_hn_best | **11.73%** | 19.90% | **39.71%** | 51.47% |

### Stage-2 EN (`pairs_stage2_en.jsonl`, 845)

| checkpoint | val R@1 | val R@5 | test R@1 | test R@5 |
|------------|---------|---------|----------|----------|
| stage1_best | 24.0% | 50.0% | 20.0% | 44.0% |
| stage2_best † | 40.0% | 68.0% | 48.0% | 86.0% |
| **stage2_en_best** | **30.0%** | 52.0% | 26.0% | 50.0% |
| stage2_en_hn_best | 30.0% | 50.0% | 28.0% | 46.0% |

† 1203로 학습된 `stage2_best`를 EN split에 cross-eval.

---

## Eval 성능 (`eval_clip_compare.py`)

### 조건

- **Screen / Oracle:** `eval_cases.json` + `eval_screenshots/` — **10 cases**, 영어 query
- **Screen:** YOLO auto imgsz, **detected=9/10** (milvus 제외, IoU≥0.5)
- 출력 라벨 `stage1=` = `--checkpoint` 인자 모델 (baseline OpenAI와 비교)

### Screen (YOLO + CLIP) — 실사용에 가장 가까움

| checkpoint | top1 | top5 | 9장 중 (top1) |
|------------|------|------|---------------|
| baseline | 0% | 33.3% | 0/9 |
| **stage1_best** | **55.6%** | **77.8%** | **5/9** |
| stage2_en_best | 44.4% | 77.8% | 4/9 |
| stage2_best (1203) | 33.3% | 66.7% | 3/9 |
| stage2_en_hn_best | 33.3% | 66.7% | 3/9 |
| stage2 @508 (소실) | 44.4% ‡ | 66.7% ‡ | 4/9 ‡ |

‡ 과거 터미널 기록 (가중치 없음).

**screen top1 순위:** stage1 (55.6%) > stage2_en (44.4%) > stage2 / stage2_en_hn (33.3%)

### Oracle (GT bbox crop, YOLO 없음, n=10)

| checkpoint | R@1 | R@5 |
|------------|-----|-----|
| baseline | 50.0% | 60.0% |
| stage1_best | **70.0%** | **100%** |
| stage2_best | 70.0% | 90.0% |
| stage2_en_best | 70.0% | 100% |
| stage2_en_hn_best | 60.0% | 100% |

### Gallery (Material test 151)

| checkpoint | R@1 | R@5 |
|------------|-----|-----|
| baseline | 7.3% | 20.5% |
| stage1_best | 33.8% | **65.6%** |
| stage2_en_best | **35.1%** | 60.3% |
| stage2_best | 33.1% | 61.6% |
| stage2_en_hn_best | 31.1% | 57.6% |

---

## 데이터셋 (export 시점)

| 항목 | 수량 |
|------|------|
| `dataset/events.jsonl` | 8,044 rows |
| ok positives (export 후보) | ~1,228 |
| `pairs_stage2.jsonl` | 1,203 |
| `pairs_stage2_en.jsonl` | 845 (한글 358 제외) |
| `pairs_stage2_en_hard_negatives.jsonl` | 3,853 |
| `negative_hard` (events, 학습 기본 미사용) | 6,816 |
| crops / frames | ~8,019 / 111 |

---

## 실험 스크립트 (공식 파이프라인 외)

| 스크립트 | 용도 |
|----------|------|
| `export_stage2_en_experiment.py` | 한글 제외 EN export |
| `export_stage2_en_1pf_experiment.py` | frame당 positive 1개 (75 pairs) |
| `train_stage2_hardneg_experiment.py` | hard negative loss |
| `eval_clip_compare.py` | gallery / screen / oracle 비교 |

공식 흐름: collect → `export_stage2_pairs.py` → `train_stage2.py`

### 데스크톱 앱 수집 (Office · 한글)

`configs/collect_targets.json` — Word, Excel, PowerPoint, Outlook, 한글/HWP, VS Code (`Chrome`/`Edge`는 `enabled: false`).

```powershell
powershell -ExecutionPolicy Bypass -File tools\collect_stage2_desktop.ps1
```

브라우저 히스토리 없음 → export 기본은 **EN-only** (`pairs_stage2_en.jsonl`). 전체 export: `-FullExport`.

### CLIP `text` 정제 (실사용 target)

UIA 접근성 문자열 → **음성 target**(action 제외 remainder)에 맞추기:

| 위치 | 모듈 |
|------|------|
| 수집 | `tools/auto_collect_runner.py` → `speech/target_text.refine_clip_query_text` |
| export | `export_stage2_pairs.py` → `text` (정제), `raw_query` (원문) |
| 런타임 음성 | `agent/process_utterance.py` → `refine_parsed_voice_query` |
| CLIP 임베딩 | `perception/icon_utils.get_text_embedding` |

규칙 예: `닫기`→`close`, `이 항목을 목록에 고정`→`pin`, `(alt+f)` 제거, 사이트명(논현일보)은 **유지**.  
정제 후 **재-export·재학습** 필요 (`pairs_stage2.jsonl` 갱신).

---

## Eval 재현

```powershell
cd <repo-root>
venv\Scripts\python.exe training_data/icons_material/eval_clip_compare.py --mode all

# 특정 checkpoint
venv\Scripts\python.exe training_data/icons_material/eval_clip_compare.py `
  --mode screen `
  --checkpoint training_data/icons_material/checkpoints/stage2_en_best.pt
```

Split R@1/R@5 재측정은 `train_stage2.py`의 `recall_at_k` + 각 `pairs_*.jsonl` / `splits_*.json` 사용.

---

## Stage-2 LoRA (EN raw, 정제 전)

**가설:** full FT는 Stage-1을 망가뜨려 screen eval ↓. LoRA + UIA 원문 라벨로 실화면 적응만 얹기.

| 단계 | 명령 / 설정 |
|------|--------------|
| Export | `python training_data/icons_material/export_stage2_en_raw_experiment.py` → `pairs_stage2_en_raw.jsonl`, `splits_stage2_en_raw.json` |
| Train | `python training_data/icons_material/train_stage2_lora_experiment.py --epochs 12 --batch-size 32 --lr 1e-4`  |
| Eval | `python training_data/icons_material/eval_clip_compare.py --mode all --checkpoint training_data/icons_material/checkpoints/stage2_en_lora_best.pt` |

- `text` = `refine_clip_query_text` **미적용** (Hangul 행은 EN export에서 제외).
- 런타임은 여전히 `refine_clip_query_text` / `refine_parsed_voice_query` 사용 → train/serve gap 있음.
- LoRA: visual+text `attn.out_proj`, `mlp.c_fc`, `mlp.c_proj` (rank 8, lr `1e-4` 기본).

**best checkpoint:** `stage2_en_lora_best.pt` (epoch 10)  
**split (stage2_lora train loop):** val_R@1 **28.26%**, test_R@1 **41.86%**

**eval_clip_compare.py (mode=all, 10 labeled screen cases):**
- Material gallery: r1 **0.2583**, r5 **0.5563**
- Screen YOLO+CLIP: top1 **0.2222**, top5 **0.6667** (detected 9/10)
- Screen oracle GT crops: r1 **0.5000**, r5 **0.8000**

### Refined label variant (EN refined `text`)

- Train command:
  `python training_data/icons_material/train_stage2_lora_experiment.py --pairs training_data/icons_material/pairs_stage2_en.jsonl --splits training_data/icons_material/splits_stage2_en.json --best-checkpoint stage2_en_refined_lora_best.pt --epoch-prefix stage2_en_refined_lora_epoch --log-file train_stage2_en_refined_lora.log --epochs 12 --batch-size 32 --lr 1e-4`
- Best checkpoint: `stage2_en_refined_lora_best.pt` (val_R@1 **0.3250**, test_R@1 **0.5862**)
- Eval (`--mode all`):
  - Material gallery: r1 **0.2583**, r5 **0.5629**
  - Screen YOLO+CLIP: top1 **0.1111**, top5 **0.7778**
  - Screen oracle GT crops: r1 **0.6000**, r5 **0.9000**

### Refined label + Visual-only LoRA (`text tower` 고정)

- Train command:
  `python training_data/icons_material/train_stage2_lora_experiment.py --pairs training_data/icons_material/pairs_stage2_en.jsonl --splits training_data/icons_material/splits_stage2_en.json --best-checkpoint stage2_en_refined_lora_visual_only_best.pt --epoch-prefix stage2_en_refined_lora_visual_only_epoch --log-file train_stage2_en_refined_lora_visual_only.log --visual-only --epochs 12 --batch-size 32 --lr 1e-4`
- Training note: 저장 중 디스크 write error로 epoch 9에서 중단. best 파일은 정상 저장/로딩 확인 (`epoch 8`, `val_R@1=0.3000`, `test_R@1=0.5517`).
- Eval (separate runs):
  - Material gallery: r1 **0.1854**, r5 **0.3841**
  - Screen oracle GT crops: r1 **0.5000**, r5 **0.9000**
  - Screen YOLO+CLIP: top1 **0.1111**, top5 **0.2222** (detected 9/10)

---

## 결론 요약

1. **eval 10장 기준 최고 = Stage-1 (Material, 영어 query 친화적).**
2. **Stage-2 (full FT, 실화면 crop)** 은 in-domain split ↑, screen eval ↓ 패턴 반복.
3. **EN-only**는 1203 full보다 screen 개선 (44.4% vs 33.3%), Stage-1 미달.
4. **Hard neg loss**는 split/test 일부 ↑, screen·oracle R@1 하락.
5. **`stage2_best.pt` (508)** 은 백업 없이 1203 run에 덮어씀 — 재학습만 가능.

---

*이 파일을 갱신할 때: checkpoint 재학습 후 `eval_clip_compare.py --mode all` 실행하고 표를 업데이트하세요.*
