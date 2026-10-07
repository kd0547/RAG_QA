import { useCallback, useEffect, useMemo, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { ApiError, mailApi } from './api';
import type { MailDetail, MailStats, MailStatus, MailSummary } from './types';
import { MOCK_ROWS, mockDetail } from './mockData';
import { Sparkline } from './Sparkline';

/* ------------------------------------------------------------------ */
/*  표시 유틸                                                          */
/* ------------------------------------------------------------------ */

const timeFmt = new Intl.DateTimeFormat('ko-KR', { hour: '2-digit', minute: '2-digit', hour12: false });
const dateTimeFmt = new Intl.DateTimeFormat('ko-KR', {
    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false,
});

const fmtTime = (iso: string) => {
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? '—' : timeFmt.format(d);
};
const fmtDateTime = (iso: string) => {
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? '—' : dateTimeFmt.format(d);
};
const fmtDuration = (sec: number | null) => {
    if (sec == null) return '—';
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    return `${m}:${String(s).padStart(2, '0')}`;
};
const pct = (n: number | null | undefined) => (n == null ? null : Math.round(n * 100));

const STATUS_META: Record<MailStatus, { label: string; chip: string }> = {
    pending: { label: '대기', chip: 'bg-chip text-muted' },
    drafted: { label: '초안 준비', chip: 'bg-chip text-ink/70' },
    in_review: { label: '검토 중', chip: 'bg-brand-soft text-brand' },
    sent: { label: '전송 완료', chip: 'bg-brand-soft text-brand' },
    failed: { label: '전송 실패', chip: 'bg-danger-soft text-danger' },
};

function StatusChip({ status }: { status: MailStatus }) {
    const m = STATUS_META[status];
    return (
        <span className={`inline-flex items-center h-[19px] px-2 rounded-full text-[11px] font-bold ${m.chip}`}>
            {m.label}
        </span>
    );
}

/* ------------------------------------------------------------------ */
/*  본문                                                               */
/* ------------------------------------------------------------------ */

type Filter = 'all' | 'drafted' | 'in_review' | 'failed';
const FILTER_STATUSES: MailStatus[] = ['drafted', 'in_review', 'failed'];
type Busy = '' | 'approve' | 'reject' | 'save' | 'retry' | 'claim';

export function MailApprovalDashboard() {
    const [rows, setRows] = useState<MailSummary[]>([]);
    const [stats, setStats] = useState<MailStats | null>(null);
    const [statsError, setStatsError] = useState(false);
    const [offline, setOffline] = useState(false);
    const [loading, setLoading] = useState(true);

    const [filter, setFilter] = useState<Filter>('all');
    const [query, setQuery] = useState('');
    const [qDebounced, setQDebounced] = useState('');

    const [selectedRow, setSelectedRow] = useState<MailSummary | null>(() => {
        const taskId = new URLSearchParams(window.location.search).get('task_id')?.trim();
        return taskId
            ? { task_id: taskId, subject: '', sender: '', received_at: '', status: 'drafted' }
            : null;
    });
    const [detail, setDetail] = useState<MailDetail | null>(null);
    const [detailLoading, setDetailLoading] = useState(false);
    const [detailError, setDetailError] = useState<string | null>(null);

    const [editing, setEditing] = useState(
        () => Boolean(new URLSearchParams(window.location.search).get('task_id')?.trim()),
    );
    const [draftText, setDraftText] = useState('');
    const [dirty, setDirty] = useState(false);
    const [rejecting, setRejecting] = useState(false);
    const [rejectReason, setRejectReason] = useState('');
    const [busy, setBusy] = useState<Busy>('');

    const [toast, setToast] = useState<{ kind: 'ok' | 'err'; msg: string } | null>(null);
    const notify = useCallback((kind: 'ok' | 'err', msg: string) => setToast({ kind, msg }), []);

    const selectedTaskId = selectedRow?.task_id ?? null;

    /* ---- 목록과 통계는 각각 요청한다. 한쪽 실패가 다른 쪽을 가리지 않는다. ---- */
    const loadMails = useCallback(
        async (quiet: boolean) => {
            const wantStatus = filter === 'all' ? FILTER_STATUSES : [filter];
            try {
                const list = await mailApi.list({ status: wantStatus, q: qDebounced || undefined, order: '-received_at', limit: 100 });
                setRows(list.items);
                setOffline(false);
            } catch (e) {
                if (!quiet) {
                    setRows(MOCK_ROWS);
                    setOffline(true);
                    if (e instanceof ApiError && e.code !== 'network') {
                        notify('err', `API 오류: ${e.message} — 예시 데이터로 표시합니다`);
                    }
                }
            } finally {
                if (!quiet) setLoading(false);
            }
        },
        [filter, qDebounced, notify],
    );

    const loadStats = useCallback(async (quiet: boolean) => {
        try {
            setStats(await mailApi.stats());
            setStatsError(false);
        } catch {
            if (!quiet) setStats(null);
            setStatsError(true);
        }
    }, []);

    useEffect(() => {
        // 목록 조건이 바뀌면 목록만 다시 요청한다.
        // eslint-disable-next-line react-hooks/set-state-in-effect
        void loadMails(false);
    }, [loadMails]);

    useEffect(() => {
        // eslint-disable-next-line react-hooks/set-state-in-effect
        void loadStats(false);
    }, [loadStats]);

    // 20초마다 조용히 새로고침 — 편집/작업 중이면 폴링을 멈춘다(effect cleanup).
    useEffect(() => {
        if (dirty || busy || rejecting) return;
        const id = window.setInterval(() => {
            void loadMails(true);
            void loadStats(true);
        }, 20_000);
        return () => window.clearInterval(id);
    }, [dirty, busy, rejecting, loadMails, loadStats]);

    // 검색어 디바운스
    useEffect(() => {
        const id = window.setTimeout(() => setQDebounced(query.trim()), 300);
        return () => window.clearTimeout(id);
    }, [query]);

    // 토스트 자동 소멸
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
        setRejecting(false);
        setRejectReason('');
        setDirty(false);
        setDetailLoading(!!row);
        if (!row) setDetail(null);
    }, []);

    /* ---- 상세 로드 (setState 는 모두 await 이후) ---- */
    useEffect(() => {
        if (!selectedRow) return;
        const row = selectedRow;
        const isEmailLink = new URLSearchParams(window.location.search).get('task_id') === row.task_id;
        let ignore = false;
        (async () => {
            try {
                const d = offline && !isEmailLink ? mockDetail(row) : await mailApi.detail(row.task_id);
                if (ignore) return;
                setDetail(d);
                setDetailError(null);
                setDraftText(d.draft ?? '');
                setDirty(false);
            } catch (e) {
                if (ignore) return;
                if (isEmailLink) {
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
    }, [selectedRow, offline, notify]);

    /* ---- 파생값 ---- */
    const visible = useMemo(() => {
        const q = qDebounced.toLowerCase();
        return rows.filter((r) => {
            if (filter !== 'all' && r.status !== filter) return false;
            if (!q) return true;
            return (
                r.subject.toLowerCase().includes(q) ||
                r.sender.toLowerCase().includes(q)
            );
        });
    }, [rows, filter, qDebounced]);

    const counts = useMemo(() => {
        const c: Record<string, number> = { all: rows.length, drafted: 0, in_review: 0, failed: 0 };
        for (const r of rows) if (r.status in c) c[r.status]++;
        return c;
    }, [rows]);

    /* ---- 키보드 j / k 이동 ---- */
    useEffect(() => {
        const onKey = (e: KeyboardEvent) => {
            const t = e.target as HTMLElement;
            if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA')) return;
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
    const dropRow = (taskId: string) => {
        setRows((prev) => prev.filter((r) => r.task_id !== taskId));
        selectRow(null);
    };
    const patchRow = (taskId: string, patch: Partial<MailSummary>) =>
        setRows((prev) => prev.map((r) => (r.task_id === taskId ? { ...r, ...patch } : r)));

    const editedFlag = !!detail && draftText.trim() !== (detail.draft ?? '').trim();

    const handleApprove = async () => {
        if (!detail) return;
        const taskId = detail.task_id;
        if (offline) {
            dropRow(taskId);
            setStats((s) =>
                s ? { ...s, pending_review: Math.max(0, s.pending_review - 1), sent_today: s.sent_today + 1 } : s,
            );
            notify('ok', '전송 완료 (예시 데이터)');
            return;
        }
        setBusy('approve');
        try {
            const res = await mailApi.approve(taskId, editedFlag ? { body: draftText, edited: true } : {});
            dropRow(taskId);
            notify('ok', `전송 완료 → ${res.to}`);
            void loadMails(true);
            void loadStats(true);
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
            void loadMails(true);
            void loadStats(true);
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
            setStats((s) =>
                s ? { ...s, pending_review: Math.max(0, s.pending_review - 1), rejected_today: s.rejected_today + 1 } : s,
            );
            notify('ok', '반려 처리 (예시 데이터)');
            return;
        }
        setBusy('reject');
        try {
            await mailApi.reject(taskId, { reason: rejectReason.trim(), requeue: true });
            dropRow(taskId);
            notify('ok', '반려했습니다 — 재작성 대기로 이동');
            void loadMails(true);
            void loadStats(true);
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
            const next: MailDetail = {
                ...detail,
                assignee: mine ? null : '나',
                status: mine ? 'drafted' : 'in_review',
            };
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

    /* ---- 렌더 ---- */
    const avgVol =
        stats && stats.daily_volume.length
            ? (stats.daily_volume.reduce((a, b) => a + b.sent, 0) / stats.daily_volume.length).toFixed(1)
            : '—';
    const adoption = pct(stats?.draft_adoption_rate);

    return (
        <div className="min-h-screen md:h-dvh md:overflow-hidden bg-white text-ink font-sans antialiased flex flex-col">
            {/* 헤더 */}
            <header className="h-14 shrink-0 border-b border-divide px-6 flex items-center justify-between">
                <div className="flex items-baseline gap-3">
                    <span className="text-[15px] font-bold tracking-tight">메일 전송 승인</span>
                    <span className="text-[12px] text-muted">AI 회신 초안 검토 · 승인 후 전송</span>
                </div>
                <div className="flex items-center gap-3">
                    {offline && (
                        <span className="inline-flex items-center h-6 px-2.5 rounded-full bg-warn-soft text-warn text-[11px] font-bold">
                            메일 목록 미연결 · 예시 데이터
                        </span>
                    )}
                    <button
                        onClick={() => {
                            void loadMails(false);
                            void loadStats(false);
                        }}
                        className="h-8 px-3 rounded-lg border border-line text-[12px] font-semibold hover:bg-surface transition-colors"
                    >
                        새로고침
                    </button>
                    <a href="#/" className="text-[12px] text-muted hover:text-ink transition-colors">
                        ← OCR 도구
                    </a>
                </div>
            </header>

            <main className="w-full max-w-[1800px] mx-auto px-4 sm:px-6 py-4 md:flex-1 md:min-h-0 md:overflow-hidden flex flex-col gap-3">
                {/* 현황은 가로 한 줄로 압축해 목록 높이를 확보한다. */}
                <div className="shrink-0 grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2">
                        <StatTile
                            label="승인 대기"
                            value={stats ? String(stats.pending_review) : '—'}
                            hint="검토 대기 중"
                            lead
                        />
                        <StatTile
                            label="오늘 전송"
                            value={stats ? String(stats.sent_today) : '—'}
                            hint={
                                stats && stats.sent_delta != null
                                    ? `${stats.sent_delta >= 0 ? '▲' : '▼'} 어제 대비 ${Math.abs(stats.sent_delta)}`
                                    : ' '
                            }
                            hintTone={stats && stats.sent_delta != null && stats.sent_delta >= 0 ? 'up' : 'muted'}
                        />
                        <StatTile label="반려" value={stats ? String(stats.rejected_today) : '—'} hint="오늘 재작성 요청" />
                        <StatTile label="평균 검토" value={fmtDuration(stats?.avg_review_seconds ?? null)} hint="건당 소요" />
                        <StatTile
                            label="초안 채택률"
                            value={adoption == null ? '—' : `${adoption}%`}
                            hint="무수정 승인 비율"
                        />
                    <div className="min-w-0 rounded-lg border border-line bg-white px-3 py-1.5">
                        <div className="flex items-center justify-between gap-2 text-[10px] text-muted">
                            <span className="font-bold whitespace-nowrap">최근 14일 전송량</span>
                            <span className="tabular-nums whitespace-nowrap">평균 {avgVol}</span>
                        </div>
                        {stats && (
                            <Sparkline data={stats.daily_volume.map((d) => d.sent)} className="w-full h-[22px] mt-1" />
                        )}
                    </div>
                </div>
                {statsError && (
                    <p className="shrink-0 text-[11px] text-muted">통계를 불러오지 못했습니다. 메일 목록은 별도로 표시됩니다.</p>
                )}

                <div className="min-h-0 md:flex-1 grid grid-cols-1 md:grid-cols-[minmax(260px,290px)_minmax(0,1fr)] xl:grid-cols-[300px_minmax(0,1fr)] gap-4 items-start md:items-stretch">
                {/* 좌: 목록 */}
                <section className="min-w-0 md:min-h-0 flex flex-col gap-3">

                    {/* 툴바 */}
                    <div className="flex items-center gap-2 flex-wrap">
                        {(
                            [
                                ['all', '전체', counts.all],
                                ['drafted', '초안', counts.drafted],
                                ['in_review', '검토중', counts.in_review],
                                ['failed', '실패', counts.failed],
                            ] as const
                        ).map(([key, label, n]) => (
                            <button
                                key={key}
                                onClick={() => setFilter(key)}
                                className={`h-8 px-3 rounded-lg text-[12px] font-semibold border transition-colors ${
                                    filter === key
                                        ? 'bg-ink text-white border-ink'
                                        : 'border-line text-muted hover:text-ink hover:bg-surface'
                                }`}
                            >
                                {label} <span className="tabular-nums opacity-70">{n}</span>
                            </button>
                        ))}
                        <input
                            value={query}
                            onChange={(e) => setQuery(e.target.value)}
                            placeholder="발신자·제목 검색"
                            className="h-8 w-full px-3 rounded-lg border border-line text-[13px] bg-white placeholder:text-muted/70 focus:outline-none focus:border-brand"
                        />
                    </div>

                    {/* 목록 */}
                    <div className="min-h-0 md:flex-1 border border-line rounded-xl bg-white overflow-hidden flex flex-col">
                        <div className="px-3.5 py-2.5 border-b border-divide text-[11px] font-bold text-muted uppercase tracking-wider">
                            검토할 메일 <span className="tabular-nums">{visible.length}</span>
                        </div>
                        <div className="min-h-0 md:flex-1 md:overflow-y-auto">
                            {loading && <p className="px-4 py-10 text-center text-muted text-[13px]">불러오는 중…</p>}
                            {!loading && visible.length === 0 && (
                                <p className="px-4 py-10 text-center text-muted text-[13px]">조건에 맞는 대기 메일이 없습니다.</p>
                            )}
                            {!loading && visible.map((r) => {
                            const sel = r.task_id === selectedTaskId;
                            return (
                                <button
                                    key={r.task_id}
                                    type="button"
                                    onClick={() => selectRow(r)}
                                    aria-current={sel ? 'true' : undefined}
                                    className={`w-full text-left px-3.5 py-2.5 border-b border-divide last:border-b-0 transition-colors focus-visible:outline-2 focus-visible:outline-brand focus-visible:outline-offset-[-2px] ${
                                        sel ? 'bg-brand-tint border-l-[3px] border-l-brand pl-[11px]' : 'hover:bg-surface'
                                    }`}
                                >
                                    <span className="block text-[13px] font-semibold leading-snug truncate">{r.subject}</span>
                                    <span className="mt-1.5 flex items-center gap-2 min-w-0 text-[11px] text-muted">
                                        <span className="truncate flex-1">{r.sender}</span>
                                        <time className="shrink-0 tabular-nums">{fmtTime(r.received_at)}</time>
                                    </span>
                                    <span className="mt-1.5 block"><StatusChip status={r.status} /></span>
                                </button>
                            );
                            })}
                        </div>
                    </div>

                    <p className="text-[11px] text-muted">
                        행 선택: 오른쪽에서 검토 · 키보드 <kbd className="font-mono">j</kbd> / <kbd className="font-mono">k</kbd>{' '}
                        이동 · 20초마다 자동 새로고침
                    </p>
                </section>

                {/* 우: 상세 검토 */}
                <aside className="min-w-0 md:min-h-0 border border-line rounded-xl bg-white overflow-hidden flex flex-col md:h-full shadow-[0_1px_2px_rgba(20,28,43,0.04)]">
                    {!selectedRow && (
                        <div className="p-10 text-center text-[13px] text-muted">
                            왼쪽에서 메일을 선택하면
                            <br />
                            여기서 원문·초안·근거를 검토합니다.
                        </div>
                    )}

                    {selectedRow && detailLoading && !detail && (
                        <div className="p-10 text-center text-[13px] text-muted">불러오는 중…</div>
                    )}

                    {selectedRow && !detailLoading && !detail && detailError && (
                        <div role="alert" className="p-10 text-center text-[13px] text-danger">
                            {detailError}
                        </div>
                    )}

                    {selectedRow && detail && (
                        <>
                            <div className="shrink-0 px-5 sm:px-6 py-3 border-b border-divide">
                                <h2 className="text-[17px] font-bold leading-snug">{detail.subject}</h2>
                                <p className="mt-1.5 text-[11px] text-muted font-mono break-all">
                                    {detail.sender} →{' '}
                                    {detail.recipient}
                                </p>
                                <div className="mt-2 flex items-center gap-2 flex-wrap">
                                    <StatusChip status={detail.status} />
                                    {detail.model && <span className="text-[11px] text-muted">{detail.model}</span>}
                                    <span className="text-[11px] text-muted tabular-nums">
                                        {fmtDateTime(detail.received_at)}
                                    </span>
                                </div>
                            </div>

                            <div className="flex-1 min-h-0 flex flex-col 2xl:grid 2xl:grid-cols-[minmax(0,1fr)_280px]">
                                {/* 검토의 중심: 실제 전송될 초안 */}
                                <section className="flex-1 min-w-0 min-h-0 flex flex-col gap-3 px-4 sm:px-6 py-4 bg-surface">
                                    <div className="shrink-0 flex items-center justify-between gap-3">
                                        <div>
                                            <h3 className="text-[17px] font-bold text-ink">
                                                AI 초안 {editedFlag && <span className="text-[11px] text-brand">· 수정됨</span>}
                                            </h3>
                                            <p className="text-[11px] text-muted mt-0.5">승인하면 이 답변이 전송됩니다</p>
                                        </div>
                                        <button
                                            onClick={() => {
                                                if (editing) {
                                                    setDraftText(detail.draft ?? '');
                                                    setDirty(false);
                                                }
                                                setEditing((v) => !v);
                                            }}
                                            className="shrink-0 h-8 px-3 rounded-lg border border-line bg-white text-[12px] font-semibold text-ink hover:border-brand hover:text-brand transition-colors"
                                        >
                                            {editing ? '취소' : '초안 수정'}
                                        </button>
                                    </div>

                                    <div
                                        aria-label="AI 초안"
                                        tabIndex={editing ? -1 : 0}
                                        className={`flex-1 min-h-0 max-h-[55vh] md:max-h-none rounded-xl border border-line bg-white shadow-[0_1px_3px_rgba(20,28,43,0.06)] focus-visible:outline-2 focus-visible:outline-brand ${editing ? 'overflow-hidden' : 'overflow-y-auto px-5 sm:px-8 py-6'}`}
                                    >
                                        {editing ? (
                                            <textarea
                                                value={draftText}
                                                onChange={(e) => {
                                                    setDraftText(e.target.value);
                                                    setDirty(true);
                                                }}
                                                rows={12}
                                                className="w-full h-full min-h-48 md:min-h-0 text-[15px] leading-[1.85] font-sans p-5 sm:p-8 bg-transparent focus:outline-none resize-none overflow-y-auto"
                                            />
                                        ) : detail.draft ? (
                                            <article className="mail-draft-markdown prose prose-slate mx-auto w-full max-w-[920px] text-ink">
                                                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                                                    {draftText || detail.draft}
                                                </ReactMarkdown>
                                            </article>
                                        ) : (
                                            <p className="text-[13px] text-muted">초안이 아직 없습니다.</p>
                                        )}
                                    </div>

                                    {editing && dirty && (
                                        <button
                                            onClick={() => void handleSaveDraft()}
                                            disabled={busy !== ''}
                                            className="shrink-0 self-start h-8 px-3 rounded-lg border border-line bg-white text-[12px] font-semibold hover:border-brand disabled:opacity-50"
                                        >
                                            {busy === 'save' ? '저장 중…' : '초안 저장 (전송 안 함)'}
                                        </button>
                                    )}
                                </section>

                                {/* 검토에 필요한 보조 정보는 초안과 분리해 고정한다. */}
                                <div className="shrink-0 min-h-0 flex flex-col sm:flex-row 2xl:flex-col md:h-40 2xl:h-full border-t 2xl:border-t-0 2xl:border-l border-divide bg-white">
                                    <section className="flex-1 min-w-0 min-h-0 overflow-y-auto px-4 py-3">
                                        <h3 className="text-[11px] font-bold text-muted mb-2">받은 원문</h3>
                                        <p className="whitespace-pre-line text-[12px] leading-relaxed text-ink/75">{detail.body}</p>
                                    </section>
                                    <section className="flex-1 min-w-0 min-h-0 overflow-y-auto px-4 py-3 border-t sm:border-t-0 sm:border-l 2xl:border-l-0 2xl:border-t border-divide">
                                        <h3 className="text-[11px] font-bold text-muted mb-2">근거 문서 {detail.sources.length}건</h3>
                                        {detail.sources.length === 0 ? (
                                            <p className="text-[12px] text-muted">연결된 근거 문서가 없습니다.</p>
                                        ) : (
                                            <ul className="flex flex-col gap-1.5">
                                                {detail.sources.map((s, i) => (
                                                    <li key={i} className="border border-line rounded-lg px-2.5 py-2">
                                                        <div className="text-[12px] font-semibold truncate">{s.source}</div>
                                                        <div className="text-[10.5px] text-muted font-mono">
                                                            {s.page != null ? `p.${s.page}` : ''} {s.text ? `· ${s.text}` : ''}
                                                        </div>
                                                    </li>
                                                ))}
                                            </ul>
                                        )}
                                    </section>
                                </div>
                            </div>

                            {/* 액션 바 */}
                            <div className="shrink-0 border-t border-divide p-3 bg-surface flex flex-col gap-2">
                                {rejecting ? (
                                    <>
                                        <input
                                            value={rejectReason}
                                            onChange={(e) => setRejectReason(e.target.value)}
                                            placeholder="반려 사유 (재작성 시 전달됩니다)"
                                            autoFocus
                                            className="h-9 px-3 rounded-lg border border-line text-[13px] bg-white focus:outline-none focus:border-brand"
                                        />
                                        <div className="flex gap-2">
                                            <button
                                                onClick={() => void handleReject()}
                                                disabled={!rejectReason.trim() || busy !== ''}
                                                className="flex-1 h-9 rounded-lg bg-danger text-white text-[13px] font-bold hover:brightness-105 disabled:opacity-50"
                                            >
                                                {busy === 'reject' ? '처리 중…' : '반려 확정'}
                                            </button>
                                            <button
                                                onClick={() => {
                                                    setRejecting(false);
                                                    setRejectReason('');
                                                }}
                                                className="h-9 px-4 rounded-lg border border-line text-[13px] font-semibold hover:bg-white"
                                            >
                                                취소
                                            </button>
                                        </div>
                                    </>
                                ) : detail.status === 'failed' ? (
                                    <div className="flex flex-col sm:flex-row-reverse gap-2">
                                        <button
                                            onClick={() => void handleRetry()}
                                            disabled={busy !== ''}
                                            className="h-10 flex-1 rounded-lg bg-brand text-white text-[13.5px] font-bold hover:bg-brand-hover disabled:opacity-50"
                                        >
                                            {busy === 'retry' ? '재전송 중…' : '재전송'}
                                        </button>
                                        <button
                                            onClick={() => setRejecting(true)}
                                            className="h-10 px-5 rounded-lg border border-danger/40 text-danger text-[13px] font-semibold hover:bg-danger-soft"
                                        >
                                            반려
                                        </button>
                                    </div>
                                ) : (
                                    <div className="flex flex-col sm:flex-row-reverse gap-2">
                                        <button
                                            onClick={() => void handleApprove()}
                                            disabled={busy !== '' || !detail.draft}
                                            className="h-10 flex-1 rounded-lg bg-brand text-white text-[13.5px] font-bold hover:bg-brand-hover disabled:opacity-50"
                                        >
                                            {busy === 'approve'
                                                ? '전송 중…'
                                                : editedFlag
                                                  ? '수정본 승인하고 전송'
                                                  : '승인하고 전송'}
                                        </button>
                                        <div className="flex gap-2">
                                            <button
                                                onClick={() => setRejecting(true)}
                                                className="h-10 px-5 rounded-lg border border-danger/40 text-danger text-[13px] font-semibold hover:bg-danger-soft"
                                            >
                                                반려
                                            </button>
                                            <button
                                                onClick={() => void handleClaimToggle()}
                                                disabled={busy !== ''}
                                                className="h-10 px-4 rounded-lg border border-line text-[13px] font-semibold hover:bg-white disabled:opacity-50"
                                            >
                                                {detail.assignee ? '담당 해제' : '내가 검토'}
                                            </button>
                                        </div>
                                    </div>
                                )}
                            </div>
                        </>
                    )}
                </aside>
                </div>
            </main>

            {toast && (
                <div
                    className={`fixed bottom-4 right-4 z-50 px-4 py-2.5 rounded-lg text-[13px] font-semibold shadow-lg border ${
                        toast.kind === 'ok'
                            ? 'bg-white border-line text-ink'
                            : 'bg-danger-surface border-danger/30 text-danger'
                    }`}
                >
                    {toast.msg}
                </div>
            )}
        </div>
    );
}

/* ------------------------------------------------------------------ */

function StatTile({
    label,
    value,
    hint,
    hintTone = 'muted',
    lead = false,
}: {
    label: string;
    value: string;
    hint: string;
    hintTone?: 'muted' | 'up';
    lead?: boolean;
}) {
    const toneCls = hintTone === 'up' ? 'text-brand' : 'text-muted';
    return (
        <div className={`min-w-0 rounded-lg bg-white px-3 py-1.5 border ${lead ? 'border-brand/40' : 'border-line'}`}>
            <div className="flex items-baseline justify-between gap-2">
                <span className="text-[10px] font-bold text-muted truncate">{label}</span>
                <span className="text-[17px] font-extrabold tabular-nums leading-none tracking-tight">{value}</span>
            </div>
            <div className={`mt-1 text-[10px] truncate ${toneCls}`}>{hint}</div>
        </div>
    );
}
