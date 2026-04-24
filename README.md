# 🐾 Pet.AI - 반려동물 건강 분석 AI

이 프로젝트는 사용자가 반려동물의 사진과 증상을 입력하면, Google Gemini AI가 의심되는 질병 정보와 건강 조언을 제공하는 Flask 기반 웹 애플리케이션입니다.

### [🌐 상세 포트폴리오 웹페이지 보기](https://minseo0316.github.io/PetAI/index.html)

> **Google Gemini API**를 활용하여 반려동물의 사진과 증상을 분석하고, 
> 건강 조언을 제공하는 Full-Stack 프로젝트입니다.

## ⚙️ 필수 환경 및 실행 방법

1. **필수 환경:** Python 3.8+
2. **라이브러리 설치:** `pip install -r requirements.txt`
3. **데이터베이스 초기화:** `python setup_db.py`
4. **환경 변수 설정:** `GEMINI_API_KEY` 설정 필요
5. **로컬 서버 실행:** `flask run`

## 🚀 배포 및 운영 이슈 해결
* **플랫폼:** Render (gunicorn 및 Procfile 활용)
* **트러블슈팅:** Render 무료 티어의 서버 유휴 상태(Spin-down)로 인한 접속 지연 문제를 해결하기 위해 **UptimeRobot**을 연동, 5분 간격 HTTP 요청을 통해 **24시간 가용성을 확보**했습니다.
