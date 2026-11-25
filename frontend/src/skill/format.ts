/** SKILL 화면에서 같이 쓰는 값·함수 (컴포넌트가 아닌 것) */
import { ApiError } from '../lib/http';
import type { DocStatus, TypeState } from './api';

export function errorMessage(e: unknown, fallback: string): string {
    if (e instanceof ApiError) return e.status === 0 ? '서버에 연결하지 못했습니다.' : e.message;
    return fallback;
}

export function formatDate(value: string | null | undefined): string {
    if (!value) return '';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return new Intl.DateTimeFormat('ko-KR', { dateStyle: 'medium', timeStyle: 'short' }).format(date);
}

export const DOC_STATUS_META: Record<DocStatus, { label: string; chip: string }> = {
    generating: { label: '생성 중', chip: 'bg-brand-pale text-brand-hover' },
    draft: { label: '검토 대기', chip: 'bg-warn-soft text-[#8a5d00]' },
    approved: { label: '승인됨', chip: 'bg-brand text-white' },
    rejected: { label: '반려됨', chip: 'bg-chip text-muted' },
    retired: { label: '사용 중지', chip: 'bg-chip text-muted' },
    error: { label: '생성 실패', chip: 'bg-danger-soft text-danger' },
};

export const TYPE_STATE_META: Record<TypeState, { label: string; chip: string }> = {
    open: { label: '열림', chip: 'bg-brand-pale text-brand-hover' },
    no_skill_needed: { label: 'SKILL 불필요', chip: 'bg-chip text-muted' },
    merged: { label: '합쳐짐', chip: 'bg-chip text-muted' },
};

export const buttonBase =
    'inline-flex h-9 items-center justify-center gap-1.5 rounded-lg px-3.5 text-[12px] font-semibold transition-colors disabled:opacity-40 disabled:cursor-not-allowed focus-visible:outline-2 focus-visible:outline-brand';
export const buttonPrimary = `${buttonBase} bg-brand text-white hover:bg-brand-hover focus-visible:outline-offset-2`;
export const buttonOutline = `${buttonBase} border border-line bg-white hover:bg-chip`;
export const buttonDanger = `${buttonBase} border border-line bg-white text-danger hover:bg-danger-surface focus-visible:outline-danger`;

export const inputClass =
    'block w-full rounded-lg border border-line bg-white px-3 py-2 text-[13px] text-ink placeholder:text-muted focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand/10';
