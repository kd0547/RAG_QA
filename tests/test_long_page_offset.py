"""C2-P2: 한 페이지가 max_chars(최대 20,000자)보다 길 때 offset으로 끝까지 이어 읽는다."""
from datetime import datetime

import pytest

from agent.evidence_context import Owner, owner_scope, run_scope
from entity.file import create_file
from entity.type import Attachment, MailEntity
from parser.pdf.type import PageText
from tools import tool as tools

# SSD_성능_비교.xlsx 전체 길이와 같은 49,933자 한 페이지 (줄마다 번호가 달라 이어 붙인 결과를 확인할 수 있다)
LONG_PAGE = "".join(f"[{i:05d}] C910G 500GB TBW 300 " for i in range(1600))[:49_933]


def _read_all(invoke) -> tuple[str, set]:
    """offset 0 → next_offset … 순서로 끝까지 읽어 이어 붙인 본문과 나온 근거 ID들."""
    text, ids, offset, calls = "", set(), 0, 0
    while True:
        result = invoke(offset)
        page = result["pages"][0]
        text += page["text"]
        ids.add(page["evidence_id"])
        calls += 1
        if "next_offset" not in page:
            assert calls == 3
            return text, ids
        assert page["page_chars"] == len(LONG_PAGE) and result["truncated"] is True
        offset = page["next_offset"]


@pytest.fixture
def run_ctx(agent_env):
    def scope(owner_id="t1"):
        run_id = agent_env.evidence_repo.start_run("task", owner_id, "test", None)
        return owner_scope(Owner("task", owner_id)), run_scope(run_id)
    return scope


def test_read_pages_reads_long_page_to_end_with_same_evidence(agent_env, tmp_path, run_ctx):
    file = create_file(original_name="SSD_성능_비교.xlsx", stored_path=str(tmp_path / "s.xlsx"))
    agent_env.file_repo.file_save(file)
    agent_env.page_repo.save_pages(file.file_id, [PageText(1, LONG_PAGE), PageText(2, "요약")])
    owner, run = run_ctx()

    with owner, run:
        text, ids = _read_all(lambda offset: tools.read_pages.invoke(
            {"file_id": file.file_id, "pages": [1], "max_chars": 20000, "offset": offset}))
        error = tools.read_pages.invoke({"file_id": file.file_id, "pages": [1, 2], "offset": 100})
        first = tools.read_pages.invoke({"file_id": file.file_id, "pages": [1], "max_chars": 20000})["pages"][0]
        past_end = tools.read_pages.invoke({"file_id": file.file_id, "pages": [1], "offset": 60000})["pages"][0]

    assert text == LONG_PAGE
    assert len(ids) == 1
    assert error == {"error": "offset은 페이지 하나를 읽을 때만 쓸 수 있습니다"}
    assert (first["next_offset"], "offset" in first) == (20000, False)
    assert past_end["text"] == "" and "읽을 내용이 없습니다" in past_end["message"]


def test_multi_page_cut_reports_next_offset(agent_env, tmp_path, run_ctx):
    """여러 페이지를 읽다 잘린 페이지에도 next_offset이 붙어, 그 페이지만 이어 읽을 수 있다."""
    file = create_file(original_name="g.pdf", stored_path=str(tmp_path / "g.pdf"))
    agent_env.file_repo.file_save(file)
    agent_env.page_repo.save_pages(file.file_id, [PageText(1, "가" * 10), PageText(2, "나" * 30), PageText(3, "다")])
    owner, run = run_ctx()

    with owner, run:
        result = tools.read_pages.invoke({"file_id": file.file_id, "pages": [1, 2, 3], "max_chars": 25})

    page2 = result["pages"][1]
    assert (page2["text"], page2["next_offset"], page2["page_chars"]) == ("나" * 15, 15, 30)
    assert result["next_pages"] == [3]
    assert "offset=next_offset" in result["message"]


def test_read_attachment_offset(agent_env, tmp_path, run_ctx, monkeypatch):
    monkeypatch.setattr(tools, "parse_file", lambda path: [PageText(1, LONG_PAGE), PageText(2, "끝")])
    pdf = tmp_path / "big.pdf"
    pdf.write_bytes(b"%PDF")
    mail = MailEntity(uid="m1", subject="s", sender="a@b.c", body="q", received_at=datetime.now(), attachments=[
        Attachment(type="pdf", filename="big.pdf", content_type="application/pdf", image=None, path=str(pdf)),
    ])
    with agent_env.db.transaction() as conn:
        agent_env.email_repo.save_pending(mail, conn)
        task_id = agent_env.task_repo.create_task("m1", conn).task_id
    attachment_id = agent_env.email_repo.get_mail_by_id("m1").attachments[0].attachment_id
    owner, run = run_ctx(task_id)

    with owner, run:
        text, ids = _read_all(lambda offset: tools.read_attachment.invoke(
            {"attachment_id": attachment_id, "pages": [1], "max_chars": 20000, "offset": offset}))
        no_pages = tools.read_attachment.invoke({"attachment_id": attachment_id, "offset": 10})
        two_pages = tools.read_attachment.invoke({"attachment_id": attachment_id, "pages": [1, 2], "offset": 10})

    assert text == LONG_PAGE and len(ids) == 1
    assert no_pages == two_pages == {"error": "offset은 페이지 하나를 읽을 때만 쓸 수 있습니다"}
