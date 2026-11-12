"""모든 테스트에 공통으로 거는 격리 장치.

- 운영 DB(storage/mail.db): `repository` 패키지는 임포트 시점에 운영 DB를 열고 스키마를 적용한다.
  스키마에 테이블·컬럼이 추가되면 테스트 실행만으로 운영 DB가 바뀌므로, 그 경로로 가는 연결을
  세션 임시 폴더로 돌린다. (개별 테스트가 자기 임시 DB를 쓰는 것과 별개로 마지막 안전장치)
- 운영 벡터DB(storage/chroma): `repository.embedding_repository`는 임포트 시점에 Chroma를 연다.
  에이전트 모듈을 임포트하는 테스트를 위해 빈 대역 모듈을 미리 넣어 둔다.
  (파일 업로드 테스트들은 각자 monkeypatch로 자기 대역을 넣으므로 영향이 없다)
- tests/parser.py가 parser 패키지를 가리지 않게 프로젝트 루트를 sys.path 앞에 둔다.
"""
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path
from types import ModuleType

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) in sys.path:
    sys.path.remove(str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT))
if not hasattr(sys.modules.get("parser"), "__path__"):
    sys.modules.pop("parser", None)
# pytest는 테스트 모듈을 읽을 때 tests/를 sys.path 맨 앞에 넣는다. 그 전에 진짜 패키지를 캐시해 둔다.
import parser  # noqa: E402,F401

# ---------- 운영 DB 보호 ----------

_PRODUCTION_DBS = {
    (PROJECT_ROOT / "storage" / "mail.db").resolve(),
}
_SESSION_DIR = Path(tempfile.mkdtemp(prefix="ragqa-test-"))
_original_connect = sqlite3.connect


def _guarded_connect(database, *args, **kwargs):
    try:
        target = Path(database).resolve()
    except (TypeError, OSError):
        target = None
    if target in _PRODUCTION_DBS:
        database = str(_SESSION_DIR / target.name)
    return _original_connect(database, *args, **kwargs)


sqlite3.connect = _guarded_connect

# ---------- 벡터DB 대역 ----------

if "repository.embedding_repository" not in sys.modules:
    _embeddings = ModuleType("repository.embedding_repository")
    _embeddings.search = lambda **kwargs: []
    _embeddings.save_embeddings = lambda chunks: None
    _embeddings.delete_embeddings = lambda file_id: None
    _embeddings.replace_page_embeddings = lambda file_id, page, chunks: 0
    _embeddings.update_group_metadata = lambda file_id, group_id: 0
    sys.modules["repository.embedding_repository"] = _embeddings


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(_SESSION_DIR, ignore_errors=True)
