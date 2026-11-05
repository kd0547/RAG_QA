"""문서 파서 테스트 스크립트.

tests/data 에 있는 지원 문서(PDF, DOCX, HWP 등)를 파싱하고,
그 결과를 markdown/ 디렉토리에 .md 파일로 저장한다.
"""
from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from langchain_openai import ChatOpenAI

import config
from agent.llm_provider import set_local_model
from parser.file_parser import SUPPORTED_EXTENSIONS, parse_file
from parser.pdf.type import PageText

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("parser_test")


def init_llm() -> None:
    """PDF 이미지 OCR 등을 위해 LLM 프로바이더를 초기화한다."""
    try:
        local_llm = ChatOpenAI(
            model=config.LLM_MODEL,
            base_url=config.LLM_BASE_URL,
            api_key=config.VLLM_API_KEY,
            timeout=60,
        )
        set_local_model(local_llm)
        logger.info("로컬 LLM 초기화 완료: %s @ %s", config.LLM_MODEL, config.LLM_BASE_URL)
    except Exception as e:
        logger.warning("로컬 LLM 초기화 실패 (이미지 OCR이 비활성화될 수 있습니다): %s", e)


def save_pages_to_markdown(pages: list[PageText], output_path: Path, title: str) -> None:
    """파싱된 페이지 목록을 하나의 마크다운 파일로 저장한다."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    contents: list[str] = []
    if len(pages) == 1:
        contents.append(pages[0].text.strip())
    else:
        for p in pages:
            contents.append(f"<!-- Page {p.page} -->\n## Page {p.page}\n\n{p.text.strip()}")

    full_text = "\n\n---\n\n".join(contents).strip() + "\n"
    output_path.write_text(full_text, encoding="utf-8")
    logger.info("마크다운 저장 완료: %s (%d chars)", output_path, len(full_text))


def test_parser(
    data_dir: Path | str = PROJECT_ROOT / "tests" / "data",
    output_dir: Path | str = PROJECT_ROOT / "markdown",
) -> dict[str, dict]:
    """data_dir 내의 모든 지원 문서를 파싱하고 output_dir 에 md 파일로 저장한다."""
    data_dir = Path(data_dir)
    output_dir = Path(output_dir)

    if not data_dir.exists():
        raise FileNotFoundError(f"테스트 데이터 폴더를 찾을 수 없습니다: {data_dir}")

    if config.OCR_BACKEND.strip().lower() == "llm":
        init_llm()

    target_files = sorted(
        [p for p in data_dir.iterdir() if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS]
    )

    if not target_files:
        logger.warning("테스트 대상 파일이 없습니다: %s", data_dir)
        return {}

    print(f"\n========================================================")
    print(f" 파서 테스트 시작: 총 {len(target_files)}개 파일")
    print(f" - 입력 경로: {data_dir}")
    print(f" - 출력 경로: {output_dir}")
    print(f"========================================================\n")

    results: dict[str, dict] = {}

    for idx, file_path in enumerate(target_files, start=1):
        file_name = file_path.name
        ext = file_path.suffix.lower()
        md_file_name = f"{file_path.stem}.md"
        output_path = output_dir / md_file_name

        print(f"[{idx}/{len(target_files)}] 파싱 진행 중: {file_name} ({ext})")
        start_time = time.perf_counter()

        try:
            pages = parse_file(file_path)
            elapsed = time.perf_counter() - start_time
            total_chars = sum(len(p.text) for p in pages)

            save_pages_to_markdown(pages, output_path, title=file_path.stem)

            results[file_name] = {
                "status": "SUCCESS",
                "pages": len(pages),
                "chars": total_chars,
                "elapsed_sec": round(elapsed, 2),
                "output_path": str(output_path),
            }
            print(f"  -> 성공: {len(pages)} 페이지, 총 {total_chars:,} 자 ({elapsed:.2f}초) -> {output_path.name}\n")

        except Exception as e:
            elapsed = time.perf_counter() - start_time
            logger.exception("파일 파싱 실패: %s", file_name)
            results[file_name] = {
                "status": "FAILED",
                "error": str(e),
                "elapsed_sec": round(elapsed, 2),
            }
            print(f"  -> 실패: {e} ({elapsed:.2f}초)\n")

    # 결과 요약
    print("========================================================")
    print(" 파서 테스트 결과 요약")
    print("========================================================")
    for name, res in results.items():
        if res["status"] == "SUCCESS":
            print(f" [O] {name}")
            print(f"     페이지: {res['pages']} | 글자 수: {res['chars']:,}자 | 소요 시간: {res['elapsed_sec']}s")
            print(f"     저장 위치: {res['output_path']}")
        else:
            print(f" [X] {name}")
            print(f"     오류: {res.get('error')} | 소요 시간: {res['elapsed_sec']}s")
    print("========================================================\n")

    return results


if __name__ == "__main__":
    test_parser()
