import {
    MDXEditor,
    headingsPlugin,
    listsPlugin,
    quotePlugin,
    thematicBreakPlugin,
    linkPlugin,
    linkDialogPlugin,
    imagePlugin,
    tablePlugin,
    codeBlockPlugin,
    codeMirrorPlugin,
    markdownShortcutPlugin,
    toolbarPlugin,
    UndoRedo,
    Separator,
    BoldItalicUnderlineToggles,
    CodeToggle,
    ListsToggle,
    BlockTypeSelect,
    CreateLink,
    InsertImage,
    InsertTable,
    InsertThematicBreak,
} from '@mdxeditor/editor';

/** WYSIWYG 마크다운 에디터 (preview + 수정 통합) */
export function MarkdownEditor({
                            markdown,
                            onChange,
                        }: {
    markdown: string;
    onChange: (md: string) => void;
}) {
    console.log(markdown);
    const html_to_markdown = convertHtmlTablesToMarkdown(markdown);

    return (
        <MDXEditor
            markdown={html_to_markdown}
            onChange={onChange}
            onError={(e) => console.warn('MDXEditor parse:', e)}
            contentEditableClassName="mdx-content prose prose-slate prose-sm max-w-none"
            plugins={[
                headingsPlugin(),
                listsPlugin(),
                quotePlugin(),
                thematicBreakPlugin(),
                linkPlugin(),
                linkDialogPlugin(),
                imagePlugin(),
                tablePlugin(),
                // 코드펜스가 OCR 결과에 섞여 있을 수 있어 둘 다 등록 (없으면 파싱 에러)
                codeBlockPlugin({ defaultCodeBlockLanguage: 'text' }),
                codeMirrorPlugin({
                    codeBlockLanguages: {
                        text: 'Text',
                        js: 'JavaScript',
                        ts: 'TypeScript',
                        python: 'Python',
                        bash: 'Bash',
                        json: 'JSON',
                    },
                }),
                markdownShortcutPlugin(),
                toolbarPlugin({
                    toolbarContents: () => (
                        <>
                            <UndoRedo />
                            <Separator />
                            <BoldItalicUnderlineToggles />
                            <CodeToggle />
                            <Separator />
                            <ListsToggle />
                            <BlockTypeSelect />
                            <Separator />
                            <CreateLink />
                            <InsertImage />
                            <InsertTable />
                            <InsertThematicBreak />
                        </>
                    ),
                }),
            ]}
        />
    );
}

/** 셀 텍스트 정리: 공백 축약, 줄바꿈 제거, 파이프 이스케이프 */
function cellText(cell: Element): string {
    return (cell.textContent || '')
        .replace(/\u00a0/g, ' ')
        .replace(/\s+/g, ' ')
        .trim()
        .replace(/\|/g, '\\|');
}

/** 단일 <table> 요소를 GFM 마크다운 표로 변환 */
function tableElementToMarkdown(table: HTMLTableElement): string {
    const rows = Array.from(table.querySelectorAll('tr'));
    if (rows.length === 0) return '';

    // colspan 만큼 셀을 펼쳐 그리드 구성 (rowspan은 단순 무시)
    const grid: string[][] = rows.map((tr) => {
        const out: string[] = [];
        Array.from(tr.children).forEach((cell) => {
            if (!/^(td|th)$/i.test(cell.tagName)) return;
            const span = parseInt(cell.getAttribute('colspan') || '1', 10) || 1;
            out.push(cellText(cell));
            for (let i = 1; i < span; i++) out.push('');
        });
        return out;
    });

    // 앞쪽의 완전히 빈 행 제거 (OCR 표의 빈 헤더 행 대응)
    let start = 0;
    while (start < grid.length && grid[start].every((c) => c === '')) start++;
    const body = grid.slice(start);
    if (body.length === 0) return '';

    const cols = Math.max(...body.map((r) => r.length));
    const pad = (r: string[]) => {
        const c = [...r];
        while (c.length < cols) c.push('');
        return c;
    };

    const header = pad(body[0]);
    const lines = [
        `| ${header.join(' | ')} |`,
        `| ${header.map(() => '---').join(' | ')} |`,
        ...body.slice(1).map((r) => `| ${pad(r).join(' | ')} |`),
    ];
    return lines.join('\n');
}

/** 마크다운 안의 HTML <table> 블록을 모두 GFM 마크다운 표로 변환 */
function convertHtmlTablesToMarkdown(markdown: string): string {
    if (!markdown || !/<table[\s\S]*?<\/table>/i.test(markdown)) return markdown;

    // <table>을 감싸는 <div ...> / <html><body> 래퍼까지 함께 치환
    const BLOCK =
        /(?:<div[^>]*>\s*)?(?:<html>\s*<body>\s*)?<table[\s\S]*?<\/table>(?:\s*<\/body>\s*<\/html>)?(?:\s*<\/div>)?/gi;

    return markdown.replace(BLOCK, (block) => {
        const tableHtml = block.match(/<table[\s\S]*?<\/table>/i)?.[0];
        if (!tableHtml) return block;
        try {
            const doc = new DOMParser().parseFromString(tableHtml, 'text/html');
            const table = doc.querySelector('table');
            if (!table) return block;
            const md = tableElementToMarkdown(table as HTMLTableElement);
            return md ? `\n\n${md}\n\n` : block;
        } catch {
            return block;
        }
    });
}