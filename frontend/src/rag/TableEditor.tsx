import { useEffect, useRef, useState } from 'react';

import {
    anchorsIn,
    canMarkdown,
    colCount,
    deleteCol,
    deleteRow,
    expandRect,
    insertCol,
    insertRow,
    mergeCells,
    setCellText,
    toggleHeader,
    unmergeCells,
    type Grid,
    type TableFormat,
} from './tableModel';

type Pos = [number, number];

/**
 * 파일 검수용 표 편집기. 셀 글자를 고치고 행·열 추가/삭제, 셀 병합/해제, 머리글 지정을 한다.
 * 적용하면 마크다운 표(병합 없는 단순 표만) 또는 HTML 표 문자열로 원문에 들어간다.
 */
export function TableEditor({
    initial,
    initialFormat,
    isNew,
    onApply,
    onCancel,
    onDelete,
}: {
    initial: Grid;
    initialFormat: TableFormat;
    isNew: boolean;
    onApply: (grid: Grid, format: TableFormat) => void;
    onCancel: () => void;
    onDelete: () => void;
}) {
    const [grid, setGrid] = useState(initial);
    const [format, setFormat] = useState<TableFormat>(initialFormat);
    const [selA, setSelA] = useState<Pos>([0, 0]);
    const [selB, setSelB] = useState<Pos>([0, 0]);
    const dragging = useRef(false);

    useEffect(() => {
        const stop = () => { dragging.current = false; };
        window.addEventListener('mouseup', stop);
        return () => window.removeEventListener('mouseup', stop);
    }, []);

    const R = grid.length;
    const W = colCount(grid);
    const rect = expandRect(grid, { r1: selA[0], c1: selA[1], r2: selB[0], c2: selB[1] });
    const multi = rect.r1 !== rect.r2 || rect.c1 !== rect.c2;
    const anchors = anchorsIn(grid, rect);
    const hasMerged = anchors.some(([r, c]) => grid[r][c]!.rowSpan > 1 || grid[r][c]!.colSpan > 1);
    const mdOk = canMarkdown(grid);
    const effective: TableFormat = format === 'markdown' && !mdOk ? 'html' : format;

    const select = (a: Pos, b: Pos = a) => {
        setSelA(a);
        setSelB(b);
    };
    /** 편집 후 격자 크기가 바뀌면 선택을 격자 안으로 당긴다 */
    const commit = (next: Grid, sel: Pos) => {
        setGrid(next);
        const r = Math.max(0, Math.min(sel[0], next.length - 1));
        const c = Math.max(0, Math.min(sel[1], colCount(next) - 1));
        select([r, c]);
    };

    const deleteRows = () => {
        let next = grid;
        for (let r = rect.r2; r >= rect.r1; r--) next = deleteRow(next, r);
        commit(next, [rect.r1, rect.c1]);
    };
    const deleteCols = () => {
        let next = grid;
        for (let c = rect.c2; c >= rect.c1; c--) next = deleteCol(next, c);
        commit(next, [rect.r1, rect.c1]);
    };

    const btn = 'h-7 px-2 rounded-md border border-line bg-white text-[11.5px] font-semibold text-ink/80 hover:border-brand hover:text-brand disabled:opacity-40 disabled:hover:border-line disabled:hover:text-ink/80';

    return (
        <div className="flex h-full min-h-0 flex-col rounded-lg border border-brand/40 bg-brand-tint">
            <div className="flex flex-wrap items-center gap-1.5 border-b border-divide px-3 py-2">
                <span className="mr-1 text-[12px] font-bold">{isNew ? '새 표' : '표 편집'}</span>
                <span className="mr-2 text-[11px] text-muted">{R}행 × {W}열</span>
                <button type="button" className={btn} onClick={() => commit(insertRow(grid, rect.r1), [rect.r1, rect.c1])}>위에 행</button>
                <button type="button" className={btn} onClick={() => commit(insertRow(grid, rect.r2 + 1), [rect.r2 + 1, rect.c1])}>아래에 행</button>
                <button type="button" className={btn} onClick={() => commit(insertCol(grid, rect.c1), [rect.r1, rect.c1])}>왼쪽에 열</button>
                <button type="button" className={btn} onClick={() => commit(insertCol(grid, rect.c2 + 1), [rect.r1, rect.c2 + 1])}>오른쪽에 열</button>
                <button type="button" className={btn} onClick={deleteRows} disabled={rect.r2 - rect.r1 + 1 >= R}>행 삭제</button>
                <button type="button" className={btn} onClick={deleteCols} disabled={rect.c2 - rect.c1 + 1 >= W}>열 삭제</button>
                <span className="mx-1 h-4 w-px bg-line" />
                <button type="button" className={btn} onClick={() => commit(mergeCells(grid, rect), [rect.r1, rect.c1])} disabled={!multi}>셀 병합</button>
                <button type="button" className={btn} onClick={() => setGrid(unmergeCells(grid, rect))} disabled={!hasMerged}>병합 해제</button>
                <button type="button" className={btn} onClick={() => setGrid(toggleHeader(grid, rect))}>머리글 셀</button>
            </div>

            <p className="px-3 pt-2 text-[11px] text-muted">
                셀을 드래그하거나 Shift+클릭으로 범위를 고른 뒤 병합합니다. 셀 안 줄바꿈은 그대로 유지됩니다. 왼쪽 원본과 비교하며 고치세요.
            </p>

            <div className="min-h-0 flex-1 overflow-auto p-3">
                <table className="border-collapse bg-white text-[12px]">
                    <tbody>
                        {grid.map((row, r) => (
                            <tr key={r}>
                                {row.map((cell, c) => {
                                    if (!cell) return null;
                                    const inSel = r >= rect.r1 && r <= rect.r2 && c >= rect.c1 && c <= rect.c2;
                                    const tone = inSel && multi ? 'bg-brand-soft' : cell.header ? 'bg-surface' : 'bg-white';
                                    const focusRing = r === selA[0] && c === selA[1] ? 'outline-2 -outline-offset-2 outline-brand' : '';
                                    return (
                                        <td
                                            key={c}
                                            rowSpan={cell.rowSpan}
                                            colSpan={cell.colSpan}
                                            onMouseDown={(e) => {
                                                if (e.shiftKey) {
                                                    e.preventDefault();
                                                    setSelB([r, c]);
                                                } else {
                                                    select([r, c]);
                                                    dragging.current = true;
                                                }
                                            }}
                                            onMouseEnter={(e) => {
                                                if (dragging.current && e.buttons === 1) setSelB([r, c]);
                                            }}
                                            className={`border border-line p-0 align-top ${tone} ${focusRing}`}
                                        >
                                            <textarea
                                                value={cell.text}
                                                rows={1}
                                                onChange={(e) => setGrid(setCellText(grid, r, c, e.target.value))}
                                                onFocus={() => {
                                                    if (!dragging.current) select([r, c]);
                                                }}
                                                aria-label={`${r + 1}행 ${c + 1}열${cell.header ? ' 머리글' : ''}`}
                                                className={`block w-full min-w-[90px] min-h-[30px] resize-none bg-transparent px-2 py-1.5 leading-snug field-sizing-content focus:outline-none ${cell.header ? 'font-semibold' : ''}`}
                                            />
                                        </td>
                                    );
                                })}
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>

            <div className="flex flex-wrap items-center gap-2 border-t border-divide px-3 py-2">
                {!isNew && (
                    <button
                        type="button"
                        onClick={onDelete}
                        className="h-8 rounded-lg px-2 text-[12px] font-semibold text-danger hover:bg-danger-soft"
                    >
                        표 삭제
                    </button>
                )}
                <div className="ml-auto flex items-center gap-2">
                    <span className="text-[11.5px] text-muted">저장 형식</span>
                    <div className="inline-flex rounded-lg border border-line bg-white p-0.5">
                        {(['markdown', 'html'] as const).map((f) => (
                            <button
                                key={f}
                                type="button"
                                onClick={() => setFormat(f)}
                                disabled={f === 'markdown' && !mdOk}
                                title={f === 'markdown' && !mdOk ? '병합 셀, 여러 줄 셀, 첫 행이 아닌 머리글이 있으면 마크다운 표로 쓸 수 없습니다' : undefined}
                                className={`h-6 rounded-md px-2 text-[11.5px] font-semibold disabled:opacity-40 ${effective === f ? 'bg-brand text-white' : 'text-ink/70 hover:text-ink'}`}
                            >
                                {f === 'markdown' ? '마크다운' : 'HTML'}
                            </button>
                        ))}
                    </div>
                    <button type="button" onClick={onCancel} className="h-8 rounded-lg px-3 text-[12px] font-semibold text-ink/70 hover:bg-surface">
                        취소
                    </button>
                    <button
                        type="button"
                        onClick={() => onApply(grid, effective)}
                        className="h-8 rounded-lg bg-brand px-3 text-[12px] font-bold text-white hover:bg-brand-hover"
                    >
                        원문에 적용
                    </button>
                </div>
            </div>
        </div>
    );
}
