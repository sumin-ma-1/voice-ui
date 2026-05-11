# dataset/runtime_overrides.py
# In-process toggles for dev (text mode ``!dataset …``). Overrides beat ``os.environ`` until cleared.

from __future__ import annotations

import os
import threading
from typing import Literal

_lock = threading.Lock()

# None = follow os.environ; True/False = force
_log_override: bool | None = None
# None = follow env for extra negatives; int = force cap (>=0)
_extra_negs_override: int | None = None


def _is_true(value: str | None) -> bool:
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def effective_dataset_log() -> bool:
    """Whether dataset logging is on (override wins, else ``VOICE_UI_DATASET_LOG``)."""
    with _lock:
        if _log_override is not None:
            return bool(_log_override)
    return _is_true(os.getenv("VOICE_UI_DATASET_LOG"))


def effective_extra_negatives_cap() -> int:
    """Hard-negative cap: override int, else ``VOICE_UI_DATASET_EXTRA_NEGATIVES``."""
    with _lock:
        if _extra_negs_override is not None:
            return max(0, int(_extra_negs_override))
    raw = os.getenv("VOICE_UI_DATASET_EXTRA_NEGATIVES")
    if raw is None or not str(raw).strip():
        return 0
    s = str(raw).strip().lower()
    if s in {"1", "true", "yes", "on"}:
        return 6
    try:
        return max(0, int(s))
    except ValueError:
        return 0


def set_dataset_log_override(value: bool | None) -> None:
    """``True``/``False`` = force; ``None`` = use ``VOICE_UI_DATASET_LOG`` env each time."""
    global _log_override
    with _lock:
        _log_override = value


def set_extra_negatives_override(value: int | None) -> None:
    """``int`` = max extra negatives; ``None`` = use ``VOICE_UI_DATASET_EXTRA_NEGATIVES`` env."""
    global _extra_negs_override
    with _lock:
        _extra_negs_override = value


def status_lines() -> list[str]:
    """Human-readable lines for ``!dataset`` / ``!dataset status``."""
    env_log = os.getenv("VOICE_UI_DATASET_LOG")
    env_negs = os.getenv("VOICE_UI_DATASET_EXTRA_NEGATIVES")
    with _lock:
        lo = _log_override
        eo = _extra_negs_override
    eff_log = effective_dataset_log()
    eff_negs = effective_extra_negatives_cap()
    lines = [
        "[runtime dataset]",
        f"  VOICE_UI_DATASET_LOG (env)     = {env_log!r}",
        f"  override log                   = {lo!r}  →  effective LOG = {eff_log}",
        f"  VOICE_UI_DATASET_EXTRA_NEGATIVES (env) = {env_negs!r}",
        f"  override extra_negs          = {eo!r}  →  effective cap = {eff_negs}",
        f"  VOICE_UI_DATASET_DIR (env)     = {os.getenv('VOICE_UI_DATASET_DIR', 'dataset')!r}",
        "  Commands:",
        "    !dataset on | off | env     (force log / follow env)",
        "    !dataset negs <n> | negs env",
        "    !dataset envlog on|off      (set env + clear log override)",
        "    !dataset envnegs <n>|unset",
        "    !dataset reset",
    ]
    return lines


def handle_dev_command(text: str) -> Literal["handled", "not_dev"]:
    """
    Parse dev ``!dataset`` commands (lowercase text). Returns ``handled`` if consumed.
    """
    t = (text or "").strip()
    if not t.startswith("!"):
        return "not_dev"
    parts = t[1:].split()
    if not parts:
        return "not_dev"
    head = parts[0].lower()
    if head != "dataset":
        return "not_dev"

    sub = [p.lower() for p in parts[1:]]
    if not sub or sub[0] in ("status", "help"):
        for line in status_lines():
            print(line)
        return "handled"

    if sub[0] == "on":
        set_dataset_log_override(True)
        print("[runtime] Dataset logging **forced ON** (until !dataset env or reset).")
        return "handled"
    if sub[0] == "off":
        set_dataset_log_override(False)
        print("[runtime] Dataset logging **forced OFF** (until !dataset env or reset).")
        return "handled"
    if sub[0] == "env":
        set_dataset_log_override(None)
        print("[runtime] Dataset logging follows **VOICE_UI_DATASET_LOG** env again.")
        return "handled"

    if sub[0] == "negs":
        if len(sub) < 2:
            print("[runtime] Usage: !dataset negs <number>  |  !dataset negs env")
            return "handled"
        if sub[1] == "env":
            set_extra_negatives_override(None)
            print("[runtime] Extra negatives follow **VOICE_UI_DATASET_EXTRA_NEGATIVES** env again.")
            return "handled"
        try:
            n = int(sub[1])
            set_extra_negatives_override(max(0, n))
            print(f"[runtime] Extra negatives **forced to {max(0, n)}** (until !dataset negs env or reset).")
        except ValueError:
            print("[runtime] negs value must be an integer or 'env'.")
        return "handled"

    if sub[0] == "reset":
        set_dataset_log_override(None)
        set_extra_negatives_override(None)
        print("[runtime] Dataset overrides cleared — both follow environment variables.")
        return "handled"

    if sub[0] == "envlog" and len(sub) > 1:
        v = sub[1]
        if v in ("on", "1", "true", "yes"):
            os.environ["VOICE_UI_DATASET_LOG"] = "1"
        elif v in ("off", "0", "false", "no"):
            os.environ["VOICE_UI_DATASET_LOG"] = "0"
        else:
            os.environ["VOICE_UI_DATASET_LOG"] = sub[1]
        set_dataset_log_override(None)
        print(
            f"[runtime] VOICE_UI_DATASET_LOG={os.environ.get('VOICE_UI_DATASET_LOG')!r} "
            "(override cleared — effective follows env)."
        )
        return "handled"

    if sub[0] == "envnegs":
        if len(sub) < 2:
            print("[runtime] Usage: !dataset envnegs <number>  |  !dataset envnegs unset")
            return "handled"
        if sub[1] == "unset":
            os.environ.pop("VOICE_UI_DATASET_EXTRA_NEGATIVES", None)
        else:
            os.environ["VOICE_UI_DATASET_EXTRA_NEGATIVES"] = sub[1]
        set_extra_negatives_override(None)
        print(
            f"[runtime] VOICE_UI_DATASET_EXTRA_NEGATIVES="
            f"{os.environ.get('VOICE_UI_DATASET_EXTRA_NEGATIVES', '(unset)')!r} "
            "(override cleared)."
        )
        return "handled"

    print("[runtime] Unknown !dataset …  Try: !dataset help")
    return "handled"
