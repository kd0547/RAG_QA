import hashlib
import uuid
from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime


class FileStatus(Enum):
    PROCESSING = "processing"  # 업로드 완료, 청킹/임베딩 진행 중
    READY = "ready"            # 인덱싱 완료, 검색 가능
    FAILED = "failed"          # 인덱싱 실패 (error_message 참고)
    DELETING = "deleting"      # 삭제 진행 중 (중간 실패 시 재시도 대상)


@dataclass
class FileEntity:
    file_id: str                  # uuid, Chroma 메타데이터의 file_id와 같은 값
    original_name: str            # 사용자가 올린 파일명
    stored_path: str              # 실제 저장 경로
    mime_type: str | None = None
    size_bytes: int | None = None
    sha256: str | None = None     # 중복 업로드 확인용
    status: FileStatus = field(default_factory=lambda: FileStatus.PROCESSING)
    chunk_count: int | None = None
    error_message: str | None = None
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)


def create_file(
        original_name: str,
        stored_path: str,
        mime_type: str | None = None,
        sha256: str | None = None,
        size_bytes: int | None = None,
        chunk_count: int = 0,
) -> FileEntity:
    """새 업로드 파일의 FileEntity를 만든다. sha256은 documents 문자열을 이어 붙여 계산한다."""
    # 구분자 없이 join하면 ["ab", "c"]와 ["a", "bc"]의 해시가 같아진다

    return FileEntity(
        file_id=str(uuid.uuid4()),
        original_name=original_name,
        stored_path=stored_path,
        mime_type=mime_type,
        size_bytes=size_bytes,
        sha256=sha256,
        chunk_count=chunk_count,
    )
