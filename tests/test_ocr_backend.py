"""외부 모델 없이 OCR 선택, 입력 전달, 실패 처리를 검증한다."""
import io
import json
from pathlib import Path
import queue
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config
from ocr import provider
from ocr.base import OCRBackend


@pytest.fixture(autouse=True)
def reset_backends():
    provider.close_ocr_backends()
    yield
    provider.close_ocr_backends()


@pytest.mark.parametrize("name", ["llm", "vlm"])
def test_env_selection_reuses_instance(name, monkeypatch):
    monkeypatch.setattr(config, "OCR_BACKEND", f" {name.upper()} ")
    backend = provider.get_ocr_backend()
    assert isinstance(backend, OCRBackend)
    assert backend.name == name
    assert provider.get_ocr_backend() is backend


def test_invalid_backend_fails(monkeypatch):
    monkeypatch.setattr(config, "OCR_BACKEND", "typo")
    with pytest.raises(ValueError, match="OCR_BACKEND"):
        provider.ocr_image(b"image")


@pytest.mark.parametrize("value", [b"", None, "image"])
def test_invalid_input(value):
    with pytest.raises(ValueError):
        provider.ocr_image(value)


def test_llm_response_and_prompt_preserved(monkeypatch):
    from ocr import llm_ocr
    calls = []
    llm = SimpleNamespace(invoke=lambda messages: calls.append(messages) or SimpleNamespace(
        content=[{"type": "text", "text": "<think>internal</think>\n# 결과"},
                 {"type": "reasoning", "text": "hidden"}], usage_metadata={"output_tokens": 7}))
    monkeypatch.setattr(llm_ocr, "get_llm_model", lambda mode: llm)
    monkeypatch.setattr(config, "OCR_BACKEND", "llm")
    assert provider.ocr_image(b"\xff\xd8\xffjpeg") == "# 결과"
    message = calls[0][0]
    assert message.content[0]["text"] == llm_ocr.OCR_PROMPT
    assert message.content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_image_parser_uses_selected_backend(tmp_path, monkeypatch):
    from parser.file_parser import parse_file
    path = tmp_path / "한글.png"
    path.write_bytes(b"image bytes")
    monkeypatch.setattr(config, "OCR_BACKEND", "vlm")
    backend = provider.get_ocr_backend()
    calls = []
    monkeypatch.setattr(backend, "ocr_image", lambda data: calls.append(data) or "| 내용 |")
    assert parse_file(path)[0].text == "| 내용 |"
    assert calls == [b"image bytes"]


def test_pdf_picture_uses_selected_backend(tmp_path, monkeypatch):
    from parser.pdf.pdf_parser import _describe_images, _render_page
    from parser.pdf.type import Page, Box
    image = tmp_path / "picture.png"
    image.write_bytes(b"pdf picture")
    monkeypatch.setattr(config, "OCR_BACKEND", "vlm")
    monkeypatch.setattr(provider.get_ocr_backend(), "ocr_image", lambda data: "PDF OCR")
    page = Page(page_number=1, width=10, height=10, boxes=[
        Box(x0=0, y0=0, x1=10, y1=10, boxclass="picture", image=str(image))])
    _describe_images(page)
    assert _render_page(page) == "PDF OCR"


def test_pdf_cli_vlm_does_not_require_llm(monkeypatch):
    from ocr.ocr_pdf import ocr_image_with_meta
    monkeypatch.setattr(config, "OCR_BACKEND", "vlm")
    monkeypatch.setattr(provider.get_ocr_backend(), "ocr_image", lambda data: "로컬 결과")
    assert ocr_image_with_meta(b"image") == ("로컬 결과", {})


def fake_worker(monkeypatch, tmp_path, response):
    from ocr.vlm_ocr import VLMOCR
    monkeypatch.setattr(config, "PADDLEOCR_CACHE_DIR", tmp_path)
    backend = VLMOCR()
    backend.log_path = tmp_path / "worker.log"
    backend.timeout = 0.01
    backend._process = SimpleNamespace(stdin=io.StringIO())
    backend._responses = queue.Queue()
    if response is not ...:
        backend._responses.put(response)
    monkeypatch.setattr(backend, "_start", lambda: None)
    closed = []
    monkeypatch.setattr(backend, "close", lambda: closed.append(True))
    return backend, closed


def test_worker_unicode_protocol_and_temp_cleanup(monkeypatch, tmp_path):
    backend, closed = fake_worker(monkeypatch, tmp_path, json.dumps({"text": "한글 표"}))
    assert backend.ocr_image(b"image") == "한글 표"
    sent = json.loads(backend._process.stdin.getvalue())
    assert not Path(sent["image_path"]).exists()
    assert not closed


@pytest.mark.parametrize("response,error", [
    (..., TimeoutError), (None, RuntimeError), ("not json", ValueError),
    (json.dumps({"error": "GPU failure"}), RuntimeError),
])
def test_worker_failure_closes_and_cleans(monkeypatch, tmp_path, response, error):
    backend, closed = fake_worker(monkeypatch, tmp_path, response)
    with pytest.raises(error):
        backend.ocr_image(b"image")
    assert closed
    assert not list(tmp_path.glob("request-*"))


def test_missing_python_is_actionable(monkeypatch, tmp_path):
    from ocr.vlm_ocr import VLMOCR
    monkeypatch.setattr(config, "PADDLEOCR_PYTHON", str(tmp_path / "missing.exe"))
    with pytest.raises(FileNotFoundError, match="PADDLEOCR_PYTHON"):
        VLMOCR().ocr_image(b"image")


def test_html_table_spans_become_markdown():
    from ocr.vlm_ocr import _normalize_markdown
    text = _normalize_markdown('''<table><tr><th>번호</th><th colspan="2">현황</th></tr>
        <tr><td rowspan="2">1</td><td>모델</td><td>A|B</td></tr>
        <tr><td>전압</td><td>19 V</td></tr></table>''')
    assert text == "| 번호 | 현황 |  |\n| --- | --- | --- |\n| 1 | 모델 | A\\|B |\n|  | 전압 | 19 V |"


def test_cli_reports_page_failures(monkeypatch, tmp_path):
    from ocr import ocr_pdf
    path = tmp_path / "sample.pdf"
    path.write_bytes(b"pdf")
    monkeypatch.setattr(ocr_pdf, "run_ocr", lambda *a, **kw: [{"error": "failed"}])
    assert ocr_pdf.run_ocr_path(tmp_path) is False
    monkeypatch.setattr(ocr_pdf, "run_ocr", lambda *a, **kw: [{"error": None}])
    assert ocr_pdf.run_ocr_path(tmp_path) is True


def test_real_worker_propagates_errors_and_recovers(monkeypatch, tmp_path):
    """실제 별도 Python/pipe로 런타임 오류 응답·재시작·종료를 검증 (모델 로드 없음)."""
    from ocr.vlm_ocr import VLMOCR
    monkeypatch.setattr(config, "PADDLEOCR_PYTHON", sys.executable)
    monkeypatch.setattr(config, "PADDLEOCR_VL_MODEL_DIR", str(tmp_path))
    monkeypatch.setattr(config, "PADDLEOCR_LAYOUT_MODEL_DIR", str(tmp_path))
    monkeypatch.setattr(config, "PADDLEOCR_CACHE_DIR", tmp_path / "cache")
    backend = VLMOCR()
    try:
        for _ in range(2):
            with pytest.raises(RuntimeError, match="PaddleOCR 실패"):
                backend.ocr_image(b"not an image")
            assert backend._process is None
            assert not list(backend.cache_dir.glob("request-*"))
    finally:
        backend.close()
