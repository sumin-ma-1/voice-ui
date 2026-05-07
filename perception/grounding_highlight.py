# perception/grounding_highlight.py
# Full-screen transparent overlay: highlight the grounded target (center or bbox) briefly.

from __future__ import annotations

import tkinter as tk
from typing import Any


def _to_int_pair(center: Any) -> tuple[int, int] | None:
    if center is None:
        return None
    if hasattr(center, "x") and hasattr(center, "y"):
        try:
            return int(center.x), int(center.y)
        except (TypeError, ValueError):
            return None
    try:
        return int(center[0]), int(center[1])
    except (TypeError, ValueError, IndexError):
        return None


def show_grounding_highlight(
    *,
    element: dict[str, Any] | None,
    master: tk.Misc | None = None,
    duration_ms: int = 1200,
    ring_radius: int = 44,
    bbox_ring: bool = True,
) -> None:
    """
    Brief highlight at ``element`` center (and optional bbox ring). Non-blocking after first draw.

    Must be called from the Tk main thread. Pass ``master`` (e.g. the floating UI root) so the overlay
    stacks correctly.
    """
    if element is None:
        return
    center = _to_int_pair(element.get("center"))
    bbox = element.get("bbox")
    if center is None and bbox is None:
        return

    cx, cy = center if center else (0, 0)
    if center is None and bbox is not None:
        x1, y1, x2, y2 = bbox
        cx = int((x1 + x2) / 2)
        cy = int((y1 + y2) / 2)

    root = tk.Toplevel(master)
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.attributes("-fullscreen", True)

    key = "#010203"
    root.config(bg=key)
    root.attributes("-transparentcolor", key)

    c = tk.Canvas(root, highlightthickness=0, bg=key, width=root.winfo_screenwidth(), height=root.winfo_screenheight())
    c.pack(fill=tk.BOTH, expand=True)

    c.create_oval(
        cx - ring_radius,
        cy - ring_radius,
        cx + ring_radius,
        cy + ring_radius,
        outline="#ffcc00",
        width=4,
    )
    c.create_oval(
        cx - 6,
        cy - 6,
        cx + 6,
        cy + 6,
        fill="#ff3333",
        outline="#ffffff",
        width=2,
    )

    if bbox_ring and bbox is not None:
        x1, y1, x2, y2 = int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])
        c.create_rectangle(
            x1,
            y1,
            x2,
            y2,
            outline="#00aaff",
            width=3,
        )

    def _close() -> None:
        try:
            root.destroy()
        except tk.TclError:
            pass

    root.after(duration_ms, _close)
    try:
        root.update_idletasks()
        root.update()
    except tk.TclError:
        pass
