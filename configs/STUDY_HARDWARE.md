# User study — hardware & session checklist

## Recommended PC specs (per participant)

| Item | Minimum | Recommended |
|------|---------|-------------|
| OS | Windows 10 64-bit | Windows 10/11 64-bit |
| RAM | 8 GB | **16 GB+** |
| Disk free | 10 GB | 20 GB+ (venv, logs, crops) |
| CPU | 4 logical cores | 6+ logical cores |
| GPU | Not required | NVIDIA CUDA (vision path faster) |
| Microphone | — | Required for `-Input voice` |

`study_manifest.json` records actual specs at session start and sets `hardware_guidance.reboot_before_session_recommended` when RAM &lt; 16 GB or disk &lt; 10 GB free.

## Before each session

1. **Reboot** if manifest recommends it, or if the machine was used heavily (many Chrome tabs, games, etc.).
2. Close unrelated heavy apps (browsers except test target, games, video calls).
3. Plug in laptop power.
4. For voice: check Windows mic permission for Python.
5. Run from repo root:
   ```powershell
   powershell -ExecutionPolicy Bypass -File tools\run_study.ps1 -Participant U1 -Input voice
   ```

## Latency metrics (what to cite in the paper)

| Field | Meaning |
|-------|---------|
| **`latency_ms.pipeline`** | **Primary** — parse → capture → grounding → execute (system work only) |
| `latency_ms.wall_clock` | Includes UX: grace, highlight, confirm, debug overlays |
| `latency_ms.ux_overhead` | Sum of grace + highlight + confirm + debug + artifacts |
| `latency_ms.stt` | Voice only: final Whisper pass for that utterance |
| `latency_ms.uia` / `ocr` / `vision` / `execute` | Stage breakdown |

Do **not** use `wall_clock` alone for system performance — it inflates by ~1–2 s when voice grace + highlight are enabled.

## task131

`task131.xlsx` (131 utterances) is matched automatically when the spoken/typed text matches a row. Logged as `study.task.task_id` when matched.
