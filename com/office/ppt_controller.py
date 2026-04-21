import win32com.client
import os

class PowerPointController:

    def __init__(self):
        self.app = None
        self.presentation = None

    def open(self):

        self.app = win32com.client.Dispatch("PowerPoint.Application")
        self.app.Visible = True

        if self.app.Presentations.Count == 0:
            self.presentation = self.app.Presentations.Add()
        else:
            self.presentation = self.app.ActivePresentation

        print("PowerPoint ready")

    def new_presentation(self):

        self.presentation = self.app.Presentations.Add()
        print("New presentation created")

    def add_slide(self, title, content):

        slide_layout = 1

        slide = self.presentation.Slides.Add(
            self.presentation.Slides.Count + 1,
            slide_layout
        )

        slide.Shapes.Title.TextFrame.TextRange.Text = title
        slide.Shapes.Placeholders(2).TextFrame.TextRange.Text = content

        print("Slide added")

    def save(self, path):

        self.presentation.SaveAs(path)
        print("Presentation saved:", path)

    def start_slideshow(self):

        self.presentation.SlideShowSettings.Run()
        print("Slideshow started")