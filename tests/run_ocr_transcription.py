"""기존 승인된 PDF를 문자 전사 전용 LLM 프롬프트로 재평가한다."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TRANSCRIPTION_PROMPT = """이미지에서 실제로 보이는 모든 글자를 그대로 전사하세요. OCR 문자 정확도 평가용입니다.
본문, 제목, 머리글, 바닥글, 페이지 번호, 표, 캡션, 로고의 읽을 수 있는 글자와 사진 속 라벨의 읽을 수 있는 글자까지 포함하세요.
위에서 아래로, 같은 높이에서는 왼쪽에서 오른쪽 순서로 읽으세요. 표는 행 순서로, 각 행 안에서는 왼쪽 셀부터 읽으세요.
원문의 철자, 대소문자, 숫자, 단위, 기호, 문장부호를 그대로 유지하세요. 요약·교정·번역하지 마세요.
사진이나 그림의 내용 설명, 추측, 서론, 맺음말을 절대 추가하지 마세요. 바코드/2D코드 패턴을 글자로 읽지 마세요.
순수 텍스트만 출력하세요. Markdown 제목/표 구분선/HTML 태그/이미지 자리표시자를 만들지 마세요.
문단과 표의 행은 줄바꿈으로 구분하고, 표의 셀은 탭으로 구분하세요. 병합 셀의 글자는 한 번만 쓰세요.
정말 읽을 수 없는 글자는 [판독불가]로 표시하고 추측해서 채우지 마세요.
"""


if __name__ == "__main__":
    import config
    from ocr.ocr_pdf import run_ocr, _get_cli_llm
    source = next((ROOT / "tests/data").glob("KC*.pdf"))
    output = ROOT / "markdown/ocr_cer/llm_transcription"
    output.mkdir(parents=True, exist_ok=True)
    (output / "prompt.txt").write_text(TRANSCRIPTION_PROMPT, encoding="utf-8")
    pages = run_ocr(source, llm=_get_cli_llm(), prompt=TRANSCRIPTION_PROMPT, out_dir=output)
    raise SystemExit(0 if all(p["error"] is None for p in pages) else 1)
