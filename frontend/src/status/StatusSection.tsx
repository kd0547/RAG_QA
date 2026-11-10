import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { AppHeader } from '../components/AppHeader';
import { ApiError } from '../lib/http';
import { monitorApi, type AccessLog, type AccessSummary, type GpuSample, type SystemStatus } from './api';
import { RequestBars, UsageChart, type UsagePoint } from './charts';

/**
 * 서버 상태 (/status).
 * - 위: CPU·메모리·GPU 현재 값과 최근 30분 추이 (5초마다 갱신, 백엔드 메모리에만 있음)
 * - 아래: DB(access_log)에 쌓인 HTTP 접속 기록 요약과 목록
 */

const SYSTEM_POLL_MS = 5_000;
const ACCESS_POLL_MS = 30_000;
const PAGE_SIZE = 50;
const WINDOW_MS = 30 * 60 * 1000;

const PERIODS = [
    { hours: 24, label: '24시간' },
    { hours: 24 * 7, label: '7일' },
    { hours: 24 * 30, label: '30일' },
];

const STATUS_FILTERS = [
    { value: '', label: '모든 상태' },
    { value: '2xx', label: '2xx 성공' },
    { value: '3xx', label: '3xx 이동' },
    { value: '4xx', label: '4xx 요청 오류' },
    { value: '5xx', label: '5xx 서버 오류' },
    { value: 'error', label: '오류 전체 (4xx·5xx)' },
];
const METHODS = ['', 'GET', 'POST', 'PUT', 'PATCH', 'DELETE'];

const dateTimeFmt = new Intl.DateTimeFormat('ko-KR', {
    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
});
const clockFmt = new Intl.DateTimeFormat('ko-KR', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });

function fmtBytes(n: number) {
    const gb = n / 1024 ** 3;
    return gb >= 100 ? `${gb.toFixed(0)} GB` : `${gb.toFixed(1)} GB`;
}
function fmtMb(mb: number | null) {
    if (mb == null) return '—';
    return mb >= 1024 ? `${(mb / 1024).toFixed(1)} GB` : `${mb.toFixed(0)} MB`;
}
function fmtSince(iso: string) {
    const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
    const d = Math.floor(s / 86400);
    const h = Math.floor((s % 86400) / 3600);
    const m = Math.floor((s % 3600) / 60);
    if (d) return `${d}일 ${h}시간`;
    if (h) return `${h}시간 ${m}분`;
    return `${m}분`;
}
function fmtAgo(iso: string) {
    const s = (Date.now() - new Date(iso).getTime()) / 1000;
    if (s < 60) return '방금';
    if (s < 3600) return `${Math.floor(s / 60)}분 전`;
    if (s < 86400) return `${Math.floor(s / 3600)}시간 전`;
    return `${Math.floor(s / 86400)}일 전`;
}
function fmtMs(ms: number | null) {
    if (ms == null) return '—';
    return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${Math.round(ms)}ms`;
}
function errorText(e: unknown) {
    if (e instanceof ApiError && (e.status === 404 || e.status === 405)) {
        return '서버에 상태 API가 없습니다. 백엔드를 최신 코드로 재시작해 주세요.';
    }
    return e instanceof Error ? e.message : '불러오지 못했습니다.';
}

/** 탭이 보일 때만 주기적으로 부른다. immediate면 처음 한 번은 바로 부른다. */
function usePolling(fn: () => void, ms: number, immediate = true) {
    const ref = useRef(fn);
    useEffect(() => {
        ref.current = fn;
    }, [fn]);
    useEffect(() => {
        if (immediate) ref.current();
        const id = window.setInterval(() => {
            if (document.visibilityState === 'visible') ref.current();
        }, ms);
        const onVisible = () => document.visibilityState === 'visible' && ref.current();
        document.addEventListener('visibilitychange', onVisible);
        return () => {
            window.clearInterval(id);
            document.removeEventListener('visibilitychange', onVisible);
        };
    }, [ms, immediate]);
}

export function StatusSection() {
    const [system, setSystem] = useState<SystemStatus | null>(null);
    const [systemError, setSystemError] = useState('');
    const [updatedAt, setUpdatedAt] = useState<Date | null>(null);

    const loadSystem = useCallback(async () => {
        try {
            setSystem(await monitorApi.system());
            setSystemError('');
            setUpdatedAt(new Date());
        } catch (e) {
            setSystemError(errorText(e));
        }
    }, []);
    usePolling(loadSystem, SYSTEM_POLL_MS);

    return (
        <div className="min-h-screen md:h-dvh md:overflow-hidden bg-white text-ink font-sans antialiased flex flex-col">
            <AppHeader
                current="status"
                aside={
                    <span className="hidden sm:inline-flex items-center gap-1.5 text-[11.5px] text-muted tabular-nums">
                        <span className={`w-1.5 h-1.5 rounded-full ${systemError ? 'bg-danger' : 'bg-brand animate-pulse'}`} aria-hidden />
                        {systemError ? '연결 끊김' : updatedAt ? `${clockFmt.format(updatedAt)} 갱신 · 5초마다` : '연결 중…'}
                    </span>
                }
            />
            <div className="flex-1 min-h-0 overflow-y-auto">
                <div className="mx-auto w-full max-w-[1120px] px-4 sm:px-10 py-8 sm:py-10">
                    <h1 className="text-[26px] font-bold tracking-tight">서버 상태</h1>
                    {system && (
                        <p className="mt-1 text-[12.5px] text-muted flex flex-wrap gap-x-2.5 gap-y-1">
                            <span className="font-semibold text-ink/70">{system.host.hostname}</span>
                            <span>{system.host.os}</span>
                            {system.host.in_container && <span>Docker 컨테이너에서 측정</span>}
                            <span>앱 가동 {fmtSince(system.host.app_started_at)}</span>
                            <span>서버 부팅 {fmtSince(system.host.boot_time)} 전</span>
                        </p>
                    )}
                    {systemError && <Banner>{systemError}</Banner>}

                    <ResourceCards system={system} />

                    <AccessSection />
                </div>
            </div>
        </div>
    );
}

/* ---------------- 자원 사용량 ---------------- */

function ResourceCards({ system }: { system: SystemStatus | null }) {
    const series = useMemo(() => {
        const h = system?.history ?? [];
        const pt = (ts: string, v: number | null): UsagePoint => ({ t: new Date(ts).getTime(), v });
        const gpuCount = system?.current.gpus.length ?? 0;
        return {
            cpu: h.map((p) => pt(p.ts, p.cpu)),
            mem: h.map((p) => pt(p.ts, p.mem)),
            gpus: Array.from({ length: gpuCount }, (_, i) => h.map((p) => pt(p.ts, p.gpus[i]?.util ?? null))),
        };
    }, [system]);

    if (!system) {
        return (
            <div className="mt-8 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {['CPU', '메모리', 'GPU'].map((t) => (
                    <div key={t} className="h-[220px] rounded-2xl border border-divide bg-surface animate-pulse" />
                ))}
            </div>
        );
    }
    const c = system.current;
    const cores = system.host.cpu_physical
        ? `${system.host.cpu_physical}코어 / ${system.host.cpu_count}스레드`
        : `${system.host.cpu_count ?? '—'}스레드`;

    return (
        <div className="mt-8 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            <ResourceCard
                title="CPU"
                percent={c.cpu_percent}
                details={[
                    ['구성', cores],
                    ['부하 평균 (1·5·15분)', c.load_avg ? c.load_avg.map((v) => v.toFixed(2)).join(' · ') : '—'],
                ]}
                chart={<UsageChart points={series.cpu} windowMs={WINDOW_MS} label="CPU 사용률" />}
            />
            <ResourceCard
                title="메모리"
                percent={c.mem_percent}
                details={[
                    ['사용 / 전체', `${fmtBytes(c.mem_used)} / ${fmtBytes(c.mem_total)}`],
                    ['여유', fmtBytes(c.mem_total - c.mem_used)],
                ]}
                chart={<UsageChart points={series.mem} windowMs={WINDOW_MS} label="메모리 사용률" />}
            />
            {c.gpus.length === 0 ? (
                <div className="rounded-2xl border border-divide p-5 flex flex-col">
                    <h2 className="text-[13px] font-bold text-muted">GPU</h2>
                    <p className="mt-auto mb-auto text-[13px] text-ink/70 leading-relaxed">
                        GPU 정보를 읽지 못했습니다.
                        <br />
                        <span className="text-[12px] text-muted">{system.gpu_error ?? 'NVIDIA GPU가 없습니다.'}</span>
                    </p>
                </div>
            ) : (
                c.gpus.map((g, i) => <GpuCard key={g.index} gpu={g} points={series.gpus[i] ?? []} />)
            )}
        </div>
    );
}

function GpuCard({ gpu, points }: { gpu: GpuSample; points: UsagePoint[] }) {
    return (
        <ResourceCard
            title={`GPU ${gpu.index}`}
            subtitle={gpu.name.replace(/^NVIDIA\s+/, '')}
            percent={gpu.util_percent}
            meter={{ label: 'VRAM', percent: gpu.mem_percent, text: `${fmtMb(gpu.mem_used_mb)} / ${fmtMb(gpu.mem_total_mb)}` }}
            details={[
                ['온도', gpu.temperature_c == null ? '—' : `${gpu.temperature_c.toFixed(0)}°C`],
                [
                    '전력',
                    gpu.power_w == null
                        ? '—'
                        : `${gpu.power_w.toFixed(0)} W${gpu.power_limit_w ? ` / ${gpu.power_limit_w.toFixed(0)} W` : ''}`,
                ],
            ]}
            chart={<UsageChart points={points} windowMs={WINDOW_MS} label={`GPU ${gpu.index} 사용률`} />}
        />
    );
}

function LoadChip({ percent }: { percent: number | null }) {
    if (percent == null || percent < 80) return null;
    const high = percent >= 95;
    return (
        <span
            className={`inline-flex items-center gap-1 h-5 px-1.5 rounded-md text-[10.5px] font-bold ${
                high ? 'bg-danger-soft text-danger' : 'bg-warn-soft text-warn'
            }`}
        >
            <span aria-hidden>▲</span>
            {high ? '포화' : '높음'}
        </span>
    );
}

function ResourceCard({
    title,
    subtitle,
    percent,
    meter,
    details,
    chart,
}: {
    title: string;
    subtitle?: string;
    percent: number | null;
    meter?: { label: string; percent: number | null; text: string };
    details: [string, string][];
    chart: ReactNode;
}) {
    return (
        <section className="rounded-2xl border border-divide p-5 flex flex-col min-w-0">
            <div className="flex items-center gap-2 min-w-0">
                <h2 className="text-[13px] font-bold text-muted shrink-0">{title}</h2>
                {subtitle && <span className="text-[12px] text-ink/70 truncate">{subtitle}</span>}
                <span className="ml-auto">
                    <LoadChip percent={percent} />
                </span>
            </div>
            <p className="mt-2 text-[34px] font-extrabold leading-none tracking-tight tabular-nums">
                {percent == null ? '—' : percent.toFixed(0)}
                <span className="ml-0.5 text-[18px] font-bold text-muted">%</span>
            </p>
            {meter && (
                <div className="mt-3">
                    <div className="flex items-baseline justify-between text-[11.5px]">
                        <span className="text-ink/70">{meter.label}</span>
                        <span className="tabular-nums font-semibold">
                            {meter.text}
                            {meter.percent != null && <span className="ml-1.5 text-muted font-normal">{meter.percent.toFixed(0)}%</span>}
                        </span>
                    </div>
                    <div className="mt-1.5 h-1.5 rounded-full bg-track overflow-hidden">
                        <div className="h-full rounded-full bg-brand" style={{ width: `${meter.percent ?? 0}%` }} />
                    </div>
                </div>
            )}
            <dl className="mt-3 flex flex-col gap-1">
                {details.map(([k, v]) => (
                    <div key={k} className="flex items-baseline justify-between gap-3 text-[11.5px]">
                        <dt className="text-ink/70 truncate">{k}</dt>
                        <dd className="tabular-nums font-semibold whitespace-nowrap">{v}</dd>
                    </div>
                ))}
            </dl>
            <div className="mt-auto pt-6">{chart}</div>
        </section>
    );
}

/* ---------------- 접속 기록 ---------------- */

function AccessSection() {
    const [hours, setHours] = useState(24);
    const [summary, setSummary] = useState<AccessSummary | null>(null);
    const [summaryError, setSummaryError] = useState('');

    const [q, setQ] = useState('');
    const [query, setQuery] = useState(''); // 입력이 멈춘 뒤 반영되는 검색어
    const [status, setStatus] = useState('');
    const [method, setMethod] = useState('');
    const [ip, setIp] = useState('');
    const [offset, setOffset] = useState(0);
    const [logs, setLogs] = useState<{ total: number; items: AccessLog[] } | null>(null);
    const [logsError, setLogsError] = useState('');
    const listRef = useRef<HTMLElement>(null);

    useEffect(() => {
        const id = window.setTimeout(() => {
            setQuery(q.trim());
            setOffset(0);
        }, 300);
        return () => window.clearTimeout(id);
    }, [q]);

    const loadSummary = useCallback(async () => {
        try {
            setSummary(await monitorApi.accessSummary(hours));
            setSummaryError('');
        } catch (e) {
            setSummaryError(errorText(e));
        }
    }, [hours]);

    const loadLogs = useCallback(async () => {
        try {
            setLogs(await monitorApi.accessLogs({ q: query, status, method, ip, limit: PAGE_SIZE, offset }));
            setLogsError('');
        } catch (e) {
            setLogsError(errorText(e));
        }
    }, [query, status, method, ip, offset]);

    // 기간·필터가 바뀌면 다시 불러온다
    useEffect(() => {
        // eslint-disable-next-line react-hooks/set-state-in-effect
        void loadSummary();
    }, [loadSummary]);
    useEffect(() => {
        // eslint-disable-next-line react-hooks/set-state-in-effect
        void loadLogs();
    }, [loadLogs]);

    // 첫 페이지를 보고 있을 때만 새 기록을 자동으로 받아온다 (뒤 페이지는 보는 중에 밀리지 않게)
    const poll = useCallback(() => {
        void loadSummary();
        if (offset === 0) void loadLogs();
    }, [loadSummary, loadLogs, offset]);
    usePolling(poll, ACCESS_POLL_MS, false); // 첫 조회는 위 useEffect가 한다

    const filterByIp = (value: string) => {
        setIp(value);
        setOffset(0);
        listRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    };

    const s = summary;
    const errRate = s && s.total ? ((s.server_errors / s.total) * 100).toFixed(1) : null;

    return (
        <>
            <div className="mt-14 flex flex-wrap items-center gap-3">
                <h2 className="text-[18px] font-bold">접속 기록</h2>
                <span className="text-[12px] text-muted">페이지·API 요청 (정적 파일과 이 화면의 자동 갱신은 제외)</span>
                <div role="group" aria-label="기간" className="ml-auto flex p-0.5 rounded-lg bg-chip">
                    {PERIODS.map((p) => (
                        <button
                            key={p.hours}
                            type="button"
                            aria-pressed={hours === p.hours}
                            onClick={() => setHours(p.hours)}
                            className={`h-7 px-3 rounded-md text-[12px] font-semibold transition-colors ${
                                hours === p.hours ? 'bg-white text-ink shadow-[0_1px_2px_rgba(20,28,43,0.10)]' : 'text-muted hover:text-ink'
                            }`}
                        >
                            {p.label}
                        </button>
                    ))}
                </div>
            </div>
            {summaryError && <Banner>{summaryError}</Banner>}

            <dl className="mt-5 grid grid-cols-2 lg:grid-cols-4 gap-y-6 border-y border-divide py-6">
                <Kpi label="요청" value={s ? s.total.toLocaleString() : '—'} hint={s ? `최근 ${PERIODS.find((p) => p.hours === hours)?.label}` : ' '} />
                <Kpi label="접속 IP" value={s ? s.unique_ips.toLocaleString() : '—'} hint="서로 다른 접속 주소" />
                <Kpi
                    label="서버 오류 (5xx)"
                    value={s ? s.server_errors.toLocaleString() : '—'}
                    danger={!!s && s.server_errors > 0}
                    hint={s ? `${errRate ?? '0.0'}% · 요청 오류(4xx) ${s.client_errors.toLocaleString()}건` : ' '}
                    action={
                        s && s.server_errors > 0 ? (
                            <button
                                type="button"
                                onClick={() => {
                                    setStatus('5xx');
                                    setOffset(0);
                                    listRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
                                }}
                                className="font-semibold text-danger hover:underline"
                            >
                                보기 →
                            </button>
                        ) : undefined
                    }
                />
                <Kpi label="응답 시간 (평균)" value={fmtMs(s?.avg_ms ?? null)} hint={s ? `느린 5% 기준 ${fmtMs(s.p95_ms)} 이상` : ' '} />
            </dl>

            <section className="mt-8">
                <div className="flex items-baseline gap-3">
                    <h3 className="text-[15px] font-bold">{s?.bucket === 'day' ? '일별' : '시간대별'} 요청</h3>
                    <span className="inline-flex items-center gap-3 text-[11.5px] text-muted">
                        <span className="inline-flex items-center gap-1.5">
                            <span className="w-2.5 h-2.5 rounded-[3px] bg-brand/70" aria-hidden />
                            요청
                        </span>
                        <span className="inline-flex items-center gap-1.5">
                            <span className="w-2.5 h-2.5 rounded-[3px] bg-danger" aria-hidden />
                            서버 오류
                        </span>
                    </span>
                </div>
                <div className="mt-6">
                    {s ? <RequestBars data={s.series} bucket={s.bucket} /> : <div className="h-[150px] rounded-xl bg-surface animate-pulse" />}
                </div>
            </section>

            <div className="mt-12 grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_340px] gap-x-12 gap-y-10">
                <section className="min-w-0">
                    <h3 className="text-[15px] font-bold">많이 부른 경로</h3>
                    {s && s.top_paths.length === 0 && <Empty>기록이 없습니다.</Empty>}
                    <ul className="mt-3 flex flex-col gap-2.5">
                        {s?.top_paths.map((p) => (
                            <li key={`${p.method} ${p.route}`} className="grid grid-cols-[52px_minmax(0,1fr)_56px_60px] items-center gap-3 text-[12px]">
                                <MethodTag method={p.method} />
                                <span className="min-w-0">
                                    <span className="block truncate font-mono text-[11.5px]" title={p.route}>
                                        {p.route}
                                    </span>
                                    <span className="mt-1 block h-1 rounded-full bg-track overflow-hidden">
                                        <span
                                            className="block h-full rounded-full bg-brand/60"
                                            style={{ width: `${(p.count / (s.top_paths[0]?.count || 1)) * 100}%` }}
                                        />
                                    </span>
                                </span>
                                <span className="text-right font-semibold tabular-nums">{p.count.toLocaleString()}</span>
                                <span className="text-right text-muted tabular-nums" title="평균 응답 시간">
                                    {fmtMs(p.avg_ms)}
                                </span>
                            </li>
                        ))}
                    </ul>
                </section>
                <section className="min-w-0">
                    <h3 className="text-[15px] font-bold">접속 IP</h3>
                    {s && s.top_ips.length === 0 && <Empty>기록이 없습니다.</Empty>}
                    <ul className="mt-2 divide-y divide-divide">
                        {s?.top_ips.map((p) => (
                            <li key={p.client_ip}>
                                <button
                                    type="button"
                                    onClick={() => filterByIp(p.client_ip)}
                                    title="이 IP의 기록만 보기"
                                    className="-mx-2 px-2 py-2 w-[calc(100%+16px)] rounded-lg flex items-center gap-3 text-[12px] hover:bg-surface transition-colors text-left"
                                >
                                    <span className="font-mono text-[12px] truncate min-w-0 flex-1">{p.client_ip || '(알 수 없음)'}</span>
                                    <span className="text-muted tabular-nums shrink-0">{fmtAgo(p.last_seen)}</span>
                                    <span className="w-12 text-right font-semibold tabular-nums shrink-0">{p.count.toLocaleString()}</span>
                                </button>
                            </li>
                        ))}
                    </ul>
                </section>
            </div>

            <section ref={listRef} className="mt-12 scroll-mt-4">
                <div className="flex flex-wrap items-center gap-2">
                    <h3 className="text-[15px] font-bold mr-2">최근 기록</h3>
                    <input
                        value={q}
                        onChange={(e) => setQ(e.target.value)}
                        placeholder="경로 검색 (예: /ask)"
                        aria-label="경로 검색"
                        className="h-8 w-full sm:w-52 px-3 rounded-lg border border-line text-[12.5px] outline-none focus:border-brand"
                    />
                    <select
                        value={status}
                        onChange={(e) => {
                            setStatus(e.target.value);
                            setOffset(0);
                        }}
                        aria-label="상태 코드"
                        className="h-8 px-2 rounded-lg border border-line text-[12.5px] bg-white outline-none focus:border-brand"
                    >
                        {STATUS_FILTERS.map((f) => (
                            <option key={f.value} value={f.value}>
                                {f.label}
                            </option>
                        ))}
                    </select>
                    <select
                        value={method}
                        onChange={(e) => {
                            setMethod(e.target.value);
                            setOffset(0);
                        }}
                        aria-label="메서드"
                        className="h-8 px-2 rounded-lg border border-line text-[12.5px] bg-white outline-none focus:border-brand"
                    >
                        {METHODS.map((m) => (
                            <option key={m} value={m}>
                                {m || '모든 메서드'}
                            </option>
                        ))}
                    </select>
                    {ip && (
                        <button
                            type="button"
                            onClick={() => filterByIp('')}
                            className="h-8 px-3 rounded-lg bg-brand-pale text-brand-hover text-[12px] font-semibold inline-flex items-center gap-1.5"
                            title="IP 필터 해제"
                        >
                            IP {ip} <span aria-hidden>✕</span>
                        </button>
                    )}
                </div>
                {logsError && <Banner>{logsError}</Banner>}

                <div className="mt-4 overflow-x-auto">
                    <table className="w-full min-w-[720px] text-[12px] border-collapse">
                        <thead>
                            <tr className="text-left text-[11px] text-muted border-b border-line">
                                <th className="py-2 pr-3 font-semibold w-[128px]">시각</th>
                                <th className="py-2 pr-3 font-semibold w-[130px]">IP</th>
                                <th className="py-2 pr-3 font-semibold w-[64px]">메서드</th>
                                <th className="py-2 pr-3 font-semibold">경로</th>
                                <th className="py-2 pr-3 font-semibold w-[56px] text-right">상태</th>
                                <th className="py-2 font-semibold w-[72px] text-right">응답</th>
                            </tr>
                        </thead>
                        <tbody>
                            {logs?.items.map((r) => (
                                <tr key={r.id} className="border-b border-divide hover:bg-surface" title={r.user_agent}>
                                    <td className="py-2 pr-3 tabular-nums text-ink/70 whitespace-nowrap">{dateTimeFmt.format(new Date(r.ts))}</td>
                                    <td className="py-2 pr-3">
                                        <button type="button" onClick={() => filterByIp(r.client_ip)} className="font-mono text-[11.5px] hover:text-brand-hover hover:underline">
                                            {r.client_ip}
                                        </button>
                                    </td>
                                    <td className="py-2 pr-3">
                                        <MethodTag method={r.method} />
                                    </td>
                                    <td className="py-2 pr-3 font-mono text-[11.5px] max-w-0">
                                        <span className="block truncate" title={r.query ? `${r.path}?${r.query}` : r.path}>
                                            {r.path}
                                            {r.query && <span className="text-muted">?{r.query}</span>}
                                        </span>
                                    </td>
                                    <td className="py-2 pr-3 text-right">
                                        <StatusCode code={r.status} />
                                    </td>
                                    <td className={`py-2 text-right tabular-nums ${r.duration_ms >= 3000 ? 'text-warn font-semibold' : 'text-ink/70'}`}>
                                        {fmtMs(r.duration_ms)}
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                    {logs && logs.items.length === 0 && <Empty>조건에 맞는 기록이 없습니다.</Empty>}
                    {!logs && !logsError && <Empty>불러오는 중…</Empty>}
                </div>

                {logs && logs.total > 0 && (
                    <div className="mt-3 flex items-center justify-end gap-3 text-[12px] text-muted tabular-nums">
                        <span>
                            {(offset + 1).toLocaleString()}–{Math.min(offset + PAGE_SIZE, logs.total).toLocaleString()} / {logs.total.toLocaleString()}건
                        </span>
                        <PagerButton disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>
                            ← 최신
                        </PagerButton>
                        <PagerButton disabled={offset + PAGE_SIZE >= logs.total} onClick={() => setOffset(offset + PAGE_SIZE)}>
                            이전 기록 →
                        </PagerButton>
                    </div>
                )}
            </section>
        </>
    );
}

/* ---------------- 작은 조각 ---------------- */

function Kpi({ label, value, hint, danger, action }: { label: string; value: string; hint: string; danger?: boolean; action?: ReactNode }) {
    return (
        <div className="min-w-0 pr-4 lg:not-first:border-l lg:not-first:border-divide lg:not-first:pl-6">
            <dt className="text-[12px] font-semibold text-muted">{label}</dt>
            <dd className={`mt-1 text-[30px] font-extrabold leading-none tracking-tight tabular-nums ${danger ? 'text-danger' : 'text-ink'}`}>{value}</dd>
            <dd className="mt-2 text-[12px] text-muted flex items-center gap-2 flex-wrap">
                <span className="truncate">{hint}</span>
                {action}
            </dd>
        </div>
    );
}

function MethodTag({ method }: { method: string }) {
    return (
        <span className="inline-flex justify-center min-w-[46px] h-5 px-1.5 items-center rounded-md bg-chip text-[10.5px] font-bold text-ink/70">
            {method}
        </span>
    );
}

function StatusCode({ code }: { code: number }) {
    const cls = code >= 500 ? 'bg-danger-soft text-danger' : code >= 400 ? 'bg-warn-soft text-warn' : 'text-ink/70';
    return <span className={`inline-block px-1.5 rounded-md font-semibold tabular-nums ${cls}`}>{code}</span>;
}

function PagerButton({ disabled, onClick, children }: { disabled: boolean; onClick: () => void; children: ReactNode }) {
    return (
        <button
            type="button"
            disabled={disabled}
            onClick={onClick}
            className="h-7 px-3 rounded-lg border border-line text-ink font-semibold disabled:opacity-40 disabled:cursor-default hover:bg-surface"
        >
            {children}
        </button>
    );
}

function Banner({ children }: { children: ReactNode }) {
    return <p className="mt-4 px-4 py-3 rounded-xl bg-danger-surface text-danger text-[12.5px]">{children}</p>;
}

function Empty({ children }: { children: ReactNode }) {
    return <p className="py-8 text-center text-[12.5px] text-muted">{children}</p>;
}
