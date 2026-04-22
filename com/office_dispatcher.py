# com/office_dispatcher.py
# Central list of actions handled by OfficeController (COM), not by UI grounding.


class OfficeDispatcher:
    """Every ``action`` string here must be implemented in ``OfficeController.execute``."""

    OFFICE_ACTIONS = frozenset(
        {
            # --- PowerPoint ---
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
            # --- Word ---
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
            # --- Excel ---
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

    def is_office_command(self, command):
        return command.get("action") in self.OFFICE_ACTIONS
