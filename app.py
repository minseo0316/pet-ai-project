# app.py
import os
import sqlite3
import psycopg2
import psycopg2.extras
import google.generativeai as genai
import markdown  # 마크다운 변환을 위해 추가
from flask import Flask, request, render_template, url_for, redirect
from PIL import Image
from werkzeug.utils import secure_filename

from petai_utils import analyze_behaviors, assess_cat_obesity, assess_dog_obesity, BEHAVIOR_DB

# --- 1. Flask 앱 설정 ---
app = Flask(__name__)
UPLOAD_FOLDER = 'static/uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# --- 2. Gemini API 설정 ---
try:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY 환경 변수가 설정되지 않았습니다.")
    genai.configure(api_key=api_key)
except Exception as e:
    print(f"API 키 설정 오류: {e}")

# --- 3. 핵심 로직 함수 ---
def analyze_image(image_path):
    print("⚠️ 개발자 노트: 현재 이미지 분석은 '가짜' 결과('피부 발진')를 반환합니다.")
    return "피부 발진"

def search_db_by_image_label(image_label):
    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        try:
            conn = psycopg2.connect(database_url)
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            query = "SELECT * FROM diseases WHERE image_labels ILIKE %s"
            cur.execute(query, (f'%{image_label}%',))
            rows = cur.fetchall()
            cur.close()
            conn.close()
            return [dict(r) for r in rows]
        except Exception as e:
            print(f"Postgres(DB) 검색 중 오류 발생: {e}")
            return None

    DB_FILE = 'pet_health.db'
    if not os.path.exists(DB_FILE):
        print(f"데이터베이스 파일({DB_FILE})을 찾을 수 없습니다.")
        return None
    try:
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        query = "SELECT * FROM diseases WHERE image_labels LIKE ?"
        cursor.execute(query, (f'%{image_label}%',))
        results = cursor.fetchall()
        conn.close()
        return [dict(row) for row in results]
    except Exception as e:
        print(f"DB 검색 중 오류 발생: {e}")
        return None

# --- 4. Flask 라우트(경로) 설정 ---
@app.route('/')
def index():
    behavior_options = list(BEHAVIOR_DB.keys())
    return render_template('index.html', behaviors=behavior_options)

@app.route('/analyze', methods=['POST'])
def analyze():
    pet_type = request.form.get('pet_type', '고양이')
    symptom_text = request.form.get('symptoms', '').strip()
    uploaded_file = request.files.get('image')
    selected_behaviors = request.form.getlist('behaviors')
    age_years = float(request.form.get('age', 2.0))
    weight_kg = float(request.form.get('weight', 4.5))

    if not symptom_text and not uploaded_file:
        return render_template('index.html', error="사진 또는 증상 중 하나는 반드시 입력해야 합니다.", behaviors=list(BEHAVIOR_DB.keys()))

    result_data = {}
    prompt_contexts = []

    try:
        # --- 이미지 처리 (이미지가 있는 경우) ---
        if uploaded_file and uploaded_file.filename != '':
            filename = secure_filename(uploaded_file.filename)
            image_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            uploaded_file.save(image_path)
            result_data['image_path'] = os.path.join(os.path.basename(app.config['UPLOAD_FOLDER']), filename).replace('\\', '/')

            image_result_label = analyze_image(image_path)
            db_results = search_db_by_image_label(image_result_label)

            prompt_contexts.append(f"[사진 분석 결과 라벨]\n{image_result_label}")
            if db_results:
                prompt_contexts.append(f"[사진 분석과 관련된 수의학 지식 (DB 검색 결과)]\n{db_results}")
            else:
                 prompt_contexts.append("[사진 분석과 관련된 수의학 지식 (DB 검색 결과)]\n일치하는 정보를 찾지 못했습니다.")

        # --- 증상 텍스트 처리 (증상이 있는 경우) ---
        if symptom_text:
            prompt_contexts.append(f"[보호자 관찰 내용]\n{symptom_text}")

        # --- Gemini 프롬프트 구성 및 호출 ---
        model = genai.GenerativeModel('models/gemini-pro-latest')
        
        mission = ""
        if symptom_text and uploaded_file:
            mission = "위의 [사진 분석과 관련된 수의학 지식]을 바탕으로, [보호자 관찰 내용]과 [사진 분석 결과 라벨]을 종합하여"
        elif uploaded_file:
            mission = "위의 [사진 분석과 관련된 수의학 지식]과 [사진 분석 결과 라벨]을 바탕으로,"
        else: # symptom_text only
            mission = "[보호자 관찰 내용]을 바탕으로,"

        prompt = f'''
        당신은 전문 {pet_type} 수의사 AI 조수입니다.

        {chr(10).join(prompt_contexts)}

        ---
        [임무]
        {mission} 보호자에게 가장 가능성이 높은 질병과 경고, 조언을 생성해주세요.
        만약 [사진 분석과 관련된 수의학 지식]이 제공되었다면, 해당 내용을 우선적으로 참고하여 답변을 구성하세요.
        증상만으로 판단이 어려울 경우, 여러 가능성을 제시하고 사진 등의 추가 정보를 요청할 수 있습니다.
        답변은 반드시 아래 [출력 형식]을 따라야 합니다.

        [규칙]
        1. 절대 '진단'을 내리지 말고, "~일 수 있습니다", "~이 의심됩니다" 또는 "~와 유사한 증상입니다"라고 표현하세요.
        2. 모든 내용은 한국어로 작성해주세요.
        3. 마지막에 "본 결과는 AI의 분석이며, 수의사의 진단을 대체할 수 없습니다. 정확한 상태 확인을 위해 반드시 동물병원을 방문하세요."라는 경고 문구를 명확하게 추가하세요.

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

        return render_template('index.html', result=result_data, behaviors=list(BEHAVIOR_DB.keys()))

    except Exception as e:
        print(f"분석 중 오류 발생: {e}")
        return render_template('index.html', error=f"분석 중 오류가 발생했습니다: {e}", behaviors=list(BEHAVIOR_DB.keys()))

# --- 5. 앱 실행 ---
if __name__ == '__main__':
    app.run(debug=True, port=5001)
