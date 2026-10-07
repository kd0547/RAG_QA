"""메일 본문의 버튼이 여는 단독 페이지 라우터 (웹 앱을 거치지 않는다).

- GET /mails/{task_id}/send : 검토 요청 메일의 '답변 전송' 버튼.
  페이지가 열리면 스크립트가 POST /mails/{task_id}/approve 를 호출해 바로 전송하고 결과만 보여준다.
"""
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from mail.templates import render_quick_send_page
from repository import task_repo

router = APIRouter()


@router.get("/mails/{task_id}/send", response_class=HTMLResponse, include_in_schema=False)
def quick_send_page(task_id: str) -> HTMLResponse:
    detail = task_repo.view_task(task_id)
    if detail is None:
        html = render_quick_send_page(task_id, subject=None, sender=None, status=None)
        return HTMLResponse(html, status_code=404)

    html = render_quick_send_page(
        task_id,
        subject=detail.subject,
        sender=detail.sender,
        status=detail.status.value,
    )
    # 결과 페이지가 캐시되면 뒤로 가기·새로고침 때 이전 상태가 보일 수 있다
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})
