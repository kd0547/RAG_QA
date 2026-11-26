"""용어집 도구(lookup_terms)와 사양 비교의 용어집 표기 맞추기.

- lookup_terms: 회사 용어 -> 표준 용어·다른 표기·연결된 사양 속성 키 (묶음이면 구성 용어)
- compare_specs(spec_service): 조건 값이 용어 표기 하나와 같으면 그 용어의 다른 표기로도 맞춘다
  ("스피커" ↔ "Built in two speakers"). 근거는 사양 DB 값이고 용어집은 표기를 맞추는 데만 쓴다.
"""
import pytest

import repository
from agent import spec_service
from repository.repo_connect import Database
from repository.spec_repository import SpecRepository
from repository.term_repository import TermRepository


@pytest.fixture
def env(tmp_path, monkeypatch):
    db = Database(str(tmp_path / "terms.db"))
    specs, terms = SpecRepository(db), TermRepository(db)
    monkeypatch.setattr(repository, "spec_repo", specs)
    monkeypatch.setattr(repository, "term_repo", terms)
    specs.create_attribute("audio", "오디오", "io", "text", "")
    specs.create_attribute("os", "운영체제", "os", "text", "")
    a650 = specs.create_product("A650-GA70-PU02")
    specs.add_spec("product", a650["id"], "audio", "HD Audio, Built in two speakers, Built in array microphone")
    specs.add_spec("product", a650["id"], "os", "Windows 11 Pro")
    return specs, terms, a650


def _lookup(text):
    from tools.tool import lookup_terms

    return lookup_terms.invoke({"text": text})


def test_lookup_terms_maps_words_to_terms_and_spec_keys(env):
    _, terms, _ = env
    terms.create("스피커", ["내장 스피커", "speaker", "speakers"], "spec_attribute", "audio")
    emc = terms.create("적합성 등록", ["전자파 인증"])
    terms.create("KC 인증 자료", ["KC 인증"], members=[emc["id"]])

    result = _lookup("내장 스피커, 무게\nKC 인증")

    assert result["not_found"] == ["무게"]
    speaker, kc = result["found"]
    assert speaker == {"question_text": "내장 스피커", "term": "스피커", "aliases": ["내장 스피커", "speaker", "speakers"],
                       "target": "사양:오디오", "spec_attribute_key": "audio"}
    assert kc["kind"] == "bundle" and [m["term"] for m in kc["members"]] == ["적합성 등록"]


def test_lookup_terms_empty_glossary(env):
    assert _lookup("스피커") == {"found": [], "not_found": ["스피커"]}


def _audio(env, value, op="contains"):
    _, _, a650 = env
    result = spec_service.compare("product", a650["id"], [{"attribute": "audio", "op": op, "value": value}])
    return result["results"][0]


def test_compare_contains_uses_glossary_spellings(env):
    _, terms, _ = env
    assert _audio(env, "스피커")["verdict"] == "unknown"  # 용어집이 없으면 글자가 달라 판정 불가

    terms.create("스피커", ["내장 스피커", "speaker"], "spec_attribute", "audio")
    result = _audio(env, "내장 스피커")
    assert result["verdict"] == "met" and "용어집 '스피커'" in result["reason"]
    assert _audio(env, "스피커")["verdict"] == "met"


def test_compare_glossary_needs_whole_condition_and_matching_target(env):
    _, terms, _ = env
    terms.create("스피커", ["speaker"], "spec_attribute", "audio")
    terms.create("마이크", ["microphone"], "spec_attribute", "os")  # 다른 속성에 연결된 용어는 쓰지 않는다
    terms.create("블루투스", ["bluetooth"])  # 값에 없는 표기

    assert _audio(env, "스피커 4개")["verdict"] == "unknown"  # 조건 일부만 용어면 나머지를 건너뛰지 않는다
    assert _audio(env, "마이크")["verdict"] == "unknown"
    assert _audio(env, "블루투스")["verdict"] == "unknown"


def test_compare_glossary_term_without_target_and_equals(env):
    specs, terms, a650 = env
    terms.create("윈도우 11 프로", ["Windows 11 Pro", "Win11 Pro"])
    result = spec_service.compare("product", a650["id"], [{"attribute": "os", "op": "==", "value": "윈도우 11 프로"}])
    assert result["results"][0]["verdict"] == "met"


def test_lookup_terms_is_an_agent_tool():
    from agent.agent import active_tools

    assert "lookup_terms" in {t.name for t in active_tools()}
