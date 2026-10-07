/**
 * 라이브러리 없는 경로 기반 라우팅 (History API).
 *  - `/`      RAG 콘솔 (업로드 + 질의) — 기본 화면
 *  - `/mail`         메일 대시보드 (현황 요약)
 *  - `/mail/inbox`   메일 (전체 메일 조회)
 *  - `/mail/review`  메일 검토 (검토 대기열 + 승인/반려)
 *  - `/ocr`   OCR 도구
 *
 * 서버에 없는 경로이므로 index.html로 fallback 해줘야 한다.
 * (개발: vite SPA fallback 기본 동작 · 배포: main.py 의 catch-all)
 */

const ROUTE_CHANGE = 'routechange'

/** 화면 간 이동 (전체 새로고침 없이) */
export function navigate(path: string) {
    if (path === window.location.pathname + window.location.search) return
    window.history.pushState(null, '', path)
    window.dispatchEvent(new Event(ROUTE_CHANGE))
}

/** <a> 클릭을 클라이언트 라우팅으로 처리한다. 새 탭·수정키 클릭은 브라우저에 맡긴다. */
export function linkProps(path: string) {
    return {
        href: path,
        onClick: (e: { button: number; metaKey: boolean; ctrlKey: boolean; shiftKey: boolean; preventDefault(): void }) => {
            if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey) return
            e.preventDefault()
            navigate(path)
        },
    }
}

/**
 * 승인 요청 메일 본문의 링크(`/mail?task_id=…`)는 메일 검토 페이지로 넘긴다.
 * (링크 형식은 백엔드 mail/templates.py 가 만든다)
 */
export function normalizeLegacyMailLink() {
    if (getRoute() !== 'mail') return
    const taskId = new URLSearchParams(window.location.search).get('task_id')
    if (!taskId) return
    // from=email: 메일 링크로 들어왔음을 검토 페이지에 알린다 (예시 데이터로 대체하지 않음)
    window.history.replaceState(null, '', `/mail/review?task_id=${encodeURIComponent(taskId)}&from=email`)
}

/** 예전 해시 링크(#/mail, #/ocr, #/rag)로 들어와도 경로 URL로 정리해준다 */
export function normalizeLegacyHash() {
    const m = window.location.hash.match(/^#\/?(mail|ocr|rag)$/)
    if (!m) return
    window.history.replaceState(null, '', m[1] === 'rag' ? '/' : `/${m[1]}`)
}

/** useSyncExternalStore 용 구독 */
export function subscribeRoute(cb: () => void) {
    // 해시로 들어오면 경로로 바꿔치운 뒤 리렌더 (replaceState는 이벤트를 안 쏜다)
    const onHashChange = () => {
        normalizeLegacyHash()
        cb()
    }
    window.addEventListener('popstate', cb)
    window.addEventListener('hashchange', onHashChange)
    window.addEventListener(ROUTE_CHANGE, cb)
    return () => {
        window.removeEventListener('popstate', cb)
        window.removeEventListener('hashchange', onHashChange)
        window.removeEventListener(ROUTE_CHANGE, cb)
    }
}

/** 현재 경로 (앞뒤 슬래시 제거) */
export function getRoute() {
    return window.location.pathname.replace(/^\/+|\/+$/g, '')
}
