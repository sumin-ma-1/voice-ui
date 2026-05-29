"""
Discover user-installed Windows applications for auto-collect whitelists.

Sources (best-effort):
- Registry ``Uninstall`` keys (DisplayName, DisplayIcon, InstallLocation)
- Start Menu ``*.lnk`` shortcuts (user + common)

Output rows are suitable for ``configs/collect_targets.json`` ``targets`` entries:
``title_substring``, ``launch`` (exe path), ``enabled``, optional ``browser_ui`` skipped.
"""

from __future__ import annotations

import os
import re
import subprocess
import winreg
from pathlib import Path
from typing import Any

# Skip redistributables / noise (case-insensitive substring match on display name).
DEFAULT_NAME_BLOCKLIST: tuple[str, ...] = (
    "microsoft visual c++",
    "microsoft .net",
    "windows sdk",
    "update for",
    "redistributable",
    "runtime",
    "webview2",
    "language pack",
    "proofing tools",
    "click-to-run",
    "office 16 click-to-run",
    "vs_",
    "kb",
    "hotfix",
    "security update",
    "documentation",
    "help pack",
    "font pack",
    "intel(r)",
    "nvidia",
    "realtek",
    "driver",
    "support assistant",
)

# Prefer GUI apps; these often expose UIA toolbars.
_PREFERRED_NAME_HINTS: tuple[str, ...] = (
    "figma",
    "slack",
    "discord",
    "notion",
    "spotify",
    "zoom",
    "teams",
    "vscode",
    "visual studio code",
    "code",
    "word",
    "excel",
    "powerpoint",
    "outlook",
    "photoshop",
    "illustrator",
    "premiere",
    "blender",
    "obs",
    "steam",
    "postman",
    "docker",
    "github desktop",
    "chrome",
    "edge",
    "firefox",
    "notepad++",
    "sublime",
    "pycharm",
    "intellij",
    "android studio",
    "unity",
    "unreal",
)


def _truthy_path(p: str | None) -> Path | None:
    if not p:
        return None
    raw = p.strip().strip('"')
    if not raw:
        return None
    # DisplayIcon often "path,0"
    if "," in raw:
        raw = raw.split(",", 1)[0].strip().strip('"')
    path = Path(raw)
    if path.suffix.lower() in (".exe", ".bat", ".cmd") and path.is_file():
        if "installer" in path.name.lower() and "setup" in path.name.lower():
            return None
        if path.name.lower().endswith("uninstall.exe"):
            return None
        return path
    if path.is_dir():
        for name in ("launcher.exe", "app.exe"):
            c = path / name
            if c.is_file():
                return c
    return None


def _blocked(display_name: str, blocklist: tuple[str, ...]) -> bool:
    n = display_name.lower()
    return any(b in n for b in blocklist)


def _score_app(display_name: str) -> int:
    n = display_name.lower()
    score = 0
    for i, hint in enumerate(_PREFERRED_NAME_HINTS):
        if hint in n:
            score += 100 - min(i, 50)
    if len(display_name) < 40:
        score += 5
    return score


def _read_uninstall_key(hkey: int, subkey: str) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        with winreg.OpenKey(hkey, subkey) as k:
            for field in ("DisplayName", "DisplayIcon", "InstallLocation", "QuietDisplayName"):
                try:
                    val, _ = winreg.QueryValueEx(k, field)
                    if val:
                        out[field] = str(val).strip()
                except OSError:
                    pass
    except OSError:
        pass
    return out


def _iter_registry_uninstall() -> list[dict[str, Any]]:
    roots = (
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    )
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()

    for hkey, root in roots:
        try:
            with winreg.OpenKey(hkey, root) as uninstall:
                n = winreg.QueryInfoKey(uninstall)[0]
                for i in range(n):
                    try:
                        sub = winreg.EnumKey(uninstall, i)
                    except OSError:
                        continue
                    meta = _read_uninstall_key(hkey, f"{root}\\{sub}")
                    name = meta.get("DisplayName") or meta.get("QuietDisplayName") or ""
                    if not name or name.lower() in seen:
                        continue
                    exe = _truthy_path(meta.get("DisplayIcon"))
                    if exe is None:
                        exe = _truthy_path(meta.get("InstallLocation"))
                    if exe is None:
                        continue
                    seen.add(name.lower())
                    rows.append(
                        {
                            "display_name": name,
                            "launch": str(exe),
                            "source": "registry",
                        }
                    )
        except OSError:
            continue
    return rows


def _iter_start_menu_lnks() -> list[dict[str, Any]]:
    """Resolve ``*.lnk`` via PowerShell (Windows-only)."""
    roots = [
        Path(os.environ.get("ProgramData", r"C:\ProgramData"))
        / "Microsoft/Windows/Start Menu/Programs",
        Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
    ]
    lnks: list[Path] = []
    for root in roots:
        if root.is_dir():
            lnks.extend(root.rglob("*.lnk"))

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for lnk in lnks:
        title = lnk.stem.strip()
        if not title or title.lower() in seen:
            continue
        if _blocked(title, DEFAULT_NAME_BLOCKLIST):
            continue
        exe = _resolve_lnk_target(lnk)
        if exe is None:
            continue
        seen.add(title.lower())
        rows.append(
            {
                "display_name": title,
                "launch": str(exe),
                "source": "start_menu",
            }
        )
    return rows


def _resolve_lnk_target(lnk: Path) -> Path | None:
    try:
        ps = (
            f"(New-Object -ComObject WScript.Shell).CreateShortcut('{lnk}').TargetPath"
        )
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True,
            text=True,
            timeout=8,
        )
        target = (r.stdout or "").strip().strip('"')
        if not target:
            return None
        p = Path(target)
        return p if p.is_file() else None
    except Exception:
        return None


def discover_installed_apps(
    *,
    blocklist: tuple[str, ...] | None = None,
    max_apps: int = 30,
    include_start_menu: bool = True,
) -> list[dict[str, Any]]:
    """
    Return discovered apps sorted by relevance score (higher first).

    Each item: ``display_name``, ``launch``, ``source``, ``title_substring``,
    ``target`` (ready-to-merge collect_targets entry).
    """
    block = blocklist or DEFAULT_NAME_BLOCKLIST
    merged: dict[str, dict[str, Any]] = {}

    for row in _iter_registry_uninstall():
        name = row["display_name"]
        if _blocked(name, block):
            continue
        key = name.lower()
        if key not in merged or merged[key]["source"] != "registry":
            merged[key] = row

    if include_start_menu:
        for row in _iter_start_menu_lnks():
            key = row["display_name"].lower()
            if key in merged:
                continue
            if _blocked(row["display_name"], block):
                continue
            merged[key] = row

    scored: list[tuple[int, dict[str, Any]]] = []
    for row in merged.values():
        name = row["display_name"]
        title = _title_substring_from_name(name)
        target = {
            "enabled": True,
            "title_substring": title,
            "launch": row["launch"],
            "fallback_queries": ["menu", "settings", "search"],
            "randomize_query": True,
            "discovered": True,
            "discovered_from": row["source"],
            "discovered_display_name": name,
        }
        item = {**row, "title_substring": title, "target": target}
        scored.append((_score_app(name), item))

    scored.sort(key=lambda x: (-x[0], x[1]["display_name"].lower()))
    out = [item for _s, item in scored[: max(1, max_apps)]]
    return out


def _title_substring_from_name(display_name: str) -> str:
    """
    Window title heuristic: use full DisplayName when short, else distinctive tail.

    Examples: ``Figma`` → ``Figma``; ``Microsoft Edge`` → ``Edge`` is NOT applied here
    (keep full name for fewer false matches unless known alias).
    """
    name = display_name.strip()
    # Drop version suffix " 1.2.3"
    name = re.sub(r"\s+v?\d+(\.\d+){1,3}\s*$", "", name, flags=re.I).strip()
    if len(name) <= 48:
        return name
    # Long names: use part before first dash/paren
    for sep in (" - ", " – ", " (", " ["):
        if sep in name:
            head = name.split(sep, 1)[0].strip()
            if len(head) >= 3:
                return head
    return name[:48].strip()


def discover_targets(
    *,
    blocklist: tuple[str, ...] | None = None,
    max_apps: int = 30,
) -> list[dict[str, Any]]:
    """Return ``targets``-shaped dicts only."""
    return [row["target"] for row in discover_installed_apps(blocklist=blocklist, max_apps=max_apps)]
