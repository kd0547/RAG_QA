"""업무 절차(skill) 로더.

skills/<name>/SKILL.md (Agent Skills 형식: YAML 머리말 + 본문)를 서버 시작 때 한 번 읽어 둔다.
문서를 바꾸면 서버를 다시 시작해야 반영된다. 테스트는 reload_skills(directory)로 다른 폴더를 읽는다.

누가 고르는가 (설계 결정, 지시서 D 5-3)
- 서버가 고른다: 메일 채널의 모든 실행에 ALWAYS_FOR_MAIL, 반려를 반영하는 실행에 ON_REJECT. 본문을 시스템 프롬프트에 붙인다.
- 모델이 고른다: 그 밖의 절차. 시스템 프롬프트에는 이름·설명만 있고, 모델이 load_skill로 본문을 읽는다.
서버가 고르는 규칙은 여기 상수로 둔다 (문서 머리말에 넣지 않는다).

절차 본문은 모델에게 주는 안내일 뿐이다. 근거 검증·실행 한도·발송 승인 같은 서버 정책은 절차 내용과 관계없이 그대로다.
"""
from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

SKILLS_DIR = Path(__file__).resolve().parents[1] / "skills"

# 서버가 고르는 절차
ALWAYS_FOR_MAIL = ("mail-reply-style",)
ON_REJECT = ("revise-after-reject",)
SERVER_CHOSEN = ALWAYS_FOR_MAIL + ON_REJECT

CHANNELS = ("mail", "web")
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

    def ref(self) -> dict:
        """run.skills_json에 남기는 형태."""
        return {"name": self.name, "digest": self.digest}


class SkillError(ValueError):
    """검사를 통과하지 못한 절차 문서."""


def parse_skill(path: Path) -> Skill:
    """SKILL.md 하나를 읽어 검사한다. 어기면 SkillError."""
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
    text = text.removeprefix("\ufeff")  # BOM
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
        raise SkillError(f"channels는 mail·web만 쓸 수 있습니다: {raw_channels!r}")
    body = rest.strip("\n").strip()
    if not body:
        raise SkillError("본문이 없습니다")
    if len(body) > MAX_BODY_CHARS:
        raise SkillError(f"본문이 {MAX_BODY_CHARS}자를 넘습니다 ({len(body)}자)")
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()[:8]
    return Skill(name=name, description=description.strip(), channels=channels, body=body, digest=digest)


def load_skills(directory: Path | str = SKILLS_DIR) -> dict[str, Skill]:
    """*/SKILL.md를 읽어 이름 → Skill. 검사를 어긴 문서는 ERROR 로그를 남기고 뺀다 (서버는 계속 뜬다)."""
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
            continue
        skills[skill.name] = skill
    return skills


_skills: dict[str, Skill] | None = None


def reload_skills(directory: Path | str = SKILLS_DIR) -> dict[str, Skill]:
    """절차를 다시 읽는다. 서버 시작 때 한 번 부른다 (테스트는 임시 폴더로 부른다)."""
    global _skills
    _skills = load_skills(directory)
    return _skills


def get_skills() -> dict[str, Skill]:
    """읽어 둔 절차. 아직 안 읽었으면 저장소 skills/를 읽는다."""
    return _skills if _skills is not None else reload_skills()


def channel_for(owner) -> str:
    """근거 소유자로 채널을 정한다: task면 mail, 그 밖에는 web."""
    return "mail" if owner is not None and owner.type == "task" else "web"


def applied_skills(channel: str, rejecting: bool) -> list[Skill]:
    """서버가 이번 실행에 붙일 절차 (메일 채널에서만)."""
    if channel != "mail":
        return []
    skills = get_skills()
    names = ALWAYS_FOR_MAIL + (ON_REJECT if rejecting else ())
    missing = [n for n in names if n not in skills]
    if missing:
        logger.error("서버가 적용할 업무 절차가 없습니다(문서를 확인하세요): %s", ", ".join(missing))
    return [skills[n] for n in names if n in skills and channel in skills[n].channels]


def selectable_skills(channel: str) -> list[Skill]:
    """모델이 load_skill로 고를 수 있는 절차: 현재 채널에서 쓸 수 있고 서버가 고르는 절차가 아닌 것."""
    return [s for s in get_skills().values() if channel in s.channels and s.name not in SERVER_CHOSEN]
