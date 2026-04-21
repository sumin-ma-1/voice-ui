import pyautogui
import numpy as np
import cv2

def capture_screen():

    img = pyautogui.screenshot()

    frame = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)

    return frame