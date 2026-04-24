import os
import cv2
from datetime import datetime

def draw_elements(frame, elements):

    for el in elements:

        x1, y1, x2, y2 = el["bbox"]

        # 본인 정보 처리: icon이면 type 생략
        if el["type"].lower() == "icon":
            label = f'{el["name"]}'
        else:
            label = f'{el["name"]} ({el["type"]})'
        
        # 부모 요소 정보가 있다면 추가: [부모이름] ([부모타입])
        parent_name = el.get("parent_name")
        parent_type = el.get("parent_type")
        
        if parent_name and parent_type:
            label += f' | P: {parent_name} ({parent_type})'

        cv2.rectangle(
            frame,
            (x1, y1),
            (x2, y2),
            (0, 255, 0),
            2
        )

        cv2.putText(
            frame,
            label,
            (x1, y1 - 5),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.5,
            (0,255,0),
            3
        )

    return frame

def draw_match(frame, element):

    x1, y1, x2, y2 = element["bbox"]

    cv2.rectangle(
        frame,
        (x1, y1),
        (x2, y2),
        (0,0,255),
        3
    )

    cv2.putText(
        frame,
        "MATCH",
        (x1, y1 - 40),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.8,
        (0,0,255),
        7
    )

    return frame

def show_debug(frame):

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")

    folder = "test_screen_img"
    os.makedirs(folder, exist_ok=True)  # Create folder if it doesn't exist

    filename = os.path.join(folder, f"debug_view_{timestamp}.png")

    cv2.imwrite(filename, frame)

    print(f"Saved debug image to {filename}")