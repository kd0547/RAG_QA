import { useEffect, useMemo, useRef, useState, type MouseEvent } from 'react';
import ReactMarkdown from 'react-markdown';
import rehypeRaw from 'rehype-raw';
import rehypeSanitize, { defaultSchema } from 'rehype-sanitize';
import remarkGfm from 'remark-gfm';

import { PAGE_PROSE_CLASS } from './pageProse';
import { TableEditor } from './TableEditor';
import {
    findTables,
    newGrid,
    parseHtmlTable,
    parseMarkdownTable,
    replaceBlock,
    serializeHtml,
    serializeMarkdown,
    type Grid,
    type TableBlock,
    type TableFormat,
} from './tableModel';

/** 페이지 텍스트 안의 HTML 표(병합 셀)를 그리되, 스크립트·이벤트 속성 등은 걸러낸다 */
const sanitizeSchema = {
    ...defaultSchema,
    attributes: {
        ...defaultSchema.attributes,
        td: [...(defaultSchema.attributes?.td ?? []), 'colSpan', 'rowSpan'],
        th: [...(defaultSchema.attributes?.th ?? []), 'colSpan', 'rowSpan'],
    },
};


/** 마크다운 + HTML 블록 렌더링 */
export function PageMarkdown({ text, tableTitle }: { text: string; tableTitle?: string }) {
    return (
        <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            rehypePlugins={[rehypeRaw, [rehypeSanitize, sanitizeSchema]]}
            components={tableTitle ? {
                table: ({ node, ...props }) => {
                    void node;
                    return <table title={tableTitle} {...props} />;
                },
            } : undefined}
        >
            {text}
        </ReactMarkdown>
    );
}

type ViewMode = 'source' | 'split' | 'preview';

interface TableSession {
    start: number;
    end: number;
    grid: Grid;
    format: TableFormat;
    isNew: boolean;
}

/**
 * 페이지 텍스트 편집기: 원문(마크다운, 표는 HTML도 가능) 편집 + 실시간 미리보기 + 표 편집기.
 * 원문 안 표에 커서를 두거나 미리보기의 표를 누르면 표 편집기가 그 자리에 열린다.
 */
export function PageTextEditor({
    value,
    onChange,
    disabled,
    label,
    onTableEditingChange,
}: {
    value: string;
    onChange: (next: string) => void;
    disabled: boolean;
    label: string;
    onTableEditingChange: (open: boolean) => void;
}) {
    const [mode, setMode] = useState<ViewMode>('split');
    const [cursor, setCursor] = useState(0);
    const [table, setTable] = useState<TableSession | null>(null);
    const [notice, setNotice] = useState('');
    const textareaRef = useRef<HTMLTextAreaElement>(null);

    const blocks = useMemo(() => findTables(value), [value]);
    const blockAtCursor = blocks.find((b) => cursor >= b.start && cursor <= b.end);

    useEffect(() => {
        onTableEditingChange(table !== null);
    }, [table, onTableEditingChange]);

    const placeCursor = (pos: number) => {
        setCursor(pos);
        requestAnimationFrame(() => {
            const ta = textareaRef.current;
            if (!ta) return;
            ta.focus();
            ta.setSelectionRange(pos, pos);
        });
    };

    const openBlock = (b: TableBlock) => {
        const src = value.slice(b.start, b.end);
        setNotice('');
        setTable({
            start: b.start,
            end: b.end,
            grid: b.kind === 'html' ? parseHtmlTable(src) : parseMarkdownTable(src),
            format: b.kind,
            isNew: false,
        });
    };

    const openNew = () => {
        // 커서가 표 안이면 그 표 뒤에, 아니면 커서가 있는 줄 끝에 넣는다
        let at = blockAtCursor ? blockAtCursor.end : cursor;
        if (!blockAtCursor) {
            const lineEnd = value.indexOf('\n', at);
            at = lineEnd === -1 ? value.length : lineEnd;
        }
        setNotice('');
        setTable({ start: at, end: at, grid: newGrid(), format: 'html', isNew: true });
    };

    const applyTable = (grid: Grid, format: TableFormat) => {
        if (!table) return;
        const text = format === 'markdown' ? serializeMarkdown(grid) : serializeHtml(grid);
        const { next, at } = replaceBlock(value, table.start, table.end, text);
        onChange(next);
        setTable(null);
        if (mode === 'preview') setMode('split');
        placeCursor(at);
    };

    const deleteTable = () => {
        if (!table) return;
        const { next, at } = replaceBlock(value, table.start, table.end, '');
        onChange(next);
        setTable(null);
        placeCursor(at);
    };

    const onPreviewClick = (e: MouseEvent<HTMLDivElement>) => {
        if (disabled) return;
        const el = (e.target as HTMLElement).closest('table');
        if (!el) return;
        const all = Array.from(e.currentTarget.querySelectorAll('table'));
        if (all.length !== blocks.length) {
            setNotice('미리보기의 표와 원문 표의 위치를 맞추지 못했습니다. 원문에서 표 안에 커서를 두고 [표 편집]을 누르세요.');
            return;
        }
        openBlock(blocks[all.indexOf(el)]);
    };

    const segBtn = (m: ViewMode, text: string) => (
        <button
            key={m}
            type="button"
            onClick={() => setMode(m)}
            className={`h-6 rounded-md px-2.5 text-[11.5px] font-semibold ${mode === m ? 'bg-brand text-white' : 'text-ink/70 hover:text-ink'}`}
        >
            {text}
        </button>
    );

    if (table) {
        return (
            <div className="h-[calc(100vh-345px)] min-h-[380px]">
                <TableEditor
                    key={`${table.start}-${table.end}-${table.isNew}`}
                    initial={table.grid}
                    initialFormat={table.format}
                    isNew={table.isNew}
                    onApply={applyTable}
                    onCancel={() => setTable(null)}
                    onDelete={deleteTable}
                />
            </div>
        );
    }

    return (
        <div>
            <div className="mb-2 flex flex-wrap items-center gap-2">
                <div className="inline-flex rounded-lg border border-line bg-white p-0.5">
                    {segBtn('source', '원문')}
                    {segBtn('split', '나란히')}
                    {segBtn('preview', '미리보기')}
                </div>
                <span className="min-w-0 flex-1 truncate text-[11.5px] text-muted">
                    {blockAtCursor
                        ? `커서가 ${blockAtCursor.kind === 'html' ? 'HTML' : '마크다운'} 표 안에 있습니다`
                        : '마크다운과 HTML을 함께 쓸 수 있습니다. 표를 누르면 표 편집기가 열립니다'}
                </span>
                <button
                    type="button"
                    onClick={() => blockAtCursor && openBlock(blockAtCursor)}
                    disabled={disabled || !blockAtCursor}
                    className="h-7 rounded-md border border-line bg-white px-2 text-[11.5px] font-semibold text-ink/80 hover:border-brand hover:text-brand disabled:opacity-40 disabled:hover:border-line disabled:hover:text-ink/80"
                >
                    표 편집
                </button>
                <button
                    type="button"
                    onClick={openNew}
                    disabled={disabled}
                    className="h-7 rounded-md border border-line bg-white px-2 text-[11.5px] font-semibold text-ink/80 hover:border-brand hover:text-brand disabled:opacity-40"
                >
                    표 삽입
                </button>
            </div>
            {notice && <p role="status" className="mb-2 text-[11.5px] text-warn">{notice}</p>}

            <div className={`grid h-[calc(100vh-385px)] min-h-[340px] gap-3 ${mode === 'split' ? 'grid-cols-2' : 'grid-cols-1'}`}>
                {mode !== 'preview' && (
                    <textarea
                        ref={textareaRef}
                        value={value}
                        onChange={(e) => {
                            onChange(e.target.value);
                            setCursor(e.target.selectionStart);
                        }}
                        onSelect={(e) => setCursor(e.currentTarget.selectionStart)}
                        disabled={disabled}
                        autoFocus
                        spellCheck={false}
                        aria-label={`${label} 원문`}
                        className="h-full w-full resize-none rounded-lg border border-line px-3 py-2 font-mono text-[12px] leading-relaxed focus:outline-none focus:border-brand disabled:opacity-50"
                    />
                )}
                {mode !== 'source' && (
                    <div
                        onClick={onPreviewClick}
                        className={`h-full overflow-auto rounded-lg border border-divide bg-surface/50 px-4 py-3 ${PAGE_PROSE_CLASS} [&_table]:cursor-pointer [&_table:hover]:outline-2 [&_table:hover]:outline-brand/60`}
                    >
                        {value.trim()
                            ? <PageMarkdown text={value} tableTitle="눌러서 표 편집" />
                            : <p className="text-muted">(빈 페이지)</p>}
                    </div>
                )}
            </div>
        </div>
    );
}
