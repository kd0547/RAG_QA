"""프론트엔드가 시작할 때 읽는 서버 설정 라우터."""
from __future__ import annotations

from fastapi import APIRouter

import config

router = APIRouter()


@router.get("/config")
def get_config() -> dict:
    # main.py는 ANTHROPIC_API_KEY가 있을 때만 Claude 모델을 주입하므로 같은 조건으로 판단한다.
    return {"claude_available": bool(config.CLAUDE_API_KEY)}
