import { useCallback, useEffect, useMemo, useState } from 'react';
import { ApiError, mailApi } from './api';
import type { MailDetail, MailStats, MailStatus, MailSummary } from './types';
import { MOCK_ROWS, MOCK_STATS, mockDetail } from './mockData';
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

function ConfidenceBar({ value }: { value: number | null }) {
    if (value == null) return <span className="text-[12px] text-muted tabular-nums">—</span>;
    const p = Math.round(value * 100);
    const fill = p >= 80 ? 'bg-brand' : p >= 60 ? 'bg-ink/30' : 'bg-warn';
    return (
        <span className="inline-flex items-center gap-2">
            <span className="w-11 h-[5px] rounded-full bg-line overflow-hidden">
                <span className={`block h-full rounded-full ${fill}`} style={{ width: `${p}%` }} />
            </span>
            <span className="text-[12px] text-muted tabular-nums">{p}</span>
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
    const [offline, setOffline] = useState(false);
    const [loading, setLoading] = useState(true);

    const [filter, setFilter] = useState<Filter>('all');
    const [query, setQuery] = useState('');
    const [qDebounced, setQDebounced] = useState('');

    const [selectedRow, setSelectedRow] = useState<MailSummary | null>(null);
    const [detail, setDetail] = useState<MailDetail | null>(null);
    const [detailLoading, setDetailLoading] = useState(false);

    const [editing, setEditing] = useState(false);
    const [draftText, setDraftText] = useState('');
    const [dirty, setDirty] = useState(false);
    const [rejecting, setRejecting] = useState(false);
    const [rejectReason, setRejectReason] = useState('');
    const [busy, setBusy] = useState<Busy>('');

    const [toast, setToast] = useState<{ kind: 'ok' | 'err'; msg: string } | null>(null);
    const notify = useCallback((kind: 'ok' | 'err', msg: string) => setToast({ kind, msg }), []);

    const selectedUid = selectedRow?.uid ?? null;

    /* ---- 목록 + 통계 로드 (setState 는 모두 await 이후) ---- */
    const load = useCallback(
        async (quiet: boolean) => {
            const wantStatus = filter === 'all' ? FILTER_STATUSES : [filter];
            try {
                const [list, st] = await Promise.all([
                    mailApi.list({ status: wantStatus, q: qDebounced || undefined, order: '-received_at', limit: 100 }),
                    mailApi.stats(),
                ]);
                setRows(list.items);
                setStats(st);
                setOffline(false);
            } catch (e) {
                if (!quiet) {
                    setRows(MOCK_ROWS);
                    setStats(MOCK_STATS);
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

    useEffect(() => {
        // load()의 setState는 모두 await 이후에 실행된다 (동기 cascading render 아님).
        // eslint-disable-next-line react-hooks/set-state-in-effect
        void load(false);
    }, [load]);

    // 20초마다 조용히 새로고침 — 편집/작업 중이면 폴링을 멈춘다(effect cleanup).
    useEffect(() => {
        if (dirty || busy || rejecting) return;
        const id = window.setInterval(() => void load(true), 20_000);
        return () => window.clearInterval(id);
    }, [dirty, busy, rejecting, load]);

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
        let ignore = false;
        (async () => {
            try {
                const d = offline ? mockDetail(row) : await mailApi.detail(row.uid);
                if (ignore) return;
                setDetail(d);
                setDraftText(d.draft ?? '');
                setDirty(false);
            } catch (e) {
                if (ignore) return;
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
                (r.sender_name ?? '').toLowerCase().includes(q) ||
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
            const idx = visible.findIndex((r) => r.uid === selectedUid);
            const next =
                e.key === 'j'
                    ? Math.min(visible.length - 1, idx < 0 ? 0 : idx + 1)
                    : Math.max(0, idx < 0 ? 0 : idx - 1);
            selectRow(visible[next]);
        };
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
    }, [visible, selectedUid, selectRow]);

    /* ---- 액션 ---- */
    const dropRow = (uid: string) => {
        setRows((prev) => prev.filter((r) => r.uid !== uid));
        selectRow(null);
    };
    const patchRow = (uid: string, patch: Partial<MailSummary>) =>
        setRows((prev) => prev.map((r) => (r.uid === uid ? { ...r, ...patch } : r)));

    const editedFlag = !!detail && draftText.trim() !== (detail.draft ?? '').trim();

    const handleApprove = async () => {
        if (!detail) return;
        const uid = detail.uid;
        if (offline) {
            dropRow(uid);
            setStats((s) =>
                s ? { ...s, pending_review: Math.max(0, s.pending_review - 1), sent_today: s.sent_today + 1 } : s,
            );
            notify('ok', '전송 완료 (예시 데이터)');
            return;
        }
        setBusy('approve');
        try {
            const res = await mailApi.approve(uid, editedFlag ? { body: draftText, edited: true } : {});
            dropRow(uid);
            notify('ok', `전송 완료 → ${res.to}`);
            void load(true);
        } catch (e) {
            notify('err', e instanceof ApiError ? e.message : '전송 실패');
        } finally {
            setBusy('');
        }
    };

    const handleRetry = async () => {
        if (!detail) return;
        const uid = detail.uid;
        if (offline) {
            dropRow(uid);
            notify('ok', '재전송 완료 (예시 데이터)');
            return;
        }
        setBusy('retry');
        try {
            const res = await mailApi.retry(uid);
            dropRow(uid);
            notify('ok', `재전송 완료 → ${res.to}`);
            void load(true);
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
            await mailApi.saveDraft(detail.uid, draftText);
            setDetail({ ...detail, draft: draftText });
            setDirty(false);
            setEditing(false);
            patchRow(detail.uid, { has_draft: true });
            notify('ok', '초안을 저장했습니다');
        } catch (e) {
            notify('err', e instanceof ApiError ? e.message : '초안 저장 실패');
        } finally {
            setBusy('');
        }
    };

    const handleReject = async () => {
        if (!detail || !rejectReason.trim()) return;
        const uid = detail.uid;
        if (offline) {
            dropRow(uid);
            setStats((s) =>
                s ? { ...s, pending_review: Math.max(0, s.pending_review - 1), rejected_today: s.rejected_today + 1 } : s,
            );
            notify('ok', '반려 처리 (예시 데이터)');
            return;
        }
        setBusy('reject');
        try {
            await mailApi.reject(uid, { reason: rejectReason.trim(), requeue: true });
            dropRow(uid);
            notify('ok', '반려했습니다 — 재작성 대기로 이동');
            void load(true);
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
            patchRow(detail.uid, { assignee: next.assignee, status: next.status });
            return;
        }
        setBusy('claim');
        try {
            const next = mine ? await mailApi.release(detail.uid) : await mailApi.claim(detail.uid, '나');
            setDetail(next);
            patchRow(detail.uid, { assignee: next.assignee, status: next.status });
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
        <div className="min-h-screen bg-white text-ink font-sans antialiased">
            {/* 헤더 */}
            <header className="h-14 border-b border-divide px-6 flex items-center justify-between">
                <div className="flex items-baseline gap-3">
                    <span className="text-[15px] font-bold tracking-tight">메일 전송 승인</span>
                    <span className="text-[12px] text-muted">AI 회신 초안 검토 · 승인 후 전송</span>
                </div>
                <div className="flex items-center gap-3">
                    {offline && (
                        <span className="inline-flex items-center h-6 px-2.5 rounded-full bg-warn-soft text-warn text-[11px] font-bold">
                            백엔드 미연결 · 예시 데이터
                        </span>
                    )}
                    <button
                        onClick={() => void load(false)}
                        className="h-8 px-3 rounded-lg border border-line text-[12px] font-semibold hover:bg-surface transition-colors"
                    >
                        새로고침
                    </button>
                    <a href="#/" className="text-[12px] text-muted hover:text-ink transition-colors">
                        ← OCR 도구
                    </a>
                </div>
            </header>

            <main className="max-w-[1180px] mx-auto px-6 py-6 grid grid-cols-1 lg:grid-cols-[1fr_344px] gap-6 items-start">
                {/* 좌: 현황 + 목록 */}
                <section className="min-w-0 flex flex-col gap-4">
                    {/* 통계 타일 */}
                    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
                        <StatTile
                            label="승인 대기"
                            value={stats ? String(stats.pending_review) : '—'}
                            hint={
                                stats && stats.low_confidence > 0
                                    ? `저신뢰 ${stats.low_confidence}건 포함`
                                    : '검토 대기 중'
                            }
                            hintTone={stats && stats.low_confidence > 0 ? 'warn' : 'muted'}
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
                    </div>

                    {/* 스파크라인 */}
                    <div className="border border-line rounded-xl bg-white px-4 py-3">
                        <div className="flex items-baseline justify-between mb-1.5">
                            <span className="text-[12.5px] font-bold">최근 14일 전송량</span>
                            <span className="text-[11px] text-muted tabular-nums">
                                일 평균 {avgVol} · 오늘 {stats ? stats.sent_today : '—'}
                            </span>
                        </div>
                        {stats && (
                            <Sparkline data={stats.daily_volume.map((d) => d.sent)} className="w-full h-[54px]" />
                        )}
                    </div>

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
                        <div className="flex-1" />
                        <input
                            value={query}
                            onChange={(e) => setQuery(e.target.value)}
                            placeholder="발신자·제목 검색"
                            className="h-8 w-52 px-3 rounded-lg border border-line text-[13px] bg-white placeholder:text-muted/70 focus:outline-none focus:border-brand"
                        />
                    </div>

                    {/* 목록 */}
                    <div className="border border-line rounded-xl bg-white overflow-hidden">
                        <div className="overflow-x-auto">
                            <table className="w-full text-[13px]">
                                <thead>
                                    <tr className="text-left text-muted">
                                        {['발신자', '제목', '수신', '신뢰도', '담당', '상태'].map((h) => (
                                            <th
                                                key={h}
                                                className="px-3 py-2.5 text-[11px] font-bold uppercase tracking-wider border-b border-line whitespace-nowrap"
                                            >
                                                {h}
                                            </th>
                                        ))}
                                    </tr>
                                </thead>
                                <tbody>
                                    {loading && (
                                        <tr>
                                            <td colSpan={6} className="px-3 py-10 text-center text-muted text-[13px]">
                                                불러오는 중…
                                            </td>
                                        </tr>
                                    )}
                                    {!loading && visible.length === 0 && (
                                        <tr>
                                            <td colSpan={6} className="px-3 py-10 text-center text-muted text-[13px]">
                                                조건에 맞는 대기 메일이 없습니다.
                                            </td>
                                        </tr>
                                    )}
                                    {!loading &&
                                        visible.map((r) => {
                                            const low = r.confidence != null && r.confidence < 0.6;
                                            const sel = r.uid === selectedUid;
                                            return (
                                                <tr
                                                    key={r.uid}
                                                    onClick={() => selectRow(r)}
                                                    className={`border-b border-divide cursor-pointer transition-colors ${
                                                        sel ? 'bg-surface' : 'hover:bg-surface/60'
                                                    }`}
                                                >
                                                    <td
                                                        className="px-3 py-2.5 whitespace-nowrap"
                                                        style={low ? { boxShadow: 'inset 3px 0 0 #E19A00' } : undefined}
                                                    >
                                                        <div className="font-semibold">{r.sender_name ?? r.sender}</div>
                                                        <div className="text-[11px] text-muted">{r.sender_domain ?? ''}</div>
                                                    </td>
                                                    <td className="px-3 py-2.5 max-w-[300px]">
                                                        <span className="block truncate">{r.subject}</span>
                                                    </td>
                                                    <td className="px-3 py-2.5 text-muted tabular-nums whitespace-nowrap">
                                                        {fmtTime(r.received_at)}
                                                    </td>
                                                    <td className="px-3 py-2.5 whitespace-nowrap">
                                                        <ConfidenceBar value={r.confidence} />
                                                    </td>
                                                    <td className="px-3 py-2.5 text-muted whitespace-nowrap">
                                                        {r.assignee ?? '—'}
                                                    </td>
                                                    <td className="px-3 py-2.5 whitespace-nowrap">
                                                        <StatusChip status={r.status} />
                                                    </td>
                                                </tr>
                                            );
                                        })}
                                </tbody>
                            </table>
                        </div>
                    </div>

                    <p className="text-[11px] text-muted">
                        행 선택: 오른쪽에서 검토 · 키보드 <kbd className="font-mono">j</kbd> / <kbd className="font-mono">k</kbd>{' '}
                        이동 · 20초마다 자동 새로고침
                    </p>
                </section>

                {/* 우: 상세 검토 */}
                <aside className="lg:sticky lg:top-6 border border-line rounded-xl bg-white overflow-hidden flex flex-col lg:max-h-[calc(100vh-3rem)] shadow-[0_1px_2px_rgba(20,28,43,0.04)]">
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

                    {selectedRow && detail && (
                        <>
                            <div className="px-4 pt-4 pb-3 border-b border-divide">
                                <h2 className="text-[14px] font-bold leading-snug">{detail.subject}</h2>
                                <p className="mt-1.5 text-[11px] text-muted font-mono break-all">
                                    {detail.sender_name ? `${detail.sender_name} <${detail.sender}>` : detail.sender} →{' '}
                                    {detail.recipient}
                                </p>
                                <div className="mt-2 flex items-center gap-2 flex-wrap">
                                    <StatusChip status={detail.status} />
                                    <ConfidenceBar value={detail.confidence} />
                                    {detail.model && <span className="text-[11px] text-muted">{detail.model}</span>}
                                    <span className="text-[11px] text-muted tabular-nums">
                                        {fmtDateTime(detail.received_at)}
                                    </span>
                                </div>
                            </div>

                            <div className="flex-1 overflow-y-auto divide-y divide-divide">
                                <section className="px-4 py-3">
                                    <p className="text-[11px] font-bold uppercase tracking-wider text-muted mb-2">받은 원문</p>
                                    <p className="whitespace-pre-line text-[12.5px] text-muted border-l-2 border-line pl-3 max-h-40 overflow-y-auto">
                                        {detail.body}
                                    </p>
                                </section>

                                <section className="px-4 py-3">
                                    <div className="flex items-center justify-between mb-2">
                                        <p className="text-[11px] font-bold uppercase tracking-wider text-muted">
                                            AI 초안 {editedFlag && <span className="text-brand">· 수정됨</span>}
                                        </p>
                                        <button
                                            onClick={() => {
                                                if (editing) {
                                                    setDraftText(detail.draft ?? '');
                                                    setDirty(false);
                                                }
                                                setEditing((v) => !v);
                                            }}
                                            className="text-[11px] font-semibold text-muted hover:text-ink"
                                        >
                                            {editing ? '취소' : '수정'}
                                        </button>
                                    </div>

                                    {editing ? (
                                        <textarea
                                            value={draftText}
                                            onChange={(e) => {
                                                setDraftText(e.target.value);
                                                setDirty(true);
                                            }}
                                            rows={12}
                                            className="w-full text-[12.5px] leading-relaxed font-sans p-2.5 rounded-lg border border-line focus:outline-none focus:border-brand resize-y"
                                        />
                                    ) : detail.draft ? (
                                        <p className="whitespace-pre-line text-[12.5px] leading-relaxed">
                                            {draftText || detail.draft}
                                        </p>
                                    ) : (
                                        <p className="text-[12.5px] text-muted">초안이 아직 없습니다.</p>
                                    )}

                                    {editing && dirty && (
                                        <button
                                            onClick={() => void handleSaveDraft()}
                                            disabled={busy !== ''}
                                            className="mt-2 h-8 px-3 rounded-lg border border-line text-[12px] font-semibold hover:bg-surface disabled:opacity-50"
                                        >
                                            {busy === 'save' ? '저장 중…' : '초안 저장 (전송 안 함)'}
                                        </button>
                                    )}
                                </section>

                                <section className="px-4 py-3">
                                    <p className="text-[11px] font-bold uppercase tracking-wider text-muted mb-2">
                                        근거 문서 {detail.sources.length}건
                                    </p>
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

                            {/* 액션 바 */}
                            <div className="border-t border-divide p-3 bg-surface flex flex-col gap-2">
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
                                    <>
                                        <button
                                            onClick={() => void handleRetry()}
                                            disabled={busy !== ''}
                                            className="h-10 rounded-lg bg-brand text-white text-[13.5px] font-bold hover:bg-brand-hover disabled:opacity-50"
                                        >
                                            {busy === 'retry' ? '재전송 중…' : '재전송'}
                                        </button>
                                        <button
                                            onClick={() => setRejecting(true)}
                                            className="h-9 rounded-lg border border-danger/40 text-danger text-[13px] font-semibold hover:bg-danger-soft"
                                        >
                                            반려
                                        </button>
                                    </>
                                ) : (
                                    <>
                                        <button
                                            onClick={() => void handleApprove()}
                                            disabled={busy !== '' || !detail.draft}
                                            className="h-10 rounded-lg bg-brand text-white text-[13.5px] font-bold hover:bg-brand-hover disabled:opacity-50"
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
                                                className="flex-1 h-9 rounded-lg border border-danger/40 text-danger text-[13px] font-semibold hover:bg-danger-soft"
                                            >
                                                반려
                                            </button>
                                            <button
                                                onClick={() => void handleClaimToggle()}
                                                disabled={busy !== ''}
                                                className="h-9 px-3 rounded-lg border border-line text-[13px] font-semibold hover:bg-white disabled:opacity-50"
                                            >
                                                {detail.assignee ? '담당 해제' : '내가 검토'}
                                            </button>
                                        </div>
                                    </>
                                )}
                            </div>
                        </>
                    )}
                </aside>
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
    hintTone?: 'muted' | 'up' | 'warn';
    lead?: boolean;
}) {
    const toneCls = hintTone === 'up' ? 'text-brand' : hintTone === 'warn' ? 'text-warn' : 'text-muted';
    return (
        <div className={`rounded-xl bg-white px-3.5 py-3 border ${lead ? 'border-brand/40' : 'border-line'}`}>
            <div className="text-[10.5px] font-bold uppercase tracking-wider text-muted">{label}</div>
            <div className="mt-1.5 text-[21px] font-extrabold tabular-nums leading-none tracking-tight">{value}</div>
            <div className={`mt-1.5 text-[11px] font-mono ${toneCls}`}>{hint}</div>
        </div>
    );
}
