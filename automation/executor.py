# automation/executor.py
import pyautogui

MOVE_DURATION = 0.15
TYPE_INTERVAL = 0.02

# Disable the fail-safe
# pyautogui.FAILSAFE = False

def execute(action, element=None, params=None):

    if params is None:
        params = {}

    # move to element if exists
    if element:
        x, y = element["center"]
        pyautogui.moveTo(x, y, duration=MOVE_DURATION)
    
    # ---------------- MOUSE ----------------

    if action == "left_click":
        pyautogui.click()

    elif action == "right_click":
        pyautogui.rightClick()

    elif action == "double_click":
        pyautogui.doubleClick()

    elif action == "hover":
        # move only (already done above)
        pass

    elif action == "scroll":

        direction = params.get("direction", "down")
        amount = params.get("amount", 500)

        if direction == "up":
            pyautogui.scroll(amount)

        elif direction == "down":
            pyautogui.scroll(-amount)

        elif direction == "left":
            pyautogui.hscroll(-amount)

        elif direction == "right":
            pyautogui.hscroll(amount)

    # ---------------- KEYBOARD ----------------

    elif action == "press_key":

        key = params.get("key")
        pyautogui.press(key)

    elif action == "hotkey":

        keys = params.get("keys", [])
        pyautogui.hotkey(*keys)

    elif action == "enter":
        pyautogui.press("enter")

    elif action == "esc":
        pyautogui.press("esc")

    elif action == "tab":
        pyautogui.press("tab")

    elif action == "backspace":
        pyautogui.press("backspace")

    elif action == "delete":
        pyautogui.press("delete")

    # ---------------- TEXT ---------------

    elif action == "type":
        text = params.get("text", "")
        pyautogui.write(text, interval=TYPE_INTERVAL)

    # ---------------- SELECTION ----------------

    elif action == "select_all":
        pyautogui.hotkey("ctrl", "a")

    elif action == "copy":
        pyautogui.hotkey("ctrl", "c")

    elif action == "paste":
        pyautogui.hotkey("ctrl", "v")

    elif action == "cut":
        pyautogui.hotkey("ctrl", "x")

    elif action == "undo":
        pyautogui.hotkey("ctrl", "z")

    elif action == "redo":
        pyautogui.hotkey("ctrl", "y")

    elif action == "save":
        pyautogui.hotkey("ctrl", "s")

    # ---------------- NAVIGATION ----------------

    elif action == "new_tab":
        pyautogui.hotkey("ctrl", "t")

    elif action == "close_tab":
        pyautogui.hotkey("ctrl", "w")

    elif action == "switch_tab":

        direction = params.get("direction", "next")

        if direction == "next":
            pyautogui.hotkey("ctrl", "tab")

        else:
            pyautogui.hotkey("ctrl", "shift", "tab")

    elif action == "refresh":
        pyautogui.press("f5")