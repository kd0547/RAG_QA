"""사용자가 만든 문서 그룹과 기존 그룹을 보존하는 저장소."""
from uuid import uuid4

from entity.group import DEFAULT_GROUPS
from repository.repo_connect import Database

_DEFAULT_ORDER = {group.id: index for index, group in enumerate(DEFAULT_GROUPS)}


class DuplicateGroupNameError(Exception):
    """같은 이름의 문서 그룹이 이미 있을 때 발생한다."""


class GroupNotFoundError(Exception):
    """수정할 문서 그룹이 없을 때 발생한다."""


class GroupNotEmptyError(Exception):
    """파일이 남아 있는 문서 그룹을 지우려 할 때 발생한다."""


def _normalize_name(name: str) -> str:
    name = " ".join(name.split())
    if not name:
        raise ValueError("문서 그룹 이름을 입력해 주세요.")
    if len(name) > 80:
        raise ValueError("문서 그룹 이름은 80자 이하로 입력해 주세요.")
    return name


def _normalize_description(description: str) -> str:
    description = description.strip()
    if len(description) > 500:
        raise ValueError("설명은 500자 이하로 입력해 주세요.")
    return description


class GroupRepository:

    def __init__(self, db: Database):
        self.db = db

    def ensure_defaults(self) -> int:
        """과거 호출부·테스트 호환용. 신규 서버 시작 경로에서는 호출하지 않는다."""
        inserted = 0
        with self.db.get_conn() as conn:
            for group in DEFAULT_GROUPS:
                cursor = conn.execute(
                    "INSERT OR IGNORE INTO file_group (id, name, description) VALUES (?, ?, ?)",
                    (group.id, group.name, group.description),
                )
                inserted += cursor.rowcount
            conn.commit()
        return inserted

    def list_all(self) -> list[dict]:
        """그룹 목록과 파일 수. 사용자가 만든 그룹을 먼저, 기존 고정 그룹은 뒤에 둔다."""
        with self.db.get_conn() as conn:
            rows = conn.execute(
                """
                SELECT g.id, g.name, g.description, g.created_at, g.updated_at,
                       COUNT(f.file_id) AS file_count
                FROM file_group g
                LEFT JOIN file f ON f.group_id = g.id
                GROUP BY g.id, g.name, g.description, g.created_at, g.updated_at
                """
            ).fetchall()
        groups = [dict(row) for row in rows]
        groups.sort(key=lambda group: (
            (1, _DEFAULT_ORDER[group["id"]], "")
            if group["id"] in _DEFAULT_ORDER
            else (0, 0, group["name"].casefold())
        ))
        return groups

    def create(self, name: str, description: str = "") -> dict:
        """그룹을 만들고 GET /groups 항목과 같은 형태로 돌려준다."""
        name = _normalize_name(name)
        description = _normalize_description(description)

        group_id = uuid4().hex
        with self.db.transaction() as conn:
            # 여러 서버 프로세스가 동시에 만들어도 이름 확인과 삽입을 하나의 쓰기 트랜잭션으로 묶는다.
            conn.execute("BEGIN IMMEDIATE")
            duplicate = conn.execute(
                "SELECT 1 FROM file_group WHERE lower(trim(name)) = lower(?) LIMIT 1",
                (name,),
            ).fetchone()
            if duplicate:
                raise DuplicateGroupNameError("같은 이름의 문서 그룹이 이미 있습니다.")
            conn.execute(
                "INSERT INTO file_group (id, name, description) VALUES (?, ?, ?)",
                (group_id, name, description),
            )
            timestamps = conn.execute(
                "SELECT created_at, updated_at FROM file_group WHERE id = ?",
                (group_id,),
            ).fetchone()

        return {
            "id": group_id,
            "name": name,
            "description": description,
            "created_at": timestamps["created_at"],
            "updated_at": timestamps["updated_at"],
            "file_count": 0,
        }

    def update(self, group_id: str, *, name: str | None = None, description: str | None = None) -> dict:
        """제공된 필드만 수정하고 GET /groups 항목과 같은 형태로 돌려준다."""
        if name is None and description is None:
            raise ValueError("수정할 그룹 이름 또는 설명을 입력해 주세요.")
        next_name = _normalize_name(name) if name is not None else None
        next_description = _normalize_description(description) if description is not None else None

        with self.db.transaction() as conn:
            conn.execute("BEGIN IMMEDIATE")
            current = conn.execute(
                "SELECT name, description FROM file_group WHERE id = ?",
                (group_id,),
            ).fetchone()
            if current is None:
                raise GroupNotFoundError("문서 그룹을 찾을 수 없습니다.")

            next_name = next_name if next_name is not None else current["name"]
            next_description = next_description if next_description is not None else current["description"]
            duplicate = conn.execute(
                "SELECT 1 FROM file_group WHERE lower(trim(name)) = lower(?) AND id <> ? LIMIT 1",
                (next_name, group_id),
            ).fetchone()
            if duplicate:
                raise DuplicateGroupNameError("같은 이름의 문서 그룹이 이미 있습니다.")

            conn.execute(
                """
                UPDATE file_group
                SET name = ?, description = ?, updated_at = strftime('%Y-%m-%d %H:%M:%f', 'now')
                WHERE id = ?
                """,
                (next_name, next_description, group_id),
            )
            file_count = conn.execute(
                "SELECT COUNT(*) FROM file WHERE group_id = ?",
                (group_id,),
            ).fetchone()[0]
            timestamps = conn.execute(
                "SELECT created_at, updated_at FROM file_group WHERE id = ?",
                (group_id,),
            ).fetchone()

        return {
            "id": group_id,
            "name": next_name,
            "description": next_description,
            "created_at": timestamps["created_at"],
            "updated_at": timestamps["updated_at"],
            "file_count": file_count,
        }

    def delete(self, group_id: str) -> None:
        """빈 문서 그룹을 지운다.

        파일이 남아 있으면 지우지 않는다. 그대로 지우면 DB의 file.group_id는 NULL이 되지만
        검색 청크(Chroma) 메타데이터에는 지운 group_id가 남아 그룹 필터 검색이 어긋난다.
        파일은 먼저 PUT /files/group 으로 옮겨야 한다 (청크 메타데이터도 함께 바뀐다).
        """
        with self.db.transaction() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if conn.execute("SELECT 1 FROM file_group WHERE id = ?", (group_id,)).fetchone() is None:
                raise GroupNotFoundError("문서 그룹을 찾을 수 없습니다.")
            file_count = conn.execute(
                "SELECT COUNT(*) FROM file WHERE group_id = ?",
                (group_id,),
            ).fetchone()[0]
            if file_count:
                raise GroupNotEmptyError(f"그룹에 파일 {file_count}개가 남아 있습니다. 파일을 먼저 다른 그룹이나 미분류로 옮겨 주세요.")
            conn.execute("DELETE FROM file_group WHERE id = ?", (group_id,))

    def prune_unused_defaults(self) -> int:
        """수정도 사용도 되지 않은 과거 자동 생성 그룹만 제거한다."""
        removed = 0
        with self.db.transaction() as conn:
            for group in DEFAULT_GROUPS:
                cursor = conn.execute(
                    """
                    DELETE FROM file_group
                    WHERE id = ? AND name = ? AND description = ?
                      AND created_at = updated_at
                      AND NOT EXISTS (SELECT 1 FROM file WHERE group_id = file_group.id)
                    """,
                    (group.id, group.name, group.description),
                )
                removed += cursor.rowcount
        return removed

    def exists(self, group_id: str) -> bool:
        with self.db.get_conn() as conn:
            row = conn.execute("SELECT 1 FROM file_group WHERE id = ? LIMIT 1", (group_id,)).fetchone()
            return row is not None
