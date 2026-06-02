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

import json
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


HISTORY_VISITED_FILENAME = "history_visited_domains.txt"


def history_visited_domains_path(dataset_root: Path) -> Path:
    return dataset_root / HISTORY_VISITED_FILENAME


def load_history_visited_domains(path: Path) -> set[str]:
    """Domains recorded when a history URL was opened (even if no probes were logged)."""
    if not path.is_file():
        return set()
    out: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        d = line.split("#", 1)[0].strip().lower()
        if d:
            out.add(d)
    return out


def record_history_visited_domain(path: Path, domain: str) -> None:
    """Append ``domain`` to the visited manifest (idempotent per line)."""
    dom = (domain or "").strip().lower()
    if not dom:
        return
    existing = load_history_visited_domains(path)
    if dom in existing:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(dom + "\n")


def load_history_skip_domains(
    *,
    events_path: Path,
    visited_path: Path,
    extra: set[str] | None = None,
) -> set[str]:
    """Union of domains to skip: logged probes + visited manifest + optional extras."""
    out = domains_from_dataset_events(events_path)
    out |= load_history_visited_domains(visited_path)
    for d in extra or set():
        s = str(d).strip().lower()
        if s:
            out.add(s)
    return out


def domains_from_dataset_events(events_path: Path) -> set[str]:
    """
    Domains already collected via browser_history (``meta.domain`` on ok probes).

    Used to skip revisiting the same site when extending history collection.
    """
    if not events_path.is_file():
        return set()
    seen: set[str] = set()
    for line in events_path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s:
            continue
        try:
            o = json.loads(s)
        except Exception:
            continue
        meta = o.get("meta") or {}
        if meta.get("collect_mode") != "browser_history":
            continue
        if not o.get("ok"):
            continue
        dom = str(meta.get("domain") or "").strip().lower()
        if dom:
            seen.add(dom)
            continue
        url = str(meta.get("source_url") or "").strip()
        if url:
            d = _domain(url)
            if d:
                seen.add(d)
    return seen


def read_recent_history(
    browser: str,
    *,
    limit: int | None = 0,
    days: int | None = 30,
    domain_allowlist: list[str] | None = None,
    domain_blocklist: list[str] | None = None,
    one_per_domain: bool = True,
    skip_domains: set[str] | None = None,
) -> list[HistoryEntry]:
    """
    Load recent history rows for one browser.

    ``one_per_domain``: keep only the newest URL per registrable domain so a
    browsing session visits many distinct sites instead of 30 GitHub tabs.

    ``skip_domains``: do not return entries whose domain was already collected
    (e.g. from ``domains_from_dataset_events``).

    ``limit``: max entries to return; ``0`` or negative = no cap (still filtered by
    ``days``, allow/block lists, and ``one_per_domain``).
    """
    cap = limit is not None and int(limit) > 0
    cap_n = int(limit) if cap else 0
    skip = {d.strip().lower() for d in (skip_domains or set()) if d and str(d).strip()}
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
        if cap:
            sql_limit = max(cap_n * 8, cap_n)
            if skip:
                sql_limit = max(sql_limit, cap_n + len(skip) * 4, 200)
            rows = conn.execute(
                """
                SELECT url, title, visit_count, last_visit_time
                FROM urls
                WHERE hidden = 0
                ORDER BY last_visit_time DESC
                LIMIT ?
                """,
                (sql_limit,),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT url, title, visit_count, last_visit_time
                FROM urls
                WHERE hidden = 0
                ORDER BY last_visit_time DESC
                """
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
        if skip and dom in skip:
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
        if cap and len(out) >= cap_n:
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


def wait_for_page(
    browser: str,
    *,
    page_load_ms: int,
    expected_title_hint: str = "",
    maximize: bool = False,
    maximize_settle_ms: int = 400,
) -> str:
    """Sleep for load, try to focus browser window, return foreground title."""
    from automation.window_focus import activate_window_by_title_substring

    time.sleep(max(0.2, page_load_ms / 1000.0))
    sub = browser_window_substring(browser)
    activate_window_by_title_substring(sub, maximize=maximize)
    if maximize:
        time.sleep(max(0.05, maximize_settle_ms / 1000.0))
    time.sleep(0.25)
    title = foreground_window_title()
    if not title and expected_title_hint:
        return expected_title_hint
    return title
