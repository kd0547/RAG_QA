/** 메일 화면 공통 UI 조각 (대시보드 · 메일 · 메일 검토 페이지가 함께 쓴다) */
import { useState, type ReactNode } from 'react';
import { DocumentIcon } from '../components/icons';
import { fmtBytes, fmtDateTime, fmtTime, isLongBody, STATUS_META } from './format';
import type { MailAttachment, MailDetail, MailSource, MailStatus } from './types';

export function StatusChip({ status }: { status: MailStatus }) {
    const m = STATUS_META[status] ?? { label: status, chip: 'bg-chip text-muted' };
    return (
        <span className={`inline-flex items-center h-[19px] px-2 rounded-full text-[11px] font-bold whitespace-nowrap ${m.chip}`}>
            {m.label}
        </span>
    );
}

/** 발신자 이메일 첫 글자로 만든 원형 아바타 */
export function Avatar({ label }: { label: string }) {
    return (
        <span className="w-9 h-9 shrink-0 rounded-full bg-brand-pale text-brand text-[13px] font-bold flex items-center justify-center uppercase">
            {label.trim().charAt(0) || '?'}
        </span>
    );
}

export function AiAvatar() {
    return (
        <span className="w-9 h-9 shrink-0 rounded-full bg-brand text-white text-[11px] font-extrabold flex items-center justify-center">
            AI
        </span>
    );
}

/** 상세 상단: 상태 · 시각 · 담당자 + 제목 */
export function MailSubject({ detail }: { detail: MailDetail }) {
    return (
        <>
            <div className="flex items-center gap-2 flex-wrap text-[12px] text-muted">
                <StatusChip status={detail.status} />
                <span className="tabular-nums">{fmtDateTime(detail.received_at)}</span>
                {detail.assignee && <span>· 담당 {detail.assignee}</span>}
            </div>
            <h1 className="mt-2.5 text-[24px] font-bold leading-snug tracking-tight">{detail.subject}</h1>
        </>
    );
}

/** 받은 원문. 길면 4줄로 접는다. 메일이 바뀌면 key로 다시 마운트해 접힘 상태를 초기화한다. */
export function ReceivedMessage({ detail }: { detail: MailDetail }) {
    const [expanded, setExpanded] = useState(false);
    return (
        <section>
            <div className="flex items-center gap-3 min-w-0">
                <Avatar label={detail.sender} />
                <div className="min-w-0 flex-1">
                    <div className="text-[13px] font-semibold truncate">{detail.sender}</div>
                    <div className="text-[11px] text-muted truncate">받는 사람 {detail.recipient}</div>
                </div>
                <time className="shrink-0 text-[11px] text-muted tabular-nums">{fmtTime(detail.received_at)}</time>
            </div>
            <p
                className={`mt-3 sm:pl-12 whitespace-pre-line text-[14px] leading-relaxed text-ink/70 ${
                    expanded ? '' : 'line-clamp-4'
                }`}
            >
                {detail.body}
            </p>
            {isLongBody(detail.body) && (
                <button
                    onClick={() => setExpanded((v) => !v)}
                    className="mt-1 sm:ml-12 text-[12px] font-semibold text-brand-hover hover:underline"
                >
                    {expanded ? '접기' : '전체 보기'}
                </button>
            )}
        </section>
    );
}

/** AI 답장 블록의 머리글 (아바타 · 제목 · 보조 설명 · 우측 액션) */
export function ReplyHeader({
    title,
    badge,
    caption,
    action,
}: {
    title: string;
    badge?: ReactNode;
    caption: string;
    action?: ReactNode;
}) {
    return (
        <div className="flex items-center gap-3">
            <AiAvatar />
            <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                    <h2 className="text-[13px] font-semibold">{title}</h2>
                    {badge}
                </div>
                <div className="text-[11px] text-muted truncate">{caption}</div>
            </div>
            {action}
        </div>
    );
}

export function SourceList({ sources }: { sources: MailSource[] }) {
    return (
        <section>
            <h2 className="text-[12px] font-bold text-muted">
                근거 문서 <span className="tabular-nums">{sources.length}</span>
            </h2>
            {sources.length === 0 ? (
                <p className="mt-2 text-[12px] text-muted">연결된 근거 문서가 없습니다.</p>
            ) : (
                <ul className="mt-1 divide-y divide-divide">
                    {sources.map((s, i) => (
                        <li key={i} className="flex gap-3 min-w-0 py-2.5">
                            <span className="shrink-0 mt-0.5 w-7 h-7 rounded-lg bg-brand-pale text-brand flex items-center justify-center">
                                <DocumentIcon className="w-3.5 h-3.5" />
                            </span>
                            <div className="min-w-0">
                                <div className="text-[12.5px] font-semibold truncate" title={s.source}>
                                    {s.source}
                                </div>
                                <div className="text-[11px] text-muted line-clamp-2">
                                    {s.page != null && <span className="font-mono">p.{s.page} · </span>}
                                    {s.text}
                                </div>
                            </div>
                        </li>
                    ))}
                </ul>
            )}
        </section>
    );
}

/**
 * 답장에 첨부할 참고 문서 고르기. 사내 문서가 외부로 나가지 않도록 기본은 아무것도 고르지 않는다.
 * 서버 디스크에 없는 파일은 고를 수 없다.
 */
export function AttachmentPicker({
    attachments,
    selected,
    onToggle,
    disabled = false,
}: {
    attachments: MailAttachment[];
    selected: ReadonlySet<string>;
    onToggle: (fileId: string) => void;
    disabled?: boolean;
}) {
    const chosen = attachments.filter((a) => selected.has(a.file_id));
    const total = chosen.reduce((sum, a) => sum + (a.size_bytes ?? 0), 0);
    return (
        <section>
            <div className="flex items-baseline justify-between gap-3">
                <h2 className="text-[12px] font-bold text-muted">
                    답장 첨부 <span className="tabular-nums">{chosen.length}</span>
                    <span className="font-normal"> / {attachments.length}</span>
                </h2>
                {chosen.length > 0 && <span className="text-[11px] text-muted tabular-nums">합계 {fmtBytes(total)}</span>}
            </div>
            {attachments.length === 0 ? (
                <p className="mt-2 text-[12px] text-muted">첨부할 수 있는 참고 문서가 없습니다.</p>
            ) : (
                <>
                    <p className="mt-1 text-[11px] text-muted">체크한 문서만 답장에 첨부됩니다. 사내 전용 문서는 고르지 마세요.</p>
                    <ul className="mt-1.5 flex flex-col gap-1">
                        {attachments.map((a) => {
                            const on = selected.has(a.file_id);
                            return (
                                <li key={a.file_id}>
                                    <label
                                        className={`flex items-center gap-3 min-w-0 px-3 py-2 rounded-xl transition-colors ${
                                            !a.available || disabled
                                                ? 'opacity-55 cursor-not-allowed'
                                                : on
                                                  ? 'bg-brand-pale cursor-pointer'
                                                  : 'hover:bg-surface cursor-pointer'
                                        }`}
                                    >
                                        <input
                                            type="checkbox"
                                            checked={on}
                                            disabled={!a.available || disabled}
                                            onChange={() => onToggle(a.file_id)}
                                            className="shrink-0 w-4 h-4 accent-brand"
                                        />
                                        <span className="shrink-0 w-7 h-7 rounded-lg bg-brand-pale text-brand flex items-center justify-center">
                                            <DocumentIcon className="w-3.5 h-3.5" />
                                        </span>
                                        <span className="min-w-0 flex-1 text-[12.5px] font-semibold truncate" title={a.filename}>
                                            {a.filename}
                                        </span>
                                        <span className="shrink-0 text-[11px] text-muted tabular-nums">
                                            {a.available ? fmtBytes(a.size_bytes) : '파일 없음'}
                                        </span>
                                    </label>
                                </li>
                            );
                        })}
                    </ul>
                </>
            )}
        </section>
    );
}

/** 가운데 정렬 안내 문구 (빈 상태 · 로딩 · 오류) */
export function CenterNote({ children, tone = 'muted' }: { children: ReactNode; tone?: 'muted' | 'danger' }) {
    return (
        <div
            role={tone === 'danger' ? 'alert' : undefined}
            className={`flex-1 flex items-center justify-center p-10 text-center text-[13px] leading-relaxed ${
                tone === 'danger' ? 'text-danger' : 'text-muted'
            }`}
        >
            <div>{children}</div>
        </div>
    );
}

export function MockBadge() {
    return (
        <span className="inline-flex items-center h-6 px-2.5 rounded-full bg-warn-soft text-warn text-[11px] font-bold whitespace-nowrap">
            예시 데이터
        </span>
    );
}

/** 상단 칩 형태의 상태 필터 (세그먼트 컨트롤) */
export function SegmentedFilter<K extends string>({
    value,
    onChange,
    items,
}: {
    value: K;
    onChange: (k: K) => void;
    items: readonly (readonly [K, string, number | null])[];
}) {
    return (
        <div className="flex p-0.5 rounded-lg bg-chip overflow-x-auto">
            {items.map(([key, label, n]) => (
                <button
                    key={key}
                    onClick={() => onChange(key)}
                    className={`flex-1 h-7 px-2.5 rounded-md text-[12px] font-semibold transition-colors whitespace-nowrap ${
                        value === key ? 'bg-white text-ink shadow-[0_1px_2px_rgba(20,28,43,0.10)]' : 'text-muted hover:text-ink'
                    }`}
                >
                    {label} {n != null && <span className="tabular-nums opacity-60">{n}</span>}
                </button>
            ))}
        </div>
    );
}
