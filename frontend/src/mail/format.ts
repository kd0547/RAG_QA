/**
 * 메일 화면 공통 표시 유틸과 상태 정의.
 * (컴포넌트는 ui.tsx — fast refresh 규칙상 컴포넌트와 상수를 한 파일에 섞지 않는다)
 */
import type { MailStatus } from './types';

const timeFmt = new Intl.DateTimeFormat('ko-KR', { hour: '2-digit', minute: '2-digit', hour12: false });
const dateTimeFmt = new Intl.DateTimeFormat('ko-KR', {
    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false,
});
const longDateFmt = new Intl.DateTimeFormat('ko-KR', { year: 'numeric', month: 'long', day: 'numeric', weekday: 'long' });

export const fmtTime = (iso: string) => {
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? '—' : timeFmt.format(d);
};
export const fmtDateTime = (iso: string) => {
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? '—' : dateTimeFmt.format(d);
};
export const fmtLongDate = (d: Date) => longDateFmt.format(d);

/** 오늘 받은 메일은 시각만, 그 외에는 월/일까지 */
export const fmtReceived = (iso: string) => {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return '—';
    return d.toDateString() === new Date().toDateString() ? timeFmt.format(d) : dateTimeFmt.format(d);
};

/** 지금부터 얼마나 지났는지 (대기 시간 표시용) */
export const fmtAgo = (iso: string, now = Date.now()) => {
    const t = new Date(iso).getTime();
    if (Number.isNaN(t)) return '—';
    const min = Math.max(0, Math.round((now - t) / 60_000));
    if (min < 1) return '방금';
    if (min < 60) return `${min}분 전`;
    const h = Math.floor(min / 60);
    if (h < 24) return `${h}시간 전`;
    return `${Math.floor(h / 24)}일 전`;
};

export const fmtDuration = (sec: number | null) => {
    if (sec == null) return '—';
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    return `${m}:${String(s).padStart(2, '0')}`;
};
export const pct = (n: number | null | undefined) => (n == null ? null : Math.round(n * 100));

/** 원문이 4줄을 넘을 만큼 길면 접어서 보여준다. */
export const isLongBody = (body: string) => body.split('\n').length > 4 || body.length > 240;

export const STATUS_META: Record<MailStatus, { label: string; chip: string }> = {
    pending: { label: '초안 생성 대기', chip: 'bg-chip text-muted' },
    drafted: { label: '초안 준비', chip: 'bg-chip text-ink/70' },
    in_review: { label: '검토 중', chip: 'bg-brand-soft text-brand' },
    rejected: { label: '반려', chip: 'bg-danger-soft text-danger' },
    approved: { label: '전송 대기', chip: 'bg-brand-soft text-brand' },
    sent: { label: '전송 완료', chip: 'bg-brand-soft text-brand' },
    failed: { label: '전송 실패', chip: 'bg-danger-soft text-danger' },
};

/** 사람이 손대야 하는 상태 — 메일 검토 페이지의 대기열 */
export const REVIEW_STATUSES: MailStatus[] = ['drafted', 'in_review', 'failed'];
export const ALL_STATUSES: MailStatus[] = ['pending', 'drafted', 'in_review', 'rejected', 'approved', 'sent', 'failed'];
export const isReviewable = (s: MailStatus) => REVIEW_STATUSES.includes(s);

/** 메일 섹션 경로 */
export const MAIL_PATHS = {
    dashboard: '/mail',
    inbox: '/mail/inbox',
    review: '/mail/review',
} as const;

export const reviewPath = (taskId?: string) =>
    taskId ? `${MAIL_PATHS.review}?task_id=${encodeURIComponent(taskId)}` : MAIL_PATHS.review;
