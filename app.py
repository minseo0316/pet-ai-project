# app.py
import os
import sqlite3
from flask import Flask, request, render_template, url_for, jsonify, flash, redirect
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
import psycopg2, psycopg2.extras
import google.generativeai as genai
import markdown
from PIL import Image
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
import bcrypt
from petai_utils import analyze_behaviors, assess_cat_obesity, assess_dog_obesity


# --- 이상행동 DB (petai_utils.py에서 이동) ---
BEHAVIOR_DB = {
    "과도한 핥기": {
        "possible_causes": ["피부 알레르기", "스트레스", "기생충"],
        "coaching": "피부 상태를 관찰하고, 국소적 염증이나 탈모가 있는지 확인하세요. 48시간 내 개선 없으면 수의사 방문을 권합니다. 스트레스 가능성도 고려해 환경 변화를 최소화하세요."
    },
    "식욕부진": {
        "possible_causes": ["소화기 문제", "통증", "감염"],
        "coaching": "24시간 이상 식사를 거부하면 즉시 수의사 상담이 필요합니다. 물 섭취량과 배변 상태를 함께 기록하세요."
    },
    "과도한 물어뜯기(깨무는 행동)": {
        "possible_causes": ["통증", "스트레스", "구강 문제"],
        "coaching": "입안 냄새, 잇몸 출혈, 침흘림 여부를 확인하세요. 통증 의심되면 동물병원에서 구강검진을 받으세요."
    },
    "숨기/은신 행동 증가": {
        "possible_causes": ["스트레스", "병든 징후", "환경 변화"],
        "coaching": "조용한 공간과 은신처를 제공하고 급격한 환경 변화를 줄이세요. 계속 숨거나 활동량이 크게 줄면 수의사 상담을 권합니다."
    },
    "과도한 배설/실내 배변": {
        "possible_causes": ["의사소통 문제", "소화기 질환", "스트레스"],
        "coaching": "배변 장소와 빈도를 기록하고, 변의 모양(혈액, 점액 등)을 확인하세요. 문제 지속 시 검진이 필요합니다."
    },
    "지속적 울음/야행성 소음": {
        "possible_causes": ["통증", "인지 기능 저하(노령)", "스트레스"],
        "coaching": "나이를 고려해 야간 행동 패턴을 점검하세요. 노령묘의 경우 인지기능 변화일 수 있으니 수의사 상담을 권합니다."
    },
    "비정상적 움직임(절뚝임 등)": {
        "possible_causes": ["외상", "관절염", "근골격계 이상"],
        "coaching": "움직임의 시작 시점과 악화 양상을 기록하세요. 통증 징후가 보이면 안정화 후 정밀검사 필요합니다."
    },
    "구토 빈발": {
        "possible_causes": ["식이 문제", "중독", "위장관 질환"],
        "coaching": "구토 횟수, 섭취한 음식, 혈액 혼합 여부를 기록하세요. 탈수 우려 시 즉시 수의사 방문이 필요합니다."
    },
    "설사": {
        "possible_causes": ["감염", "식이 부적합", "기생충"],
        "coaching": "수분 공급을 우선으로 하고 24-48시간 개선이 없으면 검진을 권합니다. 배변의 상태를 사진으로 기록해 두세요."
    },
    "과도한 긁기(발톱으로 긁음)": {
        "possible_causes": ["피부병변", "알레르기", "기생충"],
        "coaching": "피부의 발적, 비듬, 기생충 징후를 확인하세요. 국소 치료 후에도 지속되면 수의사 진료가 필요합니다."
    }
}


# --- 1. Flask 앱 설정 ---
app = Flask(__name__)
UPLOAD_FOLDER = 'static/uploads'
app.config['SECRET_KEY'] = os.urandom(24) # 세션 관리를 위한 시크릿 키
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

DB_FILE = 'pet_health.db'

# --- Flask-Login 설정 ---
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login' # 로그인 안 한 사용자가 login_required 페이지 접근 시 리디렉션

# --- User 모델 정의 ---
class User(UserMixin):
    def __init__(self, id, username, is_admin=False):
        self.id = id
        self.username = username
        self.is_admin = is_admin

@login_manager.user_loader
def load_user(user_id):
    database_url = os.environ.get("DATABASE_URL")
    conn = None
    try:
        if database_url:
            conn = psycopg2.connect(database_url)
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
        else:
            conn = sqlite3.connect(DB_FILE)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        
        user_data = cur.fetchone()
        if user_data:
            return User(id=user_data['id'], username=user_data['username'], is_admin=user_data['is_admin'])
        return None
    finally:
        if conn:
            conn.close()

# --- 2. Gemini API 설정 ---
try:
    api_key = os.environ.get("GEMINI_API_KEY")
    if api_key:
        genai.configure(api_key=api_key)
        print("INFO: GEMINI_API_KEY 설정 완료")
    else:
        print("경고: GEMINI_API_KEY 환경 변수가 설정되지 않았습니다.")
except Exception as e:
    print(f"API 키 설정 오류: {e}")

# setup_db.py에서 초기 데이터 가져오기
diseases_data = [
    ("알레르기성 피부염 (의심)", "피부 발진,붉은 반점,탈모", "가려움,핥음,비빔,발적", "주의 🟡", "사진과 증상으로 볼 때 '알레르기성 피부염'이 의심됩니다. 원인(사료, 간식, 집먼지 등)을 찾아보고, 증상이 지속되면 병원을 방문해 정확한 알레르기 원인을 찾는 것이 좋습니다."),
    ("백내장 (초기 의심)", "흐릿한 눈,하얀 동공", "눈을 잘 못 마주침,밤에 잘 부딪힘,눈이 뿌옇게 보임", "경고 🔴", "사진상 동공이 뿌옇게 보이는 것은 '백내장'의 초기 징후일 수 있습니다. 방치하면 시력을 잃을 수 있으니 즉시 안과 전문 동물병원을 방문하여 검사를 받으세요."),
    ("결막염 (의심)", "붉은 눈,눈곱,눈물", "눈을 찡그림,눈 주변을 비빔", "주의 🟡", "눈이 붉어지고 눈곱이 끼는 증상은 '결막염'일 수 있습니다. 세균 감염이나 알레르기 때문일 수 있으니, 병원에서 안약을 처방받아 치료하는 것이 좋습니다."),
    ("정상 피부", "정상 피부", "특별한 증상 없음", "안전 🟢", "사진과 증상으로는 특별한 이상 징후가 보이지 않습니다. 건강한 상태로 보입니다. 하지만 평소와 다른 행동을 보인다면 주의 깊게 관찰해주세요."),
    ("고양이 허피스 바이러스 (상부 호흡기 감염)", "눈곱,콧물,재채기,눈 부음", "재채기,콧물,눈물,식욕부진", "주의 🟡", "고양이 허피스 바이러스는 상부 호흡기 감염(고양이 감기)의 주요 원인입니다. 전염성이 매우 강하므로 다른 고양이와 격리하고, 습도를 높여주어 호흡을 편안하게 해주세요. 증상이 심하거나 2-3일 내에 개선되지 않으면 즉시 병원을 방문하여 항바이러스 치료를 받는 것이 중요합니다."),
    ("슬개골 탈구 (강아지)", "다리를 절음,깽깽이걸음,다리를 들고 뜀", "깽깽이걸음,다리를 절음,무릎에서 소리가 남", "경고 🔴", "깽깽이걸음이나 다리를 저는 증상은 슬개골 탈구의 대표적인 증상입니다. 특히 소형견에게 흔하게 발생합니다. 방치할 경우 관절염으로 악화될 수 있으니, 정형외과 전문 동물병원에서 정확한 단계를 진단받고 수술 여부를 상담하는 것이 좋습니다."),
    ("강아지 아토피성 피부염 (의심)", "피부 발적,탈모,두드러기,피부 핥음", "심한 가려움,발 핥기,귀 감염,피부 붉어짐", "주의 🟡", "사진과 증상으로 볼 때 '강아지 아토피성 피부염'이 의심됩니다. 알레르기 반응의 일종으로, 환경적 요인(꽃가루, 집먼지 진드기 등)에 의해 발생할 수 있습니다. 정확한 원인 파악과 관리를 위해 동물병원 방문을 권장합니다."),
    ("개선충증 (옴, 의심)", "심한 각질,피부 딱지,탈모,피부 상처", "극심한 가려움(특히 밤에),귀 끝과 팔꿈치 병변,전염성", "경고 🔴", "극심한 가려움과 피부 딱지는 전염성이 매우 강한 '개선충증(옴)'의 특징일 수 있습니다. 즉시 다른 동물과 격리하고 동물병원에 방문하여 정확한 진단과 치료를 받아야 합니다. 사람에게도 옮을 수 있으니 주의가 필요합니다."),
    ("곰팡이성 피부염 (링웜, 의심)", "원형 탈모,각질,붉은 테두리", "원형의 탈모반,가려움(경미하거나 없음),부서지는 털", "주의 🟡", "원형 탈모와 각질은 '곰팡이성 피부염(링웜)'의 대표적인 증상입니다. 전염성이 있으므로 다른 동물 및 사람과의 접촉을 피하고, 소독과 함께 동물병원에서 항진균제 치료를 받아야 합니다.")
]

def run_db_setup():
    """
    데이터베이스를 확인하고 필요한 테이블과 초기 데이터를 설정합니다.
    Render 환경에서는 PostgreSQL을, 로컬에서는 SQLite를 사용합니다.
    """
    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        # --- PostgreSQL 설정 (Render 환경) ---
        try:
            conn = psycopg2.connect(database_url)
            cur = conn.cursor()
            cur.execute('''
                CREATE TABLE IF NOT EXISTS diseases (
                    id SERIAL PRIMARY KEY,
                    disease_name TEXT NOT NULL,
                    image_labels TEXT,
                    text_symptoms TEXT,
                    warning_level TEXT,
                    advice TEXT
                )
            ''')
            conn.commit()
            print("Postgres: 테이블 생성 확인 완료.")

            cur.execute("SELECT COUNT(*) FROM diseases")
            if cur.fetchone()[0] == 0:
                print("Postgres: 테이블이 비어있어 초기 데이터를 삽입합니다.")
                insert_q = '''INSERT INTO diseases (disease_name, image_labels, text_symptoms, warning_level, advice) VALUES (%s,%s,%s,%s,%s)'''
                cur.executemany(insert_q, diseases_data)
                conn.commit()
                print(f"Postgres: {len(diseases_data)}개의 초기 질병 데이터가 DB에 저장되었습니다.")
            else:
                print("Postgres: 데이터가 이미 존재하므로 초기화를 건너뜁니다.")

            # 사용자 테이블 생성
            cur.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    password TEXT NOT NULL,
                    is_admin BOOLEAN DEFAULT FALSE
                )
            ''')
            conn.commit()
            print("Postgres: users 테이블 생성 확인 완료.")

            # 관리자 계정이 없으면 생성
            cur.execute("SELECT id FROM users WHERE username = 'admin'")
            if cur.fetchone() is None:
                hashed_password = bcrypt.hashpw('admin'.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
                cur.execute("INSERT INTO users (username, password, is_admin) VALUES ('admin', %s, TRUE)", (hashed_password,))
                conn.commit()
                print("Postgres: 기본 관리자(admin) 계정 생성 완료.")

            # 분석 기록 테이블 생성
            cur.execute('''
                CREATE TABLE IF NOT EXISTS analysis_history (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    analysis_result JSONB,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
                )
            ''')
            conn.commit()
            print("Postgres: analysis_history 테이블 생성 확인 완료.")

            # 챗봇 대화 기록 테이블 생성
            cur.execute('''
                CREATE TABLE IF NOT EXISTS chat_history (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    role TEXT NOT NULL, -- 'user' 또는 'model'
                    content TEXT NOT NULL,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
                )
            ''')
            conn.commit()
            print("Postgres: chat_history 테이블 생성 확인 완료.")

            cur.close()
            conn.close()
        except Exception as e:
            print(f"Postgres DB 설정 중 오류 발생: {e}")
    else:
        # --- SQLite 설정 (로컬 환경) ---
        try:
            conn = sqlite3.connect(DB_FILE)
            cur = conn.cursor()
            cur.execute('''
                CREATE TABLE IF NOT EXISTS diseases (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    disease_name TEXT NOT NULL, image_labels TEXT, text_symptoms TEXT,
                    warning_level TEXT, advice TEXT
                )
            ''')
            conn.commit()

            cur.execute("SELECT COUNT(*) FROM diseases")
            if cur.fetchone()[0] == 0:
                insert_q = '''INSERT INTO diseases (disease_name, image_labels, text_symptoms, warning_level, advice) VALUES (?,?,?,?,?)'''
                cur.executemany(insert_q, diseases_data)
                conn.commit()

            # 사용자 테이블 생성 (SQLite)
            cur.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password TEXT NOT NULL,
                    is_admin BOOLEAN DEFAULT FALSE
                )
            ''')
            cur.execute("SELECT id FROM users WHERE username = 'admin'")
            if cur.fetchone() is None:
                hashed_password = bcrypt.hashpw('admin'.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
                cur.execute("INSERT INTO users (username, password, is_admin) VALUES (?, ?, ?)", ('admin', hashed_password, True))
                conn.commit()

            # 분석 기록 테이블 생성 (SQLite)
            cur.execute('''
                CREATE TABLE IF NOT EXISTS analysis_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    analysis_result TEXT, -- JSON을 텍스트로 저장
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
                )
            ''')
            conn.commit()

            # 챗봇 대화 기록 테이블 생성 (SQLite)
            cur.execute('''
                CREATE TABLE IF NOT EXISTS chat_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
                )
            ''')

            conn.close()
        except Exception as e:
            print(f"SQLite DB 설정 중 오류 발생: {e}")


# --- 3. 핵심 로직 함수 ---
def analyze_image(image_path):
    """실제 Gemini Vision 모델을 사용하여 이미지를 분석하고 라벨을 반환합니다."""
    try:
        image_file = genai.upload_file(path=image_path)
        print(f"INFO: Analyzing image at {image_path} with Gemini Vision...")
        model = genai.GenerativeModel('models/gemini-2.5-flash')
        prompt = """
        당신은 수의학 지식이 있는 AI 보조원입니다.
        이 반려동물 사진에서 관찰할 수 있는 모든 잠재적인 의학적 증상을 자세히 묘사해주세요.
        눈, 코, 입, 귀, 피부, 털 상태, 자세 등 구체적인 부위에 집중해서 설명해주세요.
        만약 여러 증상이 보인다면 모두 나열해주세요. (예: 왼쪽 눈의 탁한 분비물, 코 주변의 약간의 붉은 기, 가슴 부분의 뭉친 털)
        만약 특별한 이상 징후 없이 건강해 보인다면 '외관상 특이 소견 없음' 이라고 답변해주세요."""

        # 파일이 처리될 때까지 기다립니다.
        while image_file.state.name == "PROCESSING":
            print('... 파일 처리 중 ...')
            image_file = genai.get_file(image_file.name) # 파일의 최신 상태를 가져옵니다.

        response = model.generate_content([prompt, image_file], request_options={'timeout': 60})
        print(f"INFO: Image analysis result: {response.text.strip()}")
        genai.delete_file(image_file.name) # 분석이 끝난 후 파일을 삭제합니다.
        return response.text.strip()
    except Exception as e:
        print(f"이미지 분석 중 오류 발생: {e}")
        return f"이미지 분석 실패: {e}"

def search_db_by_image_label(image_label):
    """이미지 라벨을 기반으로 데이터베이스에서 관련 질병을 검색합니다."""
    database_url = os.environ.get("DATABASE_URL")
    conn = None
    try:
        if database_url:
            conn = psycopg2.connect(database_url)
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        else:
            conn = sqlite3.connect(DB_FILE)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()

        cur.execute("SELECT * FROM diseases")
        all_diseases = cur.fetchall()

        matched_diseases = []
        for disease_row in all_diseases:
            disease_dict = dict(disease_row)
            keywords = [k.strip() for k in disease_dict['image_labels'].split(',')]
            if any(keyword in image_label for keyword in keywords if keyword):
                matched_diseases.append(disease_dict)

        return matched_diseases if matched_diseases else None

    except Exception as e:
        print(f"DB 검색 중 오류 발생: {e}")
        return None
    finally:
        if conn:
            conn.close()


def run_analysis_task(form_data, image_path_relative, selected_behaviors):
    """오래 걸리는 분석 작업을 수행하는 함수 (백그라운드 워커에서 실행됨)"""
    # form_data에서 필요한 값들을 다시 추출
    pet_type = form_data.get('pet_type', '고양이')
    symptom_text = form_data.get('symptoms', '').strip()

    result_data = {}
    prompt_contexts = []

    try:
        # --- 이미지 처리 (이미지가 있는 경우) ---
        if image_path_relative:
            result_data['image_path'] = image_path_relative
            image_path = os.path.join('static', image_path_relative) # 실제 파일 경로

            image_result_label = analyze_image(image_path)
            db_results = search_db_by_image_label(image_result_label)

            result_data['image_analysis_label'] = image_result_label
            if db_results:
                prompt_contexts.append(f"[사진 분석과 관련된 수의학 지식 (DB 검색 결과)]\n{db_results}")
            else:
                prompt_contexts.append("[사진 분석과 관련된 수의학 지식 (DB 검색 결과)]\n일치하는 정보를 찾지 못했습니다.")

        # --- 증상 텍스트 처리 (증상이 있는 경우) ---
        if symptom_text:
            result_data['symptom_text'] = symptom_text
            prompt_contexts.append(f"[보호자 관찰 내용]\n{symptom_text}")
        
        # --- 이상 행동 처리 (이상 행동이 있는 경우) ---
        if selected_behaviors:
            behavior_text = ", ".join(selected_behaviors)
            result_data['selected_behaviors'] = behavior_text
            prompt_contexts.append(f"[보호자가 선택한 이상 행동]\n{behavior_text}")

        # mission 설정 로직을 모든 경우의 수를 명확히 하도록 수정
        if image_path_relative and (symptom_text or selected_behaviors):
            mission = "위의 [사진 분석과 관련된 수의학 지식]을 바탕으로, 제공된 [보호자 관찰 내용], [보호자가 선택한 이상 행동], [사진 분석 결과 라벨]을 종합하여"
        elif image_path_relative:
            mission = "위의 [사진 분석과 관련된 수의학 지식]과 [사진 분석 결과 라벨]을 바탕으로,"
        elif symptom_text or selected_behaviors:
            mission = "제공된 [보호자 관찰 내용]과 [보호자가 선택한 이상 행동]을 바탕으로,"
        else:
            # 이 경우는 거의 없지만, 안전장치로 추가
            mission = "제공된 정보를 바탕으로"

        # --- Gemini 모델 초기화 ---
        # 강아지 분석 시 gemini-2.5-flash가 불안정한 것으로 보이므로,
        # 강아지일 경우 더 안정적인 gemini-1.0-pro를 사용합니다.
        # 고양이일 경우 요청하신 gemini-2.5-flash를 사용합니다.
        if pet_type == '강아지':
            model = genai.GenerativeModel('models/gemini-1.0-pro')
        else: # 고양이
            model = genai.GenerativeModel('models/gemini-2.5-flash')

        # --- 신뢰도 평가 프롬프트 추가 ---
        confidence_prompt = """
        [신뢰도 평가]
        지금까지의 정보를 바탕으로, 당신의 최종 진단에 대한 신뢰도를 0%에서 100% 사이의 백분율 숫자로 평가하고 그 이유를 한 문장으로 설명해주세요.
        신뢰도: [숫자]%
        이유: [이유]
        """

        if 'image_analysis_label' in result_data:
            prompt_contexts.append(f"[사진 분석 결과 라벨]\n{result_data['image_analysis_label']}")

        prompt = f'''
        당신은 전문 {pet_type} 수의사 AI 조수입니다. {"\n\n".join(prompt_contexts)}


        ---
        [임무]
        {mission} 보호자에게 가장 가능성이 높은 질병과 경고, 조언을 생성해주세요.
        만약 [사진 분석과 관련된 수의학 지식]이 제공되었다면, 해당 내용을 우선적으로 참고하여 답변을 구성하세요.
        증상만으로 판단이 어려울 경우, 여러 가능성을 제시하고 사진 등의 추가 정보를 요청할 수 있습니다.
        답변은 반드시 아래 [출력 형식]을 따라야 합니다.

        [규칙] 
        [출력 형식]
        ### 핵심 요약
        (가장 의심되는 질병명을 명시하여 모든 내용을 한두 문장으로 요약합니다. 예: '입력된 정보로 볼 때 '알레르기성 피부염'이 의심됩니다.')\n
        ### 상세 설명
        (의심되는 점과 그 이유를 2-3문장으로 간결하게 설명)\n
        ### 권장 조치
        (보호자가 해야 할 가장 중요한 조치 1-2가지를 간결하게 설명)\n
        {confidence_prompt}
        ---
        [경고 수준]
        (위 분석 결과에 가장 적합한 경고 수준을 다음 네 가지 중 하나만 선택하여 표시: "안전 🟢", "주의 🟡", "경고 🔴", "상담 필요 🔵")

        '''        
        response = model.generate_content(prompt, request_options={'timeout': 60})
        raw_text = response.text

        # 신뢰도 부분 파싱
        try:
            # '[신뢰도 평가]' 섹션을 기준으로 텍스트 분리
            main_response_text, rest_of_text = raw_text.split('[신뢰도 평가]', 1)
            
            # 신뢰도 점수와 이유 추출
            score_line = [line for line in rest_of_text.split('\n') if '신뢰도:' in line][0]
            reason_line = [line for line in rest_of_text.split('\n') if '이유:' in line][0]

            # 숫자만 추출 (예: "신뢰도: 90%" -> 90)
            confidence_score = int(''.join(filter(str.isdigit, score_line)))
            confidence_reason = reason_line.split(':', 1)[1].strip()

            result_data['confidence'] = {
                'score': confidence_score,
                'reason': confidence_reason
            }
            result_data['gemini_response'] = markdown.markdown(main_response_text.strip())

            # 경고 수준 파싱
            if '[경고 수준]' in rest_of_text:
                warning_level_text = rest_of_text.split('[경고 수준]')[1].strip()
                # "안전 🟢" 같은 형식에서 단어만 추출
                if "안전" in warning_level_text: result_data['warning_level'] = 'safe'
                elif "주의" in warning_level_text: result_data['warning_level'] = 'caution'
                elif "경고" in warning_level_text: result_data['warning_level'] = 'warning'
                elif "상담" in warning_level_text: result_data['warning_level'] = 'consult'

        except (ValueError, IndexError):
            # 파싱 실패 시 전체 텍스트를 그대로 보여줌
            result_data['gemini_response'] = markdown.markdown(raw_text)

        # --- 추가 분석 (이상행동, 비만) ---
        if selected_behaviors:
            result_data['behavior_analysis'] = analyze_behaviors(selected_behaviors, symptom_text, BEHAVIOR_DB)
        
        return result_data

    except Exception as e:
        print(f"분석 중 오류 발생: {e}")
        # 오류 발생 시 오류 정보를 담은 딕셔너리 반환
        return {"error": f"AI 분석 작업 중 오류가 발생했습니다: {e}"}

# --- 4. Flask 라우트(경로) 설정 ---
@app.route('/')
def index():
    return render_template('index.html') # 메인 페이지만을 렌더링합니다.

@app.context_processor
def inject_behaviors():
    return dict(behaviors=list(BEHAVIOR_DB.keys()))

@app.route('/analyze', methods=['POST'])
@login_required
def analyze():
    symptom_text = request.form.get('symptoms', '').strip()
    uploaded_file = request.files.get('image')
    selected_behaviors = request.form.getlist('behaviors')

    # 사진, 증상, 이상 행동 중 하나라도 입력되었는지 확인
    if not symptom_text and not (uploaded_file and uploaded_file.filename != '') and not selected_behaviors:
        return render_template('index.html', error="사진, 증상 설명, 이상 행동 중 하나는 반드시 입력해야 합니다."), 400

    image_path_relative = None
    if uploaded_file and uploaded_file.filename != '':
        try:
            image = Image.open(uploaded_file.stream)
            original_filename = secure_filename(uploaded_file.filename)
            filename_stem = os.path.splitext(original_filename)[0]
            new_filename = f"{filename_stem}.png"
            image_path_full = os.path.join(app.config['UPLOAD_FOLDER'], new_filename)
            image.save(image_path_full, 'PNG')
            image_path_relative = os.path.join(os.path.basename(app.config['UPLOAD_FOLDER']), new_filename).replace('\\', '/')
        except Exception as e:
            print(f"이미지 처리 중 오류 발생: {e}")
            return render_template('index.html', error=f"이미지 파일을 처리할 수 없습니다: {e}"), 400

    # 동기식으로 분석을 직접 수행하고 결과를 바로 렌더링합니다.
    try:
        result_data = run_analysis_task(dict(request.form), image_path_relative, selected_behaviors)

        # 로그인한 사용자의 경우, 분석 결과를 DB에 저장
        if current_user.is_authenticated:
            import json
            database_url = os.environ.get("DATABASE_URL")
            conn = None
            try:
                if database_url:
                    conn = psycopg2.connect(database_url)
                    cur = conn.cursor()
                    cur.execute("INSERT INTO analysis_history (user_id, analysis_result) VALUES (%s, %s)", (current_user.id, json.dumps(result_data)))
                else:
                    conn = sqlite3.connect(DB_FILE)
                    cur = conn.cursor()
                    cur.execute("INSERT INTO analysis_history (user_id, analysis_result) VALUES (?, ?)", (current_user.id, json.dumps(result_data)))
                conn.commit()
            finally:
                if conn:
                    conn.close()

        return render_template('results.html', result=result_data)
    except Exception as e:
        print(f"분석 처리 중 오류: {e}")
        # 오류 발생 시, results.html 페이지에 오류 내용을 직접 표시합니다.
        return render_template('results.html', result={"error": f"서버 처리 중 오류가 발생했습니다: {e}"})

@app.route('/login', methods=['GET', 'POST']) # 로그인 라우트
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        database_url = os.environ.get("DATABASE_URL")
        conn = None
        try:
            if database_url:
                conn = psycopg2.connect(database_url)
                cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                cur.execute("SELECT * FROM users WHERE username = %s", (username,))
            else:
                conn = sqlite3.connect(DB_FILE)
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                cur.execute("SELECT * FROM users WHERE username = ?", (username,))
            
            user_data = cur.fetchone()
            if user_data and bcrypt.checkpw(password.encode('utf-8'), user_data['password'].encode('utf-8')):
                user = User(id=user_data['id'], username=user_data['username'], is_admin=user_data['is_admin'])
                login_user(user)
                return redirect(url_for('index'))
            else:
                flash('사용자 이름 또는 비밀번호가 올바르지 않습니다.', 'danger')
        finally:
            if conn:
                conn.close()
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/register', methods=['GET', 'POST']) # 회원가입 라우트
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

        database_url = os.environ.get("DATABASE_URL")
        conn = None
        try:
            if database_url:
                conn = psycopg2.connect(database_url)
                cur = conn.cursor()
                cur.execute("INSERT INTO users (username, password) VALUES (%s, %s)", (username, hashed_password))
            else:
                conn = sqlite3.connect(DB_FILE)
                cur = conn.cursor()
                cur.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, hashed_password))
            conn.commit()
            flash('회원가입이 완료되었습니다. 로그인해주세요.', 'success')
            return redirect(url_for('login'))
        except (sqlite3.IntegrityError, psycopg2.IntegrityError):
            flash('이미 존재하는 사용자 이름입니다.', 'danger')
        finally:
            if conn:
                conn.close()
    return render_template('register.html')

@app.route('/admin') # 관리자 페이지 라우트
@login_required
def admin():
    if not current_user.is_admin:
        flash('관리자만 접근할 수 있습니다.', 'danger')
        return redirect(url_for('index'))
    
    database_url = os.environ.get("DATABASE_URL")
    conn = None
    try:
        if database_url:
            conn = psycopg2.connect(database_url)
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("SELECT id, username, is_admin FROM users ORDER BY id")
        else:
            conn = sqlite3.connect(DB_FILE)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("SELECT id, username, is_admin FROM users ORDER BY id")
        
        users = cur.fetchall()
        return render_template('admin.html', users=users)
    finally:
        if conn:
            conn.close()

@app.route('/admin/delete_user/<int:user_id>', methods=['POST']) # 사용자 삭제 라우트
@login_required
def delete_user(user_id):
    if not current_user.is_admin:
        flash('권한이 없습니다.', 'danger')
        return redirect(url_for('admin'))
    if user_id == current_user.id:
        flash('자기 자신은 삭제할 수 없습니다.', 'warning')
        return redirect(url_for('admin'))

    database_url = os.environ.get("DATABASE_URL")
    conn = None
    try:
        if database_url:
            conn = psycopg2.connect(database_url)
            cur = conn.cursor()
            # users 테이블에서 삭제 시 chat_history와 analysis_history도 자동으로 삭제됨 (ON DELETE CASCADE)
            cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
        else:
            conn = sqlite3.connect(DB_FILE)
            cur = conn.cursor()
            # SQLite는 외래 키 제약조건을 활성화해야 CASCADE가 동작함
            cur.execute("PRAGMA foreign_keys = ON")
            cur.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
        flash(f'사용자 ID {user_id}가 삭제되었습니다.', 'success')
    except Exception as e:
        flash(f'사용자 삭제 중 오류 발생: {e}', 'danger')
    finally:
        if conn:
            conn.close()
    return redirect(url_for('admin'))

@app.route('/history/delete/<int:history_id>', methods=['POST']) # 기록 삭제 라우트
@login_required
def delete_history(history_id):
    database_url = os.environ.get("DATABASE_URL")
    conn = None
    try:
        if database_url:
            conn = psycopg2.connect(database_url)
            cur = conn.cursor()
            # 현재 로그인한 사용자의 기록만 삭제하도록 user_id를 함께 확인
            cur.execute("DELETE FROM analysis_history WHERE id = %s AND user_id = %s", (history_id, current_user.id))
        else:
            conn = sqlite3.connect(DB_FILE)
            cur = conn.cursor()
            cur.execute("DELETE FROM analysis_history WHERE id = ? AND user_id = ?", (history_id, current_user.id))
        
        conn.commit()
        
        if cur.rowcount > 0:
            flash(f'분석 기록이 삭제되었습니다.', 'success')
        else:
            flash('삭제할 기록을 찾지 못했거나 권한이 없습니다.', 'danger')
    except Exception as e:
        flash(f'기록 삭제 중 오류가 발생했습니다: {e}', 'danger')
    finally:
        if conn:
            conn.close()
    return redirect(url_for('history'))

@app.route('/history') # 분석 기록 페이지 라우트
@login_required
def history():
    database_url = os.environ.get("DATABASE_URL")
    conn = None
    try:
        if database_url:
            conn = psycopg2.connect(database_url)
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("SELECT * FROM analysis_history WHERE user_id = %s ORDER BY created_at DESC", (current_user.id,))
        else:
            conn = sqlite3.connect(DB_FILE)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("SELECT * FROM analysis_history WHERE user_id = ? ORDER BY created_at DESC", (current_user.id,))
        
        history_records = cur.fetchall()
        
        # JSON 텍스트를 파이썬 딕셔너리로 변환
        import json
        if database_url:
            # Postgres의 JSONB는 이미 dict로 변환되어 오므로 추가 변환이 필요 없음
            processed_history = [dict(r) for r in history_records]
        else:
            # SQLite는 TEXT로 저장했으므로 JSON 파싱이 필요
            processed_history = []
            for record in history_records:
                processed_record = dict(record)
                processed_record['analysis_result'] = json.loads(processed_record['analysis_result'])
                processed_history.append(processed_record)

        return render_template('history.html', history=processed_history)
    finally:
        if conn:
            conn.close()

@app.route('/mypage') # 마이페이지 라우트
@login_required
def mypage():
    """마이페이지 렌더링"""
    return render_template('mypage.html')

@app.route('/obesity_check', methods=['GET', 'POST']) # 비만도 체크 라우트
@login_required
def obesity_check():
    """비만도 체크 기능"""
    if request.method == 'POST':
        pet_type = request.form.get('pet_type')
        age_years = float(request.form.get('age', 0))
        weight_kg = float(request.form.get('weight', 0))
        
        if pet_type == '고양이':
            result = assess_cat_obesity(age_years, weight_kg)
        else: # 강아지
            result = assess_dog_obesity(age_years, weight_kg)
        return render_template('obesity_check.html', result=result, pet_type=pet_type, age=age_years, weight=weight_kg)
    return render_template('obesity_check.html', result=None)

@app.route('/chatbot') # 챗봇 페이지 라우트
@login_required
def chatbot():
    """다이어트 플랜 챗봇 페이지를 렌더링합니다."""
    database_url = os.environ.get("DATABASE_URL")
    conn = None
    try:
        if database_url:
            conn = psycopg2.connect(database_url)
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("SELECT role, content FROM chat_history WHERE user_id = %s ORDER BY created_at ASC", (current_user.id,))
        else:
            conn = sqlite3.connect(DB_FILE)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("SELECT role, content FROM chat_history WHERE user_id = ? ORDER BY created_at ASC", (current_user.id,))
        
        history_records = cur.fetchall()
        # Gemini API가 요구하는 형식으로 변환: [{'role': 'user', 'parts': ['...']}, {'role': 'model', 'parts': ['...']}]
        chat_history = [{'role': record['role'], 'parts': [record['content']]} for record in history_records]

        return render_template('chatbot.html', history=chat_history)
    finally:
        if conn:
            conn.close()

@app.route('/ask_chatbot', methods=['POST']) # 챗봇 API 라우트
@login_required
def ask_chatbot():
    """챗봇의 질문에 답변하는 API 엔드포인트"""
    data = request.get_json()
    user_message = data.get('message')

    if not user_message:
        return jsonify({'error': '메시지가 없습니다.'}), 400

    try:
        # 챗봇을 위한 시스템 프롬프트
        system_prompt = """
        당신은 반려동물 영양학 전문 AI 챗봇입니다. 당신의 임무는 사용자와의 대화를 통해 반려동물의 정보를 얻고, 다이어트 계획을 제안하는 것입니다.
        
        **매우 중요한 규칙:**
        1. **극도로 간결하게, 단답형으로 답변하세요.** 모든 답변은 1-2문장 이내로, 핵심만 전달해야 합니다.
        2. **질문은 한 번에 하나씩만 하세요.** 예를 들어, "반려동물 종류는 무엇인가요?" 라고 묻고 사용자의 답변을 기다리세요.
        3. 사용자의 반려동물 종류, 현재 체중, 목표 체중, 나이, 활동 수준, 현재 먹는 사료 종류와 양 등의 정보를 파악하세요.
        4. 모든 정보가 모여 최종 계획을 제안할 때만 아래의 **[최종 계획 형식]**을 정확히 따르세요. 그 전까지는 절대 이 형식을 사용하지 마세요.
        5. 모든 조언의 마지막에는 "이 계획은 일반적인 가이드라인이며, 실제 적용 전에는 반드시 담당 수의사와 상담하시기 바랍니다." 라는 주의 문구를 포함해주세요.

        **[최종 계획 형식]**
        ### 맞춤 다이어트 플랜
        - **하루 사료 급여량:** [계산된 사료량, 예: 80g (현재 급여량의 90%)]
        - **간식 급여량:** [간식 관련 조언, 예: 하루 총 칼로리의 10% 미만, 또는 당분간 중단]
        - **활동량:** [구체적인 활동 제안, 예: 하루 2번, 각 15분씩 산책 또는 낚싯대 놀이]
        """

        # DB에서 이전 대화 기록 불러오기
        database_url = os.environ.get("DATABASE_URL")
        conn = None
        if database_url:
            conn = psycopg2.connect(database_url)
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("SELECT role, content FROM chat_history WHERE user_id = %s ORDER BY created_at ASC", (current_user.id,))
        else:
            conn = sqlite3.connect(DB_FILE)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("SELECT role, content FROM chat_history WHERE user_id = ? ORDER BY created_at ASC", (current_user.id,))
        
        history_records = cur.fetchall()
        history = [{'role': record['role'], 'parts': [record['content']]} for record in history_records]

        # 모델 초기화 및 대화 시작
        model = genai.GenerativeModel(
            'models/gemini-2.5-flash',
            system_instruction=system_prompt
        )
        chat = model.start_chat(history=history)
        response = chat.send_message(user_message, request_options={'timeout': 60})
        model_response = response.text

        # 사용자와 모델의 대화를 DB에 저장
        if database_url:
            cur.execute("INSERT INTO chat_history (user_id, role, content) VALUES (%s, %s, %s)", (current_user.id, 'user', user_message))
            cur.execute("INSERT INTO chat_history (user_id, role, content) VALUES (%s, %s, %s)", (current_user.id, 'model', model_response))
        else:
            cur.execute("INSERT INTO chat_history (user_id, role, content) VALUES (?, ?, ?)", (current_user.id, 'user', user_message))
            cur.execute("INSERT INTO chat_history (user_id, role, content) VALUES (?, ?, ?)", (current_user.id, 'model', model_response))
        conn.commit()

        return jsonify({'response': model_response})

    except Exception as e:
        print(f"챗봇 응답 생성 중 오류 발생: {e}")
        return jsonify({'error': '죄송합니다. 답변을 생성하는 중 오류가 발생했습니다.'}), 500
    finally:
        if conn:
            conn.close()

@app.route('/chatbot/reset', methods=['POST'])
@login_required
def reset_chatbot():
    """현재 사용자의 챗봇 대화 기록을 모두 삭제합니다."""
    database_url = os.environ.get("DATABASE_URL")
    conn = None
    try:
        if database_url:
            conn = psycopg2.connect(database_url)
            cur = conn.cursor()
            cur.execute("DELETE FROM chat_history WHERE user_id = %s", (current_user.id,))
        else:
            conn = sqlite3.connect(DB_FILE)
            cur = conn.cursor()
            cur.execute("DELETE FROM chat_history WHERE user_id = ?", (current_user.id,))
        conn.commit()
        flash('대화 내용이 초기화되었습니다.', 'success')
    finally:
        if conn:
            conn.close()
    return redirect(url_for('chatbot'))

_db_initialized = False # DB 초기화 플래그
@app.before_request
def initialize_database():
    """앱이 첫 요청을 받기 전에 딱 한 번 DB를 초기화합니다."""
    global _db_initialized
    if not _db_initialized:
        run_db_setup()
        _db_initialized = True

@app.errorhandler(500) # 500 에러 핸들러
def internal_error(error):
    print(f"500 Error: {error}")
    return "Internal Server Error", 500

# --- 5. 앱 실행 ---
if __name__ == '__main__':
    # 개발/테스트 시에는 waitress를 사용하여 Windows에서도 안정적으로 실행
    from waitress import serve
    port = int(os.environ.get('PORT', 5001))
    print(f"INFO: Starting web server on http://0.0.0.0:{port}")
    serve(app, host='0.0.0.0', port=port, channel_timeout=300)