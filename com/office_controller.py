# com/office_controller.py
# Routes parsed Office actions to Word / Excel / PowerPoint COM controllers.

import traceback

from com.office.ppt_controller import PowerPointController
from com.office.word_controller import WordController
from com.office.excel_controller import ExcelController


class OfficeController:
    def __init__(self):
        self.ppt = PowerPointController()
        self.word = WordController()
        self.excel = ExcelController()

    def execute(self, command):
        action = command.get("action")
        try:
            return self._dispatch(action, command)
        except Exception:
            traceback.print_exc()
            return False

    def _dispatch(self, action, command):
        # ---- PowerPoint ----
        if action == "ppt_open":
            self.ppt.open()
        elif action == "ppt_open_file":
            self.ppt.open_file(command["path"])
        elif action == "ppt_new":
            self.ppt.new_presentation()
        elif action == "ppt_slide":
            self.ppt.add_slide(
                command.get("title", "Title"),
                command.get("content", ""),
            )
        elif action == "ppt_slideshow":
            self.ppt.start_slideshow()
        elif action == "ppt_end_slideshow":
            self.ppt.end_slideshow()
        elif action == "ppt_next_slide":
            self.ppt.next_slide()
        elif action == "ppt_prev_slide":
            self.ppt.prev_slide()
        elif action == "ppt_save":
            self.ppt.save(command.get("path"))
        elif action == "ppt_save_as":
            self.ppt.save_as(command["path"])
        elif action == "ppt_close":
            self.ppt.close_presentation()
        elif action == "ppt_quit":
            self.ppt.quit_app()

        # ---- Word ----
        elif action == "word_open":
            self.word.open()
        elif action == "word_open_file":
            self.word.open_file(command["path"])
        elif action == "word_new":
            self.word.new_document()
        elif action == "word_write":
            self.word.write(command.get("text", ""))
        elif action == "word_newline":
            self.word.newline()
        elif action == "word_save":
            self.word.save(command.get("path"))
        elif action == "word_save_as":
            self.word.save_as(command["path"])
        elif action == "word_close":
            self.word.close_document(save_changes=command.get("save_changes", False))
        elif action == "word_quit":
            self.word.quit_app(save_changes=command.get("save_changes", False))
        elif action == "word_bold":
            self.word.bold()
        elif action == "word_italic":
            self.word.italic()
        elif action == "word_underline":
            self.word.underline()
        elif action == "word_font_size":
            self.word.font_size(float(command["size"]))
        elif action == "word_page_break":
            self.word.page_break()

        # ---- Excel ----
        elif action == "excel_open":
            self.excel.open()
        elif action == "excel_open_file":
            self.excel.open_file(command["path"])
        elif action == "excel_new":
            self.excel.new_workbook()
        elif action == "excel_write":
            self.excel.write_cell(
                int(command["row"]),
                int(command["col"]),
                command.get("value", ""),
            )
        elif action == "excel_select_cell":
            self.excel.select_cell(int(command["row"]), int(command["col"]))
        elif action == "excel_formula":
            self.excel.set_formula(
                int(command["row"]),
                int(command["col"]),
                str(command["formula"]),
            )
        elif action == "excel_next_sheet":
            self.excel.next_sheet()
        elif action == "excel_prev_sheet":
            self.excel.prev_sheet()
        elif action == "excel_autofit_columns":
            self.excel.autofit_columns()
        elif action == "excel_save":
            self.excel.save(command.get("path"))
        elif action == "excel_save_as":
            self.excel.save_as(command["path"])
        elif action == "excel_close":
            self.excel.close_workbook(save_changes=command.get("save_changes", False))
        elif action == "excel_quit":
            self.excel.quit_app()

        else:
            return False

        return True
