/**
 * 백엔드(FastAPI) 공용 HTTP 클라이언트.
 *
 * 기본값은 same-origin이다.
 *  - 개발: vite dev server가 /upload, /files, /ask, /search, /mails 를 백엔드로 프록시 (vite.config.ts)
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
    constructor(status: number, message: string, code?: string) {
        super(message);
        this.name = 'ApiError';
        this.status = status;
        this.code = code;
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
        try {
            const j = await res.json();
            if (typeof j?.detail === 'string') detail = j.detail;
            if (typeof j?.code === 'string') code = j.code;
        } catch {
            /* 본문 없음 */
        }
        throw new ApiError(res.status, detail, code);
    }

    if (res.status === 204) return undefined as T;
    return (await res.json()) as T;
}
