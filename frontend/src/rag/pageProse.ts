/** 파일 검수 화면의 페이지 텍스트(마크다운 + HTML 표) 본문 스타일 */
export const PAGE_PROSE_CLASS = [
    'prose prose-slate prose-sm max-w-none break-words',
    '[&_table]:border-collapse [&_table]:text-[12px] [&_table]:my-3',
    '[&_th]:border [&_th]:border-line [&_th]:bg-surface [&_th]:px-2 [&_th]:py-1 [&_th]:align-middle',
    '[&_td]:border [&_td]:border-line [&_td]:px-2 [&_td]:py-1 [&_td]:align-middle',
].join(' ');
