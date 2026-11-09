"""문서 그래프: 추출 결과 정리, 페이지 단위 저장, 상위 개념 펼치기, 문서 순위를 확인한다.

임시 SQLite DB와 가짜 LLM을 쓴다.
"""
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
# tests/parser.py가 parser 패키지를 가리지 않게 한다
if not hasattr(sys.modules.get("parser"), "__path__"):
    sys.modules.pop("parser", None)

from agent.prompt import GRAPH_GUIDE, render_prompt  # noqa: E402
from entity.file import create_file  # noqa: E402
from graph_rag import service  # noqa: E402
from graph_rag.extractor import extract_page_graph  # noqa: E402
from graph_rag.types import ExtractedEntity, ExtractedRelation, PageGraph, normalize  # noqa: E402
from parser.pdf.type import PageText  # noqa: E402
from repository.file_page_repository import FilePageRepository  # noqa: E402
from repository.file_repository import FileRepository  # noqa: E402
from repository.graph_repository import GraphRepository  # noqa: E402
from repository.repo_connect import Database  # noqa: E402

KC = {"KC 인증": ["안전확인 신고", "적합성 등록"]}


class FakeLLM:
    """with_structured_output(...).invoke(...)가 정해 둔 PageGraph를 돌려준다."""

    def __init__(self, graph: PageGraph):
        self.graph = graph
        self.calls = []

    def with_structured_output(self, schema):
        return self

    def invoke(self, messages):
        self.calls.append(messages)
        return self.graph.model_copy(deep=True)


@pytest.fixture
def env(tmp_path, monkeypatch):
    db = Database(str(tmp_path / "graph.db"))
    files, pages, graph = FileRepository(db), FilePageRepository(db), GraphRepository(db)
    monkeypatch.setattr(service, "file_repo", files)
    monkeypatch.setattr(service, "page_repo", pages)
    monkeypatch.setattr(service, "graph_repo", graph)

    def add_file(name: str):
        file = create_file(original_name=name, stored_path=str(tmp_path / name))
        files.file_save(file)
        return file

    return files, pages, graph, add_file


def _entity(type_, name, *aliases):
    return ExtractedEntity(type=type_, name=name, aliases=list(aliases))


def test_normalize_ignores_case_spaces_and_symbols():
    assert normalize("KC 인증") == normalize("kc인증") == "kc인증"
    assert normalize("R-R-TGE-N5800") == "rrtgen5800"


def test_extractor_drops_names_not_on_page_and_adds_kc_number():
    page = "노트북 N5800 방송통신기자재 적합성 등록 필증. 등록번호 R-R-TGE-N5800"
    llm = FakeLLM(PageGraph(entities=[
        _entity("product", "N5800", "N 5800", "N5800 15인치"),  # 마지막 별칭은 페이지에 없다
        _entity("certification", "적합성 등록"),
        _entity("organization", "국립전파연구원"),  # 페이지에 없는 이름 (LLM이 지어냄)
    ]))

    graph = extract_page_graph(page, llm=llm)

    names = {(e.type, e.name) for e in graph.entities}
    assert ("organization", "국립전파연구원") not in names
    assert ("cert_number", "R-R-TGE-N5800") in names
    product = next(e for e in graph.entities if e.name == "N5800")
    assert product.aliases == ["N 5800"]


def test_extractor_fills_relation_endpoints_and_keeps_known_concepts():
    page = "A650 구성: NVIDIA GeForce RTX 5070. 인증: KC 안전확인, KC 적합등록, 우수조달"
    llm = FakeLLM(PageGraph(
        entities=[
            _entity("product", "A650"),
            ExtractedEntity(type="certification", name="KC 안전확인", concept="KC인증"),  # 표기만 다른 개념 이름
            ExtractedEntity(type="certification", name="우수조달", concept="조달 인증"),  # 없는 개념
        ],
        relations=[ExtractedRelation(source="A650", type="has_component", target="NVIDIA GeForce RTX 5070")],
    ))

    graph = extract_page_graph(page, llm=llm, concepts=[{"name": "KC 인증", "members": ["안전확인 신고"]}])

    by_name = {e.name: e for e in graph.entities}
    assert by_name["NVIDIA GeForce RTX 5070"].type == "component"
    assert by_name["KC 안전확인"].concept == "KC 인증"
    assert by_name["우수조달"].concept is None
    system_prompt = llm.calls[0][0]["content"]
    assert "- KC 인증: 안전확인 신고" in system_prompt


def test_extracted_concept_link_joins_kc_expansion(env):
    _, _, graph, add_file = env
    graph.seed_concepts(KC)
    file = add_file("a650.docx")
    graph.replace_page(file.file_id, 1, PageGraph(entities=[
        _entity("product", "A650"),
        ExtractedEntity(type="certification", name="KC 적합등록", concept="KC 인증"),
    ]))

    result = service.search_graph("A650 KC인증 자료")

    assert "KC 적합등록" in result["expanded"][0]["members"]
    assert [(d["original_name"], d["matched_terms"]) for d in result["documents"]] == [("a650.docx", 2)]

    # 페이지를 다시 뽑아 인증이 빠지면 그 연결도 사라진다
    graph.replace_page(file.file_id, 1, PageGraph(entities=[_entity("product", "A650")]))
    assert "KC 적합등록" not in graph.list_concepts()[0]["members"]


def test_empty_page_does_not_call_llm():
    llm = FakeLLM(PageGraph())
    assert extract_page_graph("  \n", llm=llm) == PageGraph()
    assert llm.calls == []


def test_seed_merges_extracted_certification_into_concept_member(env):
    _, _, graph, add_file = env
    graph.seed_concepts(KC)
    file = add_file("safety.pdf")

    graph.replace_page(file.file_id, 1, PageGraph(entities=[_entity("certification", "안전확인신고")]))

    members = [e for e in graph.list_entities("certification") if e["name"].startswith("안전")]
    assert len(members) == 1  # 공백만 다른 표기는 같은 개체
    assert members[0]["mention_count"] == 1


def test_kc_question_expands_concept_and_ranks_documents(env):
    _, _, graph, add_file = env
    graph.seed_concepts(KC)
    safety, radio, other = add_file("safety.pdf"), add_file("radio.pdf"), add_file("a650.pdf")
    graph.replace_page(safety.file_id, 1, PageGraph(
        entities=[_entity("product", "N5800"), _entity("certification", "안전확인 신고")],
        relations=[ExtractedRelation(source="N5800", type="has_certification", target="안전확인 신고")],
    ))
    graph.replace_page(radio.file_id, 2, PageGraph(
        entities=[_entity("product", "N5800"), _entity("certification", "적합성 등록"), _entity("cert_number", "R-R-TGE-N5800")],
        relations=[ExtractedRelation(source="적합성 등록", type="has_number", target="R-R-TGE-N5800")],
    ))
    graph.replace_page(other.file_id, 1, PageGraph(entities=[_entity("product", "A650")]))

    result = service.search_graph("N5800 KC인증 자료 보내주세요")

    assert {m["name"] for m in result["matched"]} == {"N5800", "KC 인증"}
    assert result["expanded"] == [{"concept": "KC 인증", "members": ["안전확인 신고", "적합성 등록"]}]
    docs = {d["original_name"]: d for d in result["documents"]}
    assert set(docs) == {"safety.pdf", "radio.pdf"}
    assert docs["safety.pdf"]["matched_terms"] == 2 and docs["radio.pdf"]["matched_terms"] == 2
    assert docs["radio.pdf"]["pages"] == [2]
    assert docs["safety.pdf"]["source"].endswith("safety.pdf")
    assert any("has_certification" in r for r in result["relations"])


def test_partial_model_name_matches(env):
    _, _, graph, add_file = env
    file = add_file("guide.pdf")
    graph.replace_page(file.file_id, 3, PageGraph(entities=[_entity("product", "N5800 14세대")]))

    result = service.search_graph("N5800 무게")

    assert [d["pages"] for d in result["documents"]] == [[3]]


def test_no_match_tells_agent_to_use_vector_search(env):
    result = service.search_graph("회의실 예약 방법")
    assert result["matched"] == [] and result["documents"] == []
    assert "search_documents" in result["message"]


def test_replacing_page_and_deleting_file_clean_up(env):
    files, _, graph, add_file = env
    graph.seed_concepts(KC)
    file = add_file("doc.pdf")
    graph.replace_page(file.file_id, 1, PageGraph(entities=[_entity("product", "N5800"), _entity("component", "RTX 5070")]))

    # 검수로 페이지가 바뀌어 RTX 5070이 빠지면 그 개체도 없어진다
    graph.replace_page(file.file_id, 1, PageGraph(entities=[_entity("product", "N5800")]))
    assert [e["name"] for e in graph.list_entities("component")] == []

    files.delete_file(file.file_id)  # 외래키로 등장 위치가 지워진다
    graph.prune_orphans()
    assert graph.list_entities("product") == []
    # aliases.yaml에서 넣은 상위 개념과 인증 종류는 남는다
    assert graph.list_concepts() == [{"name": "KC 인증", "members": ["안전확인 신고", "적합성 등록"]}]


def test_index_file_combines_blocks_and_skips_failed_pages(env, monkeypatch):
    _, pages, graph, add_file = env
    file = add_file("sheet.xlsx")
    pages.save_pages(file.file_id, [
        PageText(page=1, text="N5800 블록1"), PageText(page=1, text="블록2"), PageText(page=2, text="실패할 페이지"),
    ])
    seen = []

    def fake_extract(text, concepts=None):
        seen.append(text)
        if "실패" in text:
            raise RuntimeError("LLM 오류")
        return PageGraph(entities=[_entity("product", "N5800")])

    monkeypatch.setattr(service, "extract_page_graph", fake_extract)

    summary = service.index_file(file.file_id)

    assert seen[0] == "N5800 블록1\n\n블록2"
    assert summary["pages"] == 2 and summary["failed_pages"] == 1 and summary["entities"] == 1
    assert graph.stats()["indexed_files"] == 1


def test_prompt_adds_graph_guide_only_when_graph_is_available():
    assert render_prompt("지침", {}, [], None) == "지침"
    rendered = render_prompt("지침", {}, [], [{"name": "KC 인증", "members": ["안전확인 신고"]}])
    assert GRAPH_GUIDE in rendered
    assert "- KC 인증 = 안전확인 신고" in rendered
