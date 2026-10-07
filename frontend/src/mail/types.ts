/**
 * 메일 전송 승인 대시보드 - API 데이터 타입.
 * 백엔드 명세: docs/mail_approval_api.md
 */

export type MailStatus = 'pending' | 'drafted' | 'in_review' | 'sent' | 'failed';

/** 목록(GET /mails)의 행 */
export interface MailSummary {
    task_id: string;
    subject: string;
    sender: string;                 // 이메일 주소
    received_at: string;            // ISO 8601 (+09:00)
    status: MailStatus;
}

export interface MailSource {
    source: string;                 // 문서 파일명
    page: number | null;
    text: string;                   // 근거 스니펫
}

/** 상세(GET /mails/{task_id}) */
export interface MailDetail extends MailSummary {
    assignee: string | null;        // 검토 담당자
    recipient: string;
    body: string;                   // 받은 원문 (plain text)
    draft: string | null;           // AI 초안 (편집 대상)
    model: string | null;
    retrieval: { query_top_k: number | null; rerank_top_n: number | null } | null;
    sources: MailSource[];
    created_at: string;
    updated_at: string;
}

export interface DailyVolume {
    date: string;                   // YYYY-MM-DD
    sent: number;
}

/** 대시보드 요약(GET /mails/stats) */
export interface MailStats {
    date: string;                   // YYYY-MM-DD
    pending_review: number;         // drafted + in_review
    sent_today: number;
    rejected_today: number;
    failed: number;
    avg_review_seconds: number | null;
    draft_adoption_rate: number | null;  // 무수정 승인 비율 0~1
    sent_delta: number | null;           // 전일 대비 오늘 전송 증감
    daily_volume: DailyVolume[];         // 최근 14일 (오래된 -> 최신)
}

export interface MailListResponse {
    items: MailSummary[];
    total: number;
    limit: number;
    offset: number;
}

export interface ApproveResult {
    task_id: string;
    status: MailStatus;
    sent_at: string;
    to: string;
}
