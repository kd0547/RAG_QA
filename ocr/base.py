"""OCR 백엔드 공통 계약: 이미지 바이트 -> Markdown 문자열."""
from abc import ABC, abstractmethod


class OCRBackend(ABC):
    name: str

    @abstractmethod
    def ocr_image(self, image_bytes: bytes) -> str:
        """인식 실패는 예외로 전달한다. 텍스트 없는 이미지는 빈 문자열일 수 있다."""

    def close(self) -> None:
        """백엔드가 보유한 자원을 해제한다."""
