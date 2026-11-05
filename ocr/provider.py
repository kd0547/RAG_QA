"""환경변수로 선택하는 OCR 진입점. 무거운 의존성은 선택 후에만 불러온다."""
import atexit
from threading import RLock

import config
from ocr.base import OCRBackend

_backends: dict[str, OCRBackend] = {}
_lock = RLock()


def get_ocr_backend(name: str | None = None) -> OCRBackend:
    name = (name if name is not None else config.OCR_BACKEND).strip().lower()
    if name not in {"llm", "vlm"}:
        raise ValueError(f"지원하지 않는 OCR_BACKEND={name!r}. llm 또는 vlm을 지정하세요.")
    with _lock:
        if name not in _backends:
            if name == "llm":
                from ocr.llm_ocr import LLMOCR
                _backends[name] = LLMOCR()
            else:
                from ocr.vlm_ocr import VLMOCR
                _backends[name] = VLMOCR()
        return _backends[name]


def ocr_image(image_bytes: bytes) -> str:
    if not isinstance(image_bytes, bytes) or not image_bytes:
        raise ValueError("OCR 입력은 비어 있지 않은 이미지 bytes여야 합니다.")
    return get_ocr_backend().ocr_image(image_bytes)


def close_ocr_backends() -> None:
    with _lock:
        for backend in _backends.values():
            backend.close()
        _backends.clear()


atexit.register(close_ocr_backends)
