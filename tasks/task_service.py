import logging

from entity.type import MailEntity, TaskStatus, TaskEntity
from repository.email_repository import EmailRepository
from repository.task_repository import TaskRepository
from agent.rag_agent import get_agent, run_agent

RETRY_MAX_COUNT = 3

logger = logging.getLogger(__name__)


class TaskService():

    def __init__(self,task_repo:TaskRepository,mail_repo:EmailRepository):
        self.task_repo = task_repo
        self.mail_repo = mail_repo

    def process_task(self,task:TaskEntity) -> None:

        if task.retry_count >= RETRY_MAX_COUNT:
            self.task_repo.update_status(task.task_id, TaskStatus.FAILED)
            logger.warning("최대 재시도 초과: uid=%s", task.task_id)
            return

        #Email조회
        email:MailEntity = self.mail_repo.get_mail_by_id(task.mail_uid)


        #답변 생성
        answer = generate_answer(email.body,retry_context=task.retry_count)
        self.task_repo.save_draft(answer,TaskStatus.DRAFTED)






def generate_answer(body: str, retry_context: str | None = None):
    """

    :param body:
    :param retry_context:
    :return:
    """
    # 답변 생성
    result = run_agent(body)
    answer = result["answer"]

    return answer



