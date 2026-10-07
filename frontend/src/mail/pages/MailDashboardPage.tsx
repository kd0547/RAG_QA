import { useMemo, type ReactNode } from 'react';
import { linkProps } from '../../lib/router';
import {
    ALL_STATUSES,
    fmtAgo,
    fmtDuration,
    fmtLongDate,
    MAIL_PATHS,
    pct,
    reviewPath,
    STATUS_META,
} from '../format';
import type { MailStats, MailStatus } from '../types';
import { StatusChip } from '../ui';
import type { MailList } from '../useMailList';
import { useMailList } from '../useMailList';
import { VolumeChart } from '../VolumeChart';

/** 처리 흐름 순서대로 보여줄 상태 */
const PIPELINE: MailStatus[] = ['pending', 'drafted', 'in_review', 'approved', 'sent', 'rejected', 'failed'];

/**
 * 대시보드: 한눈에 보는 현황. 여기서는 아무것도 결정하지 않고, 해야 할 일을 메일 검토 페이지로 안내한다.
 */
export function MailDashboardPage({
    queue,
    stats,
    statsError,
}: {
    queue: MailList;
    stats: MailStats | null;
    statsError: boolean;
}) {
    // 상태별 분포는 전체 메일 기준으로 센다.
    const all = useMailList(ALL_STATUSES);

    const waiting = useMemo(() => queue.rows.filter((r) => r.status === 'drafted' || r.status === 'in_review'), [queue.rows]);
    const failed = useMemo(() => queue.rows.filter((r) => r.status === 'failed'), [queue.rows]);
    const oldestWaiting = useMemo(
        () => waiting.reduce<string | null>((o, r) => (!o || r.received_at < o ? r.received_at : o), null),
        [waiting],
    );

    // 실패 건을 먼저, 그다음 오래 기다린 순서로
    const todo = useMemo(
        () =>
            [...queue.rows]
                .sort((a, b) =>
                    a.status === 'failed' && b.status !== 'failed'
                        ? -1
                        : b.status === 'failed' && a.status !== 'failed'
                          ? 1
                          : a.received_at.localeCompare(b.received_at),
                )
                .slice(0, 6),
        [queue.rows],
    );

    const byStatus = useMemo(() => {
        const c = Object.fromEntries(PIPELINE.map((s) => [s, 0])) as Record<MailStatus, number>;
        for (const r of all.rows) c[r.status] = (c[r.status] ?? 0) + 1;
        return c;
    }, [all.rows]);
    const statusMax = Math.max(1, ...Object.values(byStatus));

    const adoption = pct(stats?.draft_adoption_rate);
    const volume = stats?.daily_volume ?? [];
    const volTotal = volume.reduce((a, b) => a + b.sent, 0);
    const volAvg = volume.length ? (volTotal / volume.length).toFixed(1) : '—';
    const noStats = statsError ? '통계 API 미연결' : '불러오는 중…';

    return (
        <div className="flex-1 min-h-0 overflow-y-auto">
            <div className="mx-auto w-full max-w-[1120px] px-5 sm:px-10 py-8 sm:py-10">
                <p className="text-[12px] text-muted">{fmtLongDate(new Date())}</p>
                <h1 className="mt-1 text-[26px] font-bold tracking-tight">오늘의 메일 현황</h1>

                {/* 핵심 지표 */}
                <dl className="mt-8 grid grid-cols-2 lg:grid-cols-4 gap-y-6 border-y border-divide py-6">
                    <Kpi
                        label="검토 대기"
                        value={queue.loading ? '—' : String(waiting.length)}
                        tone="brand"
                        hint={oldestWaiting ? `가장 오래된 건 ${fmtAgo(oldestWaiting)} 도착` : '대기 중인 메일 없음'}
                        action={
                            waiting.length > 0 && (
                                <a {...linkProps(MAIL_PATHS.review)} className="font-semibold text-brand-hover hover:underline">
                                    검토 시작 →
                                </a>
                            )
                        }
                    />
                    <Kpi
                        label="오늘 전송"
                        value={stats ? String(stats.sent_today) : '—'}
                        hint={
                            stats
                                ? stats.sent_delta != null
                                    ? `어제보다 ${stats.sent_delta >= 0 ? '+' : ''}${stats.sent_delta}`
                                    : ' '
                                : noStats
                        }
                    />
                    <Kpi label="오늘 반려" value={stats ? String(stats.rejected_today) : '—'} hint={stats ? '재작성 요청' : noStats} />
                    <Kpi
                        label="전송 실패"
                        value={queue.loading ? '—' : String(failed.length)}
                        tone={failed.length > 0 ? 'danger' : undefined}
                        hint={failed.length > 0 ? '재전송이 필요합니다' : '실패한 메일 없음'}
                        action={
                            failed.length > 0 && (
                                <a {...linkProps(reviewPath(failed[0].task_id))} className="font-semibold text-danger hover:underline">
                                    확인 →
                                </a>
                            )
                        }
                    />
                </dl>

                <div className="mt-10 grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_300px] gap-x-14 gap-y-10">
                    {/* 전송 추이 */}
                    <section>
                        <SectionTitle
                            title="최근 14일 전송량"
                            aside={stats ? `일 평균 ${volAvg}건 · 합계 ${volTotal}건` : undefined}
                        />
                        <div className="mt-5">
                            {volume.length > 1 ? (
                                <VolumeChart data={volume} />
                            ) : (
                                <p className="py-12 text-center text-[13px] text-muted">{noStats}</p>
                            )}
                        </div>
                    </section>

                    {/* 검토 품질 + 상태 분포 */}
                    <div className="flex flex-col gap-10">
                        <section>
                            <SectionTitle title="검토 품질" />
                            <dl className="mt-4 flex flex-col gap-4">
                                <div className="flex items-baseline justify-between">
                                    <dt className="text-[13px] text-ink/70">평균 검토 시간</dt>
                                    <dd className="text-[18px] font-bold tabular-nums">{fmtDuration(stats?.avg_review_seconds ?? null)}</dd>
                                </div>
                                <div>
                                    <div className="flex items-baseline justify-between">
                                        <dt className="text-[13px] text-ink/70">초안 채택률</dt>
                                        <dd className="text-[18px] font-bold tabular-nums">{adoption == null ? '—' : `${adoption}%`}</dd>
                                    </div>
                                    <div className="mt-2 h-1.5 rounded-full bg-track overflow-hidden">
                                        <div className="h-full rounded-full bg-brand" style={{ width: `${adoption ?? 0}%` }} />
                                    </div>
                                    <p className="mt-1.5 text-[11px] text-muted">수정 없이 그대로 승인된 초안의 비율</p>
                                </div>
                            </dl>
                        </section>

                        <section>
                            <SectionTitle
                                title="상태별 메일"
                                aside={all.loading ? undefined : `전체 ${all.rows.length}건`}
                                link={{ path: MAIL_PATHS.inbox, label: '전체 메일 보기' }}
                            />
                            <ul className="mt-4 flex flex-col gap-2.5">
                                {PIPELINE.map((s) => (
                                    <li key={s} className="grid grid-cols-[84px_minmax(0,1fr)_28px] items-center gap-3 text-[12px]">
                                        <span className="text-ink/70 truncate">{STATUS_META[s].label}</span>
                                        <span className="h-1.5 rounded-full bg-track overflow-hidden">
                                            <span
                                                className="block h-full rounded-full bg-brand/60"
                                                style={{ width: `${(byStatus[s] / statusMax) * 100}%` }}
                                            />
                                        </span>
                                        <span className="text-right font-semibold tabular-nums">{byStatus[s]}</span>
                                    </li>
                                ))}
                            </ul>
                        </section>
                    </div>
                </div>

                {/* 해야 할 일 */}
                <section className="mt-12">
                    <SectionTitle
                        title="검토가 필요한 메일"
                        aside={queue.loading ? undefined : `${queue.rows.length}건`}
                        link={{ path: MAIL_PATHS.review, label: '모두 검토하기' }}
                    />
                    {queue.loading ? (
                        <p className="py-8 text-[13px] text-muted">불러오는 중…</p>
                    ) : todo.length === 0 ? (
                        <p className="py-8 text-[13px] text-muted">검토할 메일이 없습니다. 모두 처리했어요.</p>
                    ) : (
                        <ul className="mt-2 divide-y divide-divide">
                            {todo.map((r) => (
                                <li key={r.task_id}>
                                    <a
                                        {...linkProps(reviewPath(r.task_id))}
                                        className="-mx-3 px-3 py-3 rounded-xl flex items-center gap-4 hover:bg-surface transition-colors"
                                    >
                                        <span className="w-[76px] shrink-0">
                                            <StatusChip status={r.status} />
                                        </span>
                                        <span className="min-w-0 flex-1">
                                            <span className="block text-[13.5px] font-semibold truncate">{r.subject}</span>
                                            <span className="block text-[11px] text-muted truncate">{r.sender}</span>
                                        </span>
                                        <span className="shrink-0 text-[12px] text-muted tabular-nums">{fmtAgo(r.received_at)}</span>
                                        <span className="shrink-0 text-muted" aria-hidden>
                                            →
                                        </span>
                                    </a>
                                </li>
                            ))}
                        </ul>
                    )}
                </section>
            </div>
        </div>
    );
}

function Kpi({
    label,
    value,
    hint,
    tone,
    action,
}: {
    label: string;
    value: string;
    hint: string;
    tone?: 'brand' | 'danger';
    action?: ReactNode;
}) {
    const valueCls = tone === 'brand' ? 'text-brand' : tone === 'danger' ? 'text-danger' : 'text-ink';
    return (
        <div className="min-w-0 pr-4 lg:not-first:border-l lg:not-first:border-divide lg:not-first:pl-6">
            <dt className="text-[12px] font-semibold text-muted">{label}</dt>
            <dd className={`mt-1 text-[34px] font-extrabold leading-none tracking-tight tabular-nums ${valueCls}`}>{value}</dd>
            <dd className="mt-2 text-[12px] text-muted flex items-center gap-2 flex-wrap">
                <span className="truncate">{hint}</span>
                {action}
            </dd>
        </div>
    );
}

function SectionTitle({
    title,
    aside,
    link,
}: {
    title: string;
    aside?: string;
    link?: { path: string; label: string };
}) {
    return (
        <div className="flex items-baseline gap-3">
            <h2 className="text-[15px] font-bold">{title}</h2>
            {aside && <span className="text-[12px] text-muted tabular-nums">{aside}</span>}
            {link && (
                <a {...linkProps(link.path)} className="ml-auto text-[12px] font-semibold text-brand-hover hover:underline whitespace-nowrap">
                    {link.label} →
                </a>
            )}
        </div>
    );
}
