/**
 * 백엔드(FastAPI) 공용 HTTP 클라이언트.
 *
 * 기본값은 same-origin이다.
 *  - 개발: vite dev server가 /config, /upload, /files, /ask, /search, /mails, /prompts 를 백엔드로 프록시 (vite.config.ts)
 *  - 배포: FastAPI가 frontend/dist 를 같이 서빙 (main.py)
 * 백엔드가 다른 호스트에 있으면 VITE_API_BASE 로 덮어쓴다.
 */
export const API_BASE = (
    import.meta.env.VITE_API_BASE ??
    import.meta.env.VITE_MAIL_API_BASE ??
    ''
).replace(/\/+$/, '');

/**
 * OCR은 이 저장소 밖의 별도 서버(8082)다.
 * 기본값은 지금 페이지를 연 호스트의 8082 포트라서, 개발 PC(localhost)와
 * 릴리스 서버 어디서 열든 같은 빌드가 동작한다. 다른 곳에 있으면 VITE_OCR_API_BASE 로 덮어쓴다.
 */
export const OCR_API_BASE = (
    import.meta.env.VITE_OCR_API_BASE ??
    `${window.location.protocol}//${window.location.hostname}:8082`
).replace(/\/+$/, '');

export class ApiError extends Error {
    status: number;
    code: string | undefined;
    /** 서버가 detail을 문자열이 아닌 객체로 준 경우 그 원본 (예: 사양 가져오기의 셀별 오류 목록) */
    detail: unknown;
    constructor(status: number, message: string, code?: string, detail?: unknown) {
        super(message);
        this.name = 'ApiError';
        this.status = status;
        this.code = code;
        this.detail = detail;
    }
}

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
    // FormData는 boundary 때문에 브라우저가 Content-Type을 직접 넣어야 하므로 건드리지 않는다
    const isJsonBody = typeof init?.body === 'string';

    let res: Response;
    try {
        res = await fetch(API_BASE + path, {
            ...init,
            headers: {
                Accept: 'application/json',
                ...(isJsonBody ? { 'Content-Type': 'application/json' } : {}),
                ...init?.headers,
            },
        });
    } catch (e) {
        throw new ApiError(0, e instanceof Error ? e.message : '네트워크 오류', 'network');
    }

    if (!res.ok) {
        let detail = `${res.status} ${res.statusText}`;
        let code: string | undefined;
        let raw: unknown;
        try {
            const j = await res.json();
            if (typeof j?.detail === 'string') detail = j.detail;
            else if (j?.detail && typeof j.detail === 'object') {
                raw = j.detail;
                if (typeof j.detail.message === 'string') detail = j.detail.message;
            }
            if (typeof j?.code === 'string') code = j.code;
        } catch {
            /* 본문 없음 */
        }
        throw new ApiError(res.status, detail, code, raw);
    }

    if (res.status === 204) return undefined as T;
    const contentType = res.headers.get('content-type') ?? '';
    if (!/\bapplication\/(?:[\w.-]+\+)?json\b/i.test(contentType)) {
        throw new ApiError(
            res.status,
            '서버가 API 응답 대신 웹페이지를 반환했습니다. 백엔드를 재시작하고 API 연결 주소를 확인해주세요.',
            'invalid_response',
        );
    }
    try {
        return (await res.json()) as T;
    } catch {
        throw new ApiError(res.status, '서버 응답을 읽을 수 없습니다. 다시 시도해주세요.', 'invalid_response');
    }
}
