"""기본 프롬프트 바꾸기: 기본을 v4로 바꾸면 예전 기본을 지울 수 있고, 서버를 다시 켜도 되살아나지 않는다."""
import importlib
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from agent.prompt import PROMPT_V4_NAME  # noqa: E402
from repository.prompt_repository import DefaultPromptDeleteError, PromptRepository  # noqa: E402
from repository.repo_connect import Database  # noqa: E402


@pytest.fixture
def repo(tmp_path):
    return PromptRepository(Database(str(tmp_path / "prompt.db")))


def test_set_default_then_old_default_can_be_deleted_and_stays_gone(repo):
    old_default = repo.ensure_default()
    v4 = repo.ensure_v4()

    assert repo.set_default(v4.id).is_default
    assert not repo.get(old_default.id).is_default
    assert repo.delete(old_default.id)
    with pytest.raises(DefaultPromptDeleteError):
        repo.delete(v4.id)

    # 서버 시작 순서 (main.py): 기본이 있으니 새로 넣지 않고, v4도 이미 있다
    repo.ensure_default()
    repo.ensure_v4()
    assert [(p.name, p.is_default, p.is_selected) for p in repo.list_all()] == [(PROMPT_V4_NAME, True, True)]


def test_set_default_unknown_id(repo):
    repo.ensure_default()
    assert repo.set_default(9999) is None
    assert repo.get_default() is not None


def test_main_no_longer_seeds_v2_v3():
    source = (PROJECT_ROOT / "main.py").read_text(encoding="utf-8")
    assert "ensure_v2()" not in source and "ensure_v3()" not in source and "ensure_v4()" in source


def test_api_set_default(repo, monkeypatch):
    module = importlib.import_module("app.routers.prompt")
    monkeypatch.setattr(module, "prompt_repo", repo)
    app = FastAPI()
    app.include_router(module.router)
    old_default = repo.ensure_default()
    v4 = repo.ensure_v4()
    with TestClient(app) as client:
        assert client.post(f"/prompts/{v4.id}/default").json()["is_default"] is True
        assert client.post("/prompts/9999/default").status_code == 404
        assert client.delete(f"/prompts/{old_default.id}").status_code == 204
        assert client.delete(f"/prompts/{v4.id}").status_code == 409
