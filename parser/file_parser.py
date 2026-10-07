"""확장자별 파서를 골라 파일을 페이지별 텍스트로 변환하는 진입점."""
from importlib import import_module
from pathlib import Path

from parser.pdf.type import PageText

# 확장자 -> (모듈, 함수). 포맷별 라이브러리(python-docx, python-pptx, openpyxl, python-hwpx)가
# 설치되지 않은 환경에서도 다른 포맷은 동작하도록 실제 사용 시점에 import 한다.
_PAGED_PARSERS = {
    ".pdf": ("parser.pdf.pdf_parser", "parser_pdf_pages"),
    ".pptx": ("parser.pptx.pptx_parser", "parser_pptx_pages"),
    ".xlsx": ("parser.xlsx.xlsx_parser", "parser_xlsx_pages"),
}
_MARKDOWN_PARSERS = {
    ".docx": ("parser.docx.docx_parser", "parser_docx_md"),
    ".hwpx": ("parser.hwpx.hwpx_parser", "parser_hwpx_md"),
    ".hwp": ("parser.hwp.hwp_parser", "parser_hwp_md"),
}
_IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"})

SUPPORTED_EXTENSIONS = frozenset(_PAGED_PARSERS) | frozenset(_MARKDOWN_PARSERS) | _IMAGE_EXTENSIONS


def parse_file(file_path: str | Path) -> list[PageText]:
    """파일 확장자에 맞는 파서로 변환해 페이지별 텍스트를 반환한다.

    PDF는 실제 페이지, PPTX는 슬라이드, XLSX는 시트 단위로 나누고
    그 외 포맷은 문서 전체를 1페이지로 반환한다.
    """
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"파일을 찾을 수 없습니다: {file_path}")

    ext = file_path.suffix.lower()
    if ext in _PAGED_PARSERS:
        return _load(*_PAGED_PARSERS[ext])(file_path)
    if ext in _MARKDOWN_PARSERS:
        return [PageText(page=1, text=_load(*_MARKDOWN_PARSERS[ext])(str(file_path)))]
    if ext in _IMAGE_EXTENSIONS:
        from ocr.llm_ocr import ocr_image
        return [PageText(page=1, text=ocr_image(file_path.read_bytes()))]

    raise ValueError(
        f"지원하지 않는 파일 형식입니다: {file_path.suffix} "
        f"(지원: {', '.join(sorted(SUPPORTED_EXTENSIONS))})"
    )


def _load(module: str, func: str):
    return getattr(import_module(module), func)
