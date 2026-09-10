/**
 * 메일 전송 승인 API 클라이언트.
 * 베이스 URL은 VITE_MAIL_API_BASE 로 덮어쓸 수 있다 (기본: http://127.0.0.1:8000).
 */
import type {
    ApproveResult,
    MailDetail,
    MailListResponse,
    MailStats,
    MailStatus,
} from './types';

const BASE = (import.meta.env.VITE_MAIL_API_BASE ?? 'http://127.0.0.1:8000').replace(/\/+$/, '');

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

async function request<T>(path: string, init?: RequestInit): Promise<T> {
    let res: Response;
    try {
        res = await fetch(BASE + path, {
            headers: { 'Content-Type': 'application/json' },
            ...init,
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

export interface ListParams {
    status?: MailStatus[];
    q?: string;
    order?: string;              // received_at | -received_at | confidence | -confidence
    limit?: number;
    offset?: number;
}

export const mailApi = {
    list(p: ListParams = {}): Promise<MailListResponse> {
        const qs = new URLSearchParams();
        if (p.status && p.status.length) qs.set('status', p.status.join(','));
        if (p.q) qs.set('q', p.q);
        if (p.order) qs.set('order', p.order);
        if (p.limit != null) qs.set('limit', String(p.limit));
        if (p.offset != null) qs.set('offset', String(p.offset));
        const s = qs.toString();
        return request<MailListResponse>(`/mails${s ? `?${s}` : ''}`);
    },

    stats(date?: string): Promise<MailStats> {
        return request<MailStats>(`/mails/stats${date ? `?date=${encodeURIComponent(date)}` : ''}`);
    },

    detail(uid: string): Promise<MailDetail> {
        return request<MailDetail>(`/mails/${encodeURIComponent(uid)}`);
    },

    /** 전송 없이 초안만 저장 */
    saveDraft(uid: string, draft: string): Promise<{ uid: string; draft: string; updated_at: string }> {
        return request(`/mails/${encodeURIComponent(uid)}/draft`, {
            method: 'PATCH',
            body: JSON.stringify({ draft }),
        });
    },

    /** 승인 후 실제 전송. body 생략 시 저장된 draft 그대로 전송 */
    approve(
        uid: string,
        payload: { body?: string; subject?: string; edited?: boolean } = {},
    ): Promise<ApproveResult> {
        return request<ApproveResult>(`/mails/${encodeURIComponent(uid)}/approve`, {
            method: 'POST',
            body: JSON.stringify(payload),
        });
    },

    /** 반려. requeue=true(기본)면 pending 으로 되돌려 재작성 */
    reject(
        uid: string,
        payload: { reason: string; requeue?: boolean },
    ): Promise<{ uid: string; status: MailStatus }> {
        return request(`/mails/${encodeURIComponent(uid)}/reject`, {
            method: 'POST',
            body: JSON.stringify(payload),
        });
    },

    claim(uid: string, assignee: string): Promise<MailDetail> {
        return request<MailDetail>(`/mails/${encodeURIComponent(uid)}/claim`, {
            method: 'POST',
            body: JSON.stringify({ assignee }),
        });
    },

    release(uid: string): Promise<MailDetail> {
        return request<MailDetail>(`/mails/${encodeURIComponent(uid)}/release`, { method: 'POST' });
    },

    /** 전송 실패 건 재전송 */
    retry(uid: string): Promise<ApproveResult> {
        return request<ApproveResult>(`/mails/${encodeURIComponent(uid)}/retry`, { method: 'POST' });
    },
};
