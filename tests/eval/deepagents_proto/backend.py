"""deepagents용 읽기 전용 가상 파일 backend (통합 지시서 F-3). 운영 코드가 아니다.

가상 파일
- /docs/INDEX.md                  등록 문서 목록 (file_id, 파일명, 페이지 수)
- /docs/<file_id>/p0003.md        문서 페이지 텍스트 (file_page.text, 검수본). 읽으면 근거로 등록하고 첫 줄에 근거 ID를 적는다
- /skills/<name>/SKILL.md         저장소 skills/의 절차 문서 원문 (서버 로더가 통과시킨 것 중 모델이 고를 수 있는 것만)

쓰기·수정·삭제·업로드는 모두 거부한다 (permission_denied). 셸 실행이 없다 (SandboxBackendProtocol이 아니다).
"""
from __future__ import annotations

import fnmatch
import re
from datetime import datetime
from pathlib import PurePosixPath

from deepagents.backends.protocol import (
    BackendProtocol,
    DeleteResult,
    EditResult,
    FileDownloadResponse,
    FileUploadResponse,
    GlobResult,
    GrepResult,
    LsResult,
    ReadResult,
    WriteResult,
)

import repository
from agent import skills as skill_loader
from agent.evidence_context import current_owner, current_run

READ_ONLY = "읽기 전용입니다. 이 시제품의 파일은 쓰거나 고칠 수 없습니다."
_PAGE = re.compile(r"^/docs/(?P<file_id>[^/]+)/p(?P<page>\d{4})\.md$")


class RagReadOnlyBackend(BackendProtocol):

    def __init__(self, skill_names: list[str]):
        self._skill_names = list(skill_names)
        self.reads: list[str] = []  # 읽은 경로 (실행 기록용)

    # ------------------------------------------------------------ 가상 트리

    def _files(self) -> dict[str, dict]:
        files = {}
        for row in repository.file_repo.file_list():
            files[row["file_id"]] = row
        return files

    def _pages(self, file_id: str) -> list[int]:
        return sorted({r["page"] for r in repository.page_repo.list_pages(file_id)})

    def _skill(self, name: str):
        return skill_loader.get_skills().get(name) if name in self._skill_names else None

    def _index(self) -> str:
        counts = repository.page_repo.page_counts()
        lines = ["# 등록 문서", "", "| file_id | 파일명 | 페이지 수 | 경로 |", "|---|---|---|---|"]
        for file_id, row in self._files().items():
            if counts.get(file_id):
                lines.append(f"| {file_id} | {row.get('original_name')} | {counts[file_id]} | /docs/{file_id}/p0001.md … |")
        return "\n".join(lines) + "\n"

    def _content(self, path: str) -> str | None:
        """경로의 본문. 문서 페이지는 근거로 등록하고 첫 줄에 근거 ID를 붙인다."""
        path = str(PurePosixPath(path))
        if path == "/docs/INDEX.md":
            return self._index()
        match = _PAGE.match(path)
        if match:
            file_id, page = match["file_id"], int(match["page"])
            rows = repository.page_repo.pages_with_number(file_id, page)
            file = repository.file_repo.get_file_by_id(file_id)
            if not rows or file is None:
                return None
            text = "\n\n".join(r["text"] for r in rows)
            owner, run_id = current_owner(), current_run()
            if owner is None or run_id is None:
                return text
            evidence_id = repository.evidence_repo.register(
                owner.type, owner.id, "file_page", text, file_id=file_id, page=page, page_id=rows[0]["page_id"],
                revision=max(r["updated_at"] for r in rows), source_name=file.original_name,
            )
            repository.evidence_repo.record_use(run_id, evidence_id, "read")
            return f"[근거 ID: {evidence_id} — {file.original_name} p{page}. 답변 마지막 줄 '근거:'에 이 ID를 쓴다]\n{text}"
        parts = PurePosixPath(path).parts
        if len(parts) == 4 and parts[1] == "skills" and parts[3] == "SKILL.md":
            skill = self._skill(parts[2])
            if skill is not None:
                on_disk = skill_loader.SKILLS_DIR / skill.name / "SKILL.md"
                if on_disk.is_file():  # 저장소 절차는 원문 그대로
                    return on_disk.read_text(encoding="utf-8")
                # DB에서 승인된 절차는 파일이 없다: 머리말을 붙여 같은 형식으로
                return f"---\nname: {skill.name}\ndescription: {skill.description}\n---\n{skill.body}"
        return None

    def _all_paths(self) -> list[str]:
        paths = ["/docs/INDEX.md"]
        for file_id in self._files():
            paths += [f"/docs/{file_id}/p{page:04d}.md" for page in self._pages(file_id)]
        paths += [f"/skills/{name}/SKILL.md" for name in self._skill_names if self._skill(name)]
        return paths

    # ------------------------------------------------------------ 읽기

    def ls(self, path: str) -> LsResult:
        path = str(PurePosixPath(path or "/"))
        now = datetime.now().isoformat()
        if path == "/":
            return LsResult(entries=[{"path": "/docs/", "is_dir": True}, {"path": "/skills/", "is_dir": True}])
        if path == "/docs":
            entries = [{"path": "/docs/INDEX.md", "is_dir": False}]
            entries += [{"path": f"/docs/{fid}/", "is_dir": True} for fid in self._files() if self._pages(fid)]
            return LsResult(entries=entries)
        if path.startswith("/docs/"):
            file_id = PurePosixPath(path).parts[2]
            pages = self._pages(file_id)
            if not pages:
                return LsResult(error="file_not_found")
            return LsResult(entries=[{"path": f"/docs/{file_id}/p{p:04d}.md", "is_dir": False, "modified_at": now} for p in pages])
        if path == "/skills":
            return LsResult(entries=[{"path": f"/skills/{n}/", "is_dir": True} for n in self._skill_names if self._skill(n)])
        if path.startswith("/skills/"):
            name = PurePosixPath(path).parts[2]
            if self._skill(name) is None:
                return LsResult(error="file_not_found")
            return LsResult(entries=[{"path": f"/skills/{name}/SKILL.md", "is_dir": False}])
        return LsResult(error="file_not_found")

    def read(self, file_path: str, offset: int = 0, limit: int = 2000) -> ReadResult:
        content = self._content(file_path)
        if content is None:
            return ReadResult(error="file_not_found")
        self.reads.append(file_path)
        lines = content.splitlines()
        offset = max(0, int(offset or 0))
        if limit is not None and limit <= 0:
            return ReadResult(file_data={"content": "", "encoding": "utf-8"}, no_lines_requested=True)
        window = lines[offset:offset + (limit or len(lines))]
        if not window:
            return ReadResult(file_data={"content": "", "encoding": "utf-8"}, total_lines=len(lines))
        start, end = offset + 1, offset + len(window)
        return ReadResult(
            file_data={"content": "\n".join(window), "encoding": "utf-8"},
            total_lines=len(lines), start_line=start, end_line=end,
            next_offset=end if end < len(lines) else None,
        )

    def grep(self, pattern: str, path: str | None = None, glob: str | None = None, *, max_count: int | None = None) -> GrepResult:
        """글자 그대로 찾기 (대소문자 무시). 문서 페이지는 근거로 등록하지 않는다 (찾기만 했다)."""
        needle = (pattern or "").lower()
        if not needle:
            return GrepResult(matches=[])
        base = str(PurePosixPath(path or "/"))
        matches = []
        for item in self._all_paths():
            if not item.startswith(base.rstrip("/") + "/") and item != base:
                continue
            if glob and not fnmatch.fnmatch(PurePosixPath(item).name, glob):
                continue
            match = _PAGE.match(item)
            if match:
                rows = repository.page_repo.pages_with_number(match["file_id"], int(match["page"]))
                text = "\n\n".join(r["text"] for r in rows)
            else:
                text = self._content(item) if item.startswith("/skills/") or item == "/docs/INDEX.md" else ""
            for number, line in enumerate((text or "").splitlines(), start=1):
                if needle in line.lower():
                    matches.append({"path": item, "line": number, "text": line[:300]})
                    if max_count and len(matches) >= max_count:
                        return GrepResult(matches=matches, truncated=True)
        return GrepResult(matches=matches)

    def glob(self, pattern: str, path: str | None = None) -> GlobResult:
        base = str(PurePosixPath(path or "/"))
        found = []
        for item in self._all_paths():
            if not item.startswith(base.rstrip("/") + "/"):
                continue
            target = item if "/" in pattern else PurePosixPath(item).name
            if fnmatch.fnmatch(target, pattern) or fnmatch.fnmatch(item, pattern):
                found.append({"path": item, "is_dir": False})
        return GlobResult(matches=found)

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        responses = []
        for path in paths:
            # 절차 문서를 읽을 때 쓰인다 (SkillsMiddleware). 문서 페이지는 read로만 읽게 해 근거 등록을 한 곳에서 한다
            content = self._content(path) if str(path).startswith("/skills/") or path == "/docs/INDEX.md" else None
            responses.append(FileDownloadResponse(path=path, content=content.encode("utf-8") if content is not None else None,
                                                  error=None if content is not None else "file_not_found"))
        return responses

    # ------------------------------------------------------------ 쓰기 (모두 거부)

    def write(self, file_path: str, content: str) -> WriteResult:
        return WriteResult(error=READ_ONLY)

    def edit(self, file_path: str, old_string: str, new_string: str, replace_all: bool = False) -> EditResult:  # noqa: FBT001, FBT002
        return EditResult(error=READ_ONLY)

    def delete(self, file_path: str) -> DeleteResult:
        return DeleteResult(error=READ_ONLY)

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        return [FileUploadResponse(path=path, error="permission_denied") for path, _ in files]
