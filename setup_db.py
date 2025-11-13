# 파일 이름: setup_db.py
import os
import sqlite3

# 초기 데이터
diseases_data = [
    (
        "알레르기성 피부염 (의심)",
        "피부 발진,붉은 반점,탈모",
        "가려움,핥음,비빔,발적",
        "주의 🟡",
        "사진과 증상으로 볼 때 '알레르기성 피부염'이 의심됩니다. 원인(사료, 간식, 집먼지 등)을 찾아보고, 증상이 지속되면 병원을 방문해 정확한 알레르기 원인을 찾는 것이 좋습니다."
    ),
    (
        "백내장 (초기 의심)",
        "흐릿한 눈,하얀 동공",
        "눈을 잘 못 마주침,밤에 잘 부딪힘,눈이 뿌옇게 보임",
        "경고 🔴",
        "사진상 동공이 뿌옇게 보이는 것은 '백내장'의 초기 징후일 수 있습니다. 방치하면 시력을 잃을 수 있으니 즉시 안과 전문 동물병원을 방문하여 검사를 받으세요."
    ),
    (
        "결막염 (의심)",
        "붉은 눈,눈곱,눈물",
        "눈을 찡그림,눈 주변을 비빔",
        "주의 🟡",
        "눈이 붉어지고 눈곱이 끼는 증상은 '결막염'일 수 있습니다. 세균 감염이나 알레르기 때문일 수 있으니, 병원에서 안약을 처방받아 치료하는 것이 좋습니다."
    ),
    (
        "정상 피부",
        "정상 피부",
        "특별한 증상 없음",
        "안전 🟢",
        "사진과 증상으로는 특별한 이상 징후가 보이지 않습니다. 건강한 상태로 보입니다. 하지만 평소와 다른 행동을 보인다면 주의 깊게 관찰해주세요."
    )
]


def run_sqlite_setup(db_file='pet_health.db'):
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS diseases (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        disease_name TEXT NOT NULL,
        image_labels TEXT,
        text_symptoms TEXT,
        warning_level TEXT,
        advice TEXT
    )
    ''')
    print("SQLite: 테이블 생성 완료 (또는 이미 존재함).")
    cursor.execute("DELETE FROM diseases")
    cursor.executemany('''
    INSERT INTO diseases (disease_name, image_labels, text_symptoms, warning_level, advice)
    VALUES (?, ?, ?, ?, ?)
    ''', diseases_data)
    conn.commit()
    conn.close()
    print(f"SQLite: {len(diseases_data)}개의 초기 질병 데이터가 DB에 저장되었습니다.")


def run_postgres_setup(database_url):
    import psycopg2
    import psycopg2.extras
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
        cur.execute('DELETE FROM diseases')
        insert_q = '''INSERT INTO diseases (disease_name, image_labels, text_symptoms, warning_level, advice) VALUES (%s,%s,%s,%s,%s)'''
        cur.executemany(insert_q, diseases_data)
        conn.commit()
        cur.close()
        conn.close()
        print(f"Postgres: {len(diseases_data)}개의 초기 질병 데이터가 DB에 저장되었습니다.")
    except Exception as e:
        print(f"Postgres 설정 중 오류 발생: {e}")


if __name__ == '__main__':
    # 우선적으로 환경변수 DATABASE_URL을 사용
    db_url = os.environ.get('DATABASE_URL')
    if not db_url:
        # Streamlit secrets에서도 확인 가능하지만 setup 스크립트는 일반적으로 환경변수 사용 권장
        print("DATABASE_URL이 설정되어 있지 않습니다. 로컬 sqlite를 사용하여 DB를 초기화합니다.")
        run_sqlite_setup()
    else:
        print("DATABASE_URL이 설정되어 있어 Postgres(DB)에 테이블을 생성/초기화합니다.")
        run_postgres_setup(db_url)