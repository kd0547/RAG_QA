import { useEffect, useMemo, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { linkProps } from '../../lib/router';
import { ApiError, mailApi } from '../api';
import { ALL_STATUSES, fmtReceived, isReviewable, reviewPath } from '../format';
import { mockDetail } from '../mockData';
import type { MailDetail, MailStatus, MailSummary } from '../types';
import { CenterNote, MailSubject, ReceivedMessage, ReplyHeader, SegmentedFilter, SourceList, StatusChip } from '../ui';
import { useMailList } from '../useMailList';

type Tab = 'all' | 'review' | 'pending' | 'done' | 'rejected';

const TAB_STATUSES: Record<Tab, MailStatus[] | null> = {
    all: null,
    review: ['drafted', 'in_review', 'failed'],
    pending: ['pending'],
    done: ['approved', 'sent'],
    rejected: ['rejected'],
};

/** 답장 영역 제목 — 상태에 따라 무엇을 보고 있는지 알려준다 */
const REPLY_TITLE: Record<MailStatus, string> = {
    pending: 'AI 초안 작성 대기',
    drafted: 'AI 답장 초안',
    in_review: 'AI 답장 초안',
    rejected: '반려된 초안',
    approved: '승인된 답장',
    sent: '보낸 답장',
    failed: '전송에 실패한 답장',
};

/**
 * 전체 메일 페이지: 들어온 모든 메일을 상태와 상관없이 찾아보는 곳 (읽기 전용).
 * 결정이 필요한 메일은 "검토하기"로 메일 검토 페이지에 넘긴다.
 */
export function MailInboxPage() {
    const [tab, setTab] = useState<Tab>('all');
    const [query, setQuery] = useState('');
    const [qDebounced, setQDebounced] = useState('');

    useEffect(() => {
        const id = window.setTimeout(() => setQDebounced(query.trim()), 300);
        return () => window.clearTimeout(id);
    }, [query]);

    const { rows, loading, offline, reload } = useMailList(ALL_STATUSES, qDebounced);

    const [selected, setSelected] = useState<MailSummary | null>(null);
    const [detail, setDetail] = useState<MailDetail | null>(null);
    const [detailError, setDetailError] = useState<string | null>(null);

    useEffect(() => {
        if (!selected) return;
        const row = selected;
        let ignore = false;
        (async () => {
            try {
                const d = offline ? mockDetail(row) : await mailApi.detail(row.task_id);
                if (!ignore) setDetail(d);
            } catch (e) {
                if (ignore) return;
                setDetail(null);
                setDetailError(e instanceof ApiError ? e.message : '메일을 불러오지 못했습니다.');
            }
        })();
        return () => {
            ignore = true;
        };
    }, [selected, offline]);

    const select = (row: MailSummary | null) => {
        setSelected(row);
        setDetail(null);
        setDetailError(null);
    };

    const counts = useMemo(() => {
        const c: Record<Tab, number> = { all: rows.length, review: 0, pending: 0, done: 0, rejected: 0 };
        for (const r of rows) {
            for (const t of ['review', 'pending', 'done', 'rejected'] as const) {
                if (TAB_STATUSES[t]!.includes(r.status)) c[t]++;
            }
        }
        return c;
    }, [rows]);

    const visible = useMemo(() => {
        const want = TAB_STATUSES[tab];
        return want ? rows.filter((r) => want.includes(r.status)) : rows;
    }, [rows, tab]);

    const narrow = !!selected;

    return (
        <div className="flex-1 min-h-0 flex flex-col md:flex-row">
            {/* 목록 */}
            <section
                className={`min-w-0 min-h-0 flex flex-col ${
                    narrow
                        ? 'md:w-[380px] xl:w-[420px] shrink-0 max-h-[45vh] md:max-h-none border-b md:border-b-0 md:border-r border-divide'
                        : 'flex-1'
                }`}
            >
                <div className={`shrink-0 w-full mx-auto px-4 sm:px-6 pt-5 pb-3 flex flex-col gap-3 ${narrow ? '' : 'max-w-[1120px]'}`}>
                    <div className="flex items-center gap-3">
                        <h1 className="text-[18px] font-bold">전체 메일</h1>
                        <span className="text-[12px] text-muted tabular-nums">{loading ? '' : `${visible.length}건`}</span>
                        <button
                            onClick={() => void reload()}
                            className="ml-auto h-7 px-2.5 rounded-lg text-[12px] font-semibold text-muted hover:text-ink hover:bg-chip transition-colors"
                        >
                            새로고침
                        </button>
                    </div>
                    <div className={`flex gap-2 ${narrow ? 'flex-col' : 'flex-col sm:flex-row sm:items-center'}`}>
                        <div className={narrow ? '' : 'sm:w-[520px]'}>
                            <SegmentedFilter
                                value={tab}
                                onChange={setTab}
                                items={[
                                    ['all', '전체', counts.all],
                                    ['review', '검토 필요', counts.review],
                                    ['pending', '생성 대기', counts.pending],
                                    ['done', '전송', counts.done],
                                    ['rejected', '반려', counts.rejected],
                                ]}
                            />
                        </div>
                        <input
                            value={query}
                            onChange={(e) => setQuery(e.target.value)}
                            placeholder="발신자·제목 검색"
                            className={`h-8 px-3 rounded-lg bg-chip text-[13px] placeholder:text-muted focus:outline-none focus:bg-white focus:ring-2 focus:ring-brand/30 ${
                                narrow ? 'w-full' : 'w-full sm:w-64 sm:ml-auto'
                            }`}
                        />
                    </div>
                </div>

                <div className="flex-1 min-h-0 overflow-y-auto">
                    <div className={`w-full mx-auto px-2 sm:px-4 pb-6 ${narrow ? '' : 'max-w-[1120px]'}`}>
                        {loading && <p className="px-4 py-10 text-center text-muted text-[13px]">불러오는 중…</p>}
                        {!loading && visible.length === 0 && (
                            <p className="px-4 py-10 text-center text-muted text-[13px]">조건에 맞는 메일이 없습니다.</p>
                        )}

                        {/* 넓을 때는 표처럼 열을 맞추고, 상세가 열리면 2줄 목록으로 접는다 */}
                        {!loading && visible.length > 0 && !narrow && (
                            <div className="hidden sm:grid grid-cols-[110px_minmax(0,1fr)_220px_96px] gap-4 px-3 py-2 text-[11px] font-semibold text-muted border-b border-divide">
                                <span>상태</span>
                                <span>제목</span>
                                <span>발신자</span>
                                <span className="text-right">받은 시각</span>
                            </div>
                        )}
                        {!loading &&
                            visible.map((r) => {
                                const sel = r.task_id === selected?.task_id;
                                return (
                                    <button
                                        key={r.task_id}
                                        type="button"
                                        onClick={() => select(sel ? null : r)}
                                        aria-current={sel ? 'true' : undefined}
                                        className={`w-full text-left rounded-xl transition-colors focus-visible:outline-2 focus-visible:outline-brand ${
                                            sel ? 'bg-brand-pale' : 'hover:bg-surface'
                                        } ${
                                            narrow
                                                ? 'block px-3 py-2.5'
                                                : 'grid grid-cols-[1fr_auto] sm:grid-cols-[110px_minmax(0,1fr)_220px_96px] items-center gap-x-4 gap-y-1 px-3 py-3'
                                        }`}
                                    >
                                        {narrow ? (
                                            <>
                                                <span className="flex items-center gap-2 min-w-0 text-[11px] text-muted">
                                                    <span className="truncate flex-1">{r.sender}</span>
                                                    <time className="shrink-0 tabular-nums">{fmtReceived(r.received_at)}</time>
                                                </span>
                                                <span className={`mt-0.5 block text-[13px] leading-snug truncate ${sel ? 'font-bold' : 'font-semibold'}`}>
                                                    {r.subject}
                                                </span>
                                                <span className="mt-1.5 block">
                                                    <StatusChip status={r.status} />
                                                </span>
                                            </>
                                        ) : (
                                            <>
                                                <span className="hidden sm:block">
                                                    <StatusChip status={r.status} />
                                                </span>
                                                <span className="min-w-0 text-[13.5px] font-semibold truncate">{r.subject}</span>
                                                <span className="hidden sm:block min-w-0 text-[12px] text-muted truncate">{r.sender}</span>
                                                <time className="text-[12px] text-muted tabular-nums text-right whitespace-nowrap">
                                                    {fmtReceived(r.received_at)}
                                                </time>
                                                <span className="sm:hidden col-span-2 flex items-center gap-2 min-w-0 text-[11px] text-muted">
                                                    <StatusChip status={r.status} />
                                                    <span className="truncate">{r.sender}</span>
                                                </span>
                                            </>
                                        )}
                                    </button>
                                );
                            })}
                    </div>
                </div>
            </section>

            {/* 읽기 전용 상세 */}
            {selected && (
                <main className="flex-1 min-w-0 min-h-0 md:overflow-y-auto flex flex-col">
                    <div className="sticky top-0 z-10 bg-white/90 backdrop-blur border-b border-divide px-4 sm:px-6 h-12 flex items-center gap-2">
                        <button
                            onClick={() => select(null)}
                            className="h-8 px-2.5 rounded-lg text-[12px] font-semibold text-muted hover:text-ink hover:bg-chip transition-colors"
                        >
                            ✕ 닫기
                        </button>
                        <span className="text-[11px] text-muted">읽기 전용</span>
                        {isReviewable(selected.status) && (
                            <a
                                {...linkProps(reviewPath(selected.task_id))}
                                className="ml-auto h-8 px-4 inline-flex items-center rounded-lg bg-brand text-white text-[12.5px] font-bold hover:bg-brand-hover transition-colors"
                            >
                                검토하기 →
                            </a>
                        )}
                    </div>

                    {!detail && !detailError && <CenterNote>불러오는 중…</CenterNote>}
                    {detailError && <CenterNote tone="danger">{detailError}</CenterNote>}

                    {detail && (
                        <div className="mx-auto w-full max-w-[760px] px-5 sm:px-10 pt-8 pb-12">
                            <MailSubject detail={detail} />

                            <div className="mt-8">
                                <ReceivedMessage key={detail.task_id} detail={detail} />
                            </div>

                            <hr className="my-8 border-divide" />

                            <section>
                                <ReplyHeader
                                    title={REPLY_TITLE[detail.status] ?? '답장'}
                                    caption={`${detail.model ? `${detail.model} · ` : ''}받는 사람 ${detail.sender}`}
                                />
                                {detail.draft ? (
                                    <article className="mt-3 mail-draft-markdown prose prose-slate max-w-none text-ink py-4">
                                        <ReactMarkdown remarkPlugins={[remarkGfm]}>{detail.draft}</ReactMarkdown>
                                    </article>
                                ) : (
                                    <p className="mt-3 py-4 text-[13px] text-muted">
                                        {detail.status === 'pending' ? 'AI가 아직 초안을 작성하지 않았습니다.' : '답장 내용이 없습니다.'}
                                    </p>
                                )}
                            </section>

                            <div className="mt-8">
                                <SourceList sources={detail.sources} />
                            </div>
                        </div>
                    )}
                </main>
            )}
        </div>
    );
}
