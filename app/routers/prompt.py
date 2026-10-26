"""프롬프트 설정 API. 답변 지침(시스템 프롬프트)을 여러 개 저장하고 그중 하나를 선택한다.

경로는 /prompts 이다. /prompt 는 프론트엔드 화면 경로라서 같은 이름을 쓰면 새로고침 시 API와 겹친다.
"""
import logging
from typing import Annotated

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, StringConstraints

from repository import prompt_repo
from repository.prompt_repository import DefaultPromptDeleteError, Prompt

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/prompts", tags=["prompts"])

# 프롬프트가 지나치게 길면 매 요청마다 모델 입력을 낭비하므로 상한을 둔다
MAX_PROMPT_LENGTH = 20_000

PromptName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class PromptBody(BaseModel):
    name: PromptName
    content: str = Field(min_length=1, max_length=MAX_PROMPT_LENGTH)


def _not_found(prompt_id: int) -> HTTPException:
    return HTTPException(status_code=404, detail=f"프롬프트를 찾을 수 없습니다: id={prompt_id}")


@router.get("")
def list_prompts() -> list[Prompt]:
    return prompt_repo.list_all()


# /{prompt_id} 보다 먼저 등록해야 "default"가 id로 해석되지 않는다
@router.get("/default")
def get_default_prompt() -> Prompt:
    """DB의 기본 프롬프트. 서버 시작 시 등록되므로 보통은 항상 있다."""
    prompt = prompt_repo.get_default()
    if prompt is None:
        raise HTTPException(status_code=404, detail="기본 프롬프트가 없습니다. 서버를 다시 시작하면 등록됩니다.")
    return prompt


@router.get("/{prompt_id}")
def get_prompt(prompt_id: int) -> Prompt:
    prompt = prompt_repo.get(prompt_id)
    if prompt is None:
        raise _not_found(prompt_id)
    return prompt


@router.post("", status_code=201)
def create_prompt(body: PromptBody) -> Prompt:
    prompt = prompt_repo.create(body.name, body.content)
    logger.info("프롬프트 생성: id=%d, length=%d", prompt.id, len(body.content))
    return prompt


@router.put("/{prompt_id}")
def update_prompt(prompt_id: int, body: PromptBody) -> Prompt:
    prompt = prompt_repo.update(prompt_id, body.name, body.content)
    if prompt is None:
        raise _not_found(prompt_id)
    logger.info("프롬프트 수정: id=%d, length=%d", prompt_id, len(body.content))
    return prompt


@router.delete("/{prompt_id}", status_code=204)
def delete_prompt(prompt_id: int) -> None:
    """선택된 프롬프트를 지우면 기본 프롬프트가 선택된다. 기본 프롬프트는 지울 수 없다."""
    try:
        deleted = prompt_repo.delete(prompt_id)
    except DefaultPromptDeleteError:
        raise HTTPException(status_code=409, detail="기본 프롬프트는 삭제할 수 없습니다.")
    if not deleted:
        raise _not_found(prompt_id)
    logger.info("프롬프트 삭제: id=%d", prompt_id)


@router.post("/{prompt_id}/select")
def select_prompt(prompt_id: int) -> Prompt:
    """이 프롬프트를 선택한다. 기존에 선택된 프롬프트는 자동으로 해제된다."""
    prompt = prompt_repo.select(prompt_id)
    if prompt is None:
        raise _not_found(prompt_id)
    logger.info("프롬프트 선택: id=%d", prompt_id)
    return prompt
