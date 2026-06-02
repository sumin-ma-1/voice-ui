"""
Launch Windows apps before auto-collection when no matching window is open.

UIA capture needs a real visible window; this module starts processes only — it does
not minimize them. Use ``skip_if_window_open`` to avoid duplicate launches.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from automation.window_focus import window_exists_by_title_substring

# title_substring hint -> launch alias
_TITLE_LAUNCH_HINTS: tuple[tuple[str, str], ...] = (
    ("visual studio code", "vscode"),
    ("powerpoint", "powerpoint"),
    ("outlook", "outlook"),
    ("word", "word"),
    ("excel", "excel"),
    ("한글", "hwp"),
    ("hwp", "hwp"),
    ("hancom", "hwp"),
    ("chrome", "chrome"),
    ("edge", "edge"),
)


def _local_app_data() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", ""))


def _program_files() -> tuple[Path, Path]:
    pf = Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
    pf86 = Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))
    return pf, pf86


def resolve_executable(spec: str) -> Path | None:
    """
    Resolve ``spec`` to an executable path.

    ``spec`` may be a full path, or an alias: chrome, edge, vscode, powerpoint, word,
    excel, outlook, hwp (Hancom Hangul / Hangle).
    """
    raw = (spec or "").strip()
    if not raw:
        return None

    p = Path(raw)
    if p.is_file():
        return p

    alias = raw.lower()
    pf, pf86 = _program_files()
    local = _local_app_data()

    candidates: list[Path] = []
    if alias == "chrome":
        candidates = [
            pf / "Google/Chrome/Application/chrome.exe",
            pf86 / "Google/Chrome/Application/chrome.exe",
            local / "Google/Chrome/Application/chrome.exe",
        ]
    elif alias == "edge":
        candidates = [
            pf / "Microsoft/Edge/Application/msedge.exe",
            pf86 / "Microsoft/Edge/Application/msedge.exe",
        ]
    elif alias == "vscode":
        candidates = [
            local / "Programs/Microsoft VS Code/Code.exe",
            pf / "Microsoft VS Code/Code.exe",
        ]
        code_cmd = shutil.which("code")
        if code_cmd:
            return Path(code_cmd)
    elif alias == "powerpoint":
        candidates = [
            pf / "Microsoft Office/root/Office16/POWERPNT.EXE",
            pf86 / "Microsoft Office/root/Office16/POWERPNT.EXE",
            pf / "Microsoft Office/Office16/POWERPNT.EXE",
        ]
    elif alias == "word":
        candidates = [
            pf / "Microsoft Office/root/Office16/WINWORD.EXE",
            pf / "Microsoft Office/Office16/WINWORD.EXE",
        ]
    elif alias == "excel":
        candidates = [
            pf / "Microsoft Office/root/Office16/EXCEL.EXE",
            pf / "Microsoft Office/Office16/EXCEL.EXE",
        ]
    elif alias == "outlook":
        candidates = [
            pf / "Microsoft Office/root/Office16/OUTLOOK.EXE",
            pf86 / "Microsoft Office/root/Office16/OUTLOOK.EXE",
            pf / "Microsoft Office/Office16/OUTLOOK.EXE",
        ]
    elif alias in ("hwp", "hangle", "hancom"):
        candidates = [
            pf / "Hancom/Hancom Office/HOffice130/BBin/Hwp.exe",
            pf / "Hancom/Hancom Office/HOffice120/BBin/Hwp.exe",
            pf86 / "Hancom/Hancom Office/HOffice120/BBin/Hwp.exe",
            pf86 / "Hancom/HOffice 2022/HOffice120/BBin/Hwp.exe",
            pf86 / "Hancom/Office 2020/HOffice110/Bin/Hwp.exe",
            pf / "Hancom/HOffice 2022/HOffice120/BBin/Hwp.exe",
        ]
        found = _find_hwp_exe()
        if found is not None:
            return found

    for c in candidates:
        if c.is_file():
            return c
    return None


def _find_hwp_exe() -> Path | None:
    """Best-effort Hancom Hangul (Hwp.exe) when standard paths differ by version."""
    roots: list[Path] = []
    pf, pf86 = _program_files()
    roots.extend([pf / "Hancom", pf86 / "Hancom"])
    for base in roots:
        if not base.is_dir():
            continue
        try:
            for p in base.rglob("Hwp.exe"):
                if p.is_file():
                    return p.resolve()
        except OSError:
            continue
    return None


def infer_launch_alias(title_substring: str) -> str | None:
    t = (title_substring or "").strip().lower()
    if not t:
        return None
    for needle, alias in _TITLE_LAUNCH_HINTS:
        if needle in t:
            return alias
    return None


def _launch_spec_for_target(
    target: dict[str, Any],
    *,
    presets: dict[str, Any],
) -> tuple[str | None, list[str]]:
    title = str(target.get("title_substring") or "").strip()
    launch = target.get("launch")
    args = list(target.get("launch_args") or [])

    if launch:
        return str(launch).strip(), [str(a) for a in args]

    preset = presets.get(title) if title else None
    if isinstance(preset, dict):
        pl = preset.get("launch")
        if pl:
            pa = preset.get("launch_args") or []
            return str(pl).strip(), [str(a) for a in pa]

    alias = infer_launch_alias(title)
    if alias:
        return alias, args

    return None, args


def wait_for_window(
    title_substring: str,
    *,
    timeout_ms: int,
    poll_ms: int = 250,
) -> bool:
    deadline = time.monotonic() + max(0.5, timeout_ms / 1000.0)
    while time.monotonic() < deadline:
        if window_exists_by_title_substring(title_substring):
            return True
        time.sleep(max(0.05, poll_ms / 1000.0))
    return window_exists_by_title_substring(title_substring)


def ensure_app_for_target(
    target: dict[str, Any],
    *,
    presets: dict[str, Any],
    launch_wait_ms: int,
    skip_if_window_open: bool,
    dry_run: bool,
) -> bool:
    """
    Launch the app for ``target`` if needed. Returns True when a matching window exists
    (already open or appeared after launch).
    """
    title = str(target.get("title_substring") or "").strip()
    if not title:
        return False

    if skip_if_window_open and window_exists_by_title_substring(title):
        print(f"[launch] window already open for {title!r}")
        return True

    spec, args = _launch_spec_for_target(target, presets=presets)
    if not spec:
        print(f"[launch] no launch config for {title!r} (set launch or auto_launch.presets)")
        return window_exists_by_title_substring(title)

    exe = resolve_executable(spec)
    if exe is None and Path(spec).is_file():
        exe = Path(spec)
    if exe is None:
        print(f"[launch] could not resolve executable for {spec!r} ({title!r})")
        return False

    argv = [str(exe), *args]
    if dry_run:
        print(f"[dry-run] would launch: {' '.join(argv)}")
        return window_exists_by_title_substring(title)

    try:
        subprocess.Popen(
            argv,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        print(f"[launch] started {exe.name} for {title!r}")
    except Exception as e:
        print(f"[launch] failed for {title!r}: {e}")
        return False

    if wait_for_window(title, timeout_ms=launch_wait_ms):
        return True

    print(f"[launch] timed out waiting for window {title!r} ({launch_wait_ms} ms)")
    return False
