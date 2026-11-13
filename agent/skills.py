"""업무 절차(skill) 로더.

절차는 두 곳에서 온다.
- 저장소 절차(origin="repo"): skills/<name>/SKILL.md (Agent Skills 형식: YAML 머리말 + 본문). 서버 시작 때 한 번 읽는다.
  문서를 바꾸면 서버를 다시 시작해야 반영된다. 테스트는 reload_skills(directory)로 다른 폴더를 읽는다.
- DB 승인본(origin="db"): R&D가 승인 화면(/skill)에서 승인한 생성 절차 (skill_doc, 지시서 I).
  실행마다 조회한다 (승인·사용 중지가 재시작 없이 반영되게). 채널은 mail·web으로 고정이고, 모델이 고르는 절차로만 쓴다.

누가 고르는가 (설계 결정, 지시서 D 5-3)
- 서버가 고른다: 메일 채널의 모든 실행에 ALWAYS_FOR_MAIL, 반려를 반영하는 실행에 ON_REJECT. 본문을 시스템 프롬프트에 붙인다.
  서버가 고르는 절차는 저장소 절차에서만 찾는다 (DB 절차가 그 이름을 쓸 수 없다).
- 모델이 고른다: 그 밖의 절차. 시스템 프롬프트에는 이름·설명만 있고, 모델이 load_skill로 본문을 읽는다.
서버가 고르는 규칙은 여기 상수로 둔다 (문서 머리말에 넣지 않는다).

author 채널 절차(create-skill)는 절차 초안 생성 작업(agent/skill_author.py)의 시스템 프롬프트로만 쓴다.
메일·웹의 선택 절차 목록에 나오지 않고 load_skill로도 읽을 수 없다.

절차 본문은 모델에게 주는 안내일 뿐이다. 근거 검증·실행 한도·발송 승인 같은 서버 정책은 절차 내용과 관계없이 그대로다.
"""
from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

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


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    channels: tuple[str, ...]
    body: str
    digest: str  # 본문(줄바꿈 LF) sha256 앞 8자
    origin: str = "repo"  # repo(저장소 파일) | db(승인된 생성 절차)
    version: int | None = None  # DB 승인본의 버전. 저장소 절차는 None

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
        raise SkillError(f"본문이 {MAX_BODY_CHARS}자를 넘습니다 ({len(body)}자)")
    return Skill(name=name, description=description.strip(), channels=channels, body=body, digest=body_digest(body))


def load_skills(directory: Path | str = SKILLS_DIR, errors: dict[str, str] | None = None) -> dict[str, Skill]:
    """*/SKILL.md를 읽어 이름 → Skill. 검사를 어긴 문서는 ERROR 로그를 남기고 뺀다 (서버는 계속 뜬다).

    errors를 주면 뺀 문서의 폴더 이름 → 사유를 채운다 (화면에 '작성 절차 없음' 사유를 보이려고).
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


# ---------------------------------------------------------------- 저장소 절차 (시작 때 한 번)

_repo_skills: dict[str, Skill] | None = None
_repo_errors: dict[str, str] = {}


def reload_skills(directory: Path | str = SKILLS_DIR) -> dict[str, Skill]:
    """저장소 절차를 다시 읽는다. 서버 시작 때 한 번 부른다 (테스트는 임시 폴더로 부른다). 저장소 절차만 돌려준다."""
    global _repo_skills
    errors: dict[str, str] = {}
    _repo_skills = load_skills(directory, errors)
    _repo_errors.clear()
    _repo_errors.update(errors)
    return _repo_skills


def repo_skills() -> dict[str, Skill]:
    """읽어 둔 저장소 절차. 아직 안 읽었으면 저장소 skills/를 읽는다."""
    return _repo_skills if _repo_skills is not None else reload_skills()


# ---------------------------------------------------------------- DB 승인본 (실행마다 조회)

def _repository_source() -> list[dict]:
    """skill_doc의 사용 중 절차. 부를 때마다 repository.skill_repo를 찾는다 (테스트가 임시 DB로 바꿔 끼울 수 있게)."""
    import repository
    return repository.skill_repo.active_skill_docs()


# 사용 중인 DB 절차 행 [{name, version, description, body}]을 돌려주는 함수
_db_source: Callable[[], list[dict]] = _repository_source
# 같은 문제로 빠지는 DB 절차의 ERROR 로그를 실행마다 반복하지 않게 한다
_reported: set[tuple] = set()


def set_db_source(source: Callable[[], list[dict]] | None) -> None:
    """DB 승인본을 읽는 함수를 바꾼다 (테스트용). None이면 기본(skill_doc 조회)으로 돌린다."""
    global _db_source
    _db_source = source or _repository_source
    _reported.clear()


def _report_once(key: tuple, message: str, *args) -> None:
    if key in _reported:
        return
    _reported.add(key)
    logger.error(message, *args)


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
    """저장소 절차 + 사용 중인 DB 승인본. DB 절차는 부를 때마다 조회한다."""
    return {**repo_skills(), **db_skills()}


def author_skill() -> Skill | None:
    """절차 초안 생성 작업의 시스템 프롬프트(저장소 create-skill, author 채널). 없거나 검사를 통과하지 못했으면 None."""
    skill = repo_skills().get(AUTHOR_SKILL)
    return skill if skill is not None and skill.channels == (AUTHOR_CHANNEL,) else None


def author_skill_status() -> dict:
    """화면에 보일 작성 절차 상태: {available, name, digest, reason}."""
    skill = author_skill()
    if skill is not None:
        return {"available": True, "name": skill.name, "digest": skill.digest, "reason": None}
    if AUTHOR_SKILL in _repo_errors:
        reason = f"skills/{AUTHOR_SKILL}/SKILL.md가 검사를 통과하지 못했습니다: {_repo_errors[AUTHOR_SKILL]}"
    elif AUTHOR_SKILL in repo_skills():
        reason = f"skills/{AUTHOR_SKILL}/SKILL.md의 channels가 {AUTHOR_CHANNEL}가 아닙니다"
    else:
        reason = f"skills/{AUTHOR_SKILL}/SKILL.md가 없습니다"
    return {"available": False, "name": AUTHOR_SKILL, "digest": None, "reason": reason}


def channel_for(owner) -> str:
    """근거 소유자로 채널을 정한다: task면 mail, 그 밖에는 web."""
    return "mail" if owner is not None and owner.type == "task" else "web"


def applied_skills(channel: str, rejecting: bool) -> list[Skill]:
    """서버가 이번 실행에 붙일 절차 (메일 채널에서만, 저장소 절차에서만 찾는다)."""
    if channel != "mail":
        return []
    skills = repo_skills()
    names = ALWAYS_FOR_MAIL + (ON_REJECT if rejecting else ())
    missing = [n for n in names if n not in skills]
    if missing:
        logger.error("서버가 적용할 업무 절차가 없습니다(문서를 확인하세요): %s", ", ".join(missing))
    return [skills[n] for n in names if n in skills and channel in skills[n].channels]


def selectable_skills(channel: str) -> list[Skill]:
    """모델이 load_skill로 고를 수 있는 절차: 현재 답변 채널에서 쓸 수 있고 서버가 고르는 절차가 아닌 것.

    author 채널 절차는 어느 답변 채널에도 나오지 않는다. DB 승인본은 여기서 함께 나온다.
    """
    if channel not in ANSWER_CHANNELS:
        return []
    return [
        s for s in get_skills().values()
        if channel in s.channels and AUTHOR_CHANNEL not in s.channels and s.name not in SERVER_CHOSEN
    ]
