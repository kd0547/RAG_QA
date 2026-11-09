/**
 * 파일 검수 표 편집기의 표 모델.
 *
 * 페이지 텍스트는 마크다운이고, 셀 병합이 필요한 표는 그 안에 HTML <table> 블록으로 들어간다
 * (GFM은 HTML 블록을 그대로 허용하고, 파서 OCR 결과에도 HTML 표가 섞여 온다).
 * 여기서는 원문에서 표 블록을 찾고, 마크다운/HTML 표를 격자로 읽고, 행·열·병합 편집 후 다시 문자열로 쓴다.
 *
 * 격자(Grid)는 실제 칸 단위 2차원 배열이다. 셀의 왼쪽 위 칸에만 Cell(앵커)이 있고,
 * 그 셀이 병합으로 덮는 나머지 칸은 null이다. 모든 null 칸은 정확히 하나의 앵커에 덮인다.
 */

export interface Cell {
    text: string;
    rowSpan: number;
    colSpan: number;
    header: boolean;
}

export type Grid = (Cell | null)[][];
export type TableFormat = 'markdown' | 'html';

/** 칸 좌표 범위 (양 끝 포함) */
export interface Rect {
    r1: number;
    c1: number;
    r2: number;
    c2: number;
}

/** 원문 안의 표 위치 [start, end) */
export interface TableBlock {
    start: number;
    end: number;
    kind: TableFormat;
}

const emptyCell = (header = false): Cell => ({ text: '', rowSpan: 1, colSpan: 1, header });

export function newGrid(rows = 3, cols = 3): Grid {
    return Array.from({ length: rows }, (_, r) => Array.from({ length: cols }, () => emptyCell(r === 0)));
}

export const colCount = (g: Grid) => g[0]?.length ?? 0;

function cloneGrid(g: Grid): Grid {
    return g.map((row) => row.map((c) => c && { ...c }));
}

/** (r, c) 칸을 차지하는 앵커 셀의 좌표 */
export function anchorOf(g: Grid, r: number, c: number): [number, number] {
    for (let ar = r; ar >= 0; ar--) {
        for (let ac = c; ac >= 0; ac--) {
            const cell = g[ar][ac];
            if (cell && ar + cell.rowSpan > r && ac + cell.colSpan > c) return [ar, ac];
        }
    }
    return [r, c];
}

/** 범위가 병합 셀을 자르지 않도록, 걸친 셀 전체를 덮을 때까지 넓힌다 */
export function expandRect(g: Grid, rect: Rect): Rect {
    let r1 = Math.min(rect.r1, rect.r2);
    let r2 = Math.max(rect.r1, rect.r2);
    let c1 = Math.min(rect.c1, rect.c2);
    let c2 = Math.max(rect.c1, rect.c2);
    for (let changed = true; changed;) {
        changed = false;
        for (let r = r1; r <= r2; r++) {
            for (let c = c1; c <= c2; c++) {
                const [ar, ac] = anchorOf(g, r, c);
                const cell = g[ar][ac];
                if (!cell) continue;
                const er = ar + cell.rowSpan - 1;
                const ec = ac + cell.colSpan - 1;
                if (ar < r1) { r1 = ar; changed = true; }
                if (ac < c1) { c1 = ac; changed = true; }
                if (er > r2) { r2 = er; changed = true; }
                if (ec > c2) { c2 = ec; changed = true; }
            }
        }
    }
    return { r1, c1, r2, c2 };
}

/** 범위 안 앵커 셀 좌표 (읽는 순서) */
export function anchorsIn(g: Grid, rect: Rect): [number, number][] {
    const out: [number, number][] = [];
    for (let r = rect.r1; r <= rect.r2; r++) {
        for (let c = rect.c1; c <= rect.c2; c++) {
            if (g[r]?.[c]) out.push([r, c]);
        }
    }
    return out;
}

/** 직사각형으로 맞추고, 범위를 벗어난 병합을 자르고, 어떤 셀에도 덮이지 않은 null 칸을 빈 셀로 채운다 */
function normalizeGrid(g: Grid): Grid {
    const R = g.length;
    const W = Math.max(1, ...g.map((row) => row.length));
    const out: Grid = g.map((row) => Array.from({ length: W }, (_, c) => (row[c] === undefined ? emptyCell() : row[c])));
    const covered = out.map((row) => row.map(() => false));
    for (let r = 0; r < R; r++) {
        for (let c = 0; c < W; c++) {
            const cell = out[r][c];
            if (!cell || covered[r][c]) continue;
            cell.rowSpan = Math.max(1, Math.min(cell.rowSpan, R - r));
            cell.colSpan = Math.max(1, Math.min(cell.colSpan, W - c));
            for (let dr = 0; dr < cell.rowSpan; dr++) {
                for (let dc = 0; dc < cell.colSpan; dc++) covered[r + dr][c + dc] = true;
            }
        }
    }
    for (let r = 0; r < R; r++) {
        for (let c = 0; c < W; c++) {
            if (!covered[r][c]) out[r][c] = emptyCell();
            else if (out[r][c] && !isAnchorAt(out, r, c)) out[r][c] = null;
        }
    }
    return out.length ? out : newGrid();
}

/** 다른 셀의 병합 영역 안에 잘못 들어간 셀인지 확인 (겹친 병합을 정리할 때) */
function isAnchorAt(g: Grid, r: number, c: number): boolean {
    for (let ar = r; ar >= 0; ar--) {
        for (let ac = c; ac >= 0; ac--) {
            if (ar === r && ac === c) continue;
            const cell = g[ar][ac];
            if (cell && ar + cell.rowSpan > r && ac + cell.colSpan > c) return false;
        }
    }
    return true;
}

// ===== 원문에서 표 찾기 =====

function isDelimiterRow(line: string): boolean {
    const t = line.trim();
    if (!t.includes('-') || !t.includes('|')) return false;
    const body = t.replace(/^\|/, '').replace(/\|$/, '');
    return body.split('|').every((p) => /^\s*:?-+:?\s*$/.test(p));
}

/** 원문 안의 HTML <table> 블록과 GFM 표를 위치순으로 찾는다. 코드 펜스 안은 건너뛴다. */
export function findTables(src: string): TableBlock[] {
    const blocks: TableBlock[] = [];
    for (const m of src.matchAll(/<table\b[\s\S]*?<\/table>/gi)) {
        blocks.push({ start: m.index, end: m.index + m[0].length, kind: 'html' });
    }
    const htmlBlocks = [...blocks];
    const inHtml = (pos: number) => htmlBlocks.some((b) => pos >= b.start && pos < b.end);

    const lines = src.split('\n');
    const starts: number[] = [];
    let offset = 0;
    for (const line of lines) {
        starts.push(offset);
        offset += line.length + 1;
    }

    let fence = '';
    for (let i = 0; i < lines.length; i++) {
        const t = lines[i].trim();
        const f = t.match(/^(`{3,}|~{3,})/);
        if (f) {
            if (!fence) fence = f[1][0].repeat(3);
            else if (t.startsWith(fence)) fence = '';
            continue;
        }
        if (fence || inHtml(starts[i])) continue;
        if (t.startsWith('|') && i + 1 < lines.length && isDelimiterRow(lines[i + 1])) {
            let j = i + 1;
            while (j + 1 < lines.length && lines[j + 1].trim().startsWith('|')) j++;
            blocks.push({ start: starts[i], end: starts[j] + lines[j].replace(/\r$/, '').length, kind: 'markdown' });
            i = j;
        }
    }
    return blocks.sort((a, b) => a.start - b.start);
}

// ===== 읽기 =====

/** 이스케이프되지 않은 | 로 행을 나눈다 */
function splitMarkdownRow(line: string): string[] {
    let t = line.trim();
    if (t.startsWith('|')) t = t.slice(1);
    if (t.endsWith('|') && !t.endsWith('\\|')) t = t.slice(0, -1);
    const cells: string[] = [];
    let cur = '';
    for (let i = 0; i < t.length; i++) {
        if (t[i] === '\\' && t[i + 1] === '|') {
            cur += '|';
            i++;
        } else if (t[i] === '|') {
            cells.push(cur);
            cur = '';
        } else {
            cur += t[i];
        }
    }
    cells.push(cur);
    return cells;
}

/** 표 셀 안의 마크다운 강조 기호는 파서가 어긋나게 붙인 경우가 많아 지우고 순수 텍스트만 남긴다 */
function cleanMarkdownCell(s: string): string {
    return s.replace(/<br\s*\/?>/gi, '\n').replace(/\*\*|__/g, '').trim();
}

export function parseMarkdownTable(src: string): Grid {
    const lines = src.split('\n').filter((l) => l.trim());
    if (lines.length < 2) return newGrid();
    const rows = lines.filter((_, i) => i !== 1).map(splitMarkdownRow);
    const cols = Math.max(splitMarkdownRow(lines[1]).length, ...rows.map((r) => r.length));
    return rows.map((row, r) => Array.from({ length: cols }, () => emptyCell(r === 0)).map((cell, c) => ({
        ...cell,
        text: cleanMarkdownCell(row[c] ?? ''),
    })));
}

function htmlCellText(el: HTMLTableCellElement): string {
    const clone = el.cloneNode(true) as HTMLElement;
    clone.querySelectorAll('br').forEach((br) => br.replaceWith('\n'));
    clone.querySelectorAll('p, div, li').forEach((block) => block.append('\n'));
    return (clone.textContent ?? '')
        .split('\n')
        .map((line) => line.replace(/\s+/g, ' ').trim()) // \s는 &nbsp;(U+00A0)도 포함한다
        .filter(Boolean)
        .join('\n');
}

export function parseHtmlTable(src: string): Grid {
    const doc = new DOMParser().parseFromString(src, 'text/html');
    const table = doc.querySelector('table');
    if (!table || table.rows.length === 0) return newGrid();
    const trs = Array.from(table.rows);
    const R = trs.length;
    const g: (Cell | null | undefined)[][] = Array.from({ length: R }, () => []);
    trs.forEach((tr, r) => {
        let c = 0;
        for (const el of Array.from(tr.cells)) {
            while (g[r][c] !== undefined) c++;
            let rs = Math.min(Math.max(1, el.rowSpan || 1), R - r);
            let cs = Math.min(Math.max(1, el.colSpan || 1), 100);
            // 잘못된 HTML로 병합 영역이 겹치면 그 셀은 병합 없이 둔다
            let clash = false;
            for (let dr = 0; dr < rs && !clash; dr++) {
                for (let dc = 0; dc < cs; dc++) {
                    if ((dr || dc) && g[r + dr][c + dc] !== undefined) { clash = true; break; }
                }
            }
            if (clash) { rs = 1; cs = 1; }
            g[r][c] = { text: htmlCellText(el), rowSpan: rs, colSpan: cs, header: el.tagName === 'TH' };
            for (let dr = 0; dr < rs; dr++) {
                for (let dc = 0; dc < cs; dc++) if (dr || dc) g[r + dr][c + dc] = null;
            }
            c += cs;
        }
    });
    const W = Math.max(1, ...g.map((row) => row.length));
    return normalizeGrid(g.map((row) => Array.from({ length: W }, (_, c) => (row[c] === undefined ? emptyCell() : (row[c] as Cell | null)))));
}

// ===== 쓰기 =====

/** 마크다운 표로 손실 없이 쓸 수 있는지: 병합·여러 줄 셀이 없고 머리글이 첫 행에만 있어야 한다 */
export function canMarkdown(g: Grid): boolean {
    return g.every((row, r) => row.every((cell) => (
        !!cell && cell.rowSpan === 1 && cell.colSpan === 1 && !cell.text.includes('\n') && cell.header === (r === 0)
    )));
}

export function serializeMarkdown(g: Grid): string {
    const line = (row: (Cell | null)[]) => `| ${row.map((c) => (c?.text ?? '').replace(/\|/g, '\\|')).join(' | ')} |`;
    return [line(g[0]), `| ${g[0].map(() => '---').join(' | ')} |`, ...g.slice(1).map(line)].join('\n');
}

const escapeHtml = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

/**
 * 한 행을 한 줄로 쓴다. HTML 블록은 빈 줄에서 끝나므로 표 안에 빈 줄을 만들지 않고,
 * 검색 청크 길이를 아끼려고 들여쓰기·thead/tbody 없이 쓴다.
 */
export function serializeHtml(g: Grid): string {
    const rows = g.map((row) => {
        const cells = row.map((cell) => {
            if (!cell) return '';
            const tag = cell.header ? 'th' : 'td';
            const span = `${cell.colSpan > 1 ? ` colspan="${cell.colSpan}"` : ''}${cell.rowSpan > 1 ? ` rowspan="${cell.rowSpan}"` : ''}`;
            return `<${tag}${span}>${escapeHtml(cell.text).replace(/\n/g, '<br>')}</${tag}>`;
        });
        return `<tr>${cells.join('')}</tr>`;
    });
    return ['<table>', ...rows, '</table>'].join('\n');
}

/**
 * 원문의 [start, end)를 표 문자열로 바꾼다. 표 앞뒤에는 빈 줄을 둔다
 * (빈 줄이 없으면 HTML 블록 뒤 문단까지 HTML로 읽히고, 마크다운 표는 앞 문단에 붙는다).
 * text가 빈 문자열이면 그 구간을 지운다.
 */
export function replaceBlock(src: string, start: number, end: number, text: string): { next: string; at: number } {
    const before = src.slice(0, start);
    const after = src.slice(end);
    if (!text) {
        const head = before.replace(/\n+$/, '');
        const tail = after.replace(/^\n+/, '');
        return { next: head + (head && tail ? '\n\n' : '') + tail, at: head.length };
    }
    const pre = !before || before.endsWith('\n\n') ? '' : before.endsWith('\n') ? '\n' : '\n\n';
    const post = !after || after.startsWith('\n\n') ? '' : after.startsWith('\n') ? '\n' : '\n\n';
    return { next: before + pre + text + post + after, at: before.length + pre.length };
}

// ===== 편집 =====

/** at 위치(0..행 수)에 빈 행을 넣는다. 그 경계를 가로지르는 병합 셀은 한 칸 늘린다. */
export function insertRow(g: Grid, at: number): Grid {
    const R = g.length;
    const W = colCount(g);
    const ref = Math.min(at, R - 1); // 머리글 여부를 따라갈 행
    const spanning = new Set<Cell>();
    const row: (Cell | null)[] = [];
    for (let c = 0; c < W; c++) {
        if (at > 0 && at < R) {
            const [ar, ac] = anchorOf(g, at, c);
            if (ar < at) {
                spanning.add(g[ar][ac]!);
                row.push(null);
                continue;
            }
        }
        const [hr, hc] = anchorOf(g, ref, c);
        row.push(emptyCell(g[hr][hc]?.header ?? false));
    }
    const out = g.map((r) => r.map((c) => (c && spanning.has(c) ? { ...c, rowSpan: c.rowSpan + 1 } : c && { ...c })));
    out.splice(at, 0, row);
    return out;
}

/** r행을 지운다. 그 행에서 시작한 병합 셀은 아래 행으로 내리고, 위에서 걸친 병합 셀은 한 칸 줄인다. */
export function deleteRow(g: Grid, r: number): Grid {
    if (g.length <= 1) return g;
    const W = colCount(g);
    const seen = new Set<string>();
    const targets: [number, number][] = [];
    for (let c = 0; c < W; c++) {
        const [ar, ac] = anchorOf(g, r, c);
        const key = `${ar},${ac}`;
        if (!seen.has(key)) {
            seen.add(key);
            targets.push([ar, ac]);
        }
    }
    const out = cloneGrid(g);
    for (const [ar, ac] of targets) {
        const cell = out[ar][ac]!;
        if (cell.rowSpan <= 1) continue;
        cell.rowSpan -= 1;
        if (ar === r) {
            out[r + 1][ac] = cell;
            out[r][ac] = null;
        }
    }
    out.splice(r, 1);
    return out;
}

function transpose(g: Grid): Grid {
    return Array.from({ length: colCount(g) }, (_, c) => g.map((row) => {
        const x = row[c];
        return x && { ...x, rowSpan: x.colSpan, colSpan: x.rowSpan };
    }));
}

export const insertCol = (g: Grid, at: number) => transpose(insertRow(transpose(g), at));
export const deleteCol = (g: Grid, c: number) => (colCount(g) <= 1 ? g : transpose(deleteRow(transpose(g), c)));

/** 범위를 셀 하나로 합친다. 글자는 읽는 순서대로 공백으로 이어 붙인다. */
export function mergeCells(g: Grid, rect: Rect): Grid {
    const { r1, c1, r2, c2 } = expandRect(g, rect);
    if (r1 === r2 && c1 === c2) return g;
    const texts = anchorsIn(g, { r1, c1, r2, c2 }).map(([r, c]) => g[r][c]!.text.trim()).filter(Boolean);
    const out = cloneGrid(g);
    for (let r = r1; r <= r2; r++) for (let c = c1; c <= c2; c++) out[r][c] = null;
    out[r1][c1] = { text: texts.join(' '), rowSpan: r2 - r1 + 1, colSpan: c2 - c1 + 1, header: g[r1][c1]?.header ?? false };
    return out;
}

/** 범위 안 병합 셀을 모두 풀어 빈 칸으로 되돌린다. 글자는 왼쪽 위 칸에 남는다. */
export function unmergeCells(g: Grid, rect: Rect): Grid {
    const out = cloneGrid(g);
    for (const [r, c] of anchorsIn(g, expandRect(g, rect))) {
        const cell = out[r][c]!;
        for (let dr = 0; dr < cell.rowSpan; dr++) {
            for (let dc = 0; dc < cell.colSpan; dc++) if (dr || dc) out[r + dr][c + dc] = emptyCell(cell.header);
        }
        cell.rowSpan = 1;
        cell.colSpan = 1;
    }
    return out;
}

/** 범위 안 셀이 모두 머리글이면 해제하고, 아니면 모두 머리글로 만든다 */
export function toggleHeader(g: Grid, rect: Rect): Grid {
    const anchors = anchorsIn(g, expandRect(g, rect));
    const allHeader = anchors.every(([r, c]) => g[r][c]!.header);
    const out = cloneGrid(g);
    for (const [r, c] of anchors) out[r][c]!.header = !allHeader;
    return out;
}

export function setCellText(g: Grid, r: number, c: number, text: string): Grid {
    return g.map((row, rr) => (rr !== r ? row : row.map((x, cc) => (cc === c && x ? { ...x, text } : x))));
}
