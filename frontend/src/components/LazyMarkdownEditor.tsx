import { lazy } from 'react';

/**
 * 메인 청크에 있는 화면(메일 승인 등)에서 쓰는 지연 로딩 MarkdownEditor.
 * MDXEditor가 끌고 오는 prismjs는 전역 `Prism`이 먼저 서 있어야 하므로(Root.tsx 참고)
 * 코어를 먼저 평가한 뒤 에디터와 스타일을 별도 청크로 불러온다.
 */
export const LazyMarkdownEditor = lazy(async () => {
    const prism = await import('prismjs');
    const g = globalThis as typeof globalThis & { Prism?: unknown };
    g.Prism ??= prism.default;
    await import('@mdxeditor/editor/style.css');
    const { MarkdownEditor } = await import('./MarkdownEditor');
    return { default: MarkdownEditor };
});
