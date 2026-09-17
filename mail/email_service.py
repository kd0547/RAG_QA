import threading
from queue import Queue
from agent.rag_agent import get_agent, run_agent
from entity.type import TaskEntity
from repository.email_repository import EmailRepository
from repository.repo_connect import Database
from repository.task_repository import TaskRepository

from .email_receiver import fetch_new_emails, MailEntity
import queue
import logging

from mail.email_send import send_email


logger = logging.getLogger(__name__)


def intake_mail(mail: MailEntity, db: Database, email_repo: EmailRepository, task_repo: TaskRepository) -> None:
    with db.transaction() as conn:
        email_repo.save_pending(mail, conn)
        task_repo.create_task(mail.uid, conn)

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
        mail: MailEntity

        task_repo.get_task_peddings()

        logger.info("메일 처리 시작: uid=%s, sender=%s, subject=%s", mail.uid, mail.sender, mail.subject)

        try:
            #메일 읽기
            body = mail.body
            if not body or not body.strip():
                logger.warning("본문이 비어있어 처리 건너뜀: uid=%s, subject=%s", mail.uid, mail.subject)
                continue



            logger.debug("답변 생성 완료: uid=%s, answer_len=%d", mail.uid, len(answer))


        except Exception:
            logger.exception("메일 처리 실패: uid=%s", mail.uid)
            repo.update_status(mail.uid, MailStatus.FAILED)
        finally:
            mail_queue.task_done()

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