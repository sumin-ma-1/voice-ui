# automation/action_space.py
# Single registry of parsed ``action`` strings: routing (grounding vs direct), COM, and post-exec delays.
#
# Parsers (``speech.command_parser``, ``speech.office_command_parser``) emit these names;
# ``main`` / demos branch on DIRECT vs grounded; ``OfficeDispatcher`` / ``OfficeController`` handle OFFICE;
# ``automation.executor.execute`` performs pyautogui for DIRECT ∪ GROUNDED ∪ ``switch_tab``.

from __future__ import annotations

# --- Parsed sentinel ---
UNKNOWN_ACTION = "unknown"

# --- UI grounding: semantic target required (mouse move + action) ---
GROUNDED_ACTIONS: frozenset[str] = frozenset(
    {
        "left_click",
        "right_click",
        "double_click",
        "hover",
    }
)

# --- Skip perception: run ``executor`` with ``element=None`` ---
DIRECT_ACTIONS: frozenset[str] = frozenset(
    {
        "type",
        "scroll",
        "enter",
        "esc",
        "tab",
        "backspace",
        "delete",
        "copy",
        "paste",
        "cut",
        "undo",
        "redo",
        "save",
        "select_all",
        "new_tab",
        "close_tab",
        "refresh",
        "press_key",
        "hotkey",
        # Implemented in ``executor``; parser may add phrases later.
        "switch_tab",
    }
)

# --- After grounded click: allow target app/dialog to appear ---
POST_GROUNDING_CLICK_DELAY_ACTIONS: frozenset[str] = frozenset(
    {
        "left_click",
        "double_click",
        "right_click",
    }
)

# --- Microsoft Office COM (``OfficeController``); not pyautogui / not UI-grounded here ---
OFFICE_ACTIONS: frozenset[str] = frozenset(
    {
        # PowerPoint
        "ppt_open",
        "ppt_open_file",
        "ppt_new",
        "ppt_slide",
        "ppt_slideshow",
        "ppt_end_slideshow",
        "ppt_next_slide",
        "ppt_prev_slide",
        "ppt_save",
        "ppt_save_as",
        "ppt_close",
        "ppt_quit",
        # Word
        "word_open",
        "word_open_file",
        "word_new",
        "word_write",
        "word_newline",
        "word_save",
        "word_save_as",
        "word_close",
        "word_quit",
        "word_bold",
        "word_italic",
        "word_underline",
        "word_font_size",
        "word_page_break",
        # Excel
        "excel_open",
        "excel_open_file",
        "excel_new",
        "excel_write",
        "excel_select_cell",
        "excel_formula",
        "excel_next_sheet",
        "excel_prev_sheet",
        "excel_autofit_columns",
        "excel_save",
        "excel_save_as",
        "excel_close",
        "excel_quit",
    }
)

# All actions handled by ``executor.execute`` (pyautogui path).
PYAUTOGUI_ACTIONS: frozenset[str] = DIRECT_ACTIONS | GROUNDED_ACTIONS


def requires_ui_grounding(action: str) -> bool:
    return action in GROUNDED_ACTIONS


def is_direct_action(action: str) -> bool:
    return action in DIRECT_ACTIONS


def is_office_action(action: str) -> bool:
    return action in OFFICE_ACTIONS
