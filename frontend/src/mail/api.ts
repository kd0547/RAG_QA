/**
 * 메일 전송 승인 API 클라이언트.
 * 베이스 URL 규칙은 lib/http.ts 참고 (기본 same-origin, VITE_API_BASE 로 덮어쓰기).
 */
import { request } from '../lib/http';
import type {
    ApproveResult,
    MailDetail,
    MailListResponse,
    MailStats,
    MailStatus,
} from './types';

export { ApiError } from '../lib/http';

export interface ListParams {
    status?: MailStatus[];
    q?: string;
    order?: string;              // received_at | -received_at
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

    detail(taskId: string): Promise<MailDetail> {
        return request<MailDetail>(`/mails/${encodeURIComponent(taskId)}`);
    },

    /** 전송 없이 초안만 저장 */
    saveDraft(taskId: string, draft: string): Promise<{ task_id: string; draft: string; updated_at: string }> {
        return request(`/mails/${encodeURIComponent(taskId)}/draft`, {
            method: 'PATCH',
            body: JSON.stringify({ draft }),
        });
    },

    /** 승인 후 실제 전송. body 생략 시 저장된 draft 그대로 전송 */
    approve(
        taskId: string,
        payload: { body?: string; subject?: string; edited?: boolean; attachment_file_ids?: string[] } = {},
    ): Promise<ApproveResult> {
        return request<ApproveResult>(`/mails/${encodeURIComponent(taskId)}/approve`, {
            method: 'POST',
            body: JSON.stringify(payload),
        });
    },

    /** 반려. requeue=true(기본)면 pending 으로 되돌려 재작성 */
    reject(
        taskId: string,
        payload: { reason: string; requeue?: boolean },
    ): Promise<{ task_id: string; status: MailStatus }> {
        return request(`/mails/${encodeURIComponent(taskId)}/reject`, {
            method: 'POST',
            body: JSON.stringify(payload),
        });
    },

    claim(taskId: string, assignee: string): Promise<MailDetail> {
        return request<MailDetail>(`/mails/${encodeURIComponent(taskId)}/claim`, {
            method: 'POST',
            body: JSON.stringify({ assignee }),
        });
    },

    release(taskId: string): Promise<MailDetail> {
        return request<MailDetail>(`/mails/${encodeURIComponent(taskId)}/release`, { method: 'POST' });
    },

    /** 전송 실패 건 재전송 */
    retry(taskId: string): Promise<ApproveResult> {
        return request<ApproveResult>(`/mails/${encodeURIComponent(taskId)}/retry`, { method: 'POST' });
    },
};
