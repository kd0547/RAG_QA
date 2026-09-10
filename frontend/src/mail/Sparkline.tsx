/** 최근 N일 전송량 스파크라인. 라인은 잉크색, 채움은 옅게, 끝점만 브랜드 컬러. */
export function Sparkline({
    data,
    width = 260,
    height = 54,
    className,
}: {
    data: number[];
    width?: number;
    height?: number;
    className?: string;
}) {
    if (data.length < 2) return null;

    const pad = 4;
    const max = Math.max(...data);
    const min = Math.min(...data);
    const span = max - min || 1;
    const stepX = (width - pad * 2) / (data.length - 1);

    const pts = data.map((v, i) => {
        const x = pad + i * stepX;
        const y = pad + (height - pad * 2) * (1 - (v - min) / span);
        return [x, y] as const;
    });

    const line = pts.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`).join(' ');
    const [lastX, lastY] = pts[pts.length - 1];
    const area = `${line} L${lastX.toFixed(1)},${height - pad} L${pts[0][0].toFixed(1)},${height - pad} Z`;

    return (
        <svg
            viewBox={`0 0 ${width} ${height}`}
            className={className}
            preserveAspectRatio="none"
            role="img"
            aria-label={`최근 ${data.length}일 전송량 추이, 최근값 ${data[data.length - 1]}건`}
        >
            <path d={area} fill="rgba(20,28,43,0.06)" />
            <path
                d={line}
                fill="none"
                stroke="#141C2B"
                strokeOpacity="0.5"
                strokeWidth="1.5"
                strokeLinejoin="round"
                strokeLinecap="round"
                vectorEffect="non-scaling-stroke"
            />
            <circle cx={lastX} cy={lastY} r="3" fill="#00A4E4" />
        </svg>
    );
}
