"""docx 파서의 이미지 OCR 처리 테스트. 실제 OCR 대신 가짜 함수를 쓴다."""
import base64
import sys
from pathlib import Path

import pytest
from docx import Document

# tests/parser.py가 parser 패키지를 가리지 않도록 프로젝트 루트를 앞에 둔다.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if not hasattr(sys.modules.get("parser"), "__path__"):
    sys.modules.pop("parser", None)

import ocr.provider
from parser.docx.docx_parser import parser_docx_md

# 1x1 PNG
_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


@pytest.fixture
def docx_with_images(tmp_path):
    img = tmp_path / "a.png"
    img.write_bytes(_PNG)
    doc = Document()
    doc.add_paragraph("앞 문단")
    doc.add_picture(str(img))
    doc.add_paragraph("[그림 1] 캡션")
    doc.add_picture(str(img))  # 같은 이미지 재사용
    doc.add_paragraph("뒤 문단")
    path = tmp_path / "t.docx"
    doc.save(path)
    return path


def test_images_are_ocr_ed_in_place(docx_with_images, monkeypatch):
    calls = []

    def fake_ocr(data: bytes) -> str:
        calls.append(data)
        return "이미지 OCR 결과"

    monkeypatch.setattr(ocr.provider, "ocr_image", fake_ocr)
    md = parser_docx_md(docx_with_images)

    assert md.strip().split("\n\n") == [
        "앞 문단", "이미지 OCR 결과", "[그림 1] 캡션", "이미지 OCR 결과", "뒤 문단",
    ]
    assert len(calls) == 1  # 같은 이미지는 한 번만 OCR


def test_ocr_failure_keeps_text(docx_with_images, monkeypatch):
    def broken_ocr(data: bytes) -> str:
        raise RuntimeError("OCR 서버 없음")

    monkeypatch.setattr(ocr.provider, "ocr_image", broken_ocr)
    md = parser_docx_md(docx_with_images)

    assert md.strip().split("\n\n") == ["앞 문단", "[그림 1] 캡션", "뒤 문단"]


def test_ocr_can_be_turned_off(docx_with_images, monkeypatch):
    monkeypatch.setattr(ocr.provider, "ocr_image", lambda data: pytest.fail("OCR 호출됨"))
    md = parser_docx_md(docx_with_images, ocr_images=False)

    assert md.strip().split("\n\n") == ["앞 문단", "[그림 1] 캡션", "뒤 문단"]
