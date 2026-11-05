"""이미지 한 장을 기존 VLM OCR 함수로 읽고 Markdown으로 저장하는 수동 테스트.

상단 IMAGE_PATH를 입력한 뒤 실행하거나, 명령행에서 이미지 경로를 전달하세요.
프로젝트의 tests/ 폴더에 두고 실행할 수 있습니다. pytest 자동 수집 대상은 아닙니다.
서버를 실행하지 않고 OCR만 호출합니다.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path


# 이 값만 본인의 이미지 경로로 바꾸면 됩니다. Windows 경로는 r"..."로 입력하세요.
IMAGE_PATH = r"C:\Users\김동욱\Desktop\노트북 입찰 사양.jpg"
# 예: IMAGE_PATH = r"C:\Users\김동욱\Desktop\노트북 입찰 사양.jpg"

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if not (PROJECT_ROOT / "ocr" / "llm_ocr.py").is_file():
    # 다운로드한 스크립트를 프로젝트 밖에서 실행할 때 사용할 프로젝트 위치.
    PROJECT_ROOT = Path(r"C:\TG_AI_DEV\rag_QA")

TIMEOUT_SECONDS = 300
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"}


def read_image(image_path: Path) -> bytes:
    """현재 OCR 모듈이 받는 이미지 형식을 검사한다. 원본 바이트는 바꾸지 않는다."""
    if not image_path.is_file():
        raise FileNotFoundError(f"이미지 파일을 찾을 수 없습니다: {image_path}")
    if image_path.suffix.lower() not in IMAGE_EXTENSIONS:
        raise ValueError(f"지원 이미지 형식: {', '.join(sorted(IMAGE_EXTENSIONS))}")
    data = image_path.read_bytes()
    if not data:
        raise ValueError(f"빈 이미지 파일입니다: {image_path}")
    return data


def response_text(content: object) -> str:
    """LangChain 문자열/텍스트 블록 응답을 처리한다. 원문 교정·요약은 하지 않는다."""
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") in (None, "text"):
                value = block.get("text")
                if isinstance(value, str):
                    parts.append(value)
        text = "".join(parts)
    else:
        raise TypeError(f"지원하지 않는 VLM 응답 형식: {type(content).__name__}")
    if not text.strip():
        raise ValueError("VLM이 빈 텍스트를 반환했습니다. response.json을 확인하세요.")
    return text


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def run_image_test(
    image_path: Path,
    output_dir: Path,
    *,
    ocr: Callable[[bytes], object],
    prompt: str,
    model_name: str,
    timeout_seconds: float = TIMEOUT_SECONDS,
    backend_name: str = "llm",
) -> Path:
    """OCR 원문과 재현 정보를 실행별 폴더에 저장한다. 실패하면 예외를 전달한다."""
    image_path = image_path.expanduser().resolve()
    image_bytes = read_image(image_path)
    run_at = datetime.now().astimezone()
    run_dir = output_dir.expanduser().resolve() / (
        f"{image_path.stem}_{run_at.strftime('%Y%m%d_%H%M%S_%f')}"
    )
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "prompt.md").write_text(prompt, encoding="utf-8")

    metadata = {
        "status": "running",
        "source": str(image_path),
        "source_sha256": hashlib.sha256(image_bytes).hexdigest(),
        "source_bytes": len(image_bytes),
        "model": model_name,
        "ocr_function": "ocr.provider.ocr_image",
        "backend": backend_name,
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "run_at": run_at.isoformat(),
        "timeout_seconds": timeout_seconds,
        "max_retries": 0,
        "image_transform": "none (original bytes)",
        "output_characters": 0,
    }
    write_json(run_dir / "run.json", metadata)
    print(f"이미지: {image_path}", flush=True)
    print(f"모델: {model_name}", flush=True)
    print(f"저장 폴더: {run_dir}", flush=True)
    print("VLM OCR 실행 중...", flush=True)

    started = time.perf_counter()
    try:
        content = ocr(image_bytes)
        # 문자열/블록 구조도 보존한다. API 키나 요청의 base64 이미지는 저장하지 않는다.
        write_json(run_dir / "response.json", {"content": content})
        text = response_text(content)
        result_path = run_dir / "result.md"
        # 평가 대상인 모델 출력에 제목, 설명, 자동 교정 결과를 추가하지 않는다.
        with result_path.open("x", encoding="utf-8", newline="") as stream:
            stream.write(text)
        metadata.update(status="success", output_characters=len(text))
    except BaseException as exc:
        # 중단도 기록하되 반드시 다시 던져 성공으로 보이지 않게 한다.
        metadata.update(status="failed", error_type=type(exc).__name__, error=str(exc))
        print(f"실패 기록: {run_dir / 'run.json'}", file=sys.stderr)
        raise
    finally:
        metadata["elapsed_seconds"] = round(time.perf_counter() - started, 3)
        write_json(run_dir / "run.json", metadata)

    print(f"완료: {metadata['elapsed_seconds']}초 / {len(text):,}자", flush=True)
    print(f"Markdown: {result_path}", flush=True)
    return result_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="이미지 -> 기존 VLM OCR -> result.md")
    parser.add_argument("image", nargs="?", default=IMAGE_PATH, help="이미지 파일의 경로")
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT, help="rag_QA 프로젝트 폴더")
    parser.add_argument("--out", type=Path, help="저장 상위 폴더 (기본: 프로젝트/markdown/vlm_tests)")
    parser.add_argument("--timeout", type=float, default=TIMEOUT_SECONDS, help="VLM 요청 제한 시간(초)")
    args = parser.parse_args(argv)
    if not args.image:
        parser.error("상단 IMAGE_PATH에 이미지 경로를 넣거나 명령행 인수로 전달하세요.")
    if args.timeout <= 0:
        parser.error("--timeout은 0보다 커야 합니다.")

    project_root = args.project_root.expanduser().resolve()
    image_path = Path(args.image).expanduser().resolve()
    try:
        read_image(image_path)  # 잘못된 경로는 모델 초기화 전에 알린다.
        if not (project_root / "ocr" / "llm_ocr.py").is_file():
            raise FileNotFoundError(f"프로젝트 OCR 모듈이 없습니다: {project_root}")
        sys.path.insert(0, str(project_root))

        from dotenv import load_dotenv
        load_dotenv(project_root / ".env")

        import config
        from langchain_openai import ChatOpenAI
        from agent.llm_provider import set_local_model
        from ocr.llm_ocr import OCR_PROMPT
        from ocr.provider import get_ocr_backend, ocr_image

        # 기존 프로젝트 모델 설정과 OCR 프롬프트를 재사용한다.
        # 샘플링 설정은 서비스 기본값을 유지하고, 테스트 요청 재시도만 끈다.
        backend = get_ocr_backend()
        if backend.name == "llm":
            set_local_model(ChatOpenAI(
                model=config.LLM_MODEL,
                base_url=config.LLM_BASE_URL,
                api_key=config.VLLM_API_KEY,
                timeout=args.timeout,
                max_retries=0,
            ))
        else:
            backend.timeout = args.timeout
        run_image_test(
            image_path,
            args.out or project_root / "markdown" / "vlm_tests",
            ocr=ocr_image,
            prompt=OCR_PROMPT if backend.name == "llm" else "PaddleOCR-VL-1.6 (built-in OCR)",
            model_name=config.LLM_MODEL if backend.name == "llm" else "PaddleOCR-VL-1.6",
            timeout_seconds=args.timeout,
            backend_name=backend.name,
        )
        return 0
    except KeyboardInterrupt:
        print("사용자가 실행을 중단했습니다.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"실패: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
