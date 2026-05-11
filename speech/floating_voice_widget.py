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

_CANVAS_BG = "#16161c"
_CX, _CY = 20, 20


def _clamp_u8(x: float) -> int:
    return max(0, min(255, int(x)))


def _breath_rgb(
    base_r: int,
    base_g: int,
    base_b: int,
    phase: float,
    *,
    freq: float,
    strength: float,
) -> str:
    """Oscillate brightness around ``(base_r,base_g,base_b)`` (strength 0 = flat, ~0.15 = subtle)."""
    t = (math.sin(phase * freq) + 1) / 2
    m = 1.0 - strength + strength * (0.55 + 0.45 * t)
    return f"#{_clamp_u8(base_r * m):02x}{_clamp_u8(base_g * m):02x}{_clamp_u8(base_b * m):02x}"


class FloatingVoiceUI:

    def __init__(
        self,
        *,
        title: str = "Voice UI",
        on_close: Callable[[], None] | None = None,
    ) -> None:
        self.on_close = on_close
        self._led_state: LedState = "idle"
        self._anim_phase = 0
        self._pulse_job: str | None = None
        self._processing_override = False
        self._mic_active = False

        self.root = ctk.CTk()
        self.root.title(title)
        self.root.attributes("-topmost", True)
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.configure(fg_color="#0c0c0e")

        sw = self.root.winfo_screenwidth()
        self.root.geometry(f"720x142+{sw // 2 - 360}+14")

        # Rounded card (window stays rectangular; inner panel reads as a soft “pill” bar)
        card = ctk.CTkFrame(
            self.root,
            fg_color="#16161c",
            corner_radius=20,
            border_width=1,
            border_color="#2a2a35",
        )
        card.pack(fill="both", expand=True, padx=6, pady=6)

        # ── Row 1: LED · guide · switch ───────────────────────────────
        row1 = ctk.CTkFrame(card, fg_color="transparent")
        row1.pack(fill="x", padx=14, pady=(12, 4))

        self._led_canvas = tk.Canvas(
            row1, width=40, height=40, bg=_CANVAS_BG, highlightthickness=0
        )
        self._led_canvas.pack(side="left", pady=0)

        self._guide = ctk.CTkLabel(
            row1,
            text='Say: "Hey Voice UI", then ask your command.',
            font=ctk.CTkFont("Segoe UI", 14),
            text_color="#c4c4d0",
            anchor="w",
        )
        self._guide.pack(side="left", fill="x", expand=True, padx=(10, 8))

        self._safe_var = tk.BooleanVar(value=False)
        self._safe_switch = ctk.CTkSwitch(
            row1,
            text="Confirm before run",
            variable=self._safe_var,
            onvalue=True,
            offvalue=False,
            width=200,
            height=28,
            switch_width=46,
            switch_height=22,
            corner_radius=11,
            border_width=0,
            font=ctk.CTkFont("Segoe UI", 12),
            text_color="#a8a8b8",
            fg_color="#3a3a48",
            progress_color="#2563c4",
            button_color="#f0f0f8",
            button_hover_color="#ffffff",
        )
        self._safe_switch.pack(side="right", padx=(4, 2))

        # ── Separator ──────────────────────────────────────────────────
        ctk.CTkFrame(card, height=1, fg_color="#2a2a34").pack(fill="x", padx=16, pady=2)

        # ── Row 2: transcript (inset panel) ───────────────────────────
        self._transcript_wrap = ctk.CTkFrame(
            card, fg_color="#1c1c24", corner_radius=12, border_width=0
        )
        self._transcript_wrap.pack(fill="x", padx=12, pady=(4, 12))

        self._transcript = ctk.CTkLabel(
            self._transcript_wrap,
            text="",
            font=ctk.CTkFont("Consolas", 13),
            text_color="#7ec8ff",
            anchor="w",
            wraplength=680,
            justify="left",
        )
        self._transcript.pack(fill="x", padx=12, pady=(8, 10))

        self._start_led_animation()

    def _on_close(self) -> None:
        if self._pulse_job:
            try:
                self.root.after_cancel(self._pulse_job)
            except Exception:
                pass
            self._pulse_job = None
        if self.on_close:
            self.on_close()
        try:
            self.root.destroy()
        except Exception:
            pass

    def run(self) -> None:
        self.root.mainloop()

    # ── LED (idle = slow breathe + orbit dots; listening = fast pulse + ring;
    #         processing = blue core + chasing dots) ───────────────────

    def _effective_led_mode(self) -> LedState:
        if self._processing_override:
            return "processing"
        if self._mic_active:
            return "listening"
        return "idle"

    def set_led(self, state: LedState) -> None:
        """``processing`` / ``idle`` from main thread; ``listening`` is driven by mic via :meth:`set_mic_active`."""
        self._led_state = state
        if state == "processing":
            self._processing_override = True
        elif state == "idle":
            self._processing_override = False
        # "listening" from set_led is treated as hint only if we add later; mic drives it.

    def set_mic_active(self, active: bool) -> None:
        """Voice thread: user is speaking into the mic (VAD). Ignored while ``processing`` override is on."""
        self._mic_active = bool(active)

    def _start_led_animation(self) -> None:
        if self._pulse_job:
            try:
                self.root.after_cancel(self._pulse_job)
            except Exception:
                pass
            self._pulse_job = None
        self._anim_phase = 0
        self._pulse_job = self.root.after(16, self._animation_tick)

    def _animation_tick(self) -> None:
        try:
            self._anim_phase = (self._anim_phase + 1) % 10_000
            mode = self._effective_led_mode()

            c = self._led_canvas
            c.delete("led")

            if mode == "idle":
                self._draw_idle_led(c, self._anim_phase)
                delay_ms = 95
            elif mode == "listening":
                self._draw_listening_led(c, self._anim_phase)
                delay_ms = 38
            else:
                self._draw_processing_led(c, self._anim_phase)
                delay_ms = 48

            self._update_ui_text_pulse(mode, float(self._anim_phase))

            self._pulse_job = self.root.after(delay_ms, self._animation_tick)
        except tk.TclError:
            self._pulse_job = None

    def _draw_idle_led(self, c: tk.Canvas, phase: int) -> None:
        # Slow breathing core
        t = (math.sin(phase * 0.045) + 1) / 2
        g0 = int(0x42 + 0x24 * t)
        b0 = min(255, g0 + 8)
        fill = f"#{g0:02x}{g0:02x}{b0:02x}"
        r = 7 + int(1.2 * math.sin(phase * 0.045))
        c.create_oval(
            _CX - r,
            _CY - r,
            _CX + r,
            _CY + r,
            fill=fill,
            outline="#3a3a48",
            width=1,
            tags="led",
        )
        # Soft orbit dots (twinkle)
        for i in range(3):
            ang = (phase * 0.04) + i * (2 * math.pi / 3)
            rad = 14.0
            x, y = _CX + rad * math.cos(ang), _CY + rad * math.sin(ang)
            dim = 0.35 + 0.35 * (math.sin(phase * 0.08 + i) + 1)
            sz = 2 if dim < 0.55 else 3
            g = int(0x55 * dim)
            col = f"#{g:02x}{g:02x}{int(g * 1.05):02x}"
            c.create_oval(
                x - sz,
                y - sz,
                x + sz,
                y + sz,
                fill=col,
                outline="",
                tags="led",
            )

    def _draw_listening_led(self, c: tk.Canvas, phase: int) -> None:
        t = (math.sin(phase * 0.38) + 1) / 2
        br, bg, bb = _LED_BASE["listening"]
        r = int(br * 0.35 + br * 0.65 * t)
        g = int(bg * 0.35 + bg * 0.65 * t)
        b = int(bb * 0.35 + bb * 0.65 * t)
        fill = f"#{r:02x}{g:02x}{b:02x}"
        r_main = 8
        c.create_oval(
            _CX - r_main,
            _CY - r_main,
            _CX + r_main,
            _CY + r_main,
            fill=fill,
            outline="#ff8888",
            width=2,
            tags="led",
        )
        # Pulsing outer ring
        ring = 13 + int(3 * math.sin(phase * 0.38))
        alpha_sim = 0.25 + 0.55 * t
        col = f"#{int(0xff * alpha_sim):02x}{int(0x55 * alpha_sim):02x}{int(0x55 * alpha_sim):02x}"
        c.create_oval(
            _CX - ring,
            _CY - ring,
            _CX + ring,
            _CY + ring,
            outline=col,
            width=2,
            tags="led",
        )

    def _draw_processing_led(self, c: tk.Canvas, phase: int) -> None:
        br, bg, bb = _LED_BASE["processing"]
        pulse = 0.65 + 0.35 * (math.sin(phase * 0.22) + 1) / 2
        r = int(br * pulse)
        g = int(bg * pulse)
        b = int(bb * pulse)
        fill = f"#{r:02x}{g:02x}{b:02x}"
        c.create_oval(
            _CX - 7,
            _CY - 7,
            _CX + 7,
            _CY + 7,
            fill=fill,
            outline="#88ccff",
            width=1,
            tags="led",
        )
        # Three chasing dots
        orbit = 15.0
        for i in range(3):
            ang = (phase * 0.28) + i * (2 * math.pi / 3)
            x = _CX + orbit * math.cos(ang)
            y = _CY + orbit * math.sin(ang)
            hi = 1.0 if (phase + i * 7) % 21 < 7 else 0.45
            sz = 3 if hi > 0.8 else 2
            cc = "#ffffff" if hi > 0.8 else "#aaccee"
            c.create_oval(
                x - sz,
                y - sz,
                x + sz,
                y + sz,
                fill=cc,
                outline="",
                tags="led",
            )

    def _update_ui_text_pulse(self, mode: LedState, phase: float) -> None:
        """Subtle guide / transcript / panel tint synced to LED mode."""
        try:
            if mode == "idle":
                # Quiet: keep guide + panel visually stable; only transcript line may breathe if text is shown.
                self._guide.configure(text_color="#c4c4d0")
                self._transcript_wrap.configure(fg_color="#1c1c24")
                has_tr = bool(str(self._transcript.cget("text") or "").strip())
                if has_tr:
                    self._transcript.configure(
                        text_color=_breath_rgb(0x7E, 0xC8, 0xFF, phase, freq=0.10, strength=0.12)
                    )
                else:
                    self._transcript.configure(text_color="#526278")
            elif mode == "listening":
                self._guide.configure(
                    text_color=_breath_rgb(0xE8, 0xC8, 0xD0, phase, freq=0.18, strength=0.12)
                )
                has_tr = bool(str(self._transcript.cget("text") or "").strip())
                if has_tr:
                    self._transcript.configure(
                        text_color=_breath_rgb(0x90, 0xE0, 0xFF, phase, freq=0.22, strength=0.18)
                    )
                else:
                    self._transcript.configure(
                        text_color=_breath_rgb(0x9A, 0xB8, 0xD8, phase, freq=0.16, strength=0.12)
                    )
                self._transcript_wrap.configure(
                    fg_color=_breath_rgb(0x24, 0x1C, 0x2C, phase, freq=0.12, strength=0.10)
                )
            else:
                self._guide.configure(
                    text_color=_breath_rgb(0xB8, 0xD4, 0xF8, phase, freq=0.12, strength=0.11)
                )
                self._transcript.configure(
                    text_color=_breath_rgb(0xA0, 0xD4, 0xFF, phase, freq=0.14, strength=0.12)
                )
                self._transcript_wrap.configure(
                    fg_color=_breath_rgb(0x1A, 0x22, 0x34, phase, freq=0.10, strength=0.08)
                )
        except (tk.TclError, AttributeError):
            pass

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
