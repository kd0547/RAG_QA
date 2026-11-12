"""모든 테스트에 공통으로 거는 격리 장치.

- 운영 DB(storage/mail.db): `repository` 패키지는 임포트 시점에 운영 DB를 열고 스키마를 적용한다.
  스키마에 테이블·컬럼이 추가되면 테스트 실행만으로 운영 DB가 바뀌므로, 그 경로로 가는 연결을
  세션 임시 폴더로 돌린다. (개별 테스트가 자기 임시 DB를 쓰는 것과 별개로 마지막 안전장치)
- 운영 벡터DB(storage/chroma): `repository.embedding_repository`는 임포트 시점에 Chroma를 연다.
  에이전트 모듈을 임포트하는 테스트를 위해 빈 대역 모듈을 미리 넣어 둔다.
  (파일 업로드 테스트들은 각자 monkeypatch로 자기 대역을 넣으므로 영향이 없다)
- tests/parser.py가 parser 패키지를 가리지 않게 프로젝트 루트를 sys.path 앞에 둔다.
"""
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path
from types import ModuleType

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) in sys.path:
    sys.path.remove(str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT))
if not hasattr(sys.modules.get("parser"), "__path__"):
    sys.modules.pop("parser", None)
# pytest는 테스트 모듈을 읽을 때 tests/를 sys.path 맨 앞에 넣는다. 그 전에 진짜 패키지를 캐시해 둔다.
import parser  # noqa: E402,F401

# ---------- 메일 계정 ----------
# mail/ 모듈은 임포트 시점에 계정 환경변수를 읽는다. 테스트는 실제 계정 대신 더미 값을 쓴다
# (load_dotenv는 이미 있는 값을 덮어쓰지 않으므로 .env의 실제 값이 들어오지 않는다).
for _key, _value in {
    "MAIL_ID": "sender@example.com", "MAIL_PW": "test-only",
    "CLIENT_ID": "test-client", "TENANT_ID": "test-tenant",
}.items():
    os.environ.setdefault(_key, _value)

# ---------- 운영 DB 보호 ----------

_PRODUCTION_DBS = {
    (PROJECT_ROOT / "storage" / "mail.db").resolve(),
}
_SESSION_DIR = Path(tempfile.mkdtemp(prefix="ragqa-test-"))
_original_connect = sqlite3.connect


def _guarded_connect(database, *args, **kwargs):
    try:
        target = Path(database).resolve()
    except (TypeError, OSError):
        target = None
    if target in _PRODUCTION_DBS:
        database = str(_SESSION_DIR / target.name)
    return _original_connect(database, *args, **kwargs)


sqlite3.connect = _guarded_connect

# ---------- 벡터DB 대역 ----------

if "repository.embedding_repository" not in sys.modules:
    _embeddings = ModuleType("repository.embedding_repository")
    _embeddings.search = lambda **kwargs: []
    _embeddings.save_embeddings = lambda chunks: None
    _embeddings.delete_embeddings = lambda file_id: None
    _embeddings.replace_page_embeddings = lambda file_id, page, chunks: 0
    _embeddings.update_group_metadata = lambda file_id, group_id: 0
    sys.modules["repository.embedding_repository"] = _embeddings


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(_SESSION_DIR, ignore_errors=True)


# ---------- 에이전트 대역 ----------

import pytest  # noqa: E402
from langchain_core.language_models.chat_models import BaseChatModel  # noqa: E402
from langchain_core.messages import AIMessage  # noqa: E402
from langchain_core.outputs import ChatGeneration, ChatResult  # noqa: E402
from pydantic import Field  # noqa: E402


class ScriptedModel(BaseChatModel):
    """정해 둔 순서대로 답하는 채팅 모델 대역. 도구 호출도 낸다.

    script의 항목은 AIMessage 또는 (지금까지의 메시지 목록) -> AIMessage 함수다.
    함수를 쓰면 앞선 도구 결과(근거 ID 등)를 보고 다음 응답을 만들 수 있다.
    calls에는 모델이 받은 입력 메시지 목록이 호출마다 쌓인다.
    """

    script: list = Field(default_factory=list)
    calls: list = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls.append(list(messages))
        if not self.script:
            raise AssertionError("대역 모델 스크립트가 끝났는데 또 호출됨")
        step = self.script.pop(0)
        message = step(messages) if callable(step) else step
        return ChatResult(generations=[ChatGeneration(message=message)])


def tool_call(name: str, args: dict, call_id: str | None = None) -> AIMessage:
    """도구 하나를 부르는 AI 메시지."""
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id or f"call-{name}"}])


@pytest.fixture
def agent_env(tmp_path, monkeypatch):
    """임시 DB의 저장소들로 에이전트·도구를 돌린다. 반환: 저장소와 대역 모델을 끼우는 install()."""
    from types import SimpleNamespace

    import repository
    from agent import agent as agent_module
    from repository.email_repository import EmailRepository
    from repository.evidence_repository import EvidenceRepository
    from repository.file_page_repository import FilePageRepository
    from repository.file_repository import FileRepository
    from repository.graph_repository import GraphRepository
    from repository.group_repository import GroupRepository
    from repository.prompt_repository import PromptRepository
    from repository.repo_connect import Database
    from repository.task_repository import TaskRepository

    db = Database(str(tmp_path / "agent.db"))
    repos = {
        "db": db,
        "email_repo": EmailRepository(db),
        "evidence_repo": EvidenceRepository(db),
        "page_repo": FilePageRepository(db),
        "file_repo": FileRepository(db),
        "graph_repo": GraphRepository(db),
        "group_repo": GroupRepository(db),
        "prompt_repo": PromptRepository(db),
        "task_repo": TaskRepository(db),
    }
    for name, value in repos.items():
        monkeypatch.setattr(repository, name, value)
        if hasattr(agent_module, name):
            monkeypatch.setattr(agent_module, name, value)

    def install(script: list, mode: str = "local") -> ScriptedModel:
        """대역 모델로 실제 도구 목록을 가진 에이전트를 만들어 get_agent가 돌려주게 한다."""
        from langchain.agents import create_agent

        model = ScriptedModel(script=list(script))
        agent = create_agent(
            model=model,
            tools=agent_module.TOOLS,
            middleware=[agent_module._system_prompt],
            context_schema=agent_module.AgentContext,
        )
        monkeypatch.setattr(agent_module, "get_agent", lambda m="local": agent)
        return model

    return SimpleNamespace(**repos, install=install, tmp_path=tmp_path)
