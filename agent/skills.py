"""업무 절차(skill) 로더.

절차는 두 곳에서 온다.
- 저장소 절차(origin="repo"): skills/<name>/SKILL.md (Agent Skills 형식: YAML 머리말 + 본문).
  부를 때마다 폴더의 서명(SKILL.md·참고 파일의 경로·수정 시각·크기)을 보고, 바뀌었으면 다시 읽는다.
  파일을 넣거나 고치거나 지우면 서버를 다시 시작하지 않아도 다음 실행부터 반영된다 (Hermes agent의 목록 캐시 방식).
  테스트는 reload_skills(directory)로 다른 폴더를 읽는다.
- DB 승인본(origin="db"): R&D가 승인 화면(/skill)에서 승인한 생성 절차 (skill_doc, 지시서 I).
  실행마다 조회한다. 채널은 mail·web으로 고정이고, 모델이 고르는 절차로만 쓴다.

사용 중지(끄기): 저장소 절차는 화면에서 끌 수 있다 (skill_disabled 테이블). 파일은 그대로 두고 답변·초안 생성에서만 뺀다.
꺼진 절차도 이름은 저장소 절차로 남는다 (DB 절차가 그 이름을 가져가지 못한다).

누가 고르는가 (설계 결정, 지시서 D 5-3)
- 서버가 고른다: 메일 채널의 모든 실행에 ALWAYS_FOR_MAIL, 반려를 반영하는 실행에 ON_REJECT. 본문을 시스템 프롬프트에 붙인다.
  서버가 고르는 절차는 저장소 절차에서만 찾는다. 꺼져 있거나 파일이 없으면 붙이지 않고 넘어간다.
- 모델이 고른다: 그 밖의 절차. 시스템 프롬프트에는 이름·설명만 있고, 모델이 load_skill로 본문을, search_skills로 검색을 한다.
  load_skill(name, file)로 절차 폴더의 참고 파일(references/·templates/)도 읽는다 (본문 6000자 제한을 넘는 자료).
- 한 실행 안에서는 실행을 시작할 때 잡은 목록(catalog_scope)을 쓴다. 실행 도중 파일이 바뀌어도 프롬프트 목록과 도구가 어긋나지 않는다.

author 채널 절차(create-skill)는 절차 초안 생성 작업(agent/skill_author.py)의 시스템 프롬프트로만 쓴다.
메일·웹의 선택 절차 목록에 나오지 않고 load_skill로도 읽을 수 없다.

절차 본문은 모델에게 주는 안내일 뿐이다. 근거 검증·실행 한도·발송 승인 같은 서버 정책은 절차 내용과 관계없이 그대로다.
"""
from __future__ import annotations

import hashlib
import logging
import re
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterator

import yaml

logger = logging.getLogger(__name__)

SKILLS_DIR = Path(__file__).resolve().parents[1] / "skills"

# 서버가 고르는 절차
ALWAYS_FOR_MAIL = ("mail-reply-style",)
ON_REJECT = ("revise-after-reject",)
SERVER_CHOSEN = ALWAYS_FOR_MAIL + ON_REJECT

# 답변 채널(mail·web)과 절차 작성 채널(author)
ANSWER_CHANNELS = ("mail", "web")
AUTHOR_CHANNEL = "author"
CHANNELS = ANSWER_CHANNELS + (AUTHOR_CHANNEL,)
# 절차 초안 생성 작업이 시스템 프롬프트로 쓰는 저장소 절차
AUTHOR_SKILL = "create-skill"
# DB 승인본의 채널은 고정이다
DB_CHANNELS = ANSWER_CHANNELS
# API 고정 경로(/skills/drafts 등)와 겹치는 이름은 DB 절차에 쓸 수 없다
RESERVED_NAMES = ("drafts", "types", "analysis")

NAME_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
MAX_DESCRIPTION_CHARS = 1024
MAX_BODY_CHARS = 6000

# 참고 파일: 절차 폴더 아래 이 하위 폴더의 텍스트 파일만 읽는다 (스크립트·실행 파일은 읽지 않는다)
SUPPORT_DIRS = ("references", "templates")
SUPPORT_SUFFIXES = (".md", ".txt", ".csv")
MAX_SUPPORT_FILES = 20
MAX_SUPPORT_FILE_CHARS = 20000

# 폴더 서명을 다시 보는 최소 간격(초). 한 실행 안에서 여러 번 불러도 파일 시스템을 매번 훑지 않게 한다.
CHECK_INTERVAL_SECONDS = 1.0


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    channels: tuple[str, ...]
    body: str
    digest: str  # 본문(줄바꿈 LF) sha256 앞 8자
    origin: str = "repo"  # repo(저장소 파일) | db(승인된 생성 절차)
    version: int | None = None  # DB 승인본의 버전. 저장소 절차는 None
    files: tuple[str, ...] = ()  # 참고 파일 (절차 폴더 기준 상대 경로, 예: references/models.md). 저장소 절차만
    folder: Path | None = None  # 저장소 절차의 폴더

    def ref(self) -> dict:
        """run.skills_json에 남기는 형태."""
        return {"name": self.name, "digest": self.digest}


class SkillError(ValueError):
    """검사를 통과하지 못한 절차 문서."""


def normalize_body(text: str) -> str:
    """줄바꿈을 LF로 맞추고 앞뒤 빈 줄·공백을 지운다 (digest를 같은 기준으로 계산하려고)."""
    return text.replace("\r\n", "\n").replace("\r", "\n").strip("\n").strip()


def body_digest(body: str) -> str:
    return hashlib.sha256(normalize_body(body).encode("utf-8")).hexdigest()[:8]


def _support_paths(folder: Path) -> list[Path]:
    """절차 폴더의 참고 파일 후보 (references/·templates/ 아래 텍스트 파일, 심볼릭 링크 제외, 이름 순)."""
    found: list[Path] = []
    for sub in SUPPORT_DIRS:
        root = folder / sub
        if not root.is_dir() or root.is_symlink():
            continue
        for path in sorted(root.rglob("*")):
            if path.is_file() and not path.is_symlink() and path.suffix.lower() in SUPPORT_SUFFIXES:
                found.append(path)
    return found


def parse_skill(path: Path) -> Skill:
    """SKILL.md 하나를 읽어 검사한다. 어기면 SkillError."""
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
    text = text.removeprefix("﻿")  # BOM
    if not text.startswith("---\n"):
        raise SkillError("머리말(---)이 없습니다")
    end = text.find("\n---", 4)
    if end < 0:
        raise SkillError("머리말이 닫히지 않았습니다")
    header_text = text[4:end]
    rest = text[end + len("\n---"):]
    if rest and not rest.startswith("\n"):
        raise SkillError("머리말 닫는 줄(---) 뒤에 글자가 있습니다")
    try:
        header = yaml.safe_load(header_text) or {}
    except yaml.YAMLError as exc:
        raise SkillError(f"머리말 YAML을 읽지 못했습니다: {exc}") from exc
    if not isinstance(header, dict):
        raise SkillError("머리말이 키-값 형식이 아닙니다")

    folder = path.parent.name
    name = header.get("name")
    if not isinstance(name, str) or name != folder:
        raise SkillError(f"name({name!r})이 폴더 이름({folder!r})과 다릅니다")
    if not NAME_PATTERN.match(name):
        raise SkillError(f"name 형식이 아닙니다: {name!r}")
    description = header.get("description")
    if not isinstance(description, str) or not 1 <= len(description.strip()) <= MAX_DESCRIPTION_CHARS:
        raise SkillError(f"description은 1~{MAX_DESCRIPTION_CHARS}자여야 합니다")
    metadata = header.get("metadata") or {}
    if not isinstance(metadata, dict):
        raise SkillError("metadata가 키-값 형식이 아닙니다")
    raw_channels = metadata.get("channels")
    if not isinstance(raw_channels, str):
        raise SkillError("metadata.channels가 없습니다 (예: \"mail,web\")")
    channels = tuple(c.strip() for c in raw_channels.split(",") if c.strip())
    if not channels or any(c not in CHANNELS for c in channels):
        raise SkillError(f"channels는 {'·'.join(CHANNELS)}만 쓸 수 있습니다: {raw_channels!r}")
    if AUTHOR_CHANNEL in channels and len(channels) > 1:
        # 작성 절차가 답변 채널에 섞여 모델에 읽히지 않게 한다
        raise SkillError(f"{AUTHOR_CHANNEL} 채널은 다른 채널과 함께 쓸 수 없습니다: {raw_channels!r}")
    body = normalize_body(rest)
    if not body:
        raise SkillError("본문이 없습니다")
    if len(body) > MAX_BODY_CHARS:
        raise SkillError(f"본문이 {MAX_BODY_CHARS}자를 넘습니다 ({len(body)}자). 긴 자료는 references/ 참고 파일로 나눕니다")
    files = tuple(p.relative_to(path.parent).as_posix() for p in _support_paths(path.parent)[:MAX_SUPPORT_FILES])
    return Skill(name=name, description=description.strip(), channels=channels, body=body, digest=body_digest(body),
                 files=files, folder=path.parent)


def load_skills(directory: Path | str = SKILLS_DIR, errors: dict[str, str] | None = None) -> dict[str, Skill]:
    """*/SKILL.md를 읽어 이름 → Skill. 검사를 어긴 문서는 ERROR 로그를 남기고 뺀다 (서버는 계속 뜬다).

    errors를 주면 뺀 문서의 폴더 이름 → 사유를 채운다 (화면에 '불러오지 못한 문서'로 보이려고).
    """
    directory = Path(directory)
    skills: dict[str, Skill] = {}
    if not directory.is_dir():
        logger.error("업무 절차 폴더가 없습니다: %s", directory)
        return skills
    for path in sorted(directory.glob("*/SKILL.md")):
        try:
            skill = parse_skill(path)
        except (SkillError, OSError, UnicodeDecodeError) as exc:
            logger.error("업무 절차 문서를 뺌: %s — %s", path, exc)
            if errors is not None:
                errors[path.parent.name] = str(exc)
            continue
        skills[skill.name] = skill
    return skills


# ---------------------------------------------------------------- 저장소 절차 (바뀌면 다시 읽는다)

_skills_dir: Path = SKILLS_DIR
_repo_skills: dict[str, Skill] | None = None
_repo_errors: dict[str, str] = {}
_repo_signature: tuple | None = None
_loaded_at: str | None = None
_checked_at = 0.0
_lock = threading.RLock()


def _scan_signature(directory: Path) -> tuple:
    """폴더 서명: 절차 폴더마다 SKILL.md와 참고 파일의 (상대 경로, 수정 시각, 크기). 파일 내용은 읽지 않는다."""
    entries: list[tuple] = []
    try:
        for skill_md in sorted(directory.glob("*/SKILL.md")):
            for path in [skill_md, *_support_paths(skill_md.parent)]:
                stat = path.stat()
                entries.append((path.relative_to(directory).as_posix(), stat.st_mtime_ns, stat.st_size))
    except OSError as exc:
        # 훑는 도중 파일이 지워진 경우 등: 서명을 다르게 만들어 다음에 다시 읽게 한다
        entries.append(("<scan-error>", str(exc)))
    return str(directory), tuple(entries)


def _read(signature: tuple) -> None:
    global _repo_skills, _repo_signature, _loaded_at
    errors: dict[str, str] = {}
    previous = _repo_skills
    _repo_skills = load_skills(_skills_dir, errors)
    _repo_errors.clear()
    _repo_errors.update(errors)
    _repo_signature = signature
    _loaded_at = datetime.now().isoformat(timespec="seconds")
    _reported.clear()  # 문서가 바뀌었으니 '없음' 경고를 다시 남길 수 있게
    if previous is not None:
        logger.info("업무 절차를 다시 읽음 (%d개): %s", len(_repo_skills),
                    ", ".join(f"{s.name}·{s.digest}" for s in _repo_skills.values()) or "없음")


def reload_skills(directory: Path | str = SKILLS_DIR) -> dict[str, Skill]:
    """저장소 절차 폴더를 정하고 바로 다시 읽는다 (테스트는 임시 폴더로 부른다). 저장소 절차만 돌려준다."""
    global _skills_dir, _checked_at
    with _lock:
        _skills_dir = Path(directory)
        _read(_scan_signature(_skills_dir))
        _checked_at = time.monotonic()
        return _repo_skills


def repo_skills() -> dict[str, Skill]:
    """저장소 절차 전부 (꺼진 것 포함, 이름 충돌 검사용). 폴더가 바뀌었으면 다시 읽는다."""
    global _checked_at
    with _lock:
        now = time.monotonic()
        if _repo_skills is None or now - _checked_at >= CHECK_INTERVAL_SECONDS:
            _checked_at = now
            signature = _scan_signature(_skills_dir)
            if signature != _repo_signature:
                _read(signature)
        return _repo_skills


def repo_errors() -> dict[str, str]:
    """검사를 통과하지 못해 뺀 문서: 폴더 이름 → 사유."""
    repo_skills()
    return dict(_repo_errors)


def skills_dir() -> Path:
    """지금 읽는 저장소 절차 폴더."""
    return _skills_dir


def loaded_at() -> str | None:
    """저장소 절차를 마지막으로 읽은 시각 (ISO)."""
    repo_skills()
    return _loaded_at


def read_support_file(skill: Skill, relative: str) -> str | None:
    """참고 파일 본문. 절차가 가진 목록(skill.files)에 있는 경로만 읽는다. 없거나 폴더 밖이면 None."""
    if skill.folder is None or relative not in skill.files:
        return None
    folder = skill.folder.resolve()
    path = (folder / relative).resolve()
    if not path.is_relative_to(folder) or not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")
    except OSError:
        return None
    if len(text) > MAX_SUPPORT_FILE_CHARS:
        text = text[:MAX_SUPPORT_FILE_CHARS] + f"\n…(이하 생략: {len(text)}자 중 {MAX_SUPPORT_FILE_CHARS}자까지)"
    return text


# ---------------------------------------------------------------- 사용 중지 (실행마다 조회)

def _repository_disabled() -> set[str]:
    import repository
    return repository.skill_repo.disabled_skill_names()


_disabled_source: Callable[[], set[str]] = _repository_disabled


def set_disabled_source(source: Callable[[], set[str]] | None) -> None:
    """꺼진 절차 이름을 읽는 함수를 바꾼다 (테스트용). None이면 기본(skill_disabled 조회)으로 돌린다."""
    global _disabled_source
    _disabled_source = source or _repository_disabled


def disabled_names() -> frozenset[str]:
    """꺼진 저장소 절차 이름. 조회가 실패하면 빈 집합(모두 켠 것으로 계속한다)."""
    try:
        return frozenset(_disabled_source())
    except Exception as exc:
        _report_once(("disabled-source", type(exc).__name__), "꺼진 업무 절차 조회 실패, 모두 켠 것으로 계속: %s", exc)
        return frozenset()


def enabled_repo_skills() -> dict[str, Skill]:
    """켜져 있는 저장소 절차."""
    off = disabled_names()
    return {name: skill for name, skill in repo_skills().items() if name not in off}


# ---------------------------------------------------------------- DB 승인본 (실행마다 조회)

def _repository_source() -> list[dict]:
    """skill_doc의 사용 중 절차. 부를 때마다 repository.skill_repo를 찾는다 (테스트가 임시 DB로 바꿔 끼울 수 있게)."""
    import repository
    return repository.skill_repo.active_skill_docs()


# 사용 중인 DB 절차 행 [{name, version, description, body}]을 돌려주는 함수
_db_source: Callable[[], list[dict]] = _repository_source
# 같은 문제로 빠지는 절차의 로그를 실행마다 반복하지 않게 한다
_reported: set[tuple] = set()


def set_db_source(source: Callable[[], list[dict]] | None) -> None:
    """DB 승인본을 읽는 함수를 바꾼다 (테스트용). None이면 기본(skill_doc 조회)으로 돌린다."""
    global _db_source
    _db_source = source or _repository_source
    _reported.clear()


def _report_once(key: tuple, message: str, *args, level: int = logging.ERROR) -> None:
    if key in _reported:
        return
    _reported.add(key)
    logger.log(level, message, *args)


def db_skill_problem(name: str, description: str | None, body: str | None) -> str | None:
    """DB 절차로 쓸 수 없는 이유. 쓸 수 있으면 None (승인 전 검사와 별개로 읽을 때 한 번 더 막는다)."""
    if not isinstance(name, str) or not NAME_PATTERN.match(name):
        return f"name 형식이 아닙니다: {name!r}"
    if name in repo_skills() or name in SERVER_CHOSEN or name == AUTHOR_SKILL:
        return "저장소 절차와 이름이 같습니다"
    if name in RESERVED_NAMES:
        return "예약어 이름입니다"
    if not isinstance(description, str) or not 1 <= len(description.strip()) <= MAX_DESCRIPTION_CHARS:
        return f"description은 1~{MAX_DESCRIPTION_CHARS}자여야 합니다"
    body = normalize_body(body or "")
    if not body or len(body) > MAX_BODY_CHARS:
        return f"본문은 1~{MAX_BODY_CHARS}자여야 합니다"
    if body.startswith("---"):
        return "본문에 머리말(---)이 있습니다"
    return None


def db_skills() -> dict[str, Skill]:
    """사용 중인 DB 승인본. 조회가 실패하면 빈 사전(저장소 절차만으로 계속한다)."""
    try:
        rows = list(_db_source())
    except Exception:
        logger.exception("DB 업무 절차 조회 실패, 저장소 절차만 사용")
        return {}
    result: dict[str, Skill] = {}
    for row in rows:
        name, version = row.get("name"), row.get("version")
        problem = db_skill_problem(name, row.get("description"), row.get("body"))
        if problem is None and name in result:
            problem = "같은 이름의 사용 중 절차가 둘입니다"
        if problem:
            _report_once((name, version, problem), "DB 업무 절차를 읽지 않음: %s v%s — %s", name, version, problem)
            continue
        body = normalize_body(row["body"])
        result[name] = Skill(
            name=name, description=row["description"].strip(), channels=DB_CHANNELS, body=body,
            digest=body_digest(body), origin="db", version=version,
        )
    return result


# ---------------------------------------------------------------- 조회

def get_skills() -> dict[str, Skill]:
    """켜진 저장소 절차 + 사용 중인 DB 승인본."""
    return {**enabled_repo_skills(), **db_skills()}


def author_skill() -> Skill | None:
    """절차 초안 생성 작업의 시스템 프롬프트(저장소 create-skill, author 채널). 없거나 꺼졌거나 검사를 통과하지 못했으면 None."""
    skill = enabled_repo_skills().get(AUTHOR_SKILL)
    return skill if skill is not None and skill.channels == (AUTHOR_CHANNEL,) else None


def author_skill_status() -> dict:
    """화면에 보일 작성 절차 상태: {available, name, digest, reason}."""
    skill = author_skill()
    if skill is not None:
        return {"available": True, "name": skill.name, "digest": skill.digest, "reason": None}
    errors = repo_errors()
    if AUTHOR_SKILL in errors:
        reason = f"skills/{AUTHOR_SKILL}/SKILL.md가 검사를 통과하지 못했습니다: {errors[AUTHOR_SKILL]}"
    elif AUTHOR_SKILL in repo_skills() and AUTHOR_SKILL in disabled_names():
        reason = f"{AUTHOR_SKILL} SKILL이 사용 중지되어 있습니다 (사용 중 SKILL 화면에서 다시 켭니다)"
    elif AUTHOR_SKILL in repo_skills():
        reason = f"skills/{AUTHOR_SKILL}/SKILL.md의 channels가 {AUTHOR_CHANNEL}가 아닙니다"
    else:
        reason = f"skills/{AUTHOR_SKILL}/SKILL.md가 없습니다"
    return {"available": False, "name": AUTHOR_SKILL, "digest": None, "reason": reason}


def channel_for(owner) -> str:
    """근거 소유자로 채널을 정한다: task면 mail, 그 밖에는 web."""
    return "mail" if owner is not None and owner.type == "task" else "web"


def applied_skills(channel: str, rejecting: bool) -> list[Skill]:
    """서버가 이번 실행에 붙일 절차 (메일 채널에서만, 켜진 저장소 절차에서만 찾는다).

    꺼진 절차는 조용히 건너뛴다. 파일이 없는 절차는 경고를 한 번만 남긴다 (일부러 지웠을 수 있다).
    """
    if channel != "mail":
        return []
    names = ALWAYS_FOR_MAIL + (ON_REJECT if rejecting else ())
    everything = repo_skills()
    enabled = enabled_repo_skills()
    for name in names:
        if name not in everything:
            _report_once(("server-missing", name), "서버가 적용할 업무 절차가 없어 붙이지 않음: %s", name,
                         level=logging.WARNING)
    return [enabled[n] for n in names if n in enabled and channel in enabled[n].channels]


def selectable_skills(channel: str) -> list[Skill]:
    """모델이 load_skill로 고를 수 있는 절차: 현재 답변 채널에서 쓸 수 있고 서버가 고르는 절차가 아닌 것.

    author 채널 절차와 꺼진 절차는 나오지 않는다. DB 승인본은 여기서 함께 나온다.
    """
    if channel not in ANSWER_CHANNELS:
        return []
    return [
        s for s in get_skills().values()
        if channel in s.channels and AUTHOR_CHANNEL not in s.channels and s.name not in SERVER_CHOSEN
    ]


# ---------------------------------------------------------------- 실행 단위 목록

# (채널, 그 실행의 선택 절차) — 실행을 시작할 때 잡아 두고 프롬프트와 load_skill·search_skills가 같이 쓴다
_run_catalog: ContextVar[tuple[str, tuple[Skill, ...]] | None] = ContextVar("skill_run_catalog", default=None)


@contextmanager
def catalog_scope(channel: str, selectable: list[Skill]) -> Iterator[None]:
    """이번 실행의 선택 절차 목록을 고정한다. contextvars라서 도구가 다른 스레드에서 돌아도 같은 목록을 본다."""
    token = _run_catalog.set((channel, tuple(selectable)))
    try:
        yield
    finally:
        _run_catalog.reset(token)


def run_selectable(channel: str) -> list[Skill]:
    """이번 실행의 선택 절차. 실행 밖(테스트에서 도구를 직접 부를 때 등)이면 지금 목록."""
    snapshot = _run_catalog.get()
    if snapshot is not None and snapshot[0] == channel:
        return list(snapshot[1])
    return selectable_skills(channel)


# ---------------------------------------------------------------- 검색

_WORD = re.compile(r"\w+")


def _grams(text: str) -> set[str]:
    """낱말별 두 글자 조각 (한 글자 낱말은 그대로). 한국어는 띄어쓰기·조사가 달라도 겹치게 하려고 조각으로 비교한다."""
    grams: set[str] = set()
    for word in _WORD.findall(text.casefold()):
        if len(word) == 1:
            grams.add(word)
        else:
            grams.update(word[i:i + 2] for i in range(len(word) - 1))
    return grams


def search_skills(query: str, pool: list[Skill], limit: int = 5) -> list[tuple[Skill, float]]:
    """질문 단어와 겹치는 정도로 절차를 고른다: 이름·설명에서 겹치면 3점, 본문 제목줄 2점, 본문 1점.

    점수는 질문 조각 수로 나눈 0~3 값이다. 겹치는 것이 없는 절차는 빼고, 점수 높은 순으로 limit개.
    """
    wanted = _grams(query)
    if not wanted:
        return []
    scored: list[tuple[Skill, float]] = []
    for skill in pool:
        head = _grams(f"{skill.name.replace('-', ' ')} {skill.description}")
        titles = _grams(" ".join(line for line in skill.body.splitlines() if line.lstrip().startswith("#")))
        body = _grams(skill.body)
        score = sum(3 if g in head else 2 if g in titles else 1 if g in body else 0 for g in wanted) / len(wanted)
        if score > 0:
            scored.append((skill, round(score, 2)))
    scored.sort(key=lambda item: (-item[1], item[0].name))
    return scored[:limit]
