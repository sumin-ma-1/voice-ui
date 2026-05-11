import ctypes
import tkinter as tk

import customtkinter as ctk

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


class TextInputGUI:

    def __init__(self):
        self.root = ctk.CTk()
        self.result = None
        self._setup()
        self.root.withdraw()

    def _setup(self):
        self.root.title("Voice Agent")
        self.root.attributes("-topmost", True)
        self.root.resizable(False, False)
        self.root.overrideredirect(True)
        self.root.configure(fg_color="#1e1e1e")

        sw = self.root.winfo_screenwidth()
        self.root.geometry(f"520x52+{sw // 2 - 260}+16")

        border = ctk.CTkFrame(self.root, fg_color="#303030", corner_radius=10)
        border.pack(fill="both", expand=True)

        inner = ctk.CTkFrame(border, fg_color="#1e1e1e", corner_radius=8)
        inner.pack(fill="both", expand=True, padx=2, pady=2)

        ctk.CTkLabel(
            inner,
            text="⟩",
            font=ctk.CTkFont("Segoe UI", 18, weight="bold"),
            text_color="#3a7ebf",
            width=34,
        ).pack(side="left", padx=(10, 0))

        self.entry = ctk.CTkEntry(
            inner,
            fg_color="#1e1e1e",
            text_color="#ffffff",
            border_width=0,
            font=ctk.CTkFont("Consolas", 15),
            placeholder_text="Type your command...",
            placeholder_text_color="#505050",
        )
        self.entry.pack(side="left", fill="x", expand=True, padx=(4, 10))

        self.entry.bind("<Return>", self._on_enter)
        self.entry.bind("<Escape>", self._on_escape)

        # First layout pass while still mapped (before withdraw) so the first deiconify paints on Windows.
        self.root.update_idletasks()

    def _on_enter(self, event):
        text = self.entry.get().strip().lower()
        self.entry.delete(0, tk.END)
        self.result = text if text else None
        self.root.withdraw()
        self.root.quit()

    def _on_escape(self, event):
        self.entry.delete(0, tk.END)
        self.result = None
        self.root.withdraw()
        self.root.quit()

    def _grab_focus(self):
        hwnd = self.root.winfo_id()
        ctypes.windll.user32.SetForegroundWindow(hwnd)
        self.root.lift()
        self.root.focus_force()
        self.entry.focus_set()

    def get_input(self, delay_ms=300):
        self.result = None
        self.root.deiconify()
        self.root.lift()
        try:
            self.root.attributes("-topmost", True)
        except tk.TclError:
            pass
        # Force map + paint before mainloop; otherwise the bar can stay invisible until the next event (e.g. Ctrl+C).
        self.root.update_idletasks()
        self.root.update()
        self.root.after(delay_ms, self._grab_focus)
        self.root.mainloop()
        return self.result
