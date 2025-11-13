import base64
from io import BytesIO
from PIL import Image

# --- 이상행동 DB 및 분석 함수 ---
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


def analyze_behaviors(selected_behaviors, symptom_text):
    """선택된 이상행동 목록과 보호자 관찰 문장을 받아 간단한 코칭 및 의심 원인을 리턴합니다."""
    results = []
    for b in selected_behaviors:
        info = BEHAVIOR_DB.get(b)
        if not info:
            results.append({"behavior": b, "note": "추가 정보 없음"})
        else:
            results.append({
                "behavior": b,
                "possible_causes": info["possible_causes"],
                "coaching": info["coaching"]
            })
    # 간단한 텍스트 기반 보강: 증상 텍스트에 특정 키워드가 있으면 우선순위 표시
    if symptom_text:
        low = symptom_text.lower()
        for r in results:
            if any(k in low for k in ["피부", "발진", "탈모"]) and "피부" in r["behavior"]:
                r["priority"] = "높음"
    return results


def assess_cat_obesity(age_years, weight_kg):
    """
    매우 단순한 비만 판정 로직.
    가정: 성묘(>=1 year)의 이상 체중 기준은 평균 체중 4.5kg을 기준으로 판단.
    - 과체중: 20% 초과
    - 비만: 30% 초과

    (주의) 품종, 체격, 성별 등에 따라 차이가 크므로 실제 진단은 수의사와 상의해야 합니다.
    """
    if age_years < 1.0:
        return {"assessable": False, "message": "1세 미만의 고양이는 성장 단계로 체중만으로 비만 판정이 어렵습니다."}

    ideal = 4.5  # 단순 평균 가정
    if weight_kg <= ideal * 1.2:
        return {"assessable": True, "status": "정상", "ideal_kg": ideal, "message": "현재 체중은 대략 정상 범위입니다."}
    elif weight_kg <= ideal * 1.3:
        return {"assessable": True, "status": "과체중", "ideal_kg": ideal, "message": "과체중으로 식이조절 및 운동을 권장합니다."}
    else:
        return {"assessable": True, "status": "비만", "ideal_kg": ideal, "message": "비만으로 판단됩니다. 식이관리와 운동, 수의사와의 상담을 권장합니다."}


def assess_dog_obesity(age_years, weight_kg):
    """
    강아지 비만도(BCS) 평가 가이드.
    강아지는 품종별 차이가 커서 체중만으로 비만을 판단하기 어렵습니다.
    대신, 신체 상태 점수(Body Condition Score, BCS)를 시각 및 촉각으로 평가하는 방법을 안내합니다.
    """
    if age_years < 1.0:
        return {"assessable": False, "message": "1세 미만의 강아지는 성장 단계로 체중만으로 비만 판정이 어렵습니다."}

    guide = """
    **강아지 신체 상태 점수(BCS) 자가 평가 가이드**

    강아지의 비만도는 체중계 숫자보다 몸 상태를 직접 확인하는 것이 더 정확합니다. 아래 가이드를 따라 반려견의 신체 상태를 평가해보세요.

    **1. 갈비뼈 확인:**
       - **이상적:** 갈비뼈가 눈으로는 보이지 않지만, 가슴 옆을 부드럽게 만졌을 때 쉽게 느껴져야 합니다. 얇은 담요 위로 손가락을 스치는 느낌과 비슷합니다.
       - **마름:** 갈비뼈, 등뼈, 골반뼈가 멀리서도 쉽게 보입니다.
       - **과체중/비만:** 두꺼운 지방층에 덮여 갈비뼈가 잘 만져지지 않습니다.

    **2. 허리 라인 확인:**
       - **이상적:** 위에서 내려다봤을 때, 가슴 뒤쪽으로 허리 라인이 잘록하게 들어가 보여야 합니다.
       - **마름:** 허리 라인이 매우 심하게 들어가 있습니다.
       - **과체중/비만:** 허리 라인이 없거나, 오히려 옆으로 불룩 튀어나와 보입니다.

    **3. 복부 라인 확인:**
       - **이상적:** 옆에서 봤을 때, 가슴에서부터 뒷다리 쪽으로 복부가 완만하게 위로 올라가는 곡선이 보여야 합니다.
       - **마름:** 복부 라인이 급격하게 위로 치솟아 있습니다.
       - **과체중/비만:** 복부 라인이 수평이거나 아래로 처져 있습니다.

    **평가:**
    - **이상적인 상태**라면 건강한 체중입니다.
    - **과체중/비만**에 해당된다면, 식사량을 조절하고 활동량을 늘리는 것이 좋습니다. 정확한 진단과 관리 계획을 위해 수의사와 상담하는 것을 강력히 권장합니다.
    """
    return {"assessable": True, "status": "평가 가이드", "message": guide}


def analyze_image(image_obj):
    """
    간단한 placeholder 이미지 분석 함수.
    - 기본 동작: 업로드된 PIL.Image 객체를 받아 임시 라벨('피부 발진')을 반환합니다.
    - 실제 Gemini 멀티모달 연동 시 이 함수를 교체하거나 내부에 호출을 추가하세요.

    주의: 이 모듈은 스트림릿이나 API 키를 직접 참조하지 않도록 설계되어 있어
    테스트(유닛 테스트) 시 안전하게 임포트할 수 있습니다.
    """
    try:
        # 간단한 히ュー리스틱(예시): 이미지 높이가 넓이보다 크면 '피부 발진'으로 가정
        w, h = image_obj.size
        if h > w:
            return "피부 발진"
        return "정상 피부"
    except Exception:
        return "알 수 없음"

    # === Gemini 멀티모달 연동 예시(주석) ===
    # 아래는 실제 호출 예시로, 실행하려면 API 키 설정과 네트워크가 필요합니다.
    # import google.generativeai as genai
    # img_bytes = BytesIO()
    # image_obj.save(img_bytes, format='PNG')
    # b64 = base64.b64encode(img_bytes.getvalue()).decode('ascii')
    # prompt = f"이미지(base64): {b64}\n요약해서 이 이미지의 주요 라벨을 한 단어로 알려주세요."
    # model = genai.GenerativeModel('gemini-1.5')
    # resp = model.generate_content(prompt)
    # return resp.text.splitlines()[0]
