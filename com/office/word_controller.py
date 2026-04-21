import win32com.client

class WordController:

    def __init__(self):

        self.app = None
        self.doc = None

    def open(self):

        self.app = win32com.client.Dispatch("Word.Application")
        self.app.Visible = True

        self.doc = self.app.Documents.Add()

        print("Word opened")

    def write(self, text):

        self.app.Selection.TypeText(text)
        print("Text written")

    def newline(self):

        self.app.Selection.TypeParagraph()

    def save(self, path):

        self.doc.SaveAs(path)
        print("Document saved")