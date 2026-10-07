"""리포지토리 계층의 조립 지점.

Database/EmailRepository/TaskRepository는 SQLite 커넥션과 스레드 락을 공유해야 하므로
여기서 딱 한 번만 생성한다. main.py(서버 조립)와 app/routers/mails.py(API)가
모두 이 인스턴스를 가져다 쓴다 — 각자 새로 만들면 락이 분리되어 동시성 보장이 깨진다.
"""
from pathlib import Path

from repository.file_repository import FileRepository
from repository.repo_connect import Database
from repository.email_repository import EmailRepository
from repository.task_repository import TaskRepository

db = Database(str(Path(__file__).resolve().parent.parent / "storage" / "mail.db"))
email_repo = EmailRepository(db)
task_repo = TaskRepository(db)
file_repo = FileRepository(db)
