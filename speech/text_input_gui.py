# speech/text_input_gui.py
# Always-on-top floating input window.
# Replaces VoiceListener + WhisperEngine with keyboard text input.
# After pressing Enter, the window hides so focus returns to the target app.

import tkinter as tk
import ctypes


class TextInputGUI:

    def __init__(self):

        self.root = tk.Tk()
        self.result = None

        self._setup()

        # start hidden
        self.root.withdraw()

    def _setup(self):

        self.root.title("Voice Agent")
        self.root.attributes("-topmost", True)
        self.root.resizable(False, False)

        # position: top-center of screen
        screen_w = self.root.winfo_screenwidth()
        self.root.geometry(f"440x36+{screen_w // 2 - 220}+16")

        # remove title bar for compact look
        self.root.overrideredirect(True)

        # outer frame with border
        frame = tk.Frame(self.root, bg="#222222", padx=2, pady=2)
        frame.pack(fill=tk.BOTH, expand=True)

        inner = tk.Frame(frame, bg="#1e1e1e")
        inner.pack(fill=tk.BOTH, expand=True)

        label = tk.Label(
            inner,
            text=">",
            bg="#1e1e1e",
            fg="#888888",
            font=("Consolas", 11)
        )
        label.pack(side=tk.LEFT, padx=(6, 2))

        self.entry = tk.Entry(
            inner,
            bg="#1e1e1e",
            fg="#ffffff",
            insertbackground="#ffffff",
            relief=tk.FLAT,
            font=("Consolas", 11),
            bd=0
        )
        self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))

        self.entry.bind("<Return>", self._on_enter)
        self.entry.bind("<Escape>", self._on_escape)

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
        """Windows API로 포커스를 강제로 가져옵니다.
        overrideredirect 창은 iconify()를 쓸 수 없어서 ctypes로 우회합니다."""
        hwnd = self.root.winfo_id()
        ctypes.windll.user32.SetForegroundWindow(hwnd)
        self.root.lift()
        self.root.focus_force()
        self.entry.focus_set()

    def get_input(self, delay_ms=300):
        """Show the window, block until Enter or Escape, return the typed text.

        delay_ms: 창이 뜨고 포커스를 가져오기까지 기다리는 시간(ms).
                  직전에 click 같은 액션이 있었을 경우 OS가 포커스를
                  정착시킬 시간이 필요하므로 약간의 딜레이를 줍니다.
        """
        self.result = None

        self.root.deiconify()
        self.root.after(delay_ms, self._grab_focus)

        self.root.mainloop()

        return self.result