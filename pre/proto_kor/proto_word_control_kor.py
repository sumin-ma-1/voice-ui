import speech_recognition as sr
import win32com.client as win32
import time

def init_word():
    """
    COM을 사용하여 MS 워드 애플리케이션 객체를 생성하고 연결합니다.
    """
    try:
        # 워드 COM 객체 생성 (백그라운드에서 워드가 실행됨)
        word_app = win32.Dispatch("Word.Application")
        # 워드 창을 화면에 보이게 설정
        word_app.Visible = True
        print("[시스템] MS 워드가 성공적으로 실행되었습니다.")
        return word_app
    except Exception as e:
        print(f"[오류] 워드 실행 실패: {e}")
        return None

def process_command(text_command, word_app):
    """
    텍스트로 변환된 음성 명령을 분석하여 워드 COM 메서드를 호출합니다.
    (이 부분을 Rule-based에서 LLM 기반 Intent 분석으로 고도화 가능)
    """
    command = text_command.lower()
    
    try:
        if "새 문서" in command or "만들어" in command:
            # 워드의 Documents 컬렉션에 새 문서(Add) 추가
            word_app.Documents.Add()
            print("[실행] 새 문서를 생성했습니다.")
            
        elif "입력해" in command or "적어" in command:
            # 예: "안녕하세요 라고 입력해" -> "안녕하세요" 추출
            text_to_type = command.replace("입력해", "").replace("라고", "").strip()
            # 현재 커서(Selection) 위치에 텍스트 타이핑
            word_app.Selection.TypeText(text_to_type)
            # 엔터키 효과 (줄바꿈)
            word_app.Selection.TypeParagraph()
            print(f"[실행] '{text_to_type}' 텍스트를 입력했습니다.")
            
        elif "저장" in command:
            if word_app.ActiveDocument:
                # 활성화된 문서 저장
                word_app.ActiveDocument.Save()
                print("[실행] 문서를 저장했습니다.")
            else:
                print("[알림] 저장할 문서가 열려있지 않습니다.")
                
        elif "종료" in command or "꺼 줘" in command:
            # 워드 애플리케이션 안전 종료
            word_app.Quit()
            print("[실행] 워드를 종료합니다.")
            return False # 루프 종료 신호
            
        else:
            print("[알림] 지원하지 않는 명령어입니다. 다시 말씀해 주세요.")
            
    except Exception as e:
        print(f"[오류] 명령 실행 중 문제가 발생했습니다: {e}")
        
    return True # 루프 계속 유지 신호

def main():
    # 1. 음성 인식기 초기화
    recognizer = sr.Recognizer()
    microphone = sr.Microphone()
    
    # 2. 워드 COM 연결
    word_app = init_word()
    if not word_app:
        return

    print("\n--- 음성 제어 시스템이 시작되었습니다 ---")
    print("사용 가능한 명령: '새 문서 만들어', '[내용] 입력해', '저장해', '종료해'")
    
    is_running = True
    with microphone as source:
        # 주변 소음 수준에 맞춰 인식기 보정 (접근성 환경에서 필수적)
        recognizer.adjust_for_ambient_noise(source, duration=1)
        
        while is_running:
            print("\n[마이크] 명령을 말씀해 주세요 (듣는 중...):")
            try:
                # 음성 데이터 수집
                audio = recognizer.listen(source, timeout=5, phrase_time_limit=10)
                
                # Google Web Speech API를 이용해 음성을 텍스트로 변환 (한국어)
                text_command = recognizer.recognize_google(audio, language="ko-KR")
                print(f"[인식된 명령]: {text_command}")
                
                # 3. 명령 처리 및 COM 제어
                is_running = process_command(text_command, word_app)
                
            except sr.WaitTimeoutError:
                pass # 제한 시간 동안 아무 말도 없으면 넘어감
            except sr.UnknownValueError:
                print("[시스템] 음성을 정확히 인식하지 못했습니다.")
            except sr.RequestError as e:
                print(f"[시스템] 음성 인식 서비스에 접근할 수 없습니다: {e}")

if __name__ == "__main__":
    main()