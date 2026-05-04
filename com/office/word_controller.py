# com/office/word_controller.py
# Microsoft Word automation via COM (pywin32).

import os

import win32com.client

from com.office.foreground import bring_com_application_to_foreground


class WordController:
    def __init__(self):
        self.app = None
        self.doc = None

    def _connect(self):
        if self.app is None:
            self.app = win32com.client.Dispatch("Word.Application")
            self.app.Visible = True
        bring_com_application_to_foreground(self.app)

    def _ensure_doc(self):
        self._connect()
        if self.doc is None:
            self.doc = self.app.Documents.Add()
        return self.doc

    def open(self):
        self._connect()
        self.doc = self.app.Documents.Add()
        bring_com_application_to_foreground(self.app)
        print("Word opened (new document)")

    def open_file(self, path: str):
        self._connect()
        path = os.path.abspath(os.path.expanduser(path.strip().strip('"').strip("'")))
        self.doc = self.app.Documents.Open(path)
        bring_com_application_to_foreground(self.app)
        print("Opened Word document:", path)

    def new_document(self):
        self._connect()
        self.doc = self.app.Documents.Add()
        bring_com_application_to_foreground(self.app)
        print("New Word document")

    def write(self, text: str):
        self._ensure_doc()
        self.app.Selection.TypeText(text)
        print("Text written")

    def newline(self):
        self._ensure_doc()
        self.app.Selection.TypeParagraph()

    def save(self, path: str | None = None):
        self._ensure_doc()
        if path:
            p = os.path.abspath(os.path.expanduser(path.strip().strip('"').strip("'")))
            self.doc.SaveAs(FileName=p)
            print("Document saved as:", p)
        else:
            self.doc.Save()
            print("Document saved (in-place)")

    def save_as(self, path: str):
        self.save(path)

    def close_document(self, save_changes: bool = False):
        self._connect()
        if self.doc is None:
            return
        self.doc.Close(SaveChanges=save_changes)
        self.doc = None
        print("Word document closed")

    def quit_app(self, save_changes: bool = False):
        self._connect()
        self.app.Quit(SaveChanges=save_changes)
        self.app = None
        self.doc = None
        print("Word quit")

    def bold(self):
        self._ensure_doc()
        self.app.Selection.Font.Bold = True

    def italic(self):
        self._ensure_doc()
        self.app.Selection.Font.Italic = True

    def underline(self):
        self._ensure_doc()
        self.app.Selection.Font.Underline = 1  # wdUnderlineSingle

    def font_size(self, size: float):
        self._ensure_doc()
        self.app.Selection.Font.Size = float(size)

    def page_break(self):
        self._ensure_doc()
        self.app.Selection.InsertBreak(7)  # wdPageBreak
