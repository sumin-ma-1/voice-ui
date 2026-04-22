# com/office/excel_controller.py
# Microsoft Excel automation via COM (pywin32).

import os

import win32com.client


class ExcelController:
    def __init__(self):
        self.app = None
        self.workbook = None
        self.sheet = None

    def _connect(self):
        if self.app is None:
            self.app = win32com.client.Dispatch("Excel.Application")
            self.app.Visible = True

    def _sync_active_sheet(self):
        if self.workbook is not None:
            self.sheet = self.workbook.ActiveSheet

    def _ensure_workbook(self):
        self._connect()
        if self.workbook is None:
            self.workbook = self.app.Workbooks.Add()
            self._sync_active_sheet()
        return self.workbook

    def open(self):
        self._ensure_workbook()
        print("Excel opened (new workbook)")

    def open_file(self, path: str):
        self._connect()
        path = os.path.abspath(os.path.expanduser(path.strip().strip('"').strip("'")))
        self.workbook = self.app.Workbooks.Open(path)
        self._sync_active_sheet()
        print("Opened Excel workbook:", path)

    def new_workbook(self):
        self._connect()
        self.workbook = self.app.Workbooks.Add()
        self._sync_active_sheet()
        print("New Excel workbook")

    def write_cell(self, row: int, col: int, value):
        self._ensure_workbook()
        self.sheet.Cells(row, col).Value = value
        print(f"Cell ({row},{col}) = {value!r}")

    def select_cell(self, row: int, col: int):
        self._ensure_workbook()
        self.sheet.Cells(row, col).Select()
        print(f"Selected cell ({row},{col})")

    def set_formula(self, row: int, col: int, formula: str):
        self._ensure_workbook()
        self.sheet.Cells(row, col).Formula = formula
        print(f"Formula at ({row},{col}): {formula!r}")

    def next_sheet(self):
        self._ensure_workbook()
        idx = self.sheet.Index
        if idx < self.workbook.Sheets.Count:
            self.workbook.Sheets(idx + 1).Select()
            self._sync_active_sheet()
            print("Next sheet")
        else:
            print("Already on last sheet")

    def prev_sheet(self):
        self._ensure_workbook()
        idx = self.sheet.Index
        if idx > 1:
            self.workbook.Sheets(idx - 1).Select()
            self._sync_active_sheet()
            print("Previous sheet")
        else:
            print("Already on first sheet")

    def autofit_used_columns(self):
        self._ensure_workbook()
        used = self.sheet.UsedRange
        if used is not None:
            used.Columns.AutoFit()
        print("Autofit columns (used range)")

    def autofit_columns(self):
        """Alias for voice command ``excel autofit columns``."""
        self.autofit_used_columns()

    def save(self, path: str | None = None):
        self._ensure_workbook()
        if path:
            p = os.path.abspath(os.path.expanduser(path.strip().strip('"').strip("'")))
            self.workbook.SaveAs(p)
            print("Workbook saved as:", p)
        else:
            self.workbook.Save()
            print("Workbook saved (in-place)")

    def save_as(self, path: str):
        self.save(path)

    def close_workbook(self, save_changes: bool = False):
        self._connect()
        if self.workbook is None:
            return
        self.workbook.Close(SaveChanges=save_changes)
        self.workbook = None
        self.sheet = None
        print("Workbook closed")

    def quit_app(self):
        self._connect()
        self.app.Quit()
        self.app = None
        self.workbook = None
        self.sheet = None
        print("Excel quit")
