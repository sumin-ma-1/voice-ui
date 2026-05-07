# Voice UI — typed or spoken command → parse → Office, direct keys, or grounded UI action

Windows desktop loop: **text bar** (development default) or **hands‑free voice + floating UI** → structured command → Microsoft Office (COM), PyAutoGUI shortcuts, or **screen capture + element matching** (UIA, OCR, and/or vision).

All runnable paths go through **`agent/process_utterance.py`** so behavior stays aligned. Optional **dataset logging** (`VOICE_UI_DATASET_LOG`) records executions and grounded crops to disk without changing default runtime behavior.

---

## Main flow

```mermaid
flowchart TD
    subgraph in [Input]
        IN[TextInputGUI or VoiceSession plus floating UI]
    end

    subgraph core [Shared pipeline]
        PU[agent/process_utterance — parse + route + execute path]
    end

    subgraph route [Routing]
        O{action in OFFICE_ACTIONS?}
        D{Direct action?}
        G[UI-grounded: click / hover / …]
    end

    subgraph ground [Perception + grounding]
        CAP[screen_capture.capture_screen]
        EXT[Elements by --mode]
        FLT[ui_filter.filter_elements]
        MAT[matcher.find_best_match]
        DBG[debug_draw optional]
    end

    subgraph out [Act]
        OC[office_controller + office/*]
        EX[automation.executor.execute]
    end

    IN -->|string| PU
    PU --> O
    O -->|yes| OC
    O -->|no| D
    D -->|yes| EX
    D -->|no| G
    G --> CAP --> EXT --> FLT --> MAT
    MAT -->|score OK| DBG --> EX
    MAT -->|fail| NM[Log: no confident match]
```

**`--mode` (UI targets only):**

| Mode | Source |
|------|--------|
| `uia` | UIA on the active window — **default:** native on-screen walk (`IsOffscreen` + pruned DFS, `uia_onscreen_extractor`); optional classic `descendants` (see below) |
| `ocr` | Full-screen EasyOCR lines → element list |
| `vision` | YOLO icons + EasyOCR on local crops (`icon_utils`) |
| `both` | UIA first; if no confident match, fresh capture → vision |
| `all` | UIA → full-frame OCR → vision (three-step fallback) |

Single modes use `perception/ui_extractor.py` (`uia` / `vision`). Cascades use `perception/ui_fallback_pipeline.py` and, for OCR, `perception/ocr_elements.py`. Cascade match steps return **raw frames** (no debug overlay on the frame used for grounding/dataset crops). Default: `python main.py` → `--mode uia`.

### UIA: on-screen (default) vs classic tree

By default, UIA stages use **`perception/uia_onscreen_extractor.py`**: a depth-first walk that respects native **`IsOffscreen`** (UIA property 30022) and skips pruned subtrees, instead of flattening with `descendants(depth=20)`.

To switch to the **classic** pywinauto tree (`descendants`), set:

| Variable | Value | Effect |
|----------|--------|--------|
| `VOICE_UI_UIA_USE_CLASSIC` | `1`, `true`, `yes`, or `on` | Classic `descendants` in `ui_extractor` |
| *(unset or any other value)* | — | On-screen native UIA (default) |

PowerShell example for classic mode:

```powershell
$env:VOICE_UI_UIA_USE_CLASSIC = "1"
python main.py --mode uia
```

Other UIA tuning (unchanged): `VOICE_UI_UIA_MAX_DEPTH` is read by `uia_onscreen_extractor`.

### Action names (single registry)

Parsed `action` strings and how they are routed are defined in **`automation/action_space.py`**:

| Set | Role |
|-----|------|
| `OFFICE_ACTIONS` | COM path — `main` / demos use `is_office_action` → `OfficeController` |
| `DIRECT_ACTIONS` | No UI grounding — straight to `automation/executor.py` (mostly PyAutoGUI; **`focus`** uses Win32 title match, see `automation/window_focus.py`) |
| `GROUNDED_ACTIONS` | Needs a matched element — perception + `matcher` → then `executor` |
| `UNKNOWN_ACTION` | No recognized phrase — `speech/command_parser.py` fallback |
| `POST_GROUNDING_CLICK_DELAY_ACTIONS` | After some grounded clicks, `main` / demos sleep briefly so UIs can open |

`OfficeController` registers handlers whose keys must match `OFFICE_ACTIONS` at startup. `main.py` and `demos/ocr_grounded_agent_demo.py` import `DIRECT_ACTIONS`, `GROUNDED_ACTIONS`, `is_office_action`, etc., from the same module so routing lists do not drift.

**`focus` (window activation):** Say `focus <substring>` (e.g. `focus Chrome`) to find a **visible top-level** window whose **title** contains that text (case-insensitive), score best match (exact / prefix / substring), then activate it with `SetForegroundWindow`. This works with many apps when several windows are open, but it cannot target by process alone, tab text inside a browser, or minimized-to-tray-only UIs; Windows may still refuse focus in some cases.

**Bring Office to the foreground:** `com/office/foreground.py` is used by the Word / Excel / PowerPoint controllers after **launching or opening** the app or a document (`open`, `open_file`, `new_*`, and related paths). It calls `Application.Activate()` when available, then `ShowWindow` / `SetForegroundWindow` (with `AttachThreadInput` when another app owns the foreground) so the Office window is more likely to appear **in front of** the agent instead of staying in the background until you click it. Windows focus rules can still prevent this occasionally (e.g. other fullscreen apps or system policies).

**Typed / spoken phrasing:** `speech/command_parser_rules.py` collapses runs of whitespace so phrases like `scroll  up` still match. For **`hotkey`**, spoken **control** is sent to PyAutoGUI as **ctrl**; **windows** becomes **win** (see `executor._normalize_hotkey_token`).

**Scroll on Windows:** Vertical/horizontal wheel uses `automation/win32_scroll.py` (`MOUSEEVENTF_WHEEL` / `MOUSEEVENTF_HWHEEL` with 120-delta steps) because PyAutoGUI’s Win32 `hscroll` path only sends a vertical wheel. The pointer must be over a scrollable surface (same as any wheel scroll).

**Executor contract:** `automation/executor.execute` returns an **`ExecuteResult`** (`ok`, `reason`). On failure, `main` / demos print `reason` so users see a concrete automation or validation error. That is separate from **parse failure** (`UNKNOWN_ACTION` from `command_parser`), which uses a different message (“could not parse as a known command …”) so misparsed input is not confused with PyAutoGUI or parameter errors.

---

## Run

| Goal | Command |
|------|---------|
| **Development (text bar)** | `python main.py --mode uia` — same as `--input text` (default) |
| **Hands‑free voice** | `python main.py --mode all --input voice` |
| **Dataset collection on** | Set `VOICE_UI_DATASET_LOG=1` (see [Dataset Logging](#dataset-logging)) |

```bash
python main.py --mode uia        # default mode + default text input
python main.py --mode ocr
python main.py --mode vision
python main.py --mode both
python main.py --mode all
python main.py --mode all --input text    # explicit dev text bar
python main.py --mode all --input voice   # wake phrase + floating overlay
```

**`--input`:**

| Value | Behavior |
|-------|----------|
| `text` *(default)* | Compact always‑on‑top bar (`speech/text_input_gui.py`): type a command, Enter to submit (good when mic/STT is inconvenient). |
| `voice` | Floating status widget (`speech/floating_voice_widget.py`) + wake phrase **“Hey Voice UI”** / **“Hey Voice”** + mic pipeline (`speech/voice_session.py`). |

Exit phrases (typed or spoken after wake): `exit`, `quit`, `stop agent`, `shutdown`. With **`--input voice`**, during the grace window before automation you can say **stop** (cancel this action) or **exit** (quit the app). Interrupt with **Ctrl+C** in the terminal.

---

## Voice UI (floating overlay)

**Modules:** `speech/floating_voice_widget.py` (LED state, transcript line, pipeline guide, **Confirm before run** toggle), `speech/voice_session.py` (mic → VAD → Whisper → wake phrase gate → command queue), `perception/grounding_highlight.py` (full‑screen highlight ring before execute when a Tk parent exists).

Hands‑free flow:

1. Say **Hey Voice UI**, then your command in the **same utterance** or the **next** utterance. Parser input strips the wake phrase when present (`agent/process_utterance.py`).
2. While the agent finds a UI target, the strip shows status text (“Finding target…”, etc.).
3. After grounding, the matched region is **highlighted** briefly on screen (duration scales with grace length).
4. **Grace window** (`VOICE_UI_GRACE_SECONDS`, default ~0.85s) — **only when `--input voice`**: say **stop** to cancel before automation runs, or **exit** to quit the app. **`--input text` has no extra grace delay** (immediate execute path after confirmations).
5. Optional **Confirm before run** checkbox: `tkinter` confirmation dialog before Office / direct / grounded execution.

### Voice stack

| Piece | Role |
|-------|------|
| **WebRTC VAD** (`webrtcvad`) | End‑of‑utterance segmentation (preferred). If import fails, a simple **energy gate** fallback is used (install `webrtcvad` from `requirements.txt`). |
| **OpenAI Whisper** (`tiny` default) | Transcription (`speech/whisper_engine.py`); optional `transcribe_pcm16` for raw PCM. |

Wake words are matched on **Whisper text** (not a dedicated wake embedded model). Partial **live transcript** updates are best‑effort (periodic Whisper passes while you speak); final text is shown when a segment ends.

### Environment variables (voice)

| Variable | Effect |
|----------|--------|
| `VOICE_UI_GRACE_SECONDS` | Grace delay before execute / Office / direct / grounded actions when `--input voice` (default `0.85`). |
| `VOICE_UI_WHISPER_MODEL` | Whisper size (default `tiny`). |
| `VOICE_UI_WHISPER_LANG` | Force Whisper language (e.g. `ko`, `en`). Unset lets Whisper choose where supported. |
| `VOICE_UI_VAD_AGGRESSIVENESS` | WebRTC VAD `0`–`3` (default `2`). |
| `VOICE_UI_ENERGY_GATE` | RMS threshold when VAD falls back to energy gating (default `280`). |

---

## Dataset Logging

When enabled, every call to **`automation/executor.execute`** appends one JSON line to **`dataset/events.jsonl`** (`dataset/data_logger.py`). Grounded UI actions additionally save **raw** full‑frame and **bbox crop** images at successful match time from **`agent/process_utterance.prepare_grounding_artifacts`** (same code path for **`--input text`** and **`--input voice`**).

### Toggle with environment variables

| Variable | Value | Effect |
|----------|-------|--------|
| `VOICE_UI_DATASET_LOG` | `1`, `true`, `yes`, or `on` | Enable dataset logging |
| `VOICE_UI_DATASET_LOG` | *(unset or any other value)* | Disable dataset logging (default) |
| `VOICE_UI_DATASET_DIR` | path string | Dataset root directory (default: `dataset`) |

PowerShell examples:

```powershell
$env:VOICE_UI_DATASET_LOG = "1"
$env:VOICE_UI_DATASET_DIR = "dataset"
python main.py --mode all --input text

$env:VOICE_UI_DATASET_LOG = "1"
python main.py --mode all --input voice
```

### What gets written

When enabled, the logger writes:

- `dataset/events.jsonl`: one JSON line per `execute(...)` call
- `dataset/frames/*.png`: full frame at grounded-action time
- `dataset/crops/*.png`: crop from matched target `bbox` (when available)

### Event fields

Core fields include:

- `event_id`, `ts`, `session_id`
- `raw_text`, `action`, `query`, `mode_used`
- `ok`, `reason`
- `target` (`name`, `bbox`, `center`)
- `artifacts` (`frame_path`, `crop_path`)

### Important behavior guarantees

- Logging is best-effort and isolated from execution; logger errors are swallowed so automation keeps running.
- Default behavior is unchanged because logging is OFF unless explicitly enabled.
- Dataset frame/crop use the **raw capture** (before **match/candidate** debug overlays). Debug snapshots may still be written under `test_screen_img/` by `perception/debug_draw.show_debug` for developer inspection.

---

## Layout (runtime)

```
voice-ui/
├── main.py
├── agent/            # process_utterance (shared text + voice pipeline)
├── dataset/          # data_logger (optional events.jsonl + frames/crops)
├── requirements.txt
├── speech/           # TextInputGUI, floating_voice_widget, voice_session (wake + VAD), whisper_engine, command_parser (+ rules), office_command_parser
├── perception/       # capture, ui_extractor, grounding_cascade, grounding_highlight, ocr_elements, ui_fallback_pipeline, icon_utils, filter, debug_draw
├── grounding/        # matcher (SentenceTransformers + CLIP for icons)
├── automation/       # action_space.py, executor.py, window_focus.py (``focus``), win32_scroll.py (wheel on Windows)
├── com/              # office_controller, office/foreground.py (focus), office/* (ppt/word/excel COM); branch gated by action_space.is_office_action in main / demos
├── demos/            # Standalone OCR / explorer demos
└── pre/              # Prototypes — not imported by main.py
```

Vision expects **`epoch235.pt`** (YOLO) in the working directory (or where Ultralytics resolves it).

---

## Dependencies

Install from **`requirements.txt`**: PyAutoGUI, pywinauto, OpenCV, Sentence Transformers, CLIP, Ultralytics, EasyOCR, **webrtcvad** (voice end‑pointing; optional fallback if missing), PyAudio, OpenAI Whisper, etc. GPU is optional; COM path needs Office installed for those commands.

Use a **virtualenv**; keep `venv/` out of git (see `.gitignore`).

---

## Environment variables (quick reference)

| Variable | Area | Purpose |
|----------|------|---------|
| `VOICE_UI_UIA_USE_CLASSIC` | UIA | Classic `descendants` tree instead of on-screen walk |
| `VOICE_UI_DATASET_LOG` | Dataset | Enable `events.jsonl` + frame/crop artifacts |
| `VOICE_UI_DATASET_DIR` | Dataset | Root folder (default `dataset`) |
| `VOICE_UI_GRACE_SECONDS` | Voice | Pre‑execute cancel window when `--input voice` |
| `VOICE_UI_WHISPER_MODEL` / `VOICE_UI_WHISPER_LANG` | Voice / STT | Whisper size and language |
| `VOICE_UI_VAD_AGGRESSIVENESS` / `VOICE_UI_ENERGY_GATE` | Voice / VAD | WebRTC VAD level or energy fallback threshold |
