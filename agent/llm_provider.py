"""LLM 인스턴스 프로바이더.

로컬(Ollama)/Claude 모델을 서버 부트스트랩 단계에서 주입받아 어디서든 가져다 쓴다.
agent/agent.py(에이전트 구성)뿐 아니라 ocr/llm_ocr.py(이미지 캡셔닝)처럼
서로 다른 계층에서도 LLM 인스턴스가 필요해서 별도 모듈로 분리했다 —
agent.py에 얹혀 있으면 retrieval/가 에이전트 빌드 로직 전체를 임포트해야 했다.
"""
from __future__ import annotations

from typing import Literal

from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI

_local_llm: ChatOpenAI | None = None
_claude_llm: ChatAnthropic | None = None


def set_local_model(model: ChatOpenAI) -> None:
    global _local_llm
    _local_llm = model


def set_claude_model(model: ChatAnthropic) -> None:
    global _claude_llm
    _claude_llm = model


def get_llm_model(mode: Literal["local", "claude"]) -> ChatOpenAI | ChatAnthropic:
    if mode == "local":
        if _local_llm is None:
            raise RuntimeError(
                "로컬 LLM이 아직 로드되지 않았습니다. "
                "서버 시작 시 set_local_model()로 모델을 주입해주세요."
            )
        return _local_llm

    if _claude_llm is None:
        raise RuntimeError(
            "Claude LLM이 아직 로드되지 않았습니다. "
            "서버 시작 시 set_claude_model()로 모델을 주입해주세요."
        )
    return _claude_llm
