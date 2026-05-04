# com/office_controller.py
# Routes parsed Office actions to Word / Excel / PowerPoint COM controllers.

from __future__ import annotations

import traceback
from collections.abc import Callable

from automation.action_space import OFFICE_ACTIONS

from com.office.ppt_controller import PowerPointController
from com.office.word_controller import WordController
from com.office.excel_controller import ExcelController


class OfficeController:
    def __init__(self):
        self.ppt = PowerPointController()
        self.word = WordController()
        self.excel = ExcelController()
        self._handlers: dict[str, Callable[[dict], None]] = self._build_handlers()
        self._assert_handlers_match_registry()

    def _assert_handlers_match_registry(self) -> None:
        registered = frozenset(self._handlers)
        if registered != OFFICE_ACTIONS:
            raise RuntimeError(
                "Office handler keys must match automation.action_space.OFFICE_ACTIONS: "
                f"missing={sorted(OFFICE_ACTIONS - registered)!r} "
                f"extra={sorted(registered - OFFICE_ACTIONS)!r}"
            )

    def _build_handlers(self) -> dict[str, Callable[[dict], None]]:
        p, w, e = self.ppt, self.word, self.excel

        return {
            # --- PowerPoint ---
            "ppt_open": lambda c: p.open(),
            "ppt_open_file": lambda c: p.open_file(c["path"]),
            "ppt_new": lambda c: p.new_presentation(),
            "ppt_slide": lambda c: p.add_slide(
                c.get("title", "Title"),
                c.get("content", ""),
            ),
            "ppt_slideshow": lambda c: p.start_slideshow(),
            "ppt_end_slideshow": lambda c: p.end_slideshow(),
            "ppt_next_slide": lambda c: p.next_slide(),
            "ppt_prev_slide": lambda c: p.prev_slide(),
            "ppt_save": lambda c: p.save(c.get("path")),
            "ppt_save_as": lambda c: p.save_as(c["path"]),
            "ppt_close": lambda c: p.close_presentation(),
            "ppt_quit": lambda c: p.quit_app(),
            # --- Word ---
            "word_open": lambda c: w.open(),
            "word_open_file": lambda c: w.open_file(c["path"]),
            "word_new": lambda c: w.new_document(),
            "word_write": lambda c: w.write(c.get("text", "")),
            "word_newline": lambda c: w.newline(),
            "word_save": lambda c: w.save(c.get("path")),
            "word_save_as": lambda c: w.save_as(c["path"]),
            "word_close": lambda c: w.close_document(
                save_changes=c.get("save_changes", False)
            ),
            "word_quit": lambda c: w.quit_app(save_changes=c.get("save_changes", False)),
            "word_bold": lambda c: w.bold(),
            "word_italic": lambda c: w.italic(),
            "word_underline": lambda c: w.underline(),
            "word_font_size": lambda c: w.font_size(float(c["size"])),
            "word_page_break": lambda c: w.page_break(),
            # --- Excel ---
            "excel_open": lambda c: e.open(),
            "excel_open_file": lambda c: e.open_file(c["path"]),
            "excel_new": lambda c: e.new_workbook(),
            "excel_write": lambda c: e.write_cell(
                int(c["row"]),
                int(c["col"]),
                c.get("value", ""),
            ),
            "excel_select_cell": lambda c: e.select_cell(
                int(c["row"]),
                int(c["col"]),
            ),
            "excel_formula": lambda c: e.set_formula(
                int(c["row"]),
                int(c["col"]),
                str(c["formula"]),
            ),
            "excel_next_sheet": lambda c: e.next_sheet(),
            "excel_prev_sheet": lambda c: e.prev_sheet(),
            "excel_autofit_columns": lambda c: e.autofit_columns(),
            "excel_save": lambda c: e.save(c.get("path")),
            "excel_save_as": lambda c: e.save_as(c["path"]),
            "excel_close": lambda c: e.close_workbook(
                save_changes=c.get("save_changes", False)
            ),
            "excel_quit": lambda c: e.quit_app(),
        }

    def execute(self, command):
        action = command.get("action")
        try:
            return self._dispatch(action, command)
        except Exception:
            traceback.print_exc()
            return False

    def _dispatch(self, action, command):
        handler = self._handlers.get(action)
        if handler is None:
            return False
        handler(command)
        return True
