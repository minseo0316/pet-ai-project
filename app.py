# app.py
import os
import sqlite3
from flask import Flask, request, render_template, url_for, redirect, jsonify
import psycopg2
import psycopg2.extras
import google.generativeai as genai
import markdown
from flask_rq2 import RQ
from PIL import Image
from werkzeug.utils import secure_filename

from petai_utils import analyze_behaviors, assess_cat_obesity, assess_dog_obesity, BEHAVIOR_DB

# --- 1. Flask 앱 설정 ---
app = Flask(__name__)
UPLOAD_FOLDER = 'static/uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# --- RQ (작업 큐) 설정 ---
app.config['RQ_REDIS_URL'] = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
rq = RQ(app)


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
    """실제 Gemini Vision 모델을 사용하여 이미지를 분석하고 라벨을 반환합니다."""
    try:
        print(f"INFO: Analyzing image at {image_path} with Gemini Vision...")
        image_file = genai.upload_file(path=image_path)
        model = genai.GenerativeModel('models/gemini-pro-vision')
        prompt = "이 반려동물 사진에서 가장 두드러지는 의학적 증상이나 상태를 두세 단어의 핵심 키워드로 요약해줘. (예: 피부 발진, 눈 충혈, 정상적인 털)"
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
        model = genai.GenerativeModel('models/gemini-pro-latest')

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
        return render_template('index.html', error="사진 또는 증상 중 하나는 반드시 입력해야 합니다.", behaviors=list(BEHAVIOR_DB.keys()))

    image_path_relative = None
    if uploaded_file and uploaded_file.filename != '':
        # Pillow를 사용하여 이미지를 열고 PNG로 변환하여 안정성을 높입니다.
        try:
            image = Image.open(uploaded_file.stream)
            original_filename = secure_filename(uploaded_file.filename)
            # 파일 확장자를 .png로 통일합니다.
            filename_stem = os.path.splitext(original_filename)[0]
            new_filename = f"{filename_stem}.png"
            image_path_full = os.path.join(app.config['UPLOAD_FOLDER'], new_filename)
            image.save(image_path_full, 'PNG')
            image_path_relative = os.path.join(os.path.basename(app.config['UPLOAD_FOLDER']), new_filename).replace('\\', '/')
        except Exception as e:
            print(f"이미지 처리 중 오류 발생: {e}")
            return render_template('index.html', error=f"이미지 파일을 처리할 수 없습니다: {e}", behaviors=list(BEHAVIOR_DB.keys()))

    # request.form은 워커에서 직접 접근할 수 없으므로 딕셔너리로 변환하여 전달합니다.
    selected_behaviors = request.form.getlist('behaviors')
    job = rq.get_queue().enqueue(run_analysis_task, args=(dict(request.form), image_path_relative, selected_behaviors))

    # 사용자를 결과 로딩 페이지로 리디렉션합니다.
    return redirect(url_for('loading', job_id=job.id))

@app.route('/loading/<job_id>')
def loading(job_id):
    # 로딩 페이지를 렌더링합니다. 이 페이지는 JS를 통해 결과를 폴링합니다.
    return render_template('loading.html', job_id=job_id)

@app.route('/results/<job_id>')
def get_results(job_id):
    job = rq.get_queue().fetch_job(job_id)
    if job:
        if job.is_finished:
            # 작업이 성공적으로 완료됨
            return jsonify({'status': 'finished', 'result': job.result})
        elif job.is_failed:
            # 작업 실패
            return jsonify({'status': 'failed'})
    # 작업이 아직 진행 중이거나 존재하지 않음
    return jsonify({'status': 'pending'})

@app.route('/show_result/<job_id>')
def show_result(job_id):
    job = rq.get_queue().fetch_job(job_id)
    if job and job.is_finished:
        # 작업이 완료되었으면, 결과를 results.html 템플릿에 전달하여 렌더링
        return render_template('results.html', result=job.result)
    else:
        # 작업이 없거나 아직 끝나지 않았으면 로딩 페이지로 다시 보냄
        return redirect(url_for('loading', job_id=job_id))

# --- 5. 앱 실행 ---
if __name__ == '__main__':
    # 개발/테스트 시에는 waitress를 사용하여 Windows에서도 안정적으로 실행
    from waitress import serve
    print("INFO: Starting web server on http://localhost:5001")
    serve(app, host='0.0.0.0', port=5001)
