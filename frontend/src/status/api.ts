import { request } from '../lib/http';

/** 서버 상태 API (백엔드 app/routers/monitor.py). 시각은 모두 UTC ISO 문자열이다. */

export interface GpuSample {
    index: number;
    name: string;
    util_percent: number | null;
    mem_used_mb: number | null;
    mem_total_mb: number | null;
    mem_percent: number | null;
    temperature_c: number | null;
    power_w: number | null;
    power_limit_w: number | null;
}

export interface SystemSample {
    ts: string;
    cpu_percent: number;
    load_avg: number[] | null;
    mem_used: number;
    mem_total: number;
    mem_percent: number | null;
    gpus: GpuSample[];
}

export interface HistoryPoint {
    ts: string;
    cpu: number;
    mem: number | null;
    gpus: { util: number | null; mem: number | null }[];
}

export interface SystemStatus {
    host: {
        hostname: string;
        os: string;
        in_container: boolean;
        cpu_count: number | null;
        cpu_physical: number | null;
        boot_time: string;
        app_started_at: string;
    };
    interval_seconds: number;
    current: SystemSample;
    gpu_error: string | null;
    history: HistoryPoint[];
}

export interface AccessBucket {
    start: string;
    count: number;
    errors: number;
}

export interface AccessSummary {
    hours: number;
    bucket: 'hour' | 'day';
    total: number;
    unique_ips: number;
    client_errors: number;
    server_errors: number;
    avg_ms: number | null;
    p95_ms: number | null;
    series: AccessBucket[];
    top_paths: { method: string; route: string; count: number; avg_ms: number; errors: number }[];
    top_ips: { client_ip: string; count: number; last_seen: string }[];
}

export interface AccessLog {
    id: number;
    ts: string;
    client_ip: string;
    method: string;
    path: string;
    route: string;
    query: string;
    status: number;
    duration_ms: number;
    user_agent: string;
}

export interface AccessLogFilter {
    q?: string;
    status?: string;
    ip?: string;
    method?: string;
    limit: number;
    offset: number;
}

const qs = (params: Record<string, string | number | undefined>) =>
    new URLSearchParams(
        Object.entries(params)
            .filter(([, v]) => v !== undefined && v !== '')
            .map(([k, v]) => [k, String(v)]),
    ).toString();

export const monitorApi = {
    system: () => request<SystemStatus>('/monitor/system'),
    // 하루 단위 막대의 날짜 경계를 브라우저 시간대에 맞춘다
    accessSummary: (hours: number) =>
        request<AccessSummary>(`/monitor/access/summary?${qs({ hours, tz_minutes: -new Date().getTimezoneOffset() })}`),
    accessLogs: (f: AccessLogFilter) =>
        request<{ total: number; items: AccessLog[] }>(`/monitor/access/logs?${qs({ ...f })}`),
};
