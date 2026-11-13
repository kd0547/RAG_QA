import threading

import config
from agent.agent import run_agent, run_agent_temp_attachments, task_thread_id
from agent.evidence_context import Owner
from entity.type import MailEntity
from repository.email_repository import EmailRepository
from repository.repo_connect import Database
from repository.task_repository import TaskRepository

from .email_receiver import fetch_new_emails
from entity.type import TaskStatus
import logging

from mail.email_send import SendOutcome, send_email
from logging_config import mask_email
from mail.templates import render_mail_review_email


logger = logging.getLogger(__name__)


def intake_mail(mail: MailEntity, db: Database, email_repo: EmailRepository, task_repo: TaskRepository) -> None:
    with db.transaction() as conn:
        email_repo.save_pending(mail, conn)
        task_repo.create_task(mail.uid, conn)

def build_review_feedback(reject_reasons: list[str]) -> str | None:
    """반려 사유를 같은 대화의 다음 user 메시지로 만든다. 반려가 없으면 None.

    이전 초안은 넣지 않는다 (같은 대화에 이미 있다).
    """
    if not reject_reasons:
        return None
    reasons = "\n".join(f"- {reason}" for reason in reject_reasons)
    return (
        "[검토 담당자 반려]\n"
        f"{reasons}\n\n"
        "위 사유를 반영해 답변을 다시 작성하세요. 이 메시지는 질문이 아니므로 검색어로 쓰지 말고 답변 본문에서 언급하지 마세요. "
        "이미 읽은 근거는 evidence_id로 다시 인용할 수 있습니다."
    )


def notify_reviewer_async(reviewer: str, mail: MailEntity, answer: str, task_id: str) -> threading.Thread:
    """검토 알림을 별도 데몬 스레드(mail-notify)로 보낸다.

    메일 서버 장애 때 알림 하나가 수십 초 걸려도 처리 루프의 다음 작업이 밀리지 않게 한다.
    초안은 이미 저장된 뒤라 순서 문제가 없다. 서버 종료 때 기다리지 않는다 (데몬).
    """
    thread = threading.Thread(
        name="mail-notify", target=_notify_reviewer, args=(reviewer, mail, answer, task_id), daemon=True,
    )
    thread.start()
    return thread


def _notify_reviewer(reviewer: str, mail: MailEntity, answer: str, task_id: str) -> None:
    """검토 담당자에게 초안 알림 메일을 보낸다. 실패는 로그만 남기고 상태는 바꾸지 않는다."""
    try:
        result = send_email(
            reviewer,
            f"[테스트][검토]{mail.subject}",
            render_mail_review_email(
                mail=mail,
                answer=answer,
                task_id=task_id,
                base_url=config.PUBLIC_BASE_URL,
            ),
            html=True,
            timeout=config.NOTIFY_SMTP_TIMEOUT_SECONDS,
        )
    except Exception:
        logger.exception("검토 알림 발송 실패(초안은 저장됨): task_id=%s, reviewer=%s", task_id, mask_email(reviewer))
        return
    if result.outcome != SendOutcome.SENT:
        logger.error(
            "검토 알림 발송 실패(초안은 저장됨): task_id=%s, reviewer=%s, %s, %s",
            task_id, mask_email(reviewer), result.outcome.value, result.detail,
        )
        return
    logger.info("검토 알림 발송: task_id=%s, reviewer=%s", task_id, mask_email(reviewer))


def email_receiver_loop(
        stop_event: threading.Event,
        email_repo:EmailRepository,
        task_repo:TaskRepository,
        db: Database):
    logger.info("메일 수신 루프 시작")

    while not stop_event.is_set():
        try:
            processed_uids = email_repo.get_processed_uids()
            new_emails = fetch_new_emails(processed_uids)

            if new_emails:
                logger.info("새 메일 %d건 수신", len(new_emails))
            else:
                logger.debug("새 메일 없음")
            for mail in new_emails:
                try:
                    intake_mail(mail=mail,db=db, email_repo=email_repo,task_repo=task_repo)
                except Exception:
                    logger.exception("메일 저장 실패: uid=%s", mail.uid)
                    continue

                logger.info(
                    "메일 저장 완료: uid=%s, subject=%s, attachments=%d",
                    mail.uid, mail.subject, len(mail.attachments),
                )
        except Exception:
            logger.exception("메일 수신 루프 오류")

        stop_event.wait(60)

    logger.info("메일 수신 루프 종료")


def email_consumer_loop(stop_event: threading.Event,
                        email_repo:EmailRepository,
                        task_repo:TaskRepository):
    logger.info("메일 처리 루프 시작")

    while not stop_event.is_set():
        # DB 조회가 실패해도 스레드가 죽지 않도록 잡고 다음 주기에 다시 시도한다
        try:
            pending_tasks = task_repo.get_pending_tasks()
        except Exception:
            logger.exception("대기 작업 조회 실패")
            stop_event.wait(10)
            continue

        for task in pending_tasks:
            try:
                # 생성 중 표시. 서버가 도중에 재시작되면 main.py가 pending으로 되돌린다.
                task_repo.update_status(task.task_id, TaskStatus.PROCESSING)

                # 처리할 수 없는 작업은 pending에서 빼야 10초마다 같은 경고가 반복되지 않는다.
                # failed로 두면 대시보드 기본 목록에 보여 담당자가 직접 확인할 수 있다.
                mail = email_repo.get_mail_by_id(task.mail_uid)
                if mail is None:
                    logger.warning("메일을 찾을 수 없어 failed 처리: task_id=%s, mail_uid=%s", task.task_id, task.mail_uid)
                    task_repo.update_status(task.task_id, TaskStatus.FAILED)
                    continue

                logger.info(
                    "메일 처리 시작: task_id=%s, uid=%s, sender=%s, subject=%s",
                    task.task_id, mail.uid, mask_email(mail.sender), mail.subject,
                )

                #메일 읽기
                body = mail.body
                if not body or not body.strip():
                    logger.warning(
                        "본문이 비어있어 failed 처리: task_id=%s, uid=%s, subject=%s, attachments=%d",
                        task.task_id, mail.uid, mail.subject, len(mail.attachments),
                    )
                    task_repo.update_status(task.task_id, TaskStatus.FAILED)
                    continue


                #반려 후 재생성이면 아직 반영하지 않은 반려만 같은 대화의 다음 턴으로 넘김
                unapplied = task_repo.unapplied_reject_reasons(task.task_id)
                review = None
                if unapplied:
                    review = (unapplied[-1][0], build_review_feedback([reason for _, reason in unapplied]))
                    logger.info(
                        "반려 반영해 재생성: task_id=%s, uid=%s, 미반영 반려 %d건, review_id=%s",
                        task.task_id, mail.uid, len(unapplied), review[0],
                    )

                #답변 생성하기
                result = run_agent_temp_attachments(
                    body,
                    mode="local",
                    attachments=mail.attachments,
                    review=review,
                    owner=Owner("task", task.task_id),
                    thread_id=task_thread_id(task.task_id),
                )
                answer = result["answer"]
                sources = result["sources"]

                dandang = config.REVIEWER_EMAIL
                #담당자 배정 (지금은 .env의 REVIEWER_EMAIL 한 명)
                task_repo.assign_task(task.task_id, dandang)

                # 초안을 먼저 저장한다. 알림 메일의 링크를 누르는 시점에 초안이 DB에 있어야 한다.
                validation = result.get("validation")
                task_repo.save_draft(
                    task.task_id, answer, sources, validation=validation,
                    applied_review_id=review[0] if review else None,
                )
                if validation and not validation.get("ok", True):
                    logger.warning("초안 근거 검증 경고: task_id=%s, %s", task.task_id, validation.get("errors"))
                logger.info(
                    "초안 저장 완료: task_id=%s, uid=%s, reviewer=%s, answer_len=%d, sources=%d",
                    task.task_id, mail.uid, dandang, len(answer), len(sources),
                )

                # 알림은 별도 스레드로 보낸다. 실패해도 초안은 drafted로 남는다 (담당자는 대시보드에서 볼 수 있다)
                notify_reviewer_async(dandang, mail, answer, task.task_id)

            except Exception:
                logger.exception("메일 처리 실패: task_id=%s, mail_uid=%s", task.task_id, task.mail_uid)
                # 상태 갱신까지 실패하면 다음 주기에 다시 처리된다 (스레드는 유지)
                try:
                    task_repo.update_status(task.task_id, TaskStatus.FAILED)
                except Exception:
                    logger.exception("실패 상태 저장 실패: task_id=%s", task.task_id)

        stop_event.wait(10)

    logger.info("메일 처리 루프 종료")





def email_loop_build(email_repo: EmailRepository, task_repo: TaskRepository,db:Database):

    stop_event = threading.Event()
    # 로그의 [threadName]으로 어느 루프에서 난 로그인지 구분한다
    producer = threading.Thread(
        name="mail-receiver",
        target=email_receiver_loop,
        args=(stop_event, email_repo,task_repo,db),
    )
    consumer = threading.Thread(
        name="mail-consumer",
        target=email_consumer_loop,
        args=(stop_event, email_repo ,task_repo),
    )

    producer.start()
    consumer.start()
    logger.info("생산자/소비자 스레드 시작 완료")

    return producer, consumer, stop_event