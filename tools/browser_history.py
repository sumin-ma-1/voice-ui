"""
Read Chromium browser history (Chrome / Edge) and open URLs for dataset collection.

Chromium stores history in a SQLite DB under the user profile. The DB is often
locked while the browser runs, so we copy it to a temp file before querying.

Privacy / safety
----------------
- Reads **local** history only (no upload).
- Callers should filter domains and run in a test VM when possible.
- Opening a URL loads the page in the user's browser; collection scripts should
  not perform clicks beyond navigation.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

try:
    import win32gui
except ImportError:  # pragma: no cover
    win32gui = None  # type: ignore


@dataclass(frozen=True)
class HistoryEntry:
    url: str
    title: str
    visit_count: int
    last_visit_time: int
    browser: str
    domain: str


def _local_app_data() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", ""))


def history_db_path(browser: str) -> Path | None:
    """Return default History SQLite path for ``chrome`` or ``edge``."""
    b = browser.strip().lower()
    root = _local_app_data()
    if b == "chrome":
        p = root / "Google/Chrome/User Data/Default/History"
    elif b == "edge":
        p = root / "Microsoft/Edge/User Data/Default/History"
    else:
        return None
    return p if p.is_file() else None


def browser_executable(browser: str) -> Path | None:
    """Best-effort path to chrome.exe / msedge.exe on Windows."""
    b = browser.strip().lower()
    candidates: list[Path] = []
    pf = os.environ.get("PROGRAMFILES", r"C:\Program Files")
    pf86 = os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")
    local = _local_app_data()

    if b == "chrome":
        candidates = [
            Path(pf) / "Google/Chrome/Application/chrome.exe",
            Path(pf86) / "Google/Chrome/Application/chrome.exe",
            local / "Google/Chrome/Application/chrome.exe",
        ]
    elif b == "edge":
        candidates = [
            Path(pf) / "Microsoft/Edge/Application/msedge.exe",
            Path(pf86) / "Microsoft/Edge/Application/msedge.exe",
        ]
    for c in candidates:
        if c.is_file():
            return c
    return None


def _domain(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        return host
    except Exception:
        return ""


def _is_http_url(url: str) -> bool:
    u = (url or "").strip().lower()
    return u.startswith("http://") or u.startswith("https://")


def _blocked_url(url: str, *, blocklist: set[str]) -> bool:
    u = url.lower()
    d = _domain(url)
    for token in blocklist:
        t = token.strip().lower()
        if not t:
            continue
        if t in u or t in d:
            return True
    return False


def read_recent_history(
    browser: str,
    *,
    limit: int = 30,
    days: int | None = 30,
    domain_allowlist: list[str] | None = None,
    domain_blocklist: list[str] | None = None,
    one_per_domain: bool = True,
) -> list[HistoryEntry]:
    """
    Load recent history rows for one browser.

    ``one_per_domain``: keep only the newest URL per registrable domain so a
    browsing session visits many distinct sites instead of 30 GitHub tabs.
    """
    db = history_db_path(browser)
    if db is None:
        print(f"[history] no History DB for {browser!r} (browser closed or not installed?)")
        return []

    allow = {x.strip().lower() for x in (domain_allowlist or []) if x.strip()}
    block = {x.strip().lower() for x in (domain_blocklist or []) if x.strip()}
    # Always skip obvious internal / auth-heavy patterns unless explicitly allowed.
    block.update(
        {
            "accounts.google.com",
            "login",
            "signin",
            "auth",
            "chrome://",
            "edge://",
        }
    )

    tmp = Path(tempfile.mkstemp(suffix=".sqlite")[1])
    try:
        shutil.copy2(db, tmp)
        conn = sqlite3.connect(str(tmp))
        conn.row_factory = sqlite3.Row
        # last_visit_time: microseconds since 1601-01-01 UTC (Chromium)
        min_time = 0
        if days is not None and days > 0:
            # Approx cutoff: now - days (Windows FILETIME-ish micros is messy; use relative ordering)
            # We fetch extra rows then filter in Python using monotonic ranking when days set.
            pass
        rows = conn.execute(
            """
            SELECT url, title, visit_count, last_visit_time
            FROM urls
            WHERE hidden = 0
            ORDER BY last_visit_time DESC
            LIMIT ?
            """,
            (max(limit * 8, limit),),
        ).fetchall()
        conn.close()
    except Exception as e:
        print(f"[history] failed to read {browser} DB: {e}")
        return []
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass

    out: list[HistoryEntry] = []
    seen_domains: set[str] = set()
    newest_time = max((int(r["last_visit_time"] or 0) for r in rows), default=0)
    # Chromium time unit ~ microseconds; 1 day ≈ 86400 * 1e6
    day_us = int(86400 * 1_000_000)
    min_time_cutoff = newest_time - (days * day_us) if days and newest_time else 0

    for r in rows:
        url = str(r["url"] or "").strip()
        if not _is_http_url(url):
            continue
        if _blocked_url(url, blocklist=block):
            continue
        dom = _domain(url)
        if allow and dom not in allow and not any(a in dom for a in allow):
            continue
        lvt = int(r["last_visit_time"] or 0)
        if days and lvt < min_time_cutoff:
            continue
        if one_per_domain and dom in seen_domains:
            continue
        seen_domains.add(dom)
        out.append(
            HistoryEntry(
                url=url,
                title=str(r["title"] or "").strip(),
                visit_count=int(r["visit_count"] or 0),
                last_visit_time=lvt,
                browser=browser.strip().lower(),
                domain=dom,
            )
        )
        if len(out) >= limit:
            break

    return out


def open_url_in_browser(browser: str, url: str) -> bool:
    """Open ``url`` in a new browser tab/window. Returns True on success."""
    exe = browser_executable(browser)
    if exe is None:
        print(f"[history] executable not found for {browser!r}")
        return False
    try:
        subprocess.Popen(
            [str(exe), url],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except Exception as e:
        print(f"[history] failed to open {url!r} in {browser}: {e}")
        return False


def foreground_window_title() -> str:
    if win32gui is None:
        return ""
    try:
        return win32gui.GetWindowText(win32gui.GetForegroundWindow()) or ""
    except Exception:
        return ""


def browser_window_substring(browser: str) -> str:
    b = browser.strip().lower()
    if b == "chrome":
        return "Chrome"
    if b == "edge":
        return "Edge"
    return browser


def wait_for_page(browser: str, *, page_load_ms: int, expected_title_hint: str = "") -> str:
    """Sleep for load, try to focus browser window, return foreground title."""
    from automation.window_focus import activate_window_by_title_substring

    time.sleep(max(0.2, page_load_ms / 1000.0))
    sub = browser_window_substring(browser)
    activate_window_by_title_substring(sub)
    time.sleep(0.25)
    title = foreground_window_title()
    if not title and expected_title_hint:
        return expected_title_hint
    return title
