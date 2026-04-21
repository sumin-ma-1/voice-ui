class OfficeDispatcher:

    OFFICE_ACTIONS = {

        "ppt_open",
        "ppt_new",
        "ppt_slide",
        "ppt_slideshow",

        "word_open",
        "word_write",

        "excel_open",
        "excel_write"
    }

    def is_office_command(self, command):

        return command["action"] in self.OFFICE_ACTIONS