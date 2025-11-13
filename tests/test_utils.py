import pytest
from petai_utils import analyze_behaviors, assess_cat_obesity, assess_dog_obesity


def test_analyze_behaviors_basic():
    behaviors = ["과도한 핥기", "설사"]
    text = "피부에 발진과 탈모가 있습니다."
    res = analyze_behaviors(behaviors, text)
    assert isinstance(res, list)
    assert any(r['behavior'] == '과도한 핥기' for r in res)
    # 우선순위 표시가 있어야 함
    assert any(r.get('priority') == '높음' for r in res)


def test_assess_cat_obesity():
    # 어린 고양이
    r = assess_cat_obesity(0.5, 2.0)
    assert r['assessable'] is False

    # 정상
    r = assess_cat_obesity(3.0, 4.5)
    assert r['status'] == '정상'

    # 과체중
    r = assess_cat_obesity(4.0, 5.9)
    assert r['status'] == '과체중'

    # 비만
    r = assess_cat_obesity(5.0, 6.0)
    assert r['status'] == '비만'


def test_assess_dog_obesity():
    # 어린 강아지
    r = assess_dog_obesity(0.5, 5.0)
    assert r['assessable'] is False

    # 성견
    r = assess_dog_obesity(3.0, 15.0)
    assert r['assessable'] is True
    assert r['status'] == '평가 가이드'
