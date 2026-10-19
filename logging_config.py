"""로그 설정: 콘솔 + logs/ 폴더 파일 저장.

uvicorn은 자기 로거(uvicorn, uvicorn.access)만 설정하고 루트 로거는 비워둔다.
그대로 두면 앱 모듈의 logger.info/debug는 버려지므로 서버 시작 시 setup_logging()을 한 번 호출한다.

남기는 파일 (매일 자정에 날짜를 붙여 교체, LOG_BACKUP_DAYS일 보관):
- logs/app.log    : 앱 + uvicorn 서버 로그 (LOG_LEVEL 이상)
- logs/error.log  : WARNING 이상만 모아 장애 확인용
- logs/access.log : HTTP 요청 로그 (uvicorn.access)
"""
from __future__ import annotations

import logging
import sys
import threading
from logging.handlers import TimedRotatingFileHandler

import config

LOG_FORMAT = "%(asctime)s %(levelname)-8s [%(threadName)s] %(name)s:%(lineno)d - %(message)s"

# 요청·모델 호출마다 INFO 로그를 쏟아내는 외부 라이브러리는 WARNING 이상만 남긴다
NOISY_LOGGERS = (
    "httpx", "httpx2", "httpcore", "urllib3", "openai", "anthropic",
    "chromadb", "sentence_transformers", "msal", "multipart",
)

_configured = False


def _file_handler(filename: str, level: int, formatter: logging.Formatter) -> TimedRotatingFileHandler:
    handler = TimedRotatingFileHandler(
        config.LOG_DIR / filename,
        when="midnight",
        backupCount=config.LOG_BACKUP_DAYS,
        encoding="utf-8",
    )
    handler.setLevel(level)
    handler.setFormatter(formatter)
    return handler


def setup_logging() -> None:
    """루트 로거에 콘솔/파일 핸들러를 붙인다. 여러 번 호출돼도 한 번만 적용된다."""
    global _configured
    if _configured:
        return

    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    level = logging.getLevelName(config.LOG_LEVEL.upper())
    if not isinstance(level, int):
        level = logging.INFO

    formatter = logging.Formatter(LOG_FORMAT)
    app_file = _file_handler("app.log", level, formatter)
    error_file = _file_handler("error.log", logging.WARNING, formatter)
    access_file = _file_handler("access.log", logging.INFO, formatter)

    console = logging.StreamHandler()
    console.setLevel(level)
    console.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(level)
    for handler in (console, app_file, error_file):
        root.addHandler(handler)

    # uvicorn 로거는 propagate=False라 루트까지 오지 않는다. 콘솔은 uvicorn이 이미 찍으므로 파일만 붙인다.
    logging.getLogger("uvicorn").addHandler(app_file)
    logging.getLogger("uvicorn").addHandler(error_file)
    logging.getLogger("uvicorn.access").addHandler(access_file)

    for name in NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)

    _install_excepthooks()
    _configured = True
    logging.getLogger(__name__).info(
        "로그 설정 완료: dir=%s, level=%s, 보관=%d일",
        config.LOG_DIR, logging.getLevelName(level), config.LOG_BACKUP_DAYS,
    )


def mask_email(address: str | None) -> str | None:
    """로그용 이메일 마스킹: 'dongwook.kim@trigem.co.kr' -> 'do***@trigem.co.kr'.

    로그 파일은 DB보다 쉽게 복사·공유되므로 외부 발신자 주소를 그대로 남기지 않는다.
    원래 주소가 필요하면 함께 남기는 task_id/uid로 DB에서 찾는다.
    """
    if not address or "@" not in address:
        return address
    local, _, domain = address.rpartition("@")
    keep = 2 if len(local) > 2 else 1
    return f"{local[:keep]}***@{domain}"


def _install_excepthooks() -> None:
    """잡히지 않은 예외(특히 메일 생산자/소비자 스레드가 죽는 경우)도 로그 파일에 남긴다."""
    logger = logging.getLogger("uncaught")

    def thread_hook(args: threading.ExceptHookArgs) -> None:
        if issubclass(args.exc_type, SystemExit):
            return
        thread_name = args.thread.name if args.thread else "unknown"
        logger.critical(
            "스레드 비정상 종료: %s", thread_name,
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    def sys_hook(exc_type, exc_value, exc_traceback) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        logger.critical("처리되지 않은 예외", exc_info=(exc_type, exc_value, exc_traceback))

    threading.excepthook = thread_hook
    sys.excepthook = sys_hook
