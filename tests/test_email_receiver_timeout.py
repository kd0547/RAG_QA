"""C2-P7: 메일 수신(POP3)·토큰 요청에 시간 제한. 장애 중에도 수신 스레드가 서버 종료를 막지 않는다."""
import threading
from types import SimpleNamespace

import pytest

import config
from mail import email_receiver


@pytest.fixture
def timing_out_pop3(monkeypatch):
    """POP3_SSL 대역: 생성자 인자를 기록하고 시간 초과를 던진다. 토큰은 대역."""
    calls = []

    def pop3(*args, **kwargs):
        calls.append(kwargs)
        raise TimeoutError("POP3 연결 시간 초과")

    monkeypatch.setattr(email_receiver.poplib, "POP3_SSL", pop3)
    monkeypatch.setattr(email_receiver, "get_access_token", lambda: "token")
    return calls


def test_pop3_timeout_returns_empty_list(timing_out_pop3):
    assert email_receiver.fetch_new_emails(set()) == []
    assert timing_out_pop3 == [{"timeout": config.POP3_TIMEOUT_SECONDS}]
    assert config.POP3_TIMEOUT_SECONDS == 30


def test_msal_client_gets_timeout(monkeypatch, tmp_path):
    seen = {}

    class App:
        def __init__(self, client_id, **kwargs):
            seen.update(kwargs)

        def get_accounts(self):
            return [{"username": "me"}]

        def acquire_token_silent(self, scopes, account):
            return {"access_token": "tok"}

    monkeypatch.setattr(email_receiver.msal, "PublicClientApplication", App)
    monkeypatch.setattr(email_receiver, "TOKEN_CACHE_FILE", str(tmp_path / "missing_cache.bin"))

    assert email_receiver.get_access_token() == "tok"
    assert seen["timeout"] == config.MSAL_TIMEOUT_SECONDS == 30


def test_receiver_loop_stops_within_five_seconds_during_outage(timing_out_pop3):
    """장애 대역에서 수신 루프를 멈추면 서버 종료 대기(5초) 안에 끝난다."""
    from mail import email_service

    stop = threading.Event()
    email_repo = SimpleNamespace(get_processed_uids=lambda: set())
    thread = threading.Thread(
        name="mail-receiver", target=email_service.email_receiver_loop, args=(stop, email_repo, None, None),
    )
    thread.start()
    while not timing_out_pop3:  # 한 번은 수신을 시도할 때까지
        thread.join(0.05)
    stop.set()
    thread.join(timeout=5)

    assert not thread.is_alive()
