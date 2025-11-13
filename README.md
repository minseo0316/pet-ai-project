프로토타입 반려동물 케어 AI (Streamlit)

이 프로젝트는 반려동물(주로 고양이)의 사진과 보호자 증상을 입력하면
AI가 의심되는 질병 정보를 제공하고, 10가지 이상행동 분석 및 고양이 비만 판정/코칭을
제공하는 프로토타입입니다.

필수 환경
- Python 3.8+
- .streamlit/secrets.toml에 GEMINI_API_KEY 설정 (Gemini 멀티모달 연동 시 필요)

설치
1) 가상환경 생성
python -m venv .venv; .\.venv\Scripts\Activate.ps1
2) 패키지 설치
python -m pip install -r requirements.txt

실행
streamlit run app.py

노트
- 현재 이미지 분석은 placeholder로 동작합니다. 실제 멀티모달 모델(Gemini) 연동은 추가 구현이 필요합니다.
- DB 파일(pet_health.db)은 `setup_db.py`로 생성하세요.

Gemini 멀티모달 연동 가이드 (간단)
1) Google Gemini API 키를 발급받아 `.streamlit/secrets.toml`에 `GEMINI_API_KEY`로 설정합니다.
2) `app.py`의 `analyze_image` 함수를 멀티모달 모델 호출 코드로 교체하세요. 예: 이미지를 base64로 인코딩하여 Gemini에 전송하고, 모델의 반환 라벨/설명을 사용합니다.
3) 멀티모달 모델 호출 예시는 Google의 `google-generativeai` 패키지 문서를 참고하세요. 멀티모달의 입력/출력 포맷은 모델 버전에 따라 다르므로 최신 문서를 확인해야 합니다.
4) 개인정보(이미지) 전송에 대해 사용자 동의를 명확히 받고, 민감한 데이터 처리 방침을 마련하세요.
