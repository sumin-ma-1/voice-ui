from __future__ import annotations

import math
import tkinter as tk
from tkinter import messagebox
from typing import Callable, Literal

import customtkinter as ctk

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

LedState = Literal["idle", "listening", "processing"]

_LED_BASE = {
    "idle":       (0x55, 0x55, 0x55),
    "listening":  (0xff, 0x22, 0x33),
    "processing": (0x22, 0x88, 0xff),
}


class FloatingVoiceUI:

    def __init__(
        self,
        *,
        title: str = "Voice UI",
        on_close: Callable[[], None] | None = None,
    ) -> None:
        self.on_close = on_close
        self._led_state: LedState = "idle"
        self._pulse_phase = 0
        self._pulse_job: str | None = None

        self.root = ctk.CTk()
        self.root.title(title)
        self.root.attributes("-topmost", True)
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.configure(fg_color="#181818")

        sw = self.root.winfo_screenwidth()
        self.root.geometry(f"580x108+{sw // 2 - 290}+12")

        # ── Row 1: LED · guide · checkbox ─────────────────────────────
        row1 = ctk.CTkFrame(self.root, fg_color="transparent")
        row1.pack(fill="x", padx=14, pady=(10, 4))

        self._led_canvas = tk.Canvas(
            row1, width=14, height=14, bg="#181818", highlightthickness=0
        )
        self._led_canvas.pack(side="left", pady=2)
        self._led_id = self._led_canvas.create_oval(
            1, 1, 13, 13, fill="#555555", outline=""
        )

        self._guide = ctk.CTkLabel(
            row1,
            text='Say: "Hey Voice UI" — then your command.',
            font=ctk.CTkFont("Segoe UI", 11),
            text_color="#b8b8b8",
            anchor="w",
        )
        self._guide.pack(side="left", fill="x", expand=True, padx=(10, 8))

        self._safe_var = tk.BooleanVar(value=False)
        self._safe_cb = ctk.CTkCheckBox(
            row1,
            text="Confirm before run",
            variable=self._safe_var,
            font=ctk.CTkFont("Segoe UI", 10),
            text_color="#909090",
            fg_color="#2a6abf",
            hover_color="#3a7acf",
            checkmark_color="#ffffff",
            border_color="#505050",
            width=18,
            height=18,
        )
        self._safe_cb.pack(side="right")

        # ── Separator ──────────────────────────────────────────────────
        ctk.CTkFrame(self.root, height=1, fg_color="#2e2e2e").pack(
            fill="x", padx=14, pady=0
        )

        # ── Row 2: transcript ──────────────────────────────────────────
        self._transcript = ctk.CTkLabel(
            self.root,
            text="",
            font=ctk.CTkFont("Consolas", 10),
            text_color="#5aadee",
            anchor="w",
            wraplength=544,
            justify="left",
        )
        self._transcript.pack(fill="x", padx=16, pady=(5, 8))

        self.set_led("idle")

    def _on_close(self) -> None:
        if self.on_close:
            self.on_close()
        try:
            self.root.destroy()
        except Exception:
            pass

    def run(self) -> None:
        self.root.mainloop()

    # ── LED ────────────────────────────────────────────────────────────

    def set_led(self, state: LedState) -> None:
        self._led_state = state
        if self._pulse_job:
            self.root.after_cancel(self._pulse_job)
            self._pulse_job = None
        self._pulse_phase = 0
        if state in ("listening", "processing"):
            self._animate_pulse()
        else:
            r, g, b = _LED_BASE[state]
            self._led_canvas.itemconfig(self._led_id, fill=f"#{r:02x}{g:02x}{b:02x}")

    def _animate_pulse(self) -> None:
        self._pulse_phase = (self._pulse_phase + 1) % 30
        t = (math.sin(self._pulse_phase * math.pi / 15) + 1) / 2  # 0.0 – 1.0
        br, bg, bb = _LED_BASE[self._led_state]
        r = int(br * 0.45 + br * 0.55 * t)
        g = int(bg * 0.45 + bg * 0.55 * t)
        b = int(bb * 0.45 + bb * 0.55 * t)
        self._led_canvas.itemconfig(self._led_id, fill=f"#{r:02x}{g:02x}{b:02x}")
        self._pulse_job = self.root.after(40, self._animate_pulse)

    # ── Public API ─────────────────────────────────────────────────────

    def set_pipeline_guide(self, text: str) -> None:
        self._guide.configure(text=text[:256])

    def set_transcript_line(self, text: str) -> None:
        if not text:
            return
        self._transcript.configure(text=text[:400])

    def clear_transcript(self) -> None:
        self._transcript.configure(text="")

    def confirm_run(self, title: str, message: str) -> bool:
        return bool(messagebox.askyesno(title, message, parent=self.root))

    def get_confirm_before_run(self) -> bool:
        return bool(self._safe_var.get())
