import { useCallback, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { linkProps } from '../../lib/router';
import { ApiError, customerApi } from '../api';
import { customerPath, fmtDateTime, fmtReceived, isLongBody, reviewPath } from '../format';
import { mockCustomers, mockTimeline } from '../mockData';
import type { Customer, CustomerTimeline, TimelineEvent, TimelineInquiry } from '../types';
import { AiAvatar, Avatar, CenterNote, MockBadge, StatusChip } from '../ui';

const TRUNCATED_NOTE = '8,000자까지만 표시합니다. 전체는 검토 화면에서 보세요.';
const INFERRED_NOTE = '기록 이전 작업이라 시각·본문이 정확하지 않을 수 있음';

const SEND_OUTCOME: Record<string, { label: string; tone: 'muted' | 'danger' }> = {
    sent: { label: '발송 완료', tone: 'muted' },
    sending: { label: '발송 중', tone: 'muted' },
    send_failed: { label: '발송 실패', tone: 'danger' },
    send_unknown: { label: '발송 확인 필요', tone: 'danger' },
};

const fmtAt = (at: string | null) => (at ? fmtDateTime(at) : '시각 기록 없음');

const initialSender = () => new URLSearchParams(window.location.search).get('sender')?.trim().toLowerCase() || null;

/**
 * 고객방: 발신자별로 문의·초안·반려·발송을 시간순으로 보는 조회 화면.
 * 승인·반려·편집은 하지 않는다 — 처리는 메일 검토 화면에서만 한다.
 */
export function MailCustomersPage() {
    const [query, setQuery] = useState('');
    const [qDebounced, setQDebounced] = useState('');
    useEffect(() => {
        const id = window.setTimeout(() => setQDebounced(query.trim()), 300);
        return () => window.clearTimeout(id);
    }, [query]);

    const [customers, setCustomers] = useState<Customer[]>([]);
    const [total, setTotal] = useState(0);
    const [listLoading, setListLoading] = useState(true);
    const [offline, setOffline] = useState(false);
    const [sender, setSender] = useState<string | null>(initialSender);

    const loadCustomers = useCallback(async (q: string) => {
        setListLoading(true);
        try {
            const res = await customerApi.list({ q: q || undefined, limit: 200 });
            setCustomers(res.items);
            setTotal(res.total);
            setOffline(false);
        } catch {
            // 고객방 API가 없거나 서버에 닿지 않으면 예시 데이터로 채운다 (다른 메일 화면과 같은 방식)
            const mock = mockCustomers(q);
            setCustomers(mock);
            setTotal(mock.length);
            setOffline(true);
        } finally {
            setListLoading(false);
        }
    }, []);

    useEffect(() => {
        // eslint-disable-next-line react-hooks/set-state-in-effect
        void loadCustomers(qDebounced);
    }, [qDebounced, loadCustomers]);

    const select = (next: string | null) => {
        setSender(next);
        window.history.replaceState(null, '', customerPath(next));
    };

    return (
        <div className="flex-1 min-h-0 flex flex-col md:flex-row">
            {/* 발신자 목록 */}
            <section className="md:w-[340px] xl:w-[380px] shrink-0 min-h-0 max-h-[40vh] md:max-h-none flex flex-col border-b md:border-b-0 md:border-r border-divide">
                <div className="shrink-0 px-4 sm:px-5 pt-5 pb-3 flex flex-col gap-3">
                    <div className="flex items-center gap-2">
                        <h1 className="text-[18px] font-bold">고객방</h1>
                        <span className="text-[12px] text-muted tabular-nums">{listLoading ? '' : `${total}명`}</span>
                        {offline && <MockBadge />}
                        <button
                            onClick={() => void loadCustomers(qDebounced)}
                            className="ml-auto h-7 px-2.5 rounded-lg text-[12px] font-semibold text-muted hover:text-ink hover:bg-chip transition-colors"
                        >
                            새로고침
                        </button>
                    </div>
                    <input
                        value={query}
                        onChange={(e) => setQuery(e.target.value)}
                        placeholder="주소·제목 검색"
                        className="h-8 w-full px-3 rounded-lg bg-chip text-[13px] placeholder:text-muted focus:outline-none focus:bg-white focus:ring-2 focus:ring-brand/30"
                    />
                </div>
                <div className="flex-1 min-h-0 overflow-y-auto px-2 sm:px-3 pb-6">
                    {listLoading && <p className="px-4 py-10 text-center text-muted text-[13px]">불러오는 중…</p>}
                    {!listLoading && customers.length === 0 && (
                        <p className="px-4 py-10 text-center text-muted text-[13px]">조건에 맞는 고객이 없습니다.</p>
                    )}
                    {!listLoading &&
                        customers.map((c) => {
                            const sel = c.sender === sender;
                            return (
                                <button
                                    key={c.sender}
                                    type="button"
                                    onClick={() => select(c.sender)}
                                    aria-current={sel ? 'true' : undefined}
                                    className={`w-full text-left rounded-xl px-3 py-2.5 flex items-start gap-3 transition-colors focus-visible:outline-2 focus-visible:outline-brand ${
                                        sel ? 'bg-brand-pale' : 'hover:bg-surface'
                                    }`}
                                >
                                    <Avatar label={c.sender} />
                                    <span className="min-w-0 flex-1">
                                        <span className="flex items-center gap-2 min-w-0">
                                            <span className={`truncate flex-1 text-[13px] ${sel ? 'font-bold' : 'font-semibold'}`}>{c.sender}</span>
                                            <time className="shrink-0 text-[11px] text-muted tabular-nums">{fmtReceived(c.last_received_at)}</time>
                                        </span>
                                        <span className="mt-0.5 block text-[12px] text-muted truncate">{c.last_subject}</span>
                                        <span className="mt-1 flex items-center gap-2 text-[11px] text-muted">
                                            <span className="tabular-nums">문의 {c.mail_count}건</span>
                                            {c.needs_review > 0 && (
                                                <span
                                                    title="검토 필요"
                                                    className="h-[18px] px-1.5 rounded-full bg-brand text-white text-[10px] font-bold tabular-nums inline-flex items-center"
                                                >
                                                    검토 {c.needs_review}
                                                </span>
                                            )}
                                        </span>
                                    </span>
                                </button>
                            );
                        })}
                </div>
            </section>

            {/* 타임라인 */}
            <main className="flex-1 min-w-0 min-h-0 flex flex-col">
                {sender ? (
                    <Timeline key={`${sender}:${offline}`} sender={sender} offline={offline} />
                ) : (
                    <CenterNote>
                        왼쪽에서 고객을 고르면 문의·초안·반려·발송이 시간순으로 보입니다.
                        <br />
                        조회 전용입니다. 승인·반려는 메일 검토 화면에서 합니다.
                    </CenterNote>
                )}
            </main>
        </div>
    );
}

/** 한 발신자의 문의 묶음. 처음에는 가장 최근 문의가 보이게 아래로 스크롤하고, 위에서 이전 문의를 더 불러온다. */
function Timeline({ sender, offline }: { sender: string; offline: boolean }) {
    const [data, setData] = useState<CustomerTimeline | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [loadingMore, setLoadingMore] = useState(false);
    const scroller = useRef<HTMLDivElement>(null);
    // 이전 문의를 위에 붙인 뒤 보던 위치를 지키기 위한 값 (null이면 맨 아래로)
    const keepFromBottom = useRef<number | null>(null);

    useEffect(() => {
        let ignore = false;
        (async () => {
            try {
                const res = offline ? mockTimeline(sender) : await customerApi.timeline(sender);
                if (!ignore) setData(res);
            } catch (e) {
                if (!ignore) setError(e instanceof ApiError ? e.message : '고객방을 불러오지 못했습니다.');
            }
        })();
        return () => {
            ignore = true;
        };
    }, [sender, offline]);

    useLayoutEffect(() => {
        const el = scroller.current;
        if (!el || !data) return;
        el.scrollTop = keepFromBottom.current == null ? el.scrollHeight : el.scrollHeight - keepFromBottom.current;
        keepFromBottom.current = null;
    }, [data]);

    const loadOlder = async () => {
        if (!data?.next_before || loadingMore) return;
        setLoadingMore(true);
        try {
            const older = await customerApi.timeline(sender, { before: data.next_before });
            const el = scroller.current;
            keepFromBottom.current = el ? el.scrollHeight - el.scrollTop : null;
            setData({ ...older, items: [...older.items, ...data.items] });
        } catch (e) {
            setError(e instanceof ApiError ? e.message : '이전 문의를 불러오지 못했습니다.');
        } finally {
            setLoadingMore(false);
        }
    };

    return (
        <>
            <div className="shrink-0 border-b border-divide px-4 sm:px-6 h-12 flex items-center gap-3">
                <span className="text-[14px] font-bold truncate">{sender}</span>
                {data && <span className="text-[12px] text-muted tabular-nums shrink-0">문의 {data.total}건</span>}
                <span className="ml-auto text-[11px] text-muted shrink-0">조회 전용</span>
            </div>
            {!data && !error && <CenterNote>불러오는 중…</CenterNote>}
            {error && !data && <CenterNote tone="danger">{error}</CenterNote>}
            {data && (
                <div ref={scroller} className="flex-1 min-h-0 overflow-y-auto">
                    <div className="mx-auto w-full max-w-[820px] px-4 sm:px-8 pt-4 pb-10">
                        {data.next_before && (
                            <div className="flex justify-center py-2">
                                <button
                                    onClick={() => void loadOlder()}
                                    disabled={loadingMore}
                                    className="h-8 px-4 rounded-full bg-chip text-[12px] font-semibold text-ink/70 hover:text-ink disabled:opacity-50"
                                >
                                    {loadingMore ? '불러오는 중…' : '이전 문의 더 보기'}
                                </button>
                            </div>
                        )}
                        {error && <p role="alert" className="py-2 text-center text-[12px] text-danger">{error}</p>}
                        {data.items.length === 0 && <CenterNote>문의가 없습니다.</CenterNote>}
                        {data.items.map((item, i) => (
                            <InquiryGroup key={item.task_id ?? `${item.received_at}-${i}`} item={item} sender={sender} />
                        ))}
                    </div>
                </div>
            )}
        </>
    );
}

/** 문의 한 건: 머리줄(제목·상태·수신 시각·검토 화면 링크) + 사건 말풍선 */
function InquiryGroup({ item, sender }: { item: TimelineInquiry; sender: string }) {
    return (
        <section className="mt-6 first:mt-2">
            <header className="sticky top-0 z-10 -mx-2 px-2 py-2 bg-white/95 backdrop-blur flex items-center gap-2 flex-wrap border-b border-divide">
                {item.status && <StatusChip status={item.status} />}
                <h2 className="min-w-0 flex-1 text-[14px] font-bold truncate">{item.subject}</h2>
                <time className="text-[11px] text-muted tabular-nums">{fmtDateTime(item.received_at)}</time>
                {item.task_id && (
                    <a
                        {...linkProps(reviewPath(item.task_id))}
                        className="h-7 px-2.5 inline-flex items-center rounded-lg text-[12px] font-semibold text-brand-hover hover:bg-brand-pale transition-colors"
                    >
                        검토 화면에서 열기 →
                    </a>
                )}
            </header>
            <ol className="mt-3 flex flex-col gap-3">
                {item.events.map((ev, i) => (
                    <li key={`${ev.type}-${i}`}>
                        <EventView event={ev} sender={sender} />
                    </li>
                ))}
            </ol>
        </section>
    );
}

function EventView({ event, sender }: { event: TimelineEvent; sender: string }) {
    switch (event.type) {
        case 'received':
            return (
                <div className="flex items-start gap-2.5 max-w-[85%]">
                    <Avatar label={sender} />
                    <div className="min-w-0">
                        <div className="rounded-2xl rounded-tl-md bg-surface px-4 py-3">
                            <Collapsible text={event.body} markdown={false} />
                            {event.attachments.length > 0 && (
                                <div className="mt-2 flex flex-wrap gap-1.5">
                                    {event.attachments.map((a, i) => (
                                        <span
                                            key={`${a.filename}-${i}`}
                                            className="h-6 px-2 inline-flex items-center rounded-md bg-white text-[11px] text-ink/70 border border-divide"
                                        >
                                            {a.filename}
                                        </span>
                                    ))}
                                </div>
                            )}
                        </div>
                        <Meta at={event.at} extra={event.truncated ? TRUNCATED_NOTE : null} />
                    </div>
                </div>
            );
        case 'draft':
            return (
                <div className={`flex items-start gap-2.5 justify-end ${event.current ? '' : 'opacity-60'}`}>
                    <div className="min-w-0 max-w-[85%]">
                        <div className="rounded-2xl rounded-tr-md bg-brand-pale px-4 py-3">
                            <div className="mb-1 flex items-center gap-1.5 flex-wrap text-[11px] font-semibold text-brand">
                                <span>{event.current ? 'AI 초안' : '이전 초안'}</span>
                                {event.skills.map((s) => (
                                    <span key={s.name} title={`적용 절차 ${s.name} · ${s.digest}`} className="px-1.5 rounded bg-white/70 font-medium">
                                        {s.name}
                                    </span>
                                ))}
                            </div>
                            {event.answer == null ? (
                                <p className="text-[13px] text-muted">본문 기록 없음</p>
                            ) : (
                                <Collapsible text={event.answer} markdown />
                            )}
                        </div>
                        <Meta
                            at={event.at}
                            align="right"
                            extra={[event.inferred ? INFERRED_NOTE : null, event.truncated ? TRUNCATED_NOTE : null].filter(Boolean).join(' · ') || null}
                        />
                    </div>
                    <AiAvatar />
                </div>
            );
        case 'reject':
            return (
                <Note at={event.at}>
                    담당자 반려{event.requeue ? ' · 다시 작성' : ''}
                    {event.reason && <span className="block mt-0.5 text-ink/80 whitespace-pre-line">“{event.reason}”</span>}
                </Note>
            );
        case 'retry':
            return <Note at={event.at}>담당자가 다시 생성을 요청함</Note>;
        case 'mark_sent':
            return (
                <Note at={event.at}>
                    담당자가 발송 확인
                    {event.reason && <span className="block mt-0.5 text-ink/80 whitespace-pre-line">“{event.reason}”</span>}
                </Note>
            );
        case 'run_failed':
            return (
                <Note at={event.at} tone="danger">
                    초안 생성 실패 ({event.status === 'limit' ? '실행 한도' : '오류'})
                    {event.error && <span className="block mt-0.5 text-[11px]">{event.error}</span>}
                </Note>
            );
        case 'send':
            return <SendNote event={event} />;
    }
}

function SendNote({ event }: { event: Extract<TimelineEvent, { type: 'send' }> }) {
    const [open, setOpen] = useState(false);
    const meta = SEND_OUTCOME[event.outcome] ?? { label: event.outcome, tone: 'muted' as const };
    return (
        <Note at={event.at} tone={meta.tone} extra={event.inferred ? INFERRED_NOTE : null}>
            {meta.label}
            {event.recipient && <span> · {event.recipient}</span>}
            {event.attachments.length > 0 && <span> · 첨부 {event.attachments.join(', ')}</span>}
            {event.detail && event.outcome !== 'sent' && <span className="block mt-0.5 text-[11px]">{event.detail}</span>}
            {event.body && (
                <>
                    <button onClick={() => setOpen((v) => !v)} className="ml-2 text-[11px] font-semibold text-brand-hover hover:underline">
                        {open ? '본문 접기' : '보낸 본문 보기'}
                    </button>
                    {open && (
                        <span className="block mt-2 text-left rounded-xl bg-white border border-divide px-3 py-2 text-ink">
                            <span className="block mail-draft-markdown prose prose-sm prose-slate max-w-none">
                                <ReactMarkdown remarkPlugins={[remarkGfm]}>{event.body}</ReactMarkdown>
                            </span>
                            {event.truncated && <span className="block mt-1 text-[11px] text-muted">{TRUNCATED_NOTE}</span>}
                        </span>
                    )}
                </>
            )}
        </Note>
    );
}

/** 가운데 정렬 안내 줄 (담당자 처리·발송·실패) */
function Note({
    at,
    tone = 'muted',
    extra,
    children,
}: {
    at: string | null;
    tone?: 'muted' | 'danger';
    extra?: string | null;
    children: ReactNode;
}) {
    return (
        <div className="flex justify-center">
            <div
                className={`max-w-[80%] rounded-xl px-3 py-1.5 text-center text-[12px] ${
                    tone === 'danger' ? 'bg-danger-soft text-danger' : 'bg-chip text-ink/70'
                }`}
            >
                <div className="font-semibold">{children}</div>
                <div className="mt-0.5 text-[10.5px] text-muted tabular-nums">
                    {fmtAt(at)}
                    {extra && ` · ${extra}`}
                </div>
            </div>
        </div>
    );
}

function Meta({ at, align = 'left', extra }: { at: string | null; align?: 'left' | 'right'; extra?: string | null }) {
    return (
        <div className={`mt-1 text-[10.5px] text-muted tabular-nums ${align === 'right' ? 'text-right' : ''}`}>
            {fmtAt(at)}
            {extra && ` · ${extra}`}
        </div>
    );
}

/** 긴 본문은 접는다 (기존 isLongBody 기준) */
function Collapsible({ text, markdown }: { text: string; markdown: boolean }) {
    const long = isLongBody(text);
    const [expanded, setExpanded] = useState(false);
    const folded = long && !expanded;
    return (
        <>
            {markdown ? (
                <div className={`mail-draft-markdown prose prose-sm prose-slate max-w-none text-ink ${folded ? 'max-h-32 overflow-hidden' : ''}`}>
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
                </div>
            ) : (
                <p className={`whitespace-pre-line text-[13.5px] leading-relaxed text-ink/80 ${folded ? 'line-clamp-4' : ''}`}>{text}</p>
            )}
            {long && (
                <button onClick={() => setExpanded((v) => !v)} className="mt-1 text-[12px] font-semibold text-brand-hover hover:underline">
                    {expanded ? '접기' : '전체 보기'}
                </button>
            )}
        </>
    );
}
