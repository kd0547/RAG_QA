"""사용자 생성 문서 그룹과 과거 자동 생성 그룹 정리를 확인한다."""

from pathlib import Path
import sys

import pytest
from fastapi import HTTPException

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.routers import group as group_router  # noqa: E402
from entity.file import create_file  # noqa: E402
from entity.group import DEFAULT_GROUPS  # noqa: E402
from repository.file_repository import FileRepository  # noqa: E402
from repository.group_repository import DuplicateGroupNameError, GroupNotFoundError, GroupRepository  # noqa: E402
from repository.repo_connect import Database  # noqa: E402


@pytest.fixture
def repos(tmp_path):
    db = Database(str(tmp_path / "groups.db"))
    return db, GroupRepository(db), FileRepository(db)


def test_create_group_and_assign_file(repos):
    _, groups, files = repos
    assert groups.list_all() == []

    group = groups.create("  N5800   사양  ", "  N5800 관련 자료  ")
    assert len(group["id"]) == 32
    assert set(group) == {"id", "name", "description", "created_at", "updated_at", "file_count"}
    assert group == {
        "id": group["id"],
        "name": "N5800 사양",
        "description": "N5800 관련 자료",
        "created_at": group["created_at"],
        "updated_at": group["updated_at"],
        "file_count": 0,
    }
    assert group["created_at"]
    assert group["created_at"] == group["updated_at"]
    assert groups.exists(group["id"])

    file = create_file(original_name="spec.pdf", stored_path="uploads/spec.pdf", sha256="spec")
    files.file_save(file)
    assert files.update_group([file.file_id], group["id"]) == 1
    assert files.get_file_by_id(file.file_id).group_id == group["id"]
    assert groups.list_all() == [{**group, "file_count": 1}]


def test_create_group_rejects_invalid_or_duplicate_name(repos):
    _, groups, _ = repos
    groups.create("Sales Guide")

    with pytest.raises(DuplicateGroupNameError):
        groups.create("  sales   guide  ")
    with pytest.raises(ValueError, match="이름"):
        groups.create("  \n ")
    with pytest.raises(ValueError, match="80자"):
        groups.create("a" * 81)
    with pytest.raises(ValueError, match="500자"):
        groups.create("valid", "a" * 501)
    assert len(groups.list_all()) == 1


def test_prune_only_untouched_empty_default_groups(repos):
    db, groups, files = repos
    assert groups.ensure_defaults() == len(DEFAULT_GROUPS)
    with db.get_conn() as conn:
        conn.execute("UPDATE file_group SET description = '팀에서 사용' WHERE id = 'manual'")
        conn.execute("UPDATE file_group SET updated_at = datetime(created_at, '+1 day') WHERE id = 'sales'")
        conn.commit()

    file = create_file(original_name="kc.pdf", stored_path="uploads/kc.pdf", sha256="kc", group_id="certificate")
    files.file_save(file)

    assert groups.prune_unused_defaults() == len(DEFAULT_GROUPS) - 3
    assert {group["id"] for group in groups.list_all()} == {"manual", "sales", "certificate"}
    assert files.get_file_by_id(file.file_id).group_id == "certificate"


def test_create_group_api_contract(repos, monkeypatch):
    _, groups, _ = repos
    monkeypatch.setattr(group_router, "group_repo", groups)

    created = group_router.create_group(group_router.GroupCreateBody(name="새 문서", description="설명"))
    assert created == {
        "id": created["id"], "name": "새 문서", "description": "설명",
        "created_at": created["created_at"], "updated_at": created["updated_at"], "file_count": 0,
    }
    assert group_router.list_groups() == [created]

    with pytest.raises(HTTPException) as blank:
        group_router.create_group(group_router.GroupCreateBody(name="  "))
    assert blank.value.status_code == 400
    with pytest.raises(HTTPException) as duplicate:
        group_router.create_group(group_router.GroupCreateBody(name="새 문서"))
    assert duplicate.value.status_code == 409

    post_route = next(route for route in group_router.router.routes if "POST" in route.methods)
    assert post_route.status_code == 201


def test_update_group_changes_only_provided_fields_and_keeps_file_count(repos):
    db, groups, files = repos
    group = groups.create("기존 이름", "기존 설명")
    file = create_file(original_name="spec.pdf", stored_path="uploads/spec.pdf", sha256="spec", group_id=group["id"])
    files.file_save(file)

    renamed = groups.update(group["id"], name="  새   이름  ")
    assert renamed == {
        "id": group["id"], "name": "새 이름", "description": "기존 설명",
        "created_at": group["created_at"], "updated_at": renamed["updated_at"], "file_count": 1,
    }
    assert renamed["updated_at"] != group["updated_at"]
    cleared = groups.update(group["id"], description="  ")
    assert cleared == {
        "id": group["id"], "name": "새 이름", "description": "",
        "created_at": group["created_at"], "updated_at": cleared["updated_at"], "file_count": 1,
    }
    assert groups.list_all() == [cleared]
    with db.get_conn() as conn:
        row = conn.execute("SELECT created_at, updated_at FROM file_group WHERE id = ?", (group["id"],)).fetchone()
    assert row["updated_at"] != row["created_at"]


def test_update_group_rejects_missing_duplicate_and_invalid_values(repos):
    _, groups, _ = repos
    first = groups.create("첫 그룹")
    second = groups.create("두 번째")

    with pytest.raises(GroupNotFoundError):
        groups.update("missing", name="새 이름")
    with pytest.raises(DuplicateGroupNameError):
        groups.update(second["id"], name="  첫   그룹  ")
    with pytest.raises(ValueError, match="이름"):
        groups.update(first["id"], name="  ")
    with pytest.raises(ValueError, match="80자"):
        groups.update(first["id"], name="a" * 81)
    with pytest.raises(ValueError, match="500자"):
        groups.update(first["id"], description="a" * 501)
    assert {group["id"]: group for group in groups.list_all()} == {first["id"]: first, second["id"]: second}


def test_update_group_api_contract(repos, monkeypatch):
    _, groups, _ = repos
    monkeypatch.setattr(group_router, "group_repo", groups)
    first = groups.create("첫 그룹")
    groups.create("다른 그룹")

    renamed = group_router.update_group(first["id"], group_router.GroupUpdateBody(name="  새 그룹 "))
    assert renamed == {
        "id": first["id"], "name": "새 그룹", "description": "",
        "created_at": first["created_at"], "updated_at": renamed["updated_at"], "file_count": 0,
    }
    described = group_router.update_group(first["id"], group_router.GroupUpdateBody(description="새 설명"))
    assert described["name"] == "새 그룹"
    assert described["description"] == "새 설명"

    for body, status in (
        (group_router.GroupUpdateBody(), 400),
        (group_router.GroupUpdateBody(name=None), 400),
        (group_router.GroupUpdateBody(name="다른 그룹"), 409),
    ):
        with pytest.raises(HTTPException) as error:
            group_router.update_group(first["id"], body)
        assert error.value.status_code == status
    with pytest.raises(HTTPException) as missing:
        group_router.update_group("missing", group_router.GroupUpdateBody(description="설명"))
    assert missing.value.status_code == 404

    patch_route = next(route for route in group_router.router.routes if "PATCH" in route.methods)
    assert patch_route.path == "/groups/{group_id}"


def test_editing_legacy_default_keeps_it_on_prune(repos):
    db, groups, _ = repos
    groups.ensure_defaults()
    manual = next(group for group in DEFAULT_GROUPS if group.id == "manual")
    groups.update("manual", description=manual.description)

    assert groups.prune_unused_defaults() == len(DEFAULT_GROUPS) - 1
    assert [group["id"] for group in groups.list_all()] == ["manual"]
    with db.get_conn() as conn:
        row = conn.execute("SELECT created_at, updated_at FROM file_group WHERE id = 'manual'").fetchone()
    assert row["updated_at"] != row["created_at"]
