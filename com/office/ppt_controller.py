# com/office/ppt_controller.py
# PowerPoint automation via COM (pywin32).

import os

import win32com.client

from com.office.foreground import bring_com_application_to_foreground


class PowerPointController:
    def __init__(self):
        self.app = None
        self.presentation = None

    def _connect(self):
        if self.app is None:
            self.app = win32com.client.Dispatch("PowerPoint.Application")
            self.app.Visible = True
        bring_com_application_to_foreground(self.app)

    def _active_presentation(self):
        self._connect()
        if self.app.Presentations.Count == 0:
            self.presentation = self.app.Presentations.Add()
        else:
            self.presentation = self.app.ActivePresentation
        bring_com_application_to_foreground(self.app)
        return self.presentation

    def open(self):
        """Launch PowerPoint and ensure there is an active presentation."""
        self._active_presentation()
        print("PowerPoint ready")

    def open_file(self, path: str):
        """Open an existing .pptx / .ppt from disk."""
        self._connect()
        path = os.path.abspath(os.path.expanduser(path.strip().strip('"').strip("'")))
        self.presentation = self.app.Presentations.Open(path, WithWindow=True)
        bring_com_application_to_foreground(self.app)
        print("Opened presentation:", path)

    def new_presentation(self):
        self._connect()
        self.presentation = self.app.Presentations.Add()
        bring_com_application_to_foreground(self.app)
        print("New presentation created")

    def add_slide(self, title: str, content: str):
        pres = self._active_presentation()
        slide_layout = 1  # ppLayoutTitle
        slide = pres.Slides.Add(pres.Slides.Count + 1, slide_layout)
        slide.Shapes.Title.TextFrame.TextRange.Text = title
        slide.Shapes.Placeholders(2).TextFrame.TextRange.Text = content
        print("Slide added")

    def save(self, path: str | None = None):
        pres = self._active_presentation()
        if path:
            p = os.path.abspath(os.path.expanduser(path.strip().strip('"').strip("'")))
            pres.SaveAs(p)
            print("Presentation saved:", p)
        else:
            pres.Save()
            print("Presentation saved (in-place)")

    def save_as(self, path: str):
        self.save(path)

    def start_slideshow(self):
        pres = self._active_presentation()
        pres.SlideShowSettings.Run()
        print("Slideshow started")

    def end_slideshow(self):
        self._connect()
        try:
            wnd = self.app.SlideShowWindows(1)
            wnd.View.Exit()
            print("Slideshow ended")
        except Exception as e:
            print("No active slideshow or could not exit:", e)
            raise

    def next_slide(self):
        """Next slide in edit view, or during slideshow if running."""
        self._connect()
        try:
            if self.app.SlideShowWindows.Count > 0:
                self.app.SlideShowWindows(1).View.Next()
            else:
                win = self.app.ActiveWindow
                if win.ViewType == 1:  # ppViewSlide
                    cur = win.View.Slide.SlideIndex
                    pres = self._active_presentation()
                    if cur < pres.Slides.Count:
                        win.View.GotoSlide(cur + 1)
            print("Advanced to next slide")
        except Exception as e:
            print("next_slide:", e)
            raise

    def prev_slide(self):
        self._connect()
        try:
            if self.app.SlideShowWindows.Count > 0:
                self.app.SlideShowWindows(1).View.Previous()
            else:
                win = self.app.ActiveWindow
                if win.ViewType == 1:
                    cur = win.View.Slide.SlideIndex
                    if cur > 1:
                        win.View.GotoSlide(cur - 1)
            print("Went to previous slide")
        except Exception as e:
            print("prev_slide:", e)
            raise

    def close_presentation(self):
        """Close the active presentation without quitting PowerPoint."""
        self._connect()
        if self.app.Presentations.Count == 0:
            return
        pres = self.app.ActivePresentation
        pres.Close()
        self.presentation = None
        print("Presentation closed")

    def quit_app(self):
        """Quit PowerPoint application."""
        self._connect()
        self.app.Quit()
        self.app = None
        self.presentation = None
        print("PowerPoint quit")
