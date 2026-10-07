/**
 * 라이브러리 없는 경로 기반 라우팅 (History API).
 *  - `/`      RAG 콘솔 (업로드 + 질의) — 기본 화면
 *  - `/mail`  메일 전송 승인 대시보드
 *  - `/ocr`   OCR 도구
 *
 * 서버에 없는 경로이므로 index.html로 fallback 해줘야 한다.
 * (개발: vite SPA fallback 기본 동작 · 배포: main.py 의 catch-all)
 */

const ROUTE_CHANGE = 'routechange'

/** 화면 간 이동 (전체 새로고침 없이) */
export function navigate(path: string) {
    if (path === window.location.pathname) return
    window.history.pushState(null, '', path)
    window.dispatchEvent(new Event(ROUTE_CHANGE))
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
