"""A4: send_email의 결과 분기. smtplib.SMTP를 대역으로 바꿔 수락 확인 여부에 따른 세 결과를 재현한다."""
import logging
import smtplib

import pytest

from mail import email_send
from mail.email_send import SendOutcome


class FakeSMTP:
    """단계별로 실패를 주입할 수 있는 SMTP 대역. 실제 연결은 하지 않는다."""

    fail_at: str | None = None        # "connect" | "login" | "data" | "quit"
    mail_code = 250
    rcpt_code = 250
    data_code = 250
    data_exception: BaseException | None = None
    instances: list["FakeSMTP"] = []

    def __init__(self, host, port, timeout=None):
        if self.fail_at == "connect":
            raise ConnectionRefusedError("연결 거부")
        self.calls: list[str] = []
        self.payload: bytes | None = None
        self.closed = False
        type(self).instances.append(self)

    def ehlo(self):
        self.calls.append("ehlo")

    def starttls(self):
        self.calls.append("starttls")

    def login(self, user, password):
        self.calls.append("login")
        if self.fail_at == "login":
            raise smtplib.SMTPAuthenticationError(535, b"5.7.3 Authentication unsuccessful")

    def mail(self, sender):
        self.calls.append("mail")
        return self.mail_code, b"ok"

    def rcpt(self, recipient):
        self.calls.append("rcpt")
        return self.rcpt_code, b"ok"

    def data(self, payload):
        self.calls.append("data")
        self.payload = payload
        if self.data_exception is not None:
            raise self.data_exception
        return self.data_code, b"queued"

    def quit(self):
        self.calls.append("quit")
        if self.fail_at == "quit":
            raise smtplib.SMTPServerDisconnected("quit 중 끊김")

    def close(self):
        self.closed = True

    def send_message(self, *args, **kwargs):  # 쓰면 안 된다 (단계별 결과를 알 수 없음)
        raise AssertionError("send_message를 쓰지 않는다")


@pytest.fixture
def smtp(monkeypatch):
    class Smtp(FakeSMTP):
        instances = []

    monkeypatch.setattr(email_send.smtplib, "SMTP", Smtp)
    return Smtp


def _send():
    return email_send.send_email("customer@example.com", "[응답] 제목", "<p>본문</p>", html=True)


def test_login_failure_is_failed(smtp):
    smtp.fail_at = "login"

    result = _send()

    assert result.outcome == SendOutcome.FAILED
    assert "SMTPAuthenticationError" in result.detail
    assert "data" not in smtp.instances[0].calls
    assert smtp.instances[0].closed


def test_connect_failure_is_failed(smtp):
    smtp.fail_at = "connect"

    result = _send()

    assert result.outcome == SendOutcome.FAILED
    assert "ConnectionRefusedError" in result.detail


def test_rcpt_rejected_is_failed(smtp):
    smtp.rcpt_code = 550

    result = _send()

    assert result.outcome == SendOutcome.FAILED
    assert result.detail.startswith("RCPT 550")
    assert "data" not in smtp.instances[0].calls


def test_disconnect_during_data_is_unknown(smtp):
    smtp.data_exception = smtplib.SMTPServerDisconnected("본문 전송 중 끊김")

    result = _send()

    assert result.outcome == SendOutcome.UNKNOWN
    assert "SMTPServerDisconnected" in result.detail


def test_timeout_during_data_is_unknown(smtp):
    smtp.data_exception = TimeoutError("timed out")

    assert _send().outcome == SendOutcome.UNKNOWN


def test_data_command_refused_is_failed(smtp):
    """DATA 명령 자체를 거절(354 아님)하면 본문을 보내기 전이므로 FAILED."""
    smtp.data_exception = smtplib.SMTPDataError(554, b"Transaction failed")

    result = _send()

    assert result.outcome == SendOutcome.FAILED
    assert result.detail.startswith("DATA 554")


def test_data_non_250_reply_is_failed(smtp):
    smtp.data_code = 451

    result = _send()

    assert result.outcome == SendOutcome.FAILED
    assert result.detail.startswith("DATA 451")


def test_accepted_then_quit_fails_is_sent_with_warning(smtp, caplog):
    smtp.fail_at = "quit"

    with caplog.at_level(logging.INFO, logger="mail.email_send"):
        result = _send()

    assert result.outcome == SendOutcome.SENT
    assert result.cleanup_warning and "SMTPServerDisconnected" in result.cleanup_warning
    assert "경고=" in caplog.text


def test_sent_payload_is_crlf_mime(smtp):
    result = _send()

    assert result.outcome == SendOutcome.SENT and result.cleanup_warning is None
    instance = smtp.instances[0]
    assert instance.calls == ["ehlo", "starttls", "ehlo", "login", "mail", "rcpt", "data", "quit"]
    assert b"To: customer@example.com\r\n" in instance.payload
    assert b"Content-Type: multipart/mixed" in instance.payload


def test_timeout_argument_is_passed_to_smtp(smtp, monkeypatch):
    seen = []

    class Recording(smtp):
        def __init__(self, host, port, timeout=None):
            seen.append(timeout)
            super().__init__(host, port, timeout)

    monkeypatch.setattr(email_send.smtplib, "SMTP", Recording)

    email_send.send_email("a@example.com", "s", "b", timeout=20)
    email_send.send_email("a@example.com", "s", "b")

    assert seen == [20, email_send.SMTP_TIMEOUT_SECONDS]
