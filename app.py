# app.py
import os
import sqlite3
from flask import Flask, request, render_template, url_for, jsonify
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
import psycopg2, psycopg2.extras
import google.generativeai as genai
import markdown
from PIL import Image
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
import bcrypt
from petai_utils import analyze_behaviors, assess_cat_obesity, assess_dog_obesity, BEHAVIOR_DB


# --- 1. Flask 앱 설정 ---
app = Flask(__name__)
UPLOAD_FOLDER = 'static/uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

DB_FILE = 'pet_health.db'

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
    ("슬개골 탈구 (강아지)", "다리를 절음,깽깽이걸음,다리를 들고 뜀", "깽깽이걸음,다리를 절음,무릎에서 소리가 남", "경고 🔴", "깽깽이걸음이나 다리를 저는 증상은 슬개골 탈구의 대표적인 증상입니다. 특히 소형견에게 흔하게 발생합니다. 방치할 경우 관절염으로 악화될 수 있으니, 정형외과 전문 동물병원에서 정확한 단계를 진단받고 수술 여부를 상담하는 것이 좋습니다.")
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

            conn.close()
        except Exception as e:
            print(f"SQLite DB 설정 중 오류 발생: {e}")


# --- 3. 핵심 로직 함수 ---
def analyze_image(image_path):
    """실제 Gemini Vision 모델을 사용하여 이미지를 분석하고 라벨을 반환합니다."""
    try:
        print(f"INFO: Analyzing image at {image_path} with Gemini Vision...")
        image_file = genai.upload_file(path=image_path)
        model = genai.GenerativeModel('models/gemini-2.5-flash')
        prompt = """
        당신은 수의학 지식이 있는 AI 보조원입니다.
        이 반려동물 사진에서 관찰할 수 있는 모든 잠재적인 의학적 증상을 자세히 묘사해주세요.
        눈, 코, 입, 귀, 피부, 털 상태, 자세 등 구체적인 부위에 집중해서 설명해주세요.
        만약 여러 증상이 보인다면 모두 나열해주세요. (예: 왼쪽 눈의 탁한 분비물, 코 주변의 약간의 붉은 기, 가슴 부분의 뭉친 털)
        만약 특별한 이상 징후 없이 건강해 보인다면 '외관상 특이 소견 없음' 이라고 답변해주세요.
        """
        response = model.generate_content([prompt, image_file])
        
        # 응답 후 파일 상태 확인 및 삭제
        while image_file.state.name == "PROCESSING":
            print('... Still processing file')
            image_file.get_file()
        genai.delete_file(image_file.name)
        print(f"INFO: Image analysis result: {response.text.strip()}")
        return response.text.strip()
    except Exception as e:
        print(f"이미지 분석 중 오류 발생: {e}")
        return "이미지 분석 실패"

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
    age_years = float(form_data.get('age', 2.0))
    weight_kg = float(form_data.get('weight', 4.5))

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

        mission = "" # mission 변수 초기화
        if symptom_text and image_path_relative:
            mission = "위의 [사진 분석과 관련된 수의학 지식]을 바탕으로, [보호자 관찰 내용]과 [사진 분석 결과 라벨]을 종합하여" 
        elif image_path_relative:
            mission = "위의 [사진 분석과 관련된 수의학 지식]과 [사진 분석 결과 라벨]을 바탕으로,"
        else: # symptom_text only
            mission = "[보호자 관찰 내용]을 바탕으로,"

        # --- Gemini 모델 초기화 ---
        model = genai.GenerativeModel('models/gemini-2.5-flash')

        if 'image_analysis_label' in result_data:
            prompt_contexts.append(f"[사진 분석 결과 라벨]\n{result_data['image_analysis_label']}")

        prompt = f'''
        당신은 전문 {pet_type} 수의사 AI 조수입니다. {", ".join(prompt_contexts)}


        ---
        [임무]
        {mission} 보호자에게 가장 가능성이 높은 질병과 경고, 조언을 생성해주세요.
        만약 [사진 분석과 관련된 수의학 지식]이 제공되었다면, 해당 내용을 우선적으로 참고하여 답변을 구성하세요.
        증상만으로 판단이 어려울 경우, 여러 가능성을 제시하고 사진 등의 추가 정보를 요청할 수 있습니다.
        답변은 반드시 아래 [출력 형식]을 따라야 합니다.

        [규칙] 
        [출력 형식]
        ### 핵심 요약
        (모든 내용을 한두 문장으로 요약)
        ### 상세 설명
        (의심되는 점과 그 이유를 자세히 설명)
        ### 권장 조치
        (보호자가 해야 할 일, 예를 들어 병원 방문 권유 등)
        '''
        response = model.generate_content(prompt)
        # Gemini가 생성한 마크다운 텍스트를 HTML로 변환
        result_data['gemini_response'] = markdown.markdown(response.text)

        # --- 추가 분석 (이상행동, 비만) ---
        if selected_behaviors:
            result_data['behavior_analysis'] = analyze_behaviors(selected_behaviors, symptom_text)
        
        if pet_type == '고양이':
            result_data['obesity_analysis'] = assess_cat_obesity(age_years, weight_kg)
        elif pet_type == '강아지':
            result_data['obesity_analysis'] = assess_dog_obesity(age_years, weight_kg)

        return result_data

    except Exception as e:
        print(f"분석 중 오류 발생: {e}")
        # 오류 발생 시 오류 정보를 담은 딕셔너리 반환
        return {"error": f"분석 중 오류가 발생했습니다: {e}"}

# --- 4. Flask 라우트(경로) 설정 ---
@app.route('/')
def index():
    behavior_options = list(BEHAVIOR_DB.keys())
    return render_template('index.html', behaviors=behavior_options)

@app.route('/analyze', methods=['POST'])
def analyze():
    symptom_text = request.form.get('symptoms', '').strip()
    uploaded_file = request.files.get('image')

    if not symptom_text and not (uploaded_file and uploaded_file.filename != ''):
        return render_template('index.html', error="사진 또는 증상 중 하나는 반드시 입력해야 합니다.", behaviors=list(BEHAVIOR_DB.keys())), 400

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
            return render_template('index.html', error=f"이미지 파일을 처리할 수 없습니다: {e}", behaviors=list(BEHAVIOR_DB.keys())), 400

    selected_behaviors = request.form.getlist('behaviors')

    # 동기식으로 분석을 직접 수행하고 결과를 바로 렌더링합니다.
    try:
        result_data = run_analysis_task(dict(request.form), image_path_relative, selected_behaviors)
        # 분석이 끝나면 바로 결과 페이지를 보여줍니다.
        return render_template('results.html', result=result_data, behaviors=list(BEHAVIOR_DB.keys()))
    except Exception as e:
        print(f"분석 처리 중 오류: {e}")
        # 오류 발생 시, 에러 메시지와 함께 메인 페이지로 돌아갑니다.
        return render_template('index.html', error=f"분석 처리 중 오류가 발생했습니다: {e}", behaviors=list(BEHAVIOR_DB.keys())), 500

# --- 사용자 인증 관련 라우트 ---
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

@app.route('/register', methods=['GET', 'POST'])
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

@app.route('/login', methods=['GET', 'POST'])
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

@app.route('/admin')
@login_required
def admin():
    if not current_user.is_admin:
        flash('관리자만 접근할 수 있습니다.', 'danger')
        return redirect(url_for('index'))
    # 여기에 사용자 관리 로직 추가 예정
    return "<h1>관리자 페이지</h1><p>환영합니다, 관리자님!</p>"

_db_initialized = False
@app.before_request
def initialize_database():
    """앱이 첫 요청을 받기 전에 딱 한 번 DB를 초기화합니다."""
    global _db_initialized
    if not _db_initialized:
        run_db_setup()
        _db_initialized = True

@app.errorhandler(500)
def internal_error(error):
    print(f"500 Error: {error}")
    return render_template('index.html', error="서버 오류가 발생했습니다. 다시 시도해주세요.", behaviors=list(BEHAVIOR_DB.keys())), 500

# --- 5. 앱 실행 ---
if __name__ == '__main__':
    # 개발/테스트 시에는 waitress를 사용하여 Windows에서도 안정적으로 실행
    from waitress import serve
    port = int(os.environ.get('PORT', 5001))
    print(f"INFO: Starting web server on http://0.0.0.0:{port}")
    serve(app, host='0.0.0.0', port=port)
