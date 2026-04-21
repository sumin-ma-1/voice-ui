# perception/ui_extractor.py
# mode에 따라 UIA / Vision / Both 선택
# function per mode

from pywinauto import Application
from perception.screen_capture import capture_screen
from perception.icon_utils import detect_icons


def extract_uia_elements():
    """UIA 요소만 수집"""

    app = Application(backend="uia").connect(active_only=True)
    window = app.top_window()

    elements = []

    # 제외할 UI 타입
    EXCLUDE_TYPES = {
        "Static",
        "Groupbox",
        "ListItems",
        "ListItem",
        "GroupBox"
    }

    for element in window.descendants(depth=20):

        try:
            rect = element.rectangle()
            parent = element.parent()

            name = element.window_text()
            control_type = element.friendly_class_name()

            # ---- 요소 제거 ----
            if control_type in EXCLUDE_TYPES:
                continue

            parent_name = ""
            parent_type = ""

            if parent:
                parent_name = parent.window_text()
                parent_type = parent.friendly_class_name()

            elements.append({
                "name": name,
                "control_type": control_type,
                "parent_name": parent_name,
                "parent_type": parent_type,
                "bbox": (rect.left, rect.top, rect.right, rect.bottom),
                "center": rect.mid_point(),
                "is_icon": False
            })

        except Exception:
            continue

    return elements


def extract_vision_elements():
    """YOLO + OCR 아이콘만 수집 (UIA 없음)"""

    screen = capture_screen()
    icons = detect_icons(screen)

    print("YOLO boxes:", len(icons))

    elements = []

    for icon in icons:

        x1, y1, x2, y2 = icon["bbox"]
        text = icon["text"]

        elements.append({
            "name": text,
            "control_type": "icon",
            "parent_name": "",
            "parent_type": "",
            "bbox": (x1, y1, x2, y2),
            "center": ((x1 + x2) // 2, (y1 + y2) // 2),
            "is_icon": True
        })

    return elements


def extract_elements_by_mode(mode):
    """
    mode:
        "uia"    → UIA만
        "vision" → YOLO + OCR만
        "both"   → UIA + YOLO + OCR 전부 as fallback
    """

    if mode == "uia":
        return extract_uia_elements()

    elif mode == "vision":
        return extract_vision_elements()

    elif mode == "both":

        try:
            uia = extract_uia_elements()
            vision = []
        except Exception:
            print("[both] UIA failed → vision only")
            uia = []
            vision = extract_vision_elements()

        # vision = extract_vision_elements()
        return uia + vision

    else:
        raise ValueError(f"Unknown mode: {mode}. Use 'uia', 'vision', or 'both'.")
