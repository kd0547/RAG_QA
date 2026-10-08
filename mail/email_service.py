import threading

import config
from agent.rag_agent import run_agent, run_agent_temp_attachments
from entity.type import MailEntity
from repository.email_repository import EmailRepository
from repository.repo_connect import Database
from repository.task_repository import TaskRepository

from .email_receiver import fetch_new_emails
from entity.type import TaskStatus
import logging

from mail.email_send import send_email
from mail.templates import render_mail_review_email


logger = logging.getLogger(__name__)


def intake_mail(mail: MailEntity, db: Database, email_repo: EmailRepository, task_repo: TaskRepository) -> None:
    print("저장 실행중...")
    with db.transaction() as conn:
        email_repo.save_pending(mail, conn)
        task_repo.create_task(mail.uid, conn)

def build_review_feedback(previous_draft: str, reject_reasons: list[str]) -> str | None:
    """반려된 이전 초안과 사유를 에이전트에게 줄 안내문으로 만든다. 반려 이력이 없으면 None."""
    if not reject_reasons:
        return None

    reasons = "\n".join(f"- {reason}" for reason in reject_reasons)
    feedback = (
        "[검토 담당자 피드백]\n"
        "이전에 작성한 답변 초안이 담당자 검토에서 반려되었습니다. "
        "아래 반려 사유를 반영해 답변을 새로 작성하세요. "
        "이 피드백은 질문이 아니므로 문서 검색어로 사용하지 말고, 답변 본문에서 언급하지 마세요.\n\n"
        f"반려 사유 (오래된 순):\n{reasons}"
    )
    if previous_draft and previous_draft.strip():
        feedback += f"\n\n반려된 이전 초안:\n<previous_draft>\n{previous_draft.strip()}\n</previous_draft>"
    return feedback


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
                    logger.exception("개별 메일 처리 실패: uid=%s", mail.uid)

                logger.debug("Queue 적재 완료: uid=%s, subject=%s", mail.uid, mail.subject)
        except Exception:
            logger.exception("메일 수신 루프 오류")

        stop_event.wait(60)

    logger.info("메일 수신 루프 종료")


def email_consumer_loop(stop_event: threading.Event,
                        email_repo:EmailRepository,
                        task_repo:TaskRepository):
    logger.info("메일 처리 루프 시작")

    while not stop_event.is_set():
        pending_tasks = task_repo.get_pending_tasks()

        for task in pending_tasks:
            mail = email_repo.get_mail_by_id(task.mail_uid)
            if mail is None:
                logger.warning("메일을 찾을 수 없음: mail_uid=%s", task.mail_uid)
                continue

            logger.info("메일 처리 시작: uid=%s, sender=%s, subject=%s", mail.uid, mail.sender, mail.subject)

            try:
                #메일 읽기
                body = mail.body
                if not body or not body.strip():
                    logger.warning("본문이 비어있어 처리 건너뜀: uid=%s, subject=%s", mail.uid, mail.subject)
                    continue


                #반려 후 재생성이면 담당자 피드백을 함께 넘김
                reject_reasons = task_repo.get_reject_reasons(task.task_id)
                if reject_reasons:
                    logger.info("반려 피드백 반영해 재생성: uid=%s, 반려 %d회", mail.uid, len(reject_reasons))

                #답변 생성하기
                result = run_agent_temp_attachments(
                    body,
                    mode="local",
                    attachments=mail.attachments,
                    review_feedback=build_review_feedback(task.draft_answer, reject_reasons),
                )
                answer = result["answer"]
                sources = result["sources"]

                dandang = config.REVIEWER_EMAIL
                #담당자 배정 (지금은 .env의 REVIEWER_EMAIL 한 명)
                task_repo.assign_task(task.task_id, dandang)
                send_email(
                    dandang,
                    "[테스트] 검토가 필요한 메일이 도착했습니다.",
                    render_mail_review_email(
                        mail=mail,
                        answer=answer,
                        task_id=task.task_id,
                        base_url=config.PUBLIC_BASE_URL,
                    ),
                    html=True,
                )



                task_repo.save_draft(task.task_id, answer, sources)
                logger.debug("답변 생성 완료: uid=%s, answer_len=%d, sources=%d", mail.uid, len(answer), len(sources))

            except Exception:
                logger.exception("메일 처리 실패: uid=%s", mail.uid)
                task_repo.update_status(task.task_id, TaskStatus.FAILED)

        stop_event.wait(10)

    logger.info("메일 처리 루프 종료")





def email_loop_build(email_repo: EmailRepository, task_repo: TaskRepository,db:Database):

    stop_event = threading.Event()
    producer = threading.Thread(
        target=email_receiver_loop,
        args=(stop_event, email_repo,task_repo,db),
    )
    consumer = threading.Thread(
        target=email_consumer_loop,
        args=(stop_event, email_repo ,task_repo),
    )

    producer.start()
    consumer.start()
    logger.info("생산자/소비자 스레드 시작 완료")

    return producer, consumer, stop_event