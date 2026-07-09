import ctypes
import os
import tkinter as tk
from pathlib import Path

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
        self.root.geometry(f"560x72+{sw // 2 - 280}+16")

        border = ctk.CTkFrame(self.root, fg_color="#303030", corner_radius=10)
        border.pack(fill="both", expand=True)

        inner = ctk.CTkFrame(border, fg_color="#1e1e1e", corner_radius=8)
        inner.pack(fill="both", expand=True, padx=2, pady=2)

        input_row = ctk.CTkFrame(inner, fg_color="#1e1e1e")
        input_row.pack(fill="x", expand=True)

        ctk.CTkLabel(
            input_row,
            text="⟩",
            font=ctk.CTkFont("Segoe UI", 18, weight="bold"),
            text_color="#3a7ebf",
            width=34,
        ).pack(side="left", padx=(10, 0))

        self.entry = ctk.CTkEntry(
            input_row,
            fg_color="#1e1e1e",
            text_color="#ffffff",
            border_width=0,
            font=ctk.CTkFont("Consolas", 15),
            placeholder_text="Type your command...",
            placeholder_text_color="#505050",
        )
        self.entry.pack(side="left", fill="x", expand=True, padx=(4, 10))

        self.status = ctk.CTkLabel(
            inner,
            text="",
            font=ctk.CTkFont("Segoe UI", 10),
            text_color="#707070",
            anchor="w",
        )
        self.status.pack(fill="x", padx=(12, 10), pady=(0, 4))

        self.entry.bind("<Return>", self._on_enter)
        self.entry.bind("<Escape>", self._on_escape)

        # First layout pass while still mapped (before withdraw) so the first deiconify paints on Windows.
        self.root.update_idletasks()

    def _study_status_text(self) -> str:
        if os.getenv("VOICE_UI_STUDY", "").strip().lower() not in {"1", "true", "yes", "on"}:
            return ""
        pid = (os.getenv("VOICE_UI_STUDY_USER") or "?").strip()
        ds = Path(os.getenv("VOICE_UI_DATASET_DIR", "dataset"))
        n = 0
        ev = ds / "events.jsonl"
        if ev.is_file():
            n = sum(1 for line in ev.read_text(encoding="utf-8").splitlines() if line.strip())
        ratings = ""
        if os.getenv("VOICE_UI_STUDY_RATINGS", "").strip().lower() in {"1", "true", "yes", "on"}:
            ratings = " | ratings on"
        return f"study {pid} | logged {n}{ratings}"

    def _refresh_status(self) -> None:
        text = self._study_status_text()
        self.status.configure(text=text)

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
        self._refresh_status()
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
