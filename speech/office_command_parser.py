# speech/office_command_parser.py
# Natural-language → structured Office COM commands (parsed before UI / mouse commands).

from __future__ import annotations

import re


def _strip_quotes(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        return s[1:-1]
    return s


def _path_after_prefix(raw: str, prefix: str) -> str | None:
    """Slice path from ``raw`` after a case-insensitive ASCII ``prefix`` (prefix length used)."""
    r = raw.strip()
    pl = prefix.lower()
    if not r.lower().startswith(pl):
        return None
    return _strip_quotes(r[len(prefix) :].strip())


def _extract_title_content_slide(text: str) -> dict:
    title = "Title"
    m = re.search(r"title\s+(.+?)\s+content\s+", text, re.I)
    if m:
        title = m.group(1).strip()
    else:
        m2 = re.search(r"title\s+(.+?)(?:\s+content\b|$)", text, re.I)
        if m2:
            title = m2.group(1).strip()
    content = ""
    mc = re.search(r"content\s+(.+)$", text, re.I)
    if mc:
        content = mc.group(1).strip()
    return {"title": title, "content": content}


def _extract_excel_cell(text: str) -> tuple[int, int, str] | None:
    m = re.search(r"cell\s+(\d+)\s+(\d+)\s+(.+)", text, re.I)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), m.group(3).strip()


def _extract_word_write_text(text: str) -> str:
    m = re.search(r"\bwrite\s+(.+)$", text, re.I)
    if m:
        return m.group(1).strip()
    return ""


def parse_office_command(text: str) -> dict | None:
    """
    If ``text`` matches an Office automation phrase, return a command dict; else ``None``.

    Checked before generic ``open`` / ``click`` parsing in ``command_parser.parse_command``.
    """
    raw = text.strip()
    t = raw.lower()

    # --- Excel formula ---
    mf = re.match(r"^excel\s+formula\s+(\d+)\s+(\d+)\s+(.+)$", t)
    if mf:
        return {
            "action": "excel_formula",
            "row": int(mf.group(1)),
            "col": int(mf.group(2)),
            "formula": mf.group(3).strip(),
        }

    # --- Excel write cell ---
    if "write cell" in t:
        cell = _extract_excel_cell(t)
        if cell:
            r, c, v = cell
            return {"action": "excel_write", "row": r, "col": c, "value": v}

    # --- Save As (path required) ---
    for phrase, action in (
        ("word save as ", "word_save_as"),
        ("save word as ", "word_save_as"),
        ("excel save as ", "excel_save_as"),
        ("save excel as ", "excel_save_as"),
        ("ppt save as ", "ppt_save_as"),
        ("powerpoint save as ", "ppt_save_as"),
        ("save ppt as ", "ppt_save_as"),
        ("save powerpoint as ", "ppt_save_as"),
    ):
        path = _path_after_prefix(raw, phrase)
        if path:
            return {"action": action, "path": path}

    # --- Open file on disk ---
    m = re.match(r"^(?:word\s+open\s+file|open\s+word\s+file)\s+(.+)$", raw, re.I)
    if m:
        return {"action": "word_open_file", "path": m.group(1).strip()}
    m = re.match(r"^(?:excel\s+open\s+file|open\s+excel\s+file)\s+(.+)$", raw, re.I)
    if m:
        return {"action": "excel_open_file", "path": m.group(1).strip()}
    m = re.match(
        r"^((?:ppt|powerpoint)\s+open\s+file|open\s+(?:ppt|powerpoint)\s+file)\s+(.+)$",
        raw,
        re.I,
    )
    if m:
        return {"action": "ppt_open_file", "path": m.group(2).strip()}

    # --- PowerPoint (before loose ``open``); use word boundaries for ``ppt`` ---
    if "powerpoint" in t or re.search(r"\bppt\b", t):
        if "end slideshow" in t or "stop slideshow" in t or "exit slideshow" in t:
            return {"action": "ppt_end_slideshow"}
        if "next slide" in t:
            return {"action": "ppt_next_slide"}
        if "previous slide" in t or "prev slide" in t:
            return {"action": "ppt_prev_slide"}
        if "new presentation" in t:
            return {"action": "ppt_new"}
        if "add slide" in t:
            tc = _extract_title_content_slide(raw)
            return {"action": "ppt_slide", "title": tc["title"], "content": tc["content"]}
        if "start slideshow" in t or ("slideshow" in t and "start" in t):
            return {"action": "ppt_slideshow"}
        if re.search(r"\b(quit|exit)\s+powerpoint\b", t) or t.strip() in ("ppt quit", "powerpoint quit"):
            return {"action": "ppt_quit"}
        if "close presentation" in t or re.search(r"\bclose\s+ppt\b", t):
            return {"action": "ppt_close"}
        if re.match(r"^(ppt save|powerpoint save|save ppt|save powerpoint)$", t.strip()):
            return {"action": "ppt_save", "path": None}
        if ("powerpoint" in t or re.search(r"\bppt\b", t)) and "open" in t and "file" not in t:
            return {"action": "ppt_open"}

    # --- Excel --- (``\bexcel\b`` avoids matching substrings like in "excellent")
    if re.search(r"\bexcel\b", t) or t.startswith("open excel"):
        if "autofit" in t and "column" in t:
            return {"action": "excel_autofit_columns"}
        if "next sheet" in t:
            return {"action": "excel_next_sheet"}
        if "previous sheet" in t or "prev sheet" in t:
            return {"action": "excel_prev_sheet"}
        if "new workbook" in t or re.match(r"^new excel$", t.strip()):
            return {"action": "excel_new"}
        ms = re.search(r"select\s+cell\s+(\d+)\s+(\d+)", t)
        if ms:
            return {
                "action": "excel_select_cell",
                "row": int(ms.group(1)),
                "col": int(ms.group(2)),
            }
        if re.search(r"\b(quit|exit)\s+excel\b", t) or t.strip() == "excel quit":
            return {"action": "excel_quit"}
        if "close workbook" in t or re.search(r"\bclose\s+excel\b", t):
            save_changes = "save changes" in t or "and save" in t
            return {"action": "excel_close", "save_changes": save_changes}
        if re.match(r"^(excel save|save excel)$", t.strip()):
            return {"action": "excel_save", "path": None}
        if "open" in t and "file" not in t:
            return {"action": "excel_open"}

    # --- Word --- (``\bword\b`` avoids "keyboard", etc.)
    if re.search(r"\bword\b", t) or t.startswith("open word"):
        if "page break" in t:
            return {"action": "word_page_break"}
        mfs = re.search(r"font\s+size\s+(\d+(?:\.\d+)?)", t)
        if mfs:
            return {"action": "word_font_size", "size": mfs.group(1)}
        if re.search(r"\bword\s+bold\b|\bbold\s+in\s+word\b", t):
            return {"action": "word_bold"}
        if re.search(r"\bword\s+italic\b|\bitalic\s+in\s+word\b", t):
            return {"action": "word_italic"}
        if "underline" in t and "word" in t:
            return {"action": "word_underline"}
        if "new document" in t or re.match(r"^new word$", t.strip()):
            return {"action": "word_new"}
        if "newline" in t or "new line" in t or "new paragraph" in t:
            return {"action": "word_newline"}
        if re.search(r"\b(quit|exit)\s+word\b", t) or t.strip() == "word quit":
            return {"action": "word_quit", "save_changes": False}
        if "close document" in t or re.search(r"\bclose\s+word\b", t):
            return {"action": "word_close", "save_changes": False}
        if re.match(r"^(word save|save word)$", t.strip()):
            return {"action": "word_save", "path": None}
        if "write" in t:
            return {"action": "word_write", "text": _extract_word_write_text(raw)}
        if "open" in t and "file" not in t:
            return {"action": "word_open"}

    return None
