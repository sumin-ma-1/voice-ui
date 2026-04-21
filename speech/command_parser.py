# speech/command_parser.py
# - No target extraction
# - No context extraction
# - The whole command becomes the query

import re

def extract_title(text):

    match = re.search(r"title (.+?) content", text)

    if match:
        return match.group(1)

    match = re.search(r"title (.+)", text)

    if match:
        return match.group(1)

    return "Title"

def extract_content(text):

    match = re.search(r"content (.+)", text)

    if match:
        return match.group(1)

    return ""

def extract_text(text):

    match = re.search(r"write (.+)", text)

    if match:
        return match.group(1)

    return ""

def extract_excel_cell(text):

    match = re.search(
        r"cell (\d+) (\d+) (.+)",
        text
    )

    if match:

        return (
            int(match.group(1)),
            int(match.group(2)),
            match.group(3)
        )

    return 1, 1, ""

def parse_command(text):

    text = text.lower().strip()

    # ---- TYPE ----
    if text.startswith("type"):
        return {
            "action": "type",
            "text": text.replace("type", "").strip()
        }
    
    # ---- SCROLL ----
    if text.startswith("scroll up"):
        return {"action": "scroll", "direction": "up", "amount": 500}

    if text.startswith("scroll down"):
        return {"action": "scroll", "direction": "down", "amount": 500}

    if text.startswith("scroll left"):
        return {"action": "scroll", "direction": "left", "amount": 500}

    if text.startswith("scroll right"):
        return {"action": "scroll", "direction": "right", "amount": 500}
    
    # ---- POWERPOINT ----
    # if ("powerpoint", "ppt") in text and "open" in text:
    if ("powerpoint" in text or "ppt" in text) and "open" in text:
        return {"action": "ppt_open"}

    if "new presentation" in text:
        return {"action": "ppt_new"}

    if "add slide" in text:
        return {
            "action": "ppt_slide",
            "title": extract_title(text),
            "content": extract_content(text)
        }

    if "start slideshow" in text:
        return {"action": "ppt_slideshow"}

    # ---- WORD ----
    if "word" in text and "open" in text:
        return {"action": "word_open"}

    if "write" in text and "word" in text:
        return {
            "action": "word_write",
            "text": extract_text(text)
        }

    # ---- EXCEL ----
    if "excel" in text and "open" in text:
        return {"action": "excel_open"}

    if "write cell" in text:

        row, col, value = extract_excel_cell(text)

        return {
            "action": "excel_write",
            "row": row,
            "col": col,
            "value": value
        }
    
    # ---- MOUSE ACTIONS ----
    if text.startswith("right click"):
        return {"action": "right_click", "query": text.replace("right click", "").strip()}

    if text.startswith("double click") or text.startswith("open"):
        query = (
            text.replace("double click", "", 1)
                .replace("open", "", 1)
                .strip()
        )

        return {"action": "double_click", "query": query}

    if text.startswith("hover"):
        return {"action": "hover", "query": text.replace("hover", "").strip()}

    if text.startswith("click"):
        return {"action": "left_click", "query": text.replace("click", "").strip()}

    # ---- KEYBOARD ----

    if text.startswith("enter"):
        return {"action": "enter"}

    if text.startswith("escape"):
        return {"action": "esc"}

    if text.startswith("tab"):
        return {"action": "tab"}
    
    if text.startswith("backspace"):
        return {"action": "backspace"}

    if text.startswith("delete"):
        return {"action": "delete"}

    if text.startswith("press"):
        key = text.replace("press", "").strip().rstrip(".")
        return {
            "action": "press_key",
            "key": key
        }

    if text.startswith("hotkey"):

        keys_text = text.replace("hotkey", "").strip()

        # split keys by space
        keys = keys_text.split()

        return {
            "action": "hotkey",
            "keys": keys
        }
    
    # ---- SELECTION ----
    
    if text.startswith("copy"):
        return {"action": "copy"}

    if text.startswith("paste"):
        return {"action": "paste"}

    if text.startswith("cut"):
        return {"action": "cut"}

    if text.startswith("save"):
        return {"action": "save"}

    if text.startswith("undo"):
        return {"action": "undo"}

    if text.startswith("redo"):
        return {"action": "redo"}

    if text.startswith("select all"):
        return {"action": "select_all"}
    
    # ---- BROWSER ----

    if text.startswith("new tab"):
        return {"action": "new_tab"}

    if text.startswith("close tab"):
        return {"action": "close_tab"}

    if text.startswith("refresh"):
        return {"action": "refresh"}

    # default fallback
    return {
        "action": "unknown",
        "query": text
    }