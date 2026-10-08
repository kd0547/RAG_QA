import { Suspense, useCallback, useEffect, useMemo, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { LazyMarkdownEditor } from '../../components/LazyMarkdownEditor';
import { ApiError, mailApi } from '../api';
import { fmtReceived, reviewPath } from '../format';
import { mockDetail } from '../mockData';
import type { MailDetail, MailSummary } from '../types';
import {
    AttachmentPicker,
    CenterNote,
    MailSubject,
    ReceivedMessage,
    ReplyHeader,
    SegmentedFilter,
    SourceList,
    StatusChip,
} from '../ui';
import type { MailList } from '../useMailList';

type Filter = 'all' | 'drafted' | 'in_review' | 'failed';
type Busy = '' | 'approve' | 'reject' | 'save' | 'retry' | 'claim';

/**
 * 메일 검토 페이지: 왼쪽은 검토가 필요한 메일(대기열), 오른쪽은 원문 → AI 답장 → 근거 순서의 검토 캔버스.
 * 승인·반려·재전송·담당 지정 같은 "결정"은 이 페이지에서만 한다.
 */
export function MailReviewPage({
    queue,
    reloadStats,
    onWorkingChange,
}: {
    queue: MailList;
    reloadStats: (quiet?: boolean) => Promise<void>;
    onWorkingChange: (working: boolean) => void;
}) {
    const { rows, setRows, loading, offline, error: listError, reload: reloadQueue } = queue;

    const [filter, setFilter] = useState<Filter>('all');
    const [query, setQuery] = useState('');

    // 주소의 task_id: 대시보드·메일 페이지에서 넘어왔거나, 승인 요청 메일의 링크로 들어온 경우.
    // 메일 링크(from=email)로 들어온 건은 예시 데이터로 대체하지 않고 실제 오류를 보여주며 바로 편집을 연다.
    const [{ linkTaskId, fromEmail }] = useState(() => {
        const p = new URLSearchParams(window.location.search);
        return { linkTaskId: p.get('task_id')?.trim() || null, fromEmail: p.get('from') === 'email' };
    });

    const [selectedRow, setSelectedRow] = useState<MailSummary | null>(() =>
        linkTaskId ? { task_id: linkTaskId, subject: '', sender: '', received_at: '', status: 'drafted' } : null,
    );
    const [detail, setDetail] = useState<MailDetail | null>(null);
    const [detailLoading, setDetailLoading] = useState(!!linkTaskId);
    const [detailError, setDetailError] = useState<string | null>(null);

    const [editing, setEditing] = useState(() => fromEmail);
    const [draftText, setDraftText] = useState('');
    const [dirty, setDirty] = useState(false);
    // MDX 파싱이 실패한 초안(예: 맨 `<` 문자)은 내용을 잃지 않도록 원문 편집으로 대체한다.
    const [editorFailed, setEditorFailed] = useState(false);
    const [rejecting, setRejecting] = useState(false);
    const [rejectReason, setRejectReason] = useState('');
    // 답장에 첨부할 참고 문서 (file_id). 메일을 바꾸면 비운다 — 기본은 첨부 없음.
    const [attachIds, setAttachIds] = useState<ReadonlySet<string>>(() => new Set());
    const [busy, setBusy] = useState<Busy>('');

    const [toast, setToast] = useState<{ kind: 'ok' | 'err'; msg: string } | null>(null);
    const notify = useCallback((kind: 'ok' | 'err', msg: string) => setToast({ kind, msg }), []);

    const selectedTaskId = selectedRow?.task_id ?? null;

    // 편집·작업 중에는 상위의 자동 새로고침을 멈춘다.
    useEffect(() => {
        onWorkingChange(dirty || busy !== '' || rejecting);
    }, [dirty, busy, rejecting, onWorkingChange]);
    useEffect(() => () => onWorkingChange(false), [onWorkingChange]);

    useEffect(() => {
        if (!toast) return;
        const id = window.setTimeout(() => setToast(null), 2600);
        return () => window.clearTimeout(id);
    }, [toast]);

    /* ---- 행 선택 (이벤트 핸들러에서만 호출) ---- */
    const selectRow = useCallback((row: MailSummary | null) => {
        setSelectedRow(row);
        setDetailError(null);
        setEditing(false);
        setEditorFailed(false);
        setRejecting(false);
        setRejectReason('');
        setAttachIds(new Set());
        setDirty(false);
        setDetailLoading(!!row);
        if (!row) setDetail(null);
        // 선택한 메일을 주소에 남겨 새로고침·공유해도 같은 메일이 열리게 한다.
        window.history.replaceState(null, '', reviewPath(row?.task_id));
    }, []);

    /* ---- 상세 로드 (setState 는 모두 await 이후) ---- */
    useEffect(() => {
        if (!selectedRow) return;
        const row = selectedRow;
        const isLink = fromEmail && row.task_id === linkTaskId;
        let ignore = false;
        (async () => {
            try {
                const d = offline && !isLink ? mockDetail(row) : await mailApi.detail(row.task_id);
                if (ignore) return;
                setDetail(d);
                setDetailError(null);
                setDraftText(d.draft ?? '');
                setDirty(false);
            } catch (e) {
                if (ignore) return;
                if (isLink) {
                    setDetail(null);
                    setDetailError(e instanceof ApiError ? e.message : '메일을 불러오지 못했습니다.');
                    return;
                }
                const d = mockDetail(row);
                setDetail(d);
                setDraftText(d.draft ?? '');
                setDirty(false);
                if (e instanceof ApiError && e.code !== 'network') notify('err', e.message);
            } finally {
                if (!ignore) setDetailLoading(false);
            }
        })();
        return () => {
            ignore = true;
        };
    }, [selectedRow, offline, linkTaskId, fromEmail, notify]);

    /* ---- 파생값 ---- */
    const visible = useMemo(() => {
        const q = query.trim().toLowerCase();
        return rows.filter((r) => {
            if (filter !== 'all' && r.status !== filter) return false;
            if (!q) return true;
            return r.subject.toLowerCase().includes(q) || r.sender.toLowerCase().includes(q);
        });
    }, [rows, filter, query]);

    const counts = useMemo(() => {
        const c: Record<Filter, number> = { all: rows.length, drafted: 0, in_review: 0, failed: 0 };
        for (const r of rows) if (r.status in c) c[r.status as Filter]++;
        return c;
    }, [rows]);

    /* ---- 키보드 j / k 이동 ---- */
    useEffect(() => {
        const onKey = (e: KeyboardEvent) => {
            const t = e.target as HTMLElement;
            if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return;
            if (e.key !== 'j' && e.key !== 'k') return;
            if (visible.length === 0) return;
            e.preventDefault();
            const idx = visible.findIndex((r) => r.task_id === selectedTaskId);
            const next =
                e.key === 'j'
                    ? Math.min(visible.length - 1, idx < 0 ? 0 : idx + 1)
                    : Math.max(0, idx < 0 ? 0 : idx - 1);
            selectRow(visible[next]);
        };
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
    }, [visible, selectedTaskId, selectRow]);

    /* ---- 액션 ---- */
    const refreshAll = () => {
        void reloadQueue(true);
        void reloadStats(true);
    };
    const dropRow = (taskId: string) => {
        setRows((prev) => prev.filter((r) => r.task_id !== taskId));
        selectRow(null);
    };
    const patchRow = (taskId: string, patch: Partial<MailSummary>) =>
        setRows((prev) => prev.map((r) => (r.task_id === taskId ? { ...r, ...patch } : r)));

    const editedFlag = !!detail && draftText.trim() !== (detail.draft ?? '').trim();

    const toggleAttachment = (fileId: string) =>
        setAttachIds((prev) => {
            const next = new Set(prev);
            if (next.has(fileId)) next.delete(fileId);
            else next.add(fileId);
            return next;
        });

    const toggleEditing = () => {
        if (!detail) return;
        if (editing) {
            setDraftText(detail.draft ?? '');
            setDirty(false);
        }
        setEditorFailed(false);
        setEditing((v) => !v);
    };

    const handleApprove = async () => {
        if (!detail) return;
        const taskId = detail.task_id;
        if (offline) {
            dropRow(taskId);
            notify('ok', '전송 완료 (예시 데이터)');
            return;
        }
        setBusy('approve');
        try {
            // 상세에 없는 ID(이전 메일에서 남은 선택 등)는 보내지 않는다
            const attachment_file_ids = (detail.attachments ?? []).filter((a) => attachIds.has(a.file_id)).map((a) => a.file_id);
            const res = await mailApi.approve(taskId, {
                ...(editedFlag ? { body: draftText, edited: true } : {}),
                attachment_file_ids,
            });
            dropRow(taskId);
            notify('ok', `전송 완료 → ${res.to}${attachment_file_ids.length ? ` · 첨부 ${attachment_file_ids.length}개` : ''}`);
            refreshAll();
        } catch (e) {
            notify('err', e instanceof ApiError ? e.message : '전송 실패');
        } finally {
            setBusy('');
        }
    };

    const handleRetry = async () => {
        if (!detail) return;
        const taskId = detail.task_id;
        if (offline) {
            dropRow(taskId);
            notify('ok', '재전송 완료 (예시 데이터)');
            return;
        }
        setBusy('retry');
        try {
            const res = await mailApi.retry(taskId);
            dropRow(taskId);
            notify('ok', `재전송 완료 → ${res.to}`);
            refreshAll();
        } catch (e) {
            notify('err', e instanceof ApiError ? e.message : '재전송 실패');
        } finally {
            setBusy('');
        }
    };

    const handleSaveDraft = async () => {
        if (!detail) return;
        if (offline) {
            setDetail({ ...detail, draft: draftText });
            setDirty(false);
            setEditing(false);
            notify('ok', '초안 저장 (예시 데이터)');
            return;
        }
        setBusy('save');
        try {
            await mailApi.saveDraft(detail.task_id, draftText);
            setDetail({ ...detail, draft: draftText });
            setDirty(false);
            setEditing(false);
            notify('ok', '초안을 저장했습니다');
        } catch (e) {
            notify('err', e instanceof ApiError ? e.message : '초안 저장 실패');
        } finally {
            setBusy('');
        }
    };

    const handleReject = async () => {
        if (!detail || !rejectReason.trim()) return;
        const taskId = detail.task_id;
        if (offline) {
            dropRow(taskId);
            notify('ok', '반려 처리 (예시 데이터)');
            return;
        }
        setBusy('reject');
        try {
            await mailApi.reject(taskId, { reason: rejectReason.trim(), requeue: true });
            dropRow(taskId);
            notify('ok', '반려했습니다 — 재작성 대기로 이동');
            refreshAll();
        } catch (e) {
            notify('err', e instanceof ApiError ? e.message : '반려 실패');
        } finally {
            setBusy('');
        }
    };

    const handleClaimToggle = async () => {
        if (!detail) return;
        const mine = !!detail.assignee;
        if (offline) {
            const next: MailDetail = { ...detail, assignee: mine ? null : '나', status: mine ? 'drafted' : 'in_review' };
            setDetail(next);
            patchRow(detail.task_id, { status: next.status });
            return;
        }
        setBusy('claim');
        try {
            const next = mine ? await mailApi.release(detail.task_id) : await mailApi.claim(detail.task_id, '나');
            setDetail(next);
            patchRow(detail.task_id, { status: next.status });
        } catch (e) {
            notify('err', e instanceof ApiError ? e.message : '담당 지정 실패');
        } finally {
            setBusy('');
        }
    };

    const cancelReject = () => {
        setRejecting(false);
        setRejectReason('');
    };

    /* ---- 렌더 ---- */
    return (
        <div className="flex-1 min-h-0 flex flex-col md:flex-row">
            {/* 좌: 검토가 필요한 메일 */}
            <nav className="md:w-[320px] xl:w-[360px] shrink-0 min-h-0 max-h-[45vh] md:max-h-none flex flex-col border-b md:border-b-0 md:border-r border-divide">
                <div className="shrink-0 px-4 pt-4 pb-3 flex flex-col gap-2.5">
                    <div className="flex items-center justify-between gap-2">
                        <h1 className="text-[14px] font-bold">
                            검토가 필요한 메일 <span className="tabular-nums text-muted">{rows.length}</span>
                        </h1>
                        <button
                            onClick={() => {
                                void reloadQueue();
                                void reloadStats();
                            }}
                            className="h-7 px-2.5 rounded-lg text-[12px] font-semibold text-muted hover:text-ink hover:bg-chip transition-colors"
                        >
                            새로고침
                        </button>
                    </div>
                    <SegmentedFilter
                        value={filter}
                        onChange={setFilter}
                        items={[
                            ['all', '전체', counts.all],
                            ['drafted', '초안', counts.drafted],
                            ['in_review', '검토중', counts.in_review],
                            ['failed', '실패', counts.failed],
                        ]}
                    />
                    <input
                        value={query}
                        onChange={(e) => setQuery(e.target.value)}
                        placeholder="발신자·제목 검색"
                        className="h-8 w-full px-3 rounded-lg bg-chip text-[13px] placeholder:text-muted focus:outline-none focus:bg-white focus:ring-2 focus:ring-brand/30"
                    />
                    {listError && (
                        <p role="alert" className="text-[11px] text-danger">
                            API 오류: {listError} — 예시 데이터로 표시합니다
                        </p>
                    )}
                </div>

                <div className="flex-1 min-h-0 overflow-y-auto px-2 pb-2">
                    {loading && <p className="px-4 py-10 text-center text-muted text-[13px]">불러오는 중…</p>}
                    {!loading && visible.length === 0 && (
                        <p className="px-4 py-10 text-center text-muted text-[13px]">
                            {rows.length === 0 ? '검토할 메일이 없습니다. 모두 처리했어요.' : '조건에 맞는 메일이 없습니다.'}
                        </p>
                    )}
                    {!loading &&
                        visible.map((r) => {
                            const sel = r.task_id === selectedTaskId;
                            return (
                                <button
                                    key={r.task_id}
                                    type="button"
                                    onClick={() => selectRow(r)}
                                    aria-current={sel ? 'true' : undefined}
                                    className={`w-full text-left px-3 py-2.5 rounded-xl transition-colors focus-visible:outline-2 focus-visible:outline-brand ${
                                        sel ? 'bg-brand-pale' : 'hover:bg-surface'
                                    }`}
                                >
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
                                </button>
                            );
                        })}
                </div>

                <p className="hidden md:block shrink-0 px-5 py-2.5 border-t border-divide text-[11px] text-muted">
                    <kbd className="font-mono">j</kbd> / <kbd className="font-mono">k</kbd> 이동 · 20초마다 자동 새로고침
                </p>
            </nav>

            {/* 우: 문서처럼 읽는 검토 캔버스 */}
            <main className="flex-1 min-w-0 min-h-0 md:overflow-y-auto flex flex-col">
                {!selectedRow && (
                    <CenterNote>
                        왼쪽에서 메일을 선택하면
                        <br />
                        원문·초안·근거를 이어서 검토합니다.
                    </CenterNote>
                )}
                {selectedRow && detailLoading && !detail && <CenterNote>불러오는 중…</CenterNote>}
                {selectedRow && !detailLoading && !detail && detailError && <CenterNote tone="danger">{detailError}</CenterNote>}

                {selectedRow && detail && (
                    <>
                        <div className="flex-1 mx-auto w-full max-w-[760px] px-5 sm:px-10 pt-8 pb-4">
                            <MailSubject detail={detail} />

                            <div className="mt-8">
                                <ReceivedMessage key={detail.task_id} detail={detail} />
                            </div>

                            <hr className="my-8 border-divide" />

                            {/* AI 답장: 검토의 중심. 제자리에서 바로 고친다 */}
                            <section>
                                <ReplyHeader
                                    title="AI 답장 초안"
                                    badge={
                                        editedFlag && (
                                            <span className="inline-flex items-center h-[18px] px-1.5 rounded-md bg-brand-soft text-brand text-[10px] font-bold">
                                                수정됨
                                            </span>
                                        )
                                    }
                                    caption={`${detail.model ? `${detail.model} · ` : ''}승인하면 ${detail.sender}에게 전송됩니다`}
                                    action={
                                        detail.draft != null && (
                                            <button
                                                onClick={toggleEditing}
                                                className="shrink-0 h-8 px-3 rounded-lg text-[12px] font-semibold text-ink/70 hover:text-ink hover:bg-chip transition-colors"
                                            >
                                                {editing ? '편집 취소' : '수정하기'}
                                            </button>
                                        )
                                    }
                                />

                                <div className="mt-3 -mx-5">
                                    {editing && !editorFailed ? (
                                        <div className="mail-draft-editor">
                                            <Suspense fallback={<p className="px-5 py-4 text-[13px] text-muted">에디터 불러오는 중…</p>}>
                                                <LazyMarkdownEditor
                                                    key={detail.task_id}
                                                    markdown={draftText}
                                                    onChange={(md, initialNormalize) => {
                                                        // 마운트 시 정규화는 사용자 수정이 아니므로 무시한다.
                                                        if (initialNormalize) return;
                                                        setDraftText(md);
                                                        setDirty(true);
                                                    }}
                                                    onError={() => setEditorFailed(true)}
                                                    contentEditableClassName="mail-draft-markdown prose prose-slate max-w-none text-ink"
                                                />
                                            </Suspense>
                                        </div>
                                    ) : editing ? (
                                        <textarea
                                            value={draftText}
                                            onChange={(e) => {
                                                setDraftText(e.target.value);
                                                setDirty(true);
                                            }}
                                            rows={12}
                                            className="block w-full min-h-72 rounded-xl bg-brand-tint ring-1 ring-brand/25 px-5 py-4 text-[16px] leading-[1.85] font-sans focus:outline-none resize-y"
                                        />
                                    ) : detail.draft ? (
                                        <article
                                            onClick={() => {
                                                // 텍스트를 복사하려고 드래그한 경우는 편집으로 넘어가지 않는다.
                                                if (window.getSelection()?.toString()) return;
                                                toggleEditing();
                                            }}
                                            title="클릭해서 수정"
                                            className="mail-draft-markdown prose prose-slate max-w-none text-ink px-5 py-4 rounded-xl cursor-text hover:bg-surface transition-colors"
                                        >
                                            <ReactMarkdown remarkPlugins={[remarkGfm]}>{draftText || detail.draft}</ReactMarkdown>
                                        </article>
                                    ) : (
                                        <p className="px-5 py-4 text-[13px] text-muted">초안이 아직 없습니다.</p>
                                    )}
                                </div>
                            </section>

                            {/* 승인과 함께 나가는 것이므로 초안 바로 아래에 둔다 */}
                            {detail.status !== 'failed' && (
                                <div className="mt-8">
                                    <AttachmentPicker
                                        attachments={detail.attachments ?? []}
                                        selected={attachIds}
                                        onToggle={toggleAttachment}
                                        disabled={busy !== ''}
                                    />
                                </div>
                            )}

                            <div className="mt-8">
                                <SourceList sources={detail.sources} />
                            </div>
                        </div>

                        {/* 떠 있는 액션 바 */}
                        <div className="sticky bottom-0 z-10 pointer-events-none px-4 pt-6 pb-5 bg-linear-to-t from-white via-white/85 to-transparent">
                            <div className="pointer-events-auto mx-auto w-fit max-w-full flex items-center gap-1 p-1.5 rounded-2xl bg-white border border-divide shadow-[0_8px_30px_rgba(20,28,43,0.12)]">
                                {rejecting ? (
                                    <>
                                        <input
                                            value={rejectReason}
                                            onChange={(e) => setRejectReason(e.target.value)}
                                            onKeyDown={(e) => {
                                                if (e.key === 'Enter') void handleReject();
                                                if (e.key === 'Escape') cancelReject();
                                            }}
                                            placeholder="반려 사유 (재작성 시 전달됩니다)"
                                            autoFocus
                                            className="w-[min(380px,52vw)] h-10 px-3.5 rounded-xl bg-chip text-[13px] focus:outline-none focus:bg-white focus:ring-2 focus:ring-danger/30"
                                        />
                                        <button
                                            onClick={cancelReject}
                                            className="h-10 px-3 rounded-xl text-[13px] font-semibold text-muted hover:text-ink hover:bg-chip"
                                        >
                                            취소
                                        </button>
                                        <button
                                            onClick={() => void handleReject()}
                                            disabled={!rejectReason.trim() || busy !== ''}
                                            className="h-10 px-4 rounded-xl bg-danger text-white text-[13px] font-bold whitespace-nowrap hover:brightness-105 disabled:opacity-50"
                                        >
                                            {busy === 'reject' ? '처리 중…' : '반려 확정'}
                                        </button>
                                    </>
                                ) : (
                                    <>
                                        <button
                                            onClick={() => setRejecting(true)}
                                            className="h-10 px-3.5 rounded-xl text-[13px] font-semibold text-danger hover:bg-danger-soft"
                                        >
                                            반려
                                        </button>
                                        {detail.status !== 'failed' && (
                                            <button
                                                onClick={() => void handleClaimToggle()}
                                                disabled={busy !== ''}
                                                className="h-10 px-3.5 rounded-xl text-[13px] font-semibold text-ink/70 whitespace-nowrap hover:text-ink hover:bg-chip disabled:opacity-50"
                                            >
                                                {detail.assignee ? '담당 해제' : '내가 검토'}
                                            </button>
                                        )}
                                        {editing && dirty && (
                                            <button
                                                onClick={() => void handleSaveDraft()}
                                                disabled={busy !== ''}
                                                className="h-10 px-3.5 rounded-xl text-[13px] font-semibold text-ink/70 whitespace-nowrap hover:text-ink hover:bg-chip disabled:opacity-50"
                                            >
                                                {busy === 'save' ? '저장 중…' : '임시 저장'}
                                            </button>
                                        )}
                                        <span className="w-px h-6 mx-1 bg-divide" />
                                        {detail.status === 'failed' ? (
                                            <button
                                                onClick={() => void handleRetry()}
                                                disabled={busy !== ''}
                                                className="h-10 px-6 rounded-xl bg-brand text-white text-[13.5px] font-bold whitespace-nowrap hover:bg-brand-hover disabled:opacity-50"
                                            >
                                                {busy === 'retry' ? '재전송 중…' : '재전송'}
                                            </button>
                                        ) : (
                                            <button
                                                onClick={() => void handleApprove()}
                                                disabled={busy !== '' || !detail.draft}
                                                className="h-10 px-6 rounded-xl bg-brand text-white text-[13.5px] font-bold whitespace-nowrap hover:bg-brand-hover disabled:opacity-50"
                                            >
                                                {busy === 'approve' ? '전송 중…' : editedFlag ? '수정본 승인하고 전송' : '승인하고 전송'}
                                            </button>
                                        )}
                                    </>
                                )}
                            </div>
                        </div>
                    </>
                )}
            </main>

            {toast && (
                <div
                    className={`fixed top-4 left-1/2 -translate-x-1/2 z-50 px-4 py-2.5 rounded-xl text-[13px] font-semibold shadow-lg border ${
                        toast.kind === 'ok' ? 'bg-ink border-ink text-white' : 'bg-danger-surface border-danger/30 text-danger'
                    }`}
                >
                    {toast.msg}
                </div>
            )}
        </div>
    );
}
