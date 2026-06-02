# speech/target_text.py
"""
Refine UI / UIA strings into short *spoken targets* for CLIP (train + runtime).

Goal: training ``text`` and runtime ``command["query"]`` should match what the user
says after the action verb (``click close``, not the raw accessibility sentence).

This is NOT a Material-icon vocabulary map. Site names and app-specific labels are
kept when they are plausible spoken targets (e.g. history favicon titles).
"""

from __future__ import annotations

import re

# Whole-string replacements (match on collapsed text; keys are lowercase).
_EXACT: dict[str, str] = {
    "이 항목을 목록에 고정": "pin",
    "기타 옵션": "more options",
    "싫어요": "dislike",
    "대화 시작": "chat",
    "자세히 보기": "more",
    "copilot 열기": "copilot",
    "앱 시작 관리자": "startup apps",
    "검색": "search",
    "설정": "settings",
    "닫기": "close",
    "최소화": "minimize",
    "최대화": "maximize",
    "새로 고침": "refresh",
    "맑음": "weather",
    "더 많은 관심사": "more interests",
    "add this page to favorites": "favorites",
    "customize quick access toolbar": "toolbar",
    "to get missing image descriptions, open the context menu.": "context menu",
    "settings and more": "settings",
}

# (pattern, replacement) applied case-insensitively on Latin portions.
_SUBSTRING: list[tuple[str, str]] = [
    ("search tabs", "search tabs"),
    ("close tab", "close tab"),
    ("new tab", "new tab"),
    ("school profile", "profile"),
]

_RE_SHORTCUT = re.compile(
    r"\s*[\(\[][^\)\]]*(?:ctrl|alt|shift|win\+|⌘)[^\)\]]*[\)\]]",
    re.IGNORECASE,
)
_RE_CLICK_FOLLOW_KO = re.compile(r"^클릭하여\s+.+\s+팔로우$", re.IGNORECASE)
_RE_OPEN_PROJECT = re.compile(r"^open project options for\b", re.IGNORECASE)
_RE_OPEN_CONVO = re.compile(r"^open conversation options for\b", re.IGNORECASE)
_RE_ADD_FAVORITES = re.compile(r"add this page to favorites", re.IGNORECASE)


def _collapse_ws(s: str) -> str:
    return " ".join(str(s or "").split())


def _strip_shortcut_hints(s: str) -> str:
    t = _RE_SHORTCUT.sub(" ", s)
    return _collapse_ws(t)


def _lower_ascii_preserve_korean(s: str) -> str:
    """Lowercase for matching; Hangul unchanged under .lower()."""
    return _collapse_ws(s).lower()


def refine_clip_query_text(
    text: str,
    *,
    target_name: str = "",
    control_type: str = "",
) -> str:
    """
    Map UIA/accessibility labels → short spoken target for CLIP.

    ``control_type`` is reserved for future heuristics (unused today).
    Falls back to ``target_name`` when ``text`` is empty.
    """
    _ = control_type
    raw = _collapse_ws(text)
    if not raw:
        raw = _collapse_ws(target_name)
    if not raw:
        return ""

    t = _strip_shortcut_hints(raw)
    key = _lower_ascii_preserve_korean(t)

    if key in _EXACT:
        return _EXACT[key]

    if _RE_CLICK_FOLLOW_KO.match(t):
        return "follow"

    if _RE_OPEN_PROJECT.search(t):
        return "project options"

    if _RE_OPEN_CONVO.search(t):
        return "conversation options"

    if _RE_ADD_FAVORITES.search(t):
        return "favorites"

    for needle, repl in _SUBSTRING:
        if needle in key:
            return repl

    # Long English a11y sentences → first few meaningful tokens (cap length).
    if len(key) > 48 and not re.search(r"[\uac00-\ud7a3]", t):
        words = key.split()
        if len(words) > 6:
            key = " ".join(words[:6])

    return key


def refine_parsed_voice_query(text: str) -> str:
    """
    Runtime: user already spoke a target (post-``parse_command``).

    Light pass only — strip shortcuts/noise, do not rewrite site names.
    """
    t = _strip_shortcut_hints(_collapse_ws(text))
    if not t:
        return ""
    return _lower_ascii_preserve_korean(t)
