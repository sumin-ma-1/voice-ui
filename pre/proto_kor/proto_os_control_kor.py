import speech_recognition as sr
import pyautogui
import os
import subprocess
import time
from pywinauto import Desktop, Application
import csv
from datetime import datetime

# 1. 설정 및 로그 초기화
LOG_FILE = "proto_os_control_log_kor.csv"

def save_research_log(voice, cmd, status):
    with open(LOG_FILE, mode='a', newline='', encoding='utf-8') as f:
        csv.writer(f).writerow([datetime.now(), voice, cmd, status])

class OSController:
    def __init__(self):
        self.desktop = Desktop(backend="uia")

    def open_app(self, app_name):
        """프로그램 실행 (Shell 이용)"""
        if "메모장" in app_name:
            subprocess.Popen('notepad.exe')
        elif "브라우저" in app_name or "크롬" in app_name:
            os.system("start chrome")
        elif "계산기" in app_name:
            subprocess.Popen('calc.exe')

    def close_active_window(self):
        """UIA를 이용한 현재 활성 창 닫기"""
        try:
            active_window = self.desktop.active_window()
            window_name = active_window.window_text()
            active_window.close()
            print(f"[{window_name}] 창을 닫았습니다.")
            return True
        except Exception as e:
            print(f"창 닫기 실패: {e}")
            pyautogui.hotkey('alt', 'f4') # 강제 종료 단축키
            return False

    def show_desktop(self):
        """바탕화면 보기 (OS 단축키)"""
        pyautogui.hotkey('win', 'd')

    def system_volume(self, direction):
        """볼륨 조절"""
        if "업" in direction or "높여" in direction:
            pyautogui.press('volumeup', presses=5)
        else:
            pyautogui.press('volumedown', presses=5)

# 3. 메인 엔진
def start_agent():
    controller = OSController()
    recognizer = sr.Recognizer()
    mic = sr.Microphone()

    print("--- OS 통합 제어 에이전트 가동 중 ---")
    
    with mic as source:
        recognizer.adjust_for_ambient_noise(source, duration=1)
        
        while True:
            try:
                print("\n[명령 대기 중...]")
                audio = recognizer.listen(source, timeout=5, phrase_time_limit=5)
                command = recognizer.recognize_google(audio, language='ko-KR')
                print(f"사용자 발화: {command}")

                # 로직 처리
                if "메모장" in command or "계산기" in command:
                    controller.open_app(command)
                    save_research_log(command, "OpenApp", "Success")
                
                elif "바탕 화면" in command or "바탕화면" in command:
                    controller.show_desktop()
                    save_research_log(command, "ShowDesktop", "Success")

                elif "닫아" in command or "종료" in command:
                    controller.close_active_window()
                    save_research_log(command, "CloseWindow", "Success")

                elif "볼륨" in command:
                    controller.system_volume(command)
                    save_research_log(command, "VolumeControl", "Success")

                elif "중단" in command or "그만" in command:
                    print("시스템을 종료합니다.")
                    break

            except sr.UnknownValueError:
                print("음성을 이해하지 못했습니다.")
            except Exception as e:
                print(f"에러 발생: {e}")

if __name__ == "__main__":
    start_agent()