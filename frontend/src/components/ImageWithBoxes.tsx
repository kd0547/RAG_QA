import { useState } from 'react';
import type { OcrBlock } from '../types';

/** bbox 좌표를 정규화(0~1)/픽셀/좌표 뒤집힘 모두 처리해서 {x,y,w,h}(픽셀) 반환 */
function resolveBox(
    bbox: [number, number, number, number],
    natW: number,
    natH: number
) {
    let [x1, y1, x2, y2] = bbox;
    if (Math.max(x1, y1, x2, y2) <= 1.5) {
        x1 *= natW;
        x2 *= natW;
        y1 *= natH;
        y2 *= natH;
    }
    return {
        x: Math.min(x1, x2),
        y: Math.min(y1, y2),
        w: Math.abs(x2 - x1),
        h: Math.abs(y2 - y1),
    };
}

/** 원본 이미지 + OCR 블록 bbox 오버레이 (SVG viewBox로 자동 스케일) */
export function ImageWithBoxes({
                                   src,
                                   blocks,
                                   showBoxes,
                               }: {
    src: string;
    blocks: OcrBlock[];
    showBoxes: boolean;
}) {
    const [natural, setNatural] = useState<{ w: number; h: number } | null>(null);
    const [hovered, setHovered] = useState<number | null>(null);

    const unit = natural ? Math.max(natural.w, natural.h) : 1000;

    return (
        <div className="relative inline-block max-w-full">
        <img
            src={src}
    alt="Source"
    onLoad={(e) =>
    setNatural({
        w: e.currentTarget.naturalWidth,
        h: e.currentTarget.naturalHeight,
    })
}
    className="block max-w-full h-auto rounded-xl border border-divide bg-white"
        />
        {showBoxes && natural && blocks.length > 0 && (
            <svg
                viewBox={`0 0 ${natural.w} ${natural.h}`}
    preserveAspectRatio="none"
    className="absolute inset-0 w-full h-full pointer-events-none"
        >
        {blocks.map((b, i) => {
                const { x, y, w, h } = resolveBox(b.bbox, natural.w, natural.h);
                const active = hovered === i;
                return (
                    <g key={i}>
                        <rect
                            x={x}
                            y={y}
                            width={w}
                            height={h}
                            fill={active ? 'rgba(0,164,228,0.16)' : 'rgba(0,164,228,0.05)'}
                            stroke={active ? '#0092CC' : '#00A4E4'}
                            strokeWidth={unit / 500}
                            rx={unit / 400}
                            className="pointer-events-auto cursor-help transition-colors"
                            onMouseEnter={() => setHovered(i)}
                            onMouseLeave={() => setHovered(null)}
                        >
                            <title>
                                {(b.label ? `[${b.label}] ` : '') + (b.content || '')}
                            </title>
                        </rect>


                    </g>
            );
            })}
        </svg>
)}
    </div>
);
}