"""scripts/inject_test_mail.py: 메일 수신 없이 대기 작업을 넣는 도구.

운영 DB로 가는 연결은 tests/conftest.py가 임시 폴더로 돌린다.
"""
import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "inject_test_mail.py"


@pytest.fixture(scope="module")
def tool():
    spec = importlib.util.spec_from_file_location("inject_test_mail", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _pending_ids():
    import repository
    return {t.task_id for t in repository.task_repo.get_pending_tasks()}


def test_inject_creates_mail_and_pending_task(tool):
    import config
    import repository

    result = tool.inject("[주입] KC", "N5800 KC 인증번호 알려줘")

    assert result["uid"].startswith("manual-")
    assert result["sender"] == config.REVIEWER_EMAIL  # 승인해도 고객에게 나가지 않게 기본은 검토 담당자
    assert result["task_id"] in _pending_ids()
    mail = repository.email_repo.get_mail_by_id(result["uid"])
    assert mail.subject == "[주입] KC"
    assert mail.body == "N5800 KC 인증번호 알려줘"
    assert mail.attachments == []


def test_inject_rejects_empty_body(tool):
    with pytest.raises(ValueError):
        tool.inject("제목", "   ")


def test_attachments_document_is_copied_and_image_is_data_url(tool, tmp_path):
    import repository

    doc = tmp_path / "사양서.pdf"
    doc.write_bytes(b"%PDF-1.4 test")
    image = tmp_path / "캡처.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    uid = tool.new_uid()
    attach_dir = tmp_path / "manual"

    attachments = [tool.build_attachment(p, uid, attach_dir) for p in (doc, image)]
    result = tool.inject("첨부", "첨부 사양 확인해 줘", attachments=attachments, uid=uid)

    saved = repository.email_repo.get_mail_by_id(result["uid"]).attachments
    assert [a.filename for a in saved] == ["사양서.pdf", "캡처.png"]
    assert all(a.attachment_id is not None for a in saved)  # DB가 번호를 매긴다 (read_attachment가 쓴다)
    pdf, png = saved
    assert pdf.type.value == "pdf" and Path(pdf.path) == attach_dir / uid / "사양서.pdf"
    assert Path(pdf.path).read_bytes() == b"%PDF-1.4 test"
    assert png.type.value == "image" and png.path is None
    assert png.image.startswith("data:image/png;base64,")


def test_unsupported_attachment_is_refused(tool, tmp_path):
    bad = tmp_path / "run.exe"
    bad.write_bytes(b"MZ")
    with pytest.raises(ValueError):
        tool.build_attachment(bad, tool.new_uid(), tmp_path / "manual")
    with pytest.raises(FileNotFoundError):
        tool.build_attachment(tmp_path / "없는파일.pdf", tool.new_uid(), tmp_path / "manual")


def test_clone_copies_body_and_attachments_and_reports_missing_files(tool, tmp_path):
    import config
    import repository
    from entity.type import Attachment

    kept = tmp_path / "남은.pdf"
    kept.write_bytes(b"%PDF-1.4 kept")
    original = tool.inject(
        "원본 제목", "첨부된 규격에 맞는 모델 찾아줘", sender="customer@example.com",
        attachments=[
            Attachment(type="pdf", filename="남은.pdf", content_type="application/pdf", image=None, path=str(kept)),
            Attachment(type="pdf", filename="지워진.pdf", content_type="application/pdf", image=None,
                       path=str(tmp_path / "지워진.pdf")),
        ],
    )

    # task_id로도, 메일 uid로도 찾는다
    by_task = tool.clone(original["task_id"])
    by_uid = tool.clone(original["uid"], body="다시 확인해")

    assert by_task["cloned_from"] == original["uid"]
    assert by_task["subject"] == "[주입] 원본 제목"
    assert by_task["sender"] == config.REVIEWER_EMAIL  # 원래 발신자(고객)에게 다시 나가지 않게 바꾼다
    assert by_task["attachments"] == ["남은.pdf"]
    assert by_task["missing_attachments"] == ["지워진.pdf"]
    assert repository.email_repo.get_mail_by_id(by_task["uid"]).body == "첨부된 규격에 맞는 모델 찾아줘"
    assert repository.email_repo.get_mail_by_id(by_uid["uid"]).body == "다시 확인해"
    assert {by_task["task_id"], by_uid["task_id"]} <= _pending_ids()
    assert len({original["uid"], by_task["uid"], by_uid["uid"]}) == 3


def test_clone_unknown_key_raises(tool):
    with pytest.raises(LookupError):
        tool.clone("no-such-task")


def test_cli_prints_task_and_returns_zero(tool, capsys):
    code = tool.main(["--subject", "CLI", "--body", "A650 무게 알려줘"])
    out = capsys.readouterr().out
    assert code == 0
    assert "task_id" in out and "[주입] CLI" in out
    assert tool.main(["--clone", "no-such-task"]) == 1
