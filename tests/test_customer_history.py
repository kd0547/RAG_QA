"""G1: 고객 이력 도구(get_customer_history)와 담당자 메모. 이력은 자동으로 모델 입력에 들어가지 않는다 (안내 줄은 건수만)."""
import json
from datetime import datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

import config
from agent.evidence_context import Owner, owner_scope, run_scope
from conftest import tool_call
from entity.type import MailEntity


def _mail(env, uid, sender, subject, body, days_ago=0, status=None, draft=None):
    mail = MailEntity(uid=uid, subject=subject, sender=sender, body=body,
                      received_at=datetime.now() - timedelta(days=days_ago))
    with env.db.transaction() as conn:
        env.email_repo.save_pending(mail, conn)
        task_id = env.task_repo.create_task(uid, conn).task_id
    if status or draft:
        with env.db.transaction() as conn:
            conn.execute("UPDATE tasks SET status = COALESCE(?, status), draft_answer = ? WHERE task_id = ?",
                         (status, draft, task_id))
    return task_id


@pytest.fixture
def history(agent_env):
    env = agent_env
    old = _mail(env, "m-old", "a@example.com", "작년 입찰 조건", "OLD-BODY 91일 전", days_ago=91, status="sent")
    recent = _mail(env, "m-recent", "A@Example.com ", "N5800 무게 문의", "A-BODY-N5800무게", days_ago=10,
                   status="sent", draft="A-DRAFT-1.5kg")
    pending = _mail(env, "m-pending", "a@example.com", "인증서 요청", "PENDING-BODY", days_ago=89, status="drafted",
                    draft="PENDING-DRAFT")
    other = _mail(env, "m-other", "b@example.com", "남의 문의", "OTHER-BODY", days_ago=1, status="sent")
    current = _mail(env, "m-now", "a@example.com", "지금 문의", "NOW-BODY", days_ago=0)
    with env.db.transaction() as conn:  # 발송 본문 (이력에 나오면 안 된다)
        conn.execute("""INSERT INTO task_send (task_id, body, recipient, attempted_at, outcome)
                        VALUES (?, 'SENT-BODY-발송본문', 'a@example.com', ?, 'sent')""", (recent, datetime.now().isoformat()))
    type_row = env.skill_repo.create_type("사양 조회", "제품 사양 값을 묻는다")
    env.skill_repo.save_analysis(recent, status="ok", type_id=type_row["type_id"], covered_by=None, used_skills=[],
                                 reason="N5800 무게를 묻는 단순 사실 조회\n두 번째 줄", model="test")
    return {"env": env, "old": old, "recent": recent, "pending": pending, "other": other, "current": current}


def _call(tool, args, owner):
    with owner_scope(owner), run_scope("r1"):
        return tool.invoke(args)


def test_history_is_same_sender_only_recent_and_has_no_bodies(history):
    from tools.tool import get_customer_history

    result = _call(get_customer_history, {}, Owner("task", history["current"]))

    assert [i["subject"] for i in result["inquiries"]] == ["N5800 무게 문의", "인증서 요청"]  # 91일 전·다른 발신자 없음
    first = result["inquiries"][0]
    assert first["status"] == "답변 발송됨" and first["request_type"] == "사양 조회"
    assert first["reason"] == "N5800 무게를 묻는 단순 사실 조회 두 번째 줄"
    assert result["inquiries"][1]["status"] == "검토 중" and result["inquiries"][1]["request_type"] is None
    dumped = json.dumps(result, ensure_ascii=False)
    for secret in ("A-BODY", "A-DRAFT", "PENDING-BODY", "PENDING-DRAFT", "SENT-BODY", "OTHER-BODY", "남의 문의",
                   "작년 입찰 조건", "NOW-BODY"):
        assert secret not in dumped


def test_sender_cannot_be_changed_by_arguments(history):
    from tools.tool import get_customer_history

    assert set(get_customer_history.args) == {"limit"}
    result = _call(get_customer_history, {"limit": 10, "sender": "b@example.com"}, Owner("task", history["current"]))
    assert "남의 문의" not in json.dumps(result, ensure_ascii=False)
    other_view = _call(get_customer_history, {}, Owner("task", history["other"]))
    assert other_view["inquiries"] == []  # b의 다른 문의는 없다 (a의 문의가 보이지 않는다)


def test_days_setting_and_limit(history, monkeypatch):
    from tools.tool import get_customer_history

    monkeypatch.setattr(config, "CUSTOMER_HISTORY_DAYS", 30)
    result = _call(get_customer_history, {"limit": 1}, Owner("task", history["current"]))
    assert [i["subject"] for i in result["inquiries"]] == ["N5800 무게 문의"] and result["inquiry_total"] == 1


def test_retired_notes_are_hidden(history):
    from tools.tool import get_customer_history

    repo = history["env"].customer_history_repo
    keep = repo.add_note("A@example.com", "견적은 부가세 별도로 안내", created_by="10.0.0.1")
    gone = repo.add_note("a@example.com", "지난 분기 입찰 담당", created_by="10.0.0.1")
    repo.retire_note("a@example.com", gone["note_id"])

    result = _call(get_customer_history, {}, Owner("task", history["current"]))

    assert [n["text"] for n in result["notes"]] == [keep["text"]]
    assert repository_counts(history) == (2, 1)


def repository_counts(history):
    return history["env"].customer_history_repo.counts_for_task(history["current"], config.CUSTOMER_HISTORY_DAYS)


def test_web_question_gets_error_string(agent_env):
    from tools.tool import get_customer_history

    result = _call(get_customer_history, {}, Owner("session", "s1"))
    assert isinstance(result, str) and result.startswith("오류:")
    assert get_customer_history.invoke({}).startswith("오류:")  # 실행 컨텍스트 밖


def test_history_does_not_register_evidence(history):
    from tools.tool import get_customer_history

    _call(get_customer_history, {}, Owner("task", history["current"]))
    assert history["env"].evidence_repo.list_for_owner("task", history["current"]) == []


# ---------------------------------------------------------------- 모델 입력

def test_next_inquiry_gets_count_line_only(agent_env, monkeypatch):
    from mail import email_service
    from mail.email_send import SendOutcome, SendResult
    from test_email_consumer import OneShotStop

    env = agent_env
    _mail(env, "mA", "a@example.com", "A 문의 제목", "A본문-N5800무게")
    model = env.install([AIMessage(content="A초안-1.5kg"), AIMessage(content="B초안-KC")])
    monkeypatch.setattr(email_service, "send_email", lambda *a, **k: SendResult(SendOutcome.SENT, "DATA 250"))
    email_service.email_consumer_loop(OneShotStop(), env.email_repo, env.task_repo)
    env.customer_history_repo.add_note("a@example.com", "메모-NOTE-TEXT")

    _mail(env, "mB", "A@example.com", "B 문의", "B본문-KC인증")
    email_service.email_consumer_loop(OneShotStop(), env.email_repo, env.task_repo)

    first_input = "\n".join(str(m.content) for m in model.calls[0])
    second_input = "\n".join(str(m.content) for m in model.calls[1])  # 시스템 프롬프트 포함
    assert "이전 문의" not in first_input  # 첫 문의에는 이력이 없어 안내 줄도 없다
    assert "[이 발신자의 이전 문의 1건, 담당자 메모 1건이 있다. 필요하면 get_customer_history로 본다]" in second_input
    for leaked in ("A본문-N5800무게", "A초안-1.5kg", "A 문의 제목", "메모-NOTE-TEXT"):
        assert leaked not in second_input


def test_model_can_read_history_and_it_is_not_citable(agent_env, monkeypatch):
    from agent import agent as agent_module

    env = agent_env
    _mail(env, "mA", "a@example.com", "이전 문의", "본문")
    current = _mail(env, "mB", "a@example.com", "지금 문의", "본문2")

    def answer(messages):
        result = json.loads(messages[-1].content)
        assert [i["subject"] for i in result["inquiries"]] == ["이전 문의"]
        return AIMessage(content="이전에도 문의하셨습니다.\n근거: 없음")

    env.install([tool_call("get_customer_history", {}), answer])
    out = agent_module.run_agent_temp_attachments("지금 문의", mode="local", owner=Owner("task", current),
                                                  thread_id=f"task:{current}")
    assert out["validation"]["ok"] is True and out["sources"] == []


def test_flag_off_removes_tool_and_hint(agent_env, monkeypatch):
    from agent import agent as agent_module

    env = agent_env
    _mail(env, "mA", "a@example.com", "이전 문의", "본문")
    current = _mail(env, "mB", "a@example.com", "지금 문의", "본문2")
    assert agent_module.customer_history_hint(Owner("task", current)) is not None
    assert "get_customer_history" in {t.name for t in agent_module.active_tools()}

    monkeypatch.setattr(config, "CUSTOMER_HISTORY_ENABLED", False)

    assert "get_customer_history" not in {t.name for t in agent_module.active_tools()}
    assert agent_module.customer_history_hint(Owner("task", current)) is None
    model = env.install([AIMessage(content="답\n근거: 없음")])
    agent_module.run_agent_temp_attachments("지금 문의", mode="local", owner=Owner("task", current), thread_id=f"task:{current}")
    assert "이전 문의" not in "\n".join(str(m.content) for m in model.calls[0])


def test_history_tool_not_excluded_from_clearing():
    from agent import agent as agent_module
    from langchain.agents.middleware import ContextEditingMiddleware

    from conftest import ScriptedModel

    editing = next(m for m in agent_module.build_middleware(ScriptedModel()) if isinstance(m, ContextEditingMiddleware))
    assert "get_customer_history" not in editing.edits[0].exclude_tools


# ---------------------------------------------------------------- 메모 API

@pytest.fixture
def client(agent_env, monkeypatch):
    from app.routers import customers

    monkeypatch.setattr(customers, "customer_history_repo", agent_env.customer_history_repo)
    app = FastAPI()
    app.include_router(customers.router)
    return TestClient(app)


def test_note_api_add_list_retire(client):
    created = client.post("/customers/A@Example.com/notes", json={"text": "  부가세 별도  "})
    assert created.status_code == 201
    note = created.json()
    assert note["sender"] == "a@example.com" and note["text"] == "부가세 별도" and note["created_by"] == "testclient"

    listed = client.get("/customers/a@example.com/notes").json()["items"]
    assert [n["note_id"] for n in listed] == [note["note_id"]]

    retired = client.post(f"/customers/a@example.com/notes/{note['note_id']}/retire")
    assert retired.status_code == 200 and retired.json()["retired_at"]
    assert client.get("/customers/a@example.com/notes").json()["items"][0]["retired_at"]  # 지우지 않는다


def test_note_api_validation(client):
    assert client.post("/customers/a@example.com/notes", json={"text": "  "}).status_code == 400
    assert client.post("/customers/a@example.com/notes", json={"text": "가" * 501}).status_code == 400
    assert client.post("/customers/a@example.com/notes", json={"text": "가" * 500}).status_code == 201
    note_id = client.get("/customers/a@example.com/notes").json()["items"][0]["note_id"]
    # 다른 발신자의 메모는 사용 중지할 수 없다
    assert client.post(f"/customers/b@example.com/notes/{note_id}/retire").status_code == 404
