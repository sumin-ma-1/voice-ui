import win32com.client

class ExcelController:

    def __init__(self):

        self.app = None
        self.workbook = None
        self.sheet = None

    def open(self):

        self.app = win32com.client.Dispatch("Excel.Application")
        self.app.Visible = True

        self.workbook = self.app.Workbooks.Add()
        self.sheet = self.workbook.ActiveSheet

        print("Excel opened")

    def write_cell(self, row, col, value):

        self.sheet.Cells(row, col).Value = value

        print(f"Cell {row},{col} = {value}")

    def save(self, path):

        self.workbook.SaveAs(path)
        print("Excel saved")