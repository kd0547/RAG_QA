"""B2: read_pages · list_documents · grep_documents. 임시 DB와 도구 호출 대역 모델로 확인한다."""
import json

import pytest
from langchain_core.messages import AIMessage

from agent.evidence_context import Owner, owner_scope, run_scope
from conftest import tool_call
from entity.file import create_file
from parser.pdf.type import PageText
from tools import tool as tools


@pytest.fixture
def docs(agent_env, tmp_path):
    """페이지 텍스트가 있는 문서 2개와 없는 문서 1개."""
    def add(name, pages, description=""):
        file = create_file(original_name=name, stored_path=str(tmp_path / name), description=description)
        agent_env.file_repo.file_save(file)
        if pages:
            agent_env.page_repo.save_pages(file.file_id, [PageText(page=p, text=t) for p, t in pages])
        return file.file_id

    ids = {
        "guide": add("N5800_Sales_Guide.pdf", [(1, "표지"), (2, "N5800 무게 1.5kg, RAM 16GB"), (3, "KC 인증 R-R-TGE-N5800")],
                     description="N5800 영업 가이드"),
        "sheet": add("SSD_성능_비교.xlsx", [(1, "블록1 C910G"), (1, "블록2 Ti600s"), (2, "요약")]),
        "empty": add("스캔본.pdf", []),
    }
    return ids


@pytest.fixture
def in_run(agent_env):
    """에이전트 실행 중인 것처럼 owner/run 컨텍스트를 연다."""
    run_id = agent_env.evidence_repo.start_run("task", "t1", "test", None)
    with owner_scope(Owner("task", "t1")), run_scope(run_id):
        yield run_id


def test_read_pages_registers_evidence(agent_env, docs, in_run):
    result = tools.read_pages.invoke({"file_id": docs["guide"], "pages": [2, 9]})

    assert result["original_name"] == "N5800_Sales_Guide.pdf"
    assert [(p["page"], p["text"]) for p in result["pages"]] == [(2, "N5800 무게 1.5kg, RAM 16GB")]
    assert result["missing_pages"] == [9] and result["truncated"] is False
    evidence = agent_env.evidence_repo.get(result["pages"][0]["evidence_id"], "task", "t1")
    assert (evidence["origin_type"], evidence["file_id"], evidence["page"]) == ("file_page", docs["guide"], 2)
    assert evidence["revision"] and evidence["page_id"]
    assert [u["evidence_id"] for u in agent_env.evidence_repo.uses_for_run(in_run, "read")] == [evidence["evidence_id"]]


def test_reviewed_text_is_reflected_immediately(agent_env, docs, in_run):
    before = tools.read_pages.invoke({"file_id": docs["guide"], "pages": [2]})["pages"][0]
    page_id = agent_env.page_repo.pages_with_number(docs["guide"], 2)[0]["page_id"]

    agent_env.page_repo.update_text(page_id, "N5800 무게 1.45kg (검수 수정)")
    after = tools.read_pages.invoke({"file_id": docs["guide"], "pages": [2]})["pages"][0]

    assert after["text"] == "N5800 무게 1.45kg (검수 수정)"
    assert after["evidence_id"] != before["evidence_id"]


def test_xlsx_blocks_of_same_sheet_are_joined(docs, in_run):
    page = tools.read_pages.invoke({"file_id": docs["sheet"], "pages": [1]})["pages"][0]
    assert page["text"] == "블록1 C910G\n\n블록2 Ti600s"


def test_file_without_pages_is_not_parsed(docs, in_run, monkeypatch):
    import parser.file_parser

    calls = []
    monkeypatch.setattr(tools, "parse_file", lambda path: calls.append(path) or [])
    monkeypatch.setattr(parser.file_parser, "parse_file", lambda path: calls.append(path) or [])

    result = tools.read_pages.invoke({"file_id": docs["empty"], "pages": [1]})

    assert result["error"].startswith("페이지 텍스트 없음")
    assert calls == []
    assert "없는 file_id" in tools.read_pages.invoke({"file_id": "nope", "pages": [1]})["error"]


def test_read_pages_truncates_to_max_chars(docs, in_run):
    result = tools.read_pages.invoke({"file_id": docs["guide"], "pages": [1, 2, 3], "max_chars": 10})

    assert [p["page"] for p in result["pages"]] == [1, 2]
    assert result["pages"][1]["text"] == "N5800 무게"  # 표지(2자) + 8자
    assert result["pages"][1]["truncated"] is True
    assert result["truncated"] is True and result["next_pages"] == [3]


def test_read_pages_needs_run_context(docs):
    assert "실행 컨텍스트" in tools.read_pages.invoke({"file_id": docs["guide"], "pages": [1]})["error"]


def test_list_documents_filters_and_counts(docs):
    everything = tools.list_documents.invoke({})
    by_name = {d["original_name"]: d for d in everything}

    assert by_name["SSD_성능_비교.xlsx"]["page_count"] == 2
    assert by_name["스캔본.pdf"]["has_pages"] is False
    assert [d["file_id"] for d in tools.list_documents.invoke({"keyword": "영업"})] == [docs["guide"]]
    assert [d["file_id"] for d in tools.list_documents.invoke({"keyword": "ssd"})] == [docs["sheet"]]


def test_grep_documents_literal_regex_and_errors(docs):
    literal = tools.grep_documents.invoke({"pattern": "r-r-tge-n5800"})
    assert [(r["original_name"], r["page"]) for r in literal] == [("N5800_Sales_Guide.pdf", 3)]
    assert "R-R-TGE-N5800" in literal[0]["snippet"]

    regex = tools.grep_documents.invoke({"pattern": r"RAM ?\d+GB"})
    assert [r["page"] for r in regex] == [2]

    scoped = tools.grep_documents.invoke({"pattern": "C910G|Ti600s", "file_id": docs["sheet"]})
    assert [r["snippet"] for r in scoped] == ["블록1 C910G", "블록2 Ti600s"]

    assert "정규식 오류" in tools.grep_documents.invoke({"pattern": "RAM("})["error"]


def test_agent_reads_pages_end_to_end(agent_env, docs):
    """대역 모델이 grep → read_pages → 답변. 실행 기록에 읽은 근거가 남는다."""
    from agent import agent as agent_module

    def answer_from_read(messages):
        read = json.loads(messages[-1].content)
        return AIMessage(content=f"1.5kg입니다.\n근거: {read['pages'][0]['evidence_id']}")

    agent_env.install([
        tool_call("grep_documents", {"pattern": "무게"}),
        tool_call("read_pages", {"file_id": docs["guide"], "pages": [2]}),
        answer_from_read,
    ])

    out = agent_module.run_agent_temp_attachments("N5800 무게?", mode="local", owner=Owner("task", "t1"))

    run = agent_env.evidence_repo.latest_run("task", "t1")
    reads = agent_env.evidence_repo.uses_for_run(run["run_id"], "read")
    assert run["status"] == "ok"
    assert [(r["file_id"], r["page"]) for r in reads] == [(docs["guide"], 2)]
    assert "1.5kg" in out["answer"]
