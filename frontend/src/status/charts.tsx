import { useRef, useState } from 'react';

const timeFmt = new Intl.DateTimeFormat('ko-KR', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
const hourFmt = new Intl.DateTimeFormat('ko-KR', { month: 'numeric', day: 'numeric', hour: '2-digit', hour12: false });
const dayFmt = new Intl.DateTimeFormat('ko-KR', { month: 'numeric', day: 'numeric', weekday: 'short' });

export interface UsagePoint {
    t: number; // epoch ms
    v: number | null;
}

/**
 * 최근 사용률(0~100%) 선 그래프. 세로축은 항상 0~100으로 고정해 카드끼리 높이를 비교할 수 있게 한다.
 * - 가로축은 시간 기준(최근 windowMs). 측정이 덜 쌓였으면 오른쪽부터 채워진다
 * - 측정 값이 없는 구간(null)은 선을 끊는다
 * - 마우스를 올리면 세로 보조선 + 그 시각의 값
 */
export function UsageChart({
    points,
    windowMs,
    label,
    height = 72,
}: {
    points: UsagePoint[];
    windowMs: number;
    label: string;
    height?: number;
}) {
    const ref = useRef<HTMLDivElement>(null);
    const [hover, setHover] = useState<number | null>(null);
    const W = 300;
    const H = height;
    // 가장 최근 측정 시각을 오른쪽 끝으로 둔다 (측정이 없으면 그릴 것도 없다)
    const now = points.length ? points[points.length - 1].t : windowMs;
    const t0 = now - windowMs;
    const x = (t: number) => ((t - t0) / windowMs) * W;
    const y = (v: number) => H - (Math.min(100, Math.max(0, v)) / 100) * H;

    // null에서 끊어 여러 조각으로 그린다
    const segments: UsagePoint[][] = [];
    let cur: UsagePoint[] = [];
    for (const p of points) {
        if (p.t < t0) continue;
        if (p.v == null) {
            if (cur.length) segments.push(cur);
            cur = [];
        } else cur.push(p);
    }
    if (cur.length) segments.push(cur);

    const line = (seg: UsagePoint[]) => seg.map((p, i) => `${i ? 'L' : 'M'}${x(p.t).toFixed(1)},${y(p.v!).toFixed(1)}`).join(' ');
    const area = (seg: UsagePoint[]) =>
        `${line(seg)} L${x(seg[seg.length - 1].t).toFixed(1)},${H} L${x(seg[0].t).toFixed(1)},${H} Z`;

    const visible = points.filter((p) => p.t >= t0);
    const onMove = (e: React.MouseEvent) => {
        const box = ref.current?.getBoundingClientRect();
        if (!box || !visible.length) return;
        const t = t0 + ((e.clientX - box.left) / box.width) * windowMs;
        let best = 0;
        for (let i = 1; i < visible.length; i++) if (Math.abs(visible[i].t - t) < Math.abs(visible[best].t - t)) best = i;
        setHover(best);
    };
    const hp = hover != null ? visible[hover] : null;
    const last = visible.length ? visible[visible.length - 1] : null;

    return (
        <figure className="m-0">
            <div
                ref={ref}
                className="relative"
                style={{ height: H }}
                onMouseMove={onMove}
                onMouseLeave={() => setHover(null)}
                role="img"
                aria-label={`${label} 최근 ${Math.round(windowMs / 60000)}분 추이${last?.v != null ? `, 현재 ${last.v.toFixed(0)}%` : ''}`}
            >
                <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="absolute inset-0 w-full h-full overflow-visible">
                    {/* 50% / 100% 기준선 */}
                    {[0, 50].map((v) => (
                        <line key={v} x1={0} x2={W} y1={y(100 - v)} y2={y(100 - v)} stroke="#E9EDF1" strokeDasharray="3 3" vectorEffect="non-scaling-stroke" />
                    ))}
                    <line x1={0} x2={W} y1={H} y2={H} stroke="#D9DFE6" vectorEffect="non-scaling-stroke" />
                    {segments.map((seg, i) => (
                        <g key={i}>
                            <path d={area(seg)} fill="#00A4E4" fillOpacity={0.1} />
                            <path
                                d={line(seg)}
                                fill="none"
                                stroke="#00A4E4"
                                strokeWidth={2}
                                strokeLinejoin="round"
                                strokeLinecap="round"
                                vectorEffect="non-scaling-stroke"
                            />
                        </g>
                    ))}
                </svg>
                <span className="absolute -top-1.5 right-0 bg-white pl-1 text-[10px] leading-none text-muted" aria-hidden>
                    100%
                </span>
                <span className="absolute top-1/2 -translate-y-1/2 right-0 bg-white pl-1 text-[10px] leading-none text-muted" aria-hidden>
                    50%
                </span>
                {hp && (
                    <>
                        <span className="absolute top-0 bottom-0 w-px bg-ink/25 pointer-events-none" style={{ left: `${(x(hp.t) / W) * 100}%` }} />
                        {hp.v != null && (
                            <span
                                className="absolute w-2 h-2 -ml-1 -mt-1 rounded-full bg-brand ring-2 ring-white pointer-events-none"
                                style={{ left: `${(x(hp.t) / W) * 100}%`, top: y(hp.v) }}
                            />
                        )}
                        <span
                            className={`absolute -top-9 z-10 px-2 py-1 rounded-md bg-ink text-white text-[11px] whitespace-nowrap pointer-events-none tabular-nums ${
                                x(hp.t) / W > 0.6 ? '-translate-x-full -ml-2' : 'ml-2'
                            }`}
                            style={{ left: `${(x(hp.t) / W) * 100}%` }}
                        >
                            {timeFmt.format(hp.t)} · <b>{hp.v == null ? '—' : `${hp.v.toFixed(1)}%`}</b>
                        </span>
                    </>
                )}
            </div>
            <figcaption className="mt-1 flex justify-between text-[10px] text-muted" aria-hidden>
                <span>{Math.round(windowMs / 60000)}분 전</span>
                <span>지금</span>
            </figcaption>
        </figure>
    );
}

export interface BarDatum {
    start: string;
    count: number;
    errors: number;
}

/**
 * 시간대(또는 일)별 요청 수 막대. 서버 오류(5xx)는 같은 막대 위쪽에 빨간 조각으로 쌓는다.
 * 막대보다 넓은 열 전체가 hover/포커스 대상이고 위에 툴팁을 띄운다. 스크린리더용 표를 함께 둔다.
 */
export function RequestBars({ data, bucket, height = 150 }: { data: BarDatum[]; bucket: 'hour' | 'day'; height?: number }) {
    const [active, setActive] = useState<number | null>(null);
    if (!data.length) return null;
    const fmt = bucket === 'hour' ? hourFmt : dayFmt;
    const max = Math.max(1, ...data.map((d) => d.count));
    const last = data.length - 1;
    const ticks = new Set([0, Math.floor(last / 2), last]);
    // ko-KR 시각 서식이 '18시'처럼 단위를 붙여 준다
    const label = (d: BarDatum) => fmt.format(new Date(d.start));

    return (
        <figure className="m-0">
            <div className="relative" style={{ height }}>
                <div className="absolute inset-x-0 top-0 border-t border-dashed border-divide" aria-hidden />
                <span className="absolute -top-2 right-0 bg-white pl-1.5 text-[10px] text-muted tabular-nums" aria-hidden>
                    {max.toLocaleString()}
                </span>
                <div className="absolute inset-0 flex items-end gap-[2px] border-b border-line" onMouseLeave={() => setActive(null)}>
                    {data.map((d, i) => {
                        const ok = d.count - d.errors;
                        const on = active === i;
                        return (
                            <button
                                key={d.start}
                                type="button"
                                onMouseEnter={() => setActive(i)}
                                onFocus={() => setActive(i)}
                                onBlur={() => setActive(null)}
                                aria-label={`${label(d)} 요청 ${d.count}건, 서버 오류 ${d.errors}건`}
                                className="relative flex-1 min-w-0 h-full flex flex-col justify-end items-stretch outline-none"
                            >
                                {d.errors > 0 && (
                                    <span
                                        className="block rounded-t-[4px] bg-danger"
                                        style={{ height: `${(d.errors / max) * 100}%`, minHeight: 2, marginBottom: ok > 0 ? 2 : 0 }}
                                    />
                                )}
                                {ok > 0 && (
                                    <span
                                        className={`block ${d.errors > 0 ? '' : 'rounded-t-[4px]'} ${on ? 'bg-brand' : 'bg-brand/70'}`}
                                        style={{ height: `${(ok / max) * 100}%`, minHeight: 2 }}
                                    />
                                )}
                                {on && (
                                    <span
                                        className={`absolute bottom-full mb-2 z-10 px-2 py-1 rounded-md bg-ink text-white text-[11px] whitespace-nowrap pointer-events-none tabular-nums text-left ${
                                            i > last * 0.6 ? 'right-0' : 'left-0'
                                        }`}
                                    >
                                        {label(d)}
                                        <br />
                                        요청 <b>{d.count.toLocaleString()}</b>
                                        {d.errors > 0 && <> · 오류 <b>{d.errors}</b></>}
                                    </span>
                                )}
                            </button>
                        );
                    })}
                </div>
            </div>
            <div className="mt-1.5 flex text-[10px] text-muted" aria-hidden>
                {data.map((d, i) => (
                    <span key={d.start} className={`flex-1 min-w-0 whitespace-nowrap ${i === last ? 'text-right' : i === 0 ? '' : 'text-center'}`}>
                        {ticks.has(i) ? label(d) : ''}
                    </span>
                ))}
            </div>
            <table className="sr-only">
                <caption>{bucket === 'hour' ? '시간대별' : '일별'} 요청 수</caption>
                <tbody>
                    {data.map((d) => (
                        <tr key={d.start}>
                            <th>{label(d)}</th>
                            <td>{d.count}</td>
                            <td>{d.errors}</td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </figure>
    );
}
