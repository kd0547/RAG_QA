"""테스트용 SKILL 샘플.

저장소 skills/의 답변 SKILL(certification-bundle·mail-reply-style·revise-after-reject·spec-compare)과
create-skill은 2026-11-25에 일부러 지웠다 (커밋 9150614). 그래서 로더·load_skill·search_skills·SKILL API 테스트는
저장소 파일 대신 이 샘플을 임시 폴더에 써서 읽는다. 샘플은 실제 업무 SKILL 내용이 아니다.
"""
from __future__ import annotations

from pathlib import Path

from agent import skills

# 이름: (channels, description, body). 본문은 실제 도구 이름만 쓴다 (test_skill_bodies_only_mention_existing_tools)
SAMPLES: dict[str, tuple[str, str, str]] = {
    "certification-bundle": (
        "mail,web",
        "KC 인증처럼 여러 인증·증명서를 묶어 부르는 요청에 답할 때 읽는다. \"KC 인증 자료\", \"인증서를 보내 달라\", "
        "인증번호·발급기관·유효기간을 묻는 질문에 쓴다.",
        "# 인증 자료 묶음 (테스트 샘플)\n\n1. graph_search로 모델과 인증을 찾는다.\n2. read_pages로 인증서 페이지를 읽는다.",
    ),
    "mail-reply-style": (
        "mail",
        "메일 문의에 대한 답장 초안의 문체와 구성.",
        "# 메일 답장 문체 (테스트 샘플)\n\n인사, 결론, 근거 순으로 쓴다.",
    ),
    "revise-after-reject": (
        "mail",
        "검토 담당자가 초안을 반려했을 때 반려 사유를 반영해 다시 쓰는 절차.",
        "# 반려 반영 (테스트 샘플)\n\n사유마다 list_evidence로 이미 읽은 근거를 다시 확인한다.",
    ),
    "spec-compare": (
        "mail,web",
        "입찰·구매 사양서(첨부 또는 본문)의 조건을 우리 제품·부품과 조건별로 대조해 충족/미충족/확인 필요 표로 답할 때 읽는다. "
        "\"이 사양에 맞는 모델을 찾아 달라\", \"입찰 조건에 우리 제품이 해당되는지\" 같은 질문에 쓴다.",
        "# 입찰 사양 대조 (테스트 샘플)\n\n1. read_attachment로 조건을 모은다.\n2. compare_specs로 조건별로 대조한다.",
    ),
}
ANSWER_SKILLS = tuple(SAMPLES)

AUTHOR_DESCRIPTION = "업무 절차 초안을 쓰는 방법"


def write_samples(root: Path, *, author_body: str | None = None) -> Path:
    """샘플 답변 SKILL을 root 아래에 쓴다. author_body를 주면 create-skill(author 채널)도 쓴다."""
    entries = dict(SAMPLES)
    if author_body is not None:
        entries[skills.AUTHOR_SKILL] = ("author", AUTHOR_DESCRIPTION, author_body)
    for name, (channels, description, body) in entries.items():
        path = root / name / "SKILL.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f"---\nname: {name}\ndescription: {description}\nmetadata:\n  channels: \"{channels}\"\n---\n{body}\n",
            encoding="utf-8",
        )
    return root


def install_samples(root: Path, *, author_body: str | None = None) -> dict:
    """샘플을 쓰고 저장소 SKILL로 읽는다. 끝난 뒤에는 호출한 쪽이 skills.reload_skills()로 되돌린다."""
    return skills.reload_skills(write_samples(root, author_body=author_body))
