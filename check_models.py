# c:\petAI\check_models.py
import google.generativeai as genai
import os

try:
    # app.py와 동일한 방식으로 API 키를 가져옵니다.
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("오류: GEMINI_API_KEY 환경 변수를 설정해주세요.")
    else:
        genai.configure(api_key=api_key)
        print("\n" + "="*50)
        print("사용자님의 API 키로 사용 가능한 모델 목록입니다.")
        print("="*50)
        for m in genai.list_models():
            # 'generateContent' 메소드를 지원하는 모델만 필터링합니다.
            if 'generateContent' in m.supported_generation_methods:
                print(f"  - {m.name}")
        print("="*50)
        print("\n위 목록에 있는 모델 이름을 app.py 파일에 사용해주세요.")
        print("(예: 'models/gemini-pro', 'models/gemini-pro-vision')\n")

except Exception as e:
    print(f"모델 목록을 가져오는 중 오류 발생: {e}")