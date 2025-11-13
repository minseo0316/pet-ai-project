# Pet.AI - 반려동물 건강 분석 AI

이 프로젝트는 사용자가 반려동물의 사진과 증상을 입력하면, Google Gemini AI가 의심되는 질병 정보와 건강 조언을 제공하는 Flask 기반 웹 애플리케이션입니다.

## 필수 환경
- Python 3.8+

## 설치 및 실행

1.  **라이브러리 설치**
    ```bash
    pip install -r requirements.txt
    ```

2.  **데이터베이스 초기화 (최초 1회)**
    ```bash
    python setup_db.py
    ```

3.  **환경 변수 설정**
    -   `GEMINI_API_KEY`를 본인의 API 키로 설정해야 합니다.

4.  **로컬 서버 실행**
    ```bash
    flask run
    ```

## 배포
이 프로젝트는 `gunicorn`과 `Procfile`을 사용하여 Render와 같은 PaaS 플랫폼에 배포할 수 있도록 설정되어 있습니다.
