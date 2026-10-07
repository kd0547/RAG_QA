import { useState } from 'react';
import type { DailyVolume } from './types';

const dayFmt = new Intl.DateTimeFormat('ko-KR', { month: 'numeric', day: 'numeric', weekday: 'short' });
const axisFmt = new Intl.DateTimeFormat('ko-KR', { month: 'numeric', day: 'numeric' });
const parseDay = (ymd: string) => new Date(`${ymd}T00:00:00`);

/**
 * 일별 전송량 막대 차트 (단일 계열 · 단일 색).
 * - 막대 끝만 4px 둥글게, 막대 사이 2px 간격
 * - 막대보다 넓은 열 전체가 hover/포커스 대상이고, 위에 툴팁을 띄운다
 * - 스크린리더용 표를 함께 둔다
 */
export function VolumeChart({ data, height = 160 }: { data: DailyVolume[]; height?: number }) {
    const [active, setActive] = useState<number | null>(null);
    if (data.length === 0) return null;

    const max = Math.max(1, ...data.map((d) => d.sent));
    const last = data.length - 1;
    const tickIdx = new Set([0, Math.floor(last / 2), last]);

    return (
        <figure className="m-0">
            <div className="relative" style={{ height }}>
                {/* 최댓값 기준선 (흐리게) */}
                <div className="absolute inset-x-0 top-0 border-t border-dashed border-divide" aria-hidden />
                <span className="absolute -top-2 right-0 bg-white pl-1.5 text-[10px] text-muted tabular-nums" aria-hidden>
                    {max}
                </span>

                <div className="absolute inset-0 flex items-end gap-[2px] border-b border-line" onMouseLeave={() => setActive(null)}>
                    {data.map((d, i) => {
                        const on = active === i;
                        return (
                            <button
                                key={d.date}
                                type="button"
                                onMouseEnter={() => setActive(i)}
                                onFocus={() => setActive(i)}
                                onBlur={() => setActive(null)}
                                aria-label={`${dayFmt.format(parseDay(d.date))} ${d.sent}건`}
                                className="relative flex-1 h-full flex items-end focus-visible:outline-2 focus-visible:outline-brand"
                            >
                                <span
                                    className={`w-full rounded-t-[4px] transition-colors ${
                                        on ? 'bg-brand' : i === last ? 'bg-brand/80' : 'bg-brand/45'
                                    }`}
                                    style={{ height: `${Math.max(2, (d.sent / max) * 100)}%` }}
                                />
                                {on && (
                                    <span className={`pointer-events-none absolute bottom-full mb-1.5 ${
                                        // 양 끝 막대의 툴팁이 차트 밖으로 잘리지 않게 붙이는 쪽을 바꾼다
                                        i < 2 ? 'left-0' : i > last - 2 ? 'right-0' : 'left-1/2 -translate-x-1/2'
                                    } z-10 px-2.5 py-1.5 rounded-lg bg-ink text-white text-[11px] whitespace-nowrap shadow-lg`}>
                                        <span className="text-white/70">{dayFmt.format(parseDay(d.date))}</span>{' '}
                                        <b className="tabular-nums">{d.sent}건</b>
                                    </span>
                                )}
                            </button>
                        );
                    })}
                </div>
            </div>

            <div className="mt-1.5 flex gap-[2px] text-[10px] text-muted tabular-nums" aria-hidden>
                {data.map((d, i) => (
                    <span key={d.date} className={`flex-1 whitespace-nowrap ${i === last ? 'text-right' : i === 0 ? 'text-left' : 'text-center'}`}>
                        {tickIdx.has(i) ? (i === last ? '오늘' : axisFmt.format(parseDay(d.date))) : ''}
                    </span>
                ))}
            </div>

            <table className="sr-only">
                <caption>일별 전송량</caption>
                <tbody>
                    {data.map((d) => (
                        <tr key={d.date}>
                            <th scope="row">{d.date}</th>
                            <td>{d.sent}</td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </figure>
    );
}
