from com.office.ppt_controller import PowerPointController
from com.office.word_controller import WordController
from com.office.excel_controller import ExcelController

class OfficeController:

    def __init__(self):

        self.ppt = PowerPointController()
        self.word = WordController()
        self.excel = ExcelController()

    def execute(self, command):

        action = command["action"]

        # ---- PowerPoint ----

        if action == "ppt_open":
            self.ppt.open()

        elif action == "ppt_new":
            self.ppt.new_presentation()

        elif action == "ppt_slide":
            self.ppt.add_slide(
                command.get("title", "Title"),
                command.get("content", "")
            )

        elif action == "ppt_save":
            self.ppt.save(command["path"])

        elif action == "ppt_slideshow":
            self.ppt.start_slideshow()

        # ---- Word ----

        elif action == "word_open":
            self.word.open()

        elif action == "word_write":
            self.word.write(command["text"])

        elif action == "word_newline":
            self.word.newline()

        elif action == "word_save":
            self.word.save(command["path"])

        # ---- Excel ----

        elif action == "excel_open":
            self.excel.open()

        elif action == "excel_write":
            self.excel.write_cell(
                command["row"],
                command["col"],
                command["value"]
            )

        elif action == "excel_save":
            self.excel.save(command["path"])

        else:
            return False

        return True