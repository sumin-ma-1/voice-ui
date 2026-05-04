# speech/command_parser_rules.py
# Table-driven parsing for generic (non-Office) commands used by ``command_parser.parse_command``.
#
# * Longer multi-word phrases are matched before shorter prefixes (stable sort by phrase length).
# * Phrase matches require a word boundary after the phrase (no ``openword`` → ``open``).
# * Single-key shortcuts require the whole line to be that token (avoids ``tab`` in ``tablet``).

from __future__ import annotations

import re
from collections.abc import Callable

from automation.action_space import UNKNOWN_ACTION


def _collapse_whitespace(line: str) -> str:
    """Single spaces between tokens so ``scroll  up`` / ``hotkey control s`` match phrase rules."""
    return re.sub(r"\s+", " ", line.strip())


def consume_leading_phrase(raw: str, phrase_lower: str) -> str | None:
    """
    If ``raw`` starts with ``phrase_lower`` (ASCII case-insensitive) and the next character
    is end-of-string or whitespace, return the remainder; else ``None``.
    """
    s = raw.strip()
    t = s.lower()
    pl = phrase_lower
    if not t.startswith(pl):
        return None
    n = len(pl)
    if len(s) > n and s[n] not in (" ", "\t"):
        return None
    return s[n:].lstrip()


def _double_click(rem: str) -> dict:
    return {"action": "double_click", "query": rem.strip()}


def _build_phrase_table() -> list[tuple[str, Callable[[str], dict]]]:
    """Longest phrase first so ``right click`` wins over ``right``, ``select all`` over ``select``, etc."""
    rows: list[tuple[str, Callable[[str], dict]]] = [
        ("select all", lambda _r: {"action": "select_all"}),
        ("double click", _double_click),
        ("right click", lambda r: {"action": "right_click", "query": r.strip()}),
        ("scroll left", lambda _r: {"action": "scroll", "direction": "left", "amount": 500}),
        ("scroll right", lambda _r: {"action": "scroll", "direction": "right", "amount": 500}),
        ("scroll down", lambda _r: {"action": "scroll", "direction": "down", "amount": 500}),
        ("scroll up", lambda _r: {"action": "scroll", "direction": "up", "amount": 500}),
        ("close tab", lambda _r: {"action": "close_tab"}),
        ("new tab", lambda _r: {"action": "new_tab"}),
        ("hover", lambda r: {"action": "hover", "query": r.strip()}),
        ("click", lambda r: {"action": "left_click", "query": r.strip()}),
        ("type", lambda r: {"action": "type", "text": r}),
        ("open", _double_click),
    ]
    rows.sort(key=lambda row: -len(row[0]))
    return rows


PHRASE_TABLE: list[tuple[str, Callable[[str], dict]]] = _build_phrase_table()

# Whole-line shortcuts (lowercased stripped line must match exactly).
EXACT_LINE_ACTIONS: dict[str, str] = {
    "enter": "enter",
    "escape": "esc",
    "tab": "tab",
    "backspace": "backspace",
    "delete": "delete",
    "copy": "copy",
    "paste": "paste",
    "cut": "cut",
    "save": "save",
    "undo": "undo",
    "redo": "redo",
    "refresh": "refresh",
}


def parse_focus_command(raw: str) -> dict | None:
    """
    ``focus <target>`` — must run before Office parsing so ``focus excel`` is not COM ``excel_open``.

    Returns a command dict (including ``UNKNOWN_ACTION``) if the line is clearly a ``focus`` attempt;
    returns ``None`` if the line does not start with the word ``focus``.
    """
    s = _collapse_whitespace(raw)
    t = s.lower()
    if not t.startswith("focus"):
        return None
    rem = consume_leading_phrase(s, "focus")
    if rem is None or not rem:
        return {"action": UNKNOWN_ACTION, "query": raw.strip()}
    return {"action": "focus", "query": rem}


def apply_phrase_rules(raw: str) -> dict | None:
    for phrase, builder in PHRASE_TABLE:
        rem = consume_leading_phrase(raw, phrase)
        if rem is not None:
            return builder(rem)
    return None


def apply_first_token_commands(raw: str) -> dict | None:
    """``press``, ``hotkey`` (``type`` / ``click`` / … live in the phrase table)."""
    parts = raw.strip().split(None, 1)
    if not parts:
        return None
    head = parts[0].lower()
    rest = parts[1].strip() if len(parts) > 1 else ""

    if head == "press":
        if not rest:
            return {"action": UNKNOWN_ACTION, "query": raw.strip()}
        return {"action": "press_key", "key": rest.rstrip(".")}

    if head == "hotkey":
        if not rest:
            return {"action": UNKNOWN_ACTION, "query": raw.strip()}
        return {"action": "hotkey", "keys": rest.split()}

    return None


def apply_exact_line_command(raw: str) -> dict | None:
    key = raw.strip().lower()
    action = EXACT_LINE_ACTIONS.get(key)
    if action is None:
        return None
    return {"action": action}


def parse_generic_command(raw: str) -> dict:
    """
    Parse a line that is **not** an Office phrase (caller runs ``parse_office_command`` first).

    Order: phrase table (length-prioritised) → ``press`` / ``hotkey`` → exact single-line commands.
    """
    s = _collapse_whitespace(raw)
    hit = apply_phrase_rules(s)
    if hit is not None:
        return hit

    hit = apply_first_token_commands(s)
    if hit is not None:
        return hit

    hit = apply_exact_line_command(s)
    if hit is not None:
        return hit

    return {"action": UNKNOWN_ACTION, "query": raw.strip()}
