import React, { useState, useRef, useEffect, useCallback } from 'react';
import ReactMarkdown, { defaultUrlTransform } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeRaw from 'rehype-raw';
import rehypeSanitize,{defaultSchema} from 'rehype-sanitize';
import { renderToStaticMarkup } from 'react-dom/server';
import JSZip from 'jszip';

import '@mdxeditor/editor/style.css';
import type {FileStatus, OcrFile, OcrPageInfo, Selection, PreviewMode, CopyStatus, OcrResponse, OcrMarkdownImage} from './types';
import {ImageWithBoxes} from "./components/ImageWithBoxes.tsx";
import {MarkdownEditor} from "./components/MarkdownEditor.tsx";
import {
    AlertIcon,
    CheckIcon,
    ChevronIcon,
    CloseIcon,
    CopyIcon,
    DocumentIcon,
    DownloadIcon,
    LogoMark,
    PageIcon,
    RetryIcon,
    UploadIcon,
} from './components/icons.tsx';

/**
 * OCR Tool
 * - 좌측: 파일 업로드 + 리스트 (PDF는 펼치기/접기로 페이지 단위 선택 가능)
 * - 우측: 선택된 파일 또는 PDF 단일 페이지의 OCR 결과
 *   · Source Image 패널에 OCR 블록(bbox) 영역을 오버레이로 표시 (토글 가능)
 *   · Preview(markdown) 모드는 WYSIWYG 에디터로 바로 수정 가능
 *   · 수정 결과는 pages[index].markdown 에 반영되어 복사/다운로드/HTML에 자동 적용
 * - 다운로드: (1) 현재 선택 항목 (2) 업로드된 모든 파일 일괄 (PDF는 페이지 합쳐서 단일 .md)
 */

const sanitizeSchema = {
    ...defaultSchema,
    protocols: {
        ...defaultSchema.protocols,
        src: [...(defaultSchema.protocols?.src || []), 'data'],
    },
}

/**
 * react-markdown은 보안상 기본적으로 data: URI를 차단한다(sanitize 스키마와는 별개의 레이어).
 * OCR 결과 이미지가 base64 data URI로 인라인되므로, data: 스킴만 예외로 통과시킨다.
 */
function allowDataUrlTransform(url: string): string {
    if (url.startsWith('data:')) return url;
    return defaultUrlTransform(url);
}


// ===== 마크다운 -> HTML 변환기 =====
/** 마크다운 문자열을 HTML 문자열로 변환 (## -> <h2> 등) */
function markdownToHtml(markdown: string): string {
    if (!markdown) return '';
    try {
        return renderToStaticMarkup(
            <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                rehypePlugins={[rehypeRaw, [rehypeSanitize, sanitizeSchema]]}
                urlTransform={allowDataUrlTransform}
            >
                {markdown}
            </ReactMarkdown>
        );
    } catch {
        return markdown;
    }
}

/** 저장/미리보기용으로 본문 HTML을 완전한 HTML 문서로 감싸기 */
function wrapHtmlDocument(bodyHtml: string, title: string): string {
    return `<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>${escapeHtml(title)}</title>
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; line-height: 1.7; color: #1e293b; max-width: 860px; margin: 2rem auto; padding: 0 1.5rem; }
  h1, h2, h3, h4 { line-height: 1.3; margin-top: 1.6em; }
  h1 { font-size: 1.8em; border-bottom: 1px solid #e2e8f0; padding-bottom: .3em; }
  h2 { font-size: 1.5em; border-bottom: 1px solid #e2e8f0; padding-bottom: .3em; }
  h3 { font-size: 1.25em; }
  code { background: #f1f5f9; padding: .15em .4em; border-radius: 4px; font-size: .9em; }
  pre { background: #f1f5f9; padding: 1em; border-radius: 8px; overflow-x: auto; }
  pre code { background: none; padding: 0; }
  table { border-collapse: collapse; width: 100%; margin: 1em 0; }
  th, td { border: 1px solid #cbd5e1; padding: .5em .75em; text-align: left; }
  th { background: #f8fafc; }
  blockquote { border-left: 4px solid #cbd5e1; margin: 1em 0; padding: .2em 1em; color: #475569; }
  img { max-width: 100%; }
  hr { border: none; border-top: 1px solid #e2e8f0; margin: 2em 0; }
</style>
</head>
<body>
${bodyHtml}
</body>
</html>`;
}

function escapeHtml(s: string): string {
    return s
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

/** OCR 서버가 돌려주는 상대경로(imgs/...)를 비교 가능한 형태로 정규화 */
function normalizeImagePath(p: string): string {
    try {
        return decodeURIComponent(p).trim().replace(/\\/g, '/').replace(/^\.\//, '');
    } catch {
        return p.trim().replace(/\\/g, '/').replace(/^\.\//, '');
    }
}

/**
 * markdown 본문의 `<img src="imgs/...">` / `![alt](imgs/...)` 상대경로 참조를
 * markdown_images 배열의 base64(data:) 데이터로 치환한다.
 * (서버가 markdown 텍스트와 이미지 바이너리를 분리해서 내려주기 때문에 필요)
 */
function resolveMarkdownImages(
    markdown: string,
    images: OcrMarkdownImage[] | undefined | null
): string {
    if (!markdown || !images || images.length === 0) return markdown;

    const map = new Map<string, string>();
    images.forEach((img) => {
        if (img?.path && img?.image) map.set(normalizeImagePath(img.path), img.image);
    });
    if (map.size === 0) return markdown;

    // <img ... src="...">  (rehype-raw로 그대로 렌더링되는 raw HTML 태그)
    let resolved = markdown.replace(
        /(<img\b[^>]*?\bsrc\s*=\s*)(["'])([^"']+)\2/gi,
        (match, prefix, quote, src) => {
            const data = map.get(normalizeImagePath(src));
            return data ? `${prefix}${quote}${data}${quote}` : match;
        }
    );

    // ![alt](path "title")  (표준 마크다운 이미지 문법)
    resolved = resolved.replace(
        /!\[([^\]]*)\]\(([^)\s]+)((?:\s+"[^"]*")?)\)/g,
        (match, alt, src, title) => {
            const data = map.get(normalizeImagePath(src));
            return data ? `![${alt}](${data}${title})` : match;
        }
    );

    return resolved;
}

/** data:image/...;base64,... 문자열을 바이너리(Uint8Array)로 디코딩 */
function dataUrlToBytes(dataUrl: string): Uint8Array | null {
    const match = /^data:[^;]+;base64,(.+)$/.exec(dataUrl);
    if (!match) return null;
    const binary = atob(match[1]);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
    return bytes;
}

/**
 * 마크다운(이미지 base64 치환 없이 서버가 내려준 상대경로 그대로 유지) +
 * markdown_images를 디코딩한 실제 이미지 파일(img/...)을 하나의 zip으로 묶어 다운로드한다.
 */
async function downloadMarkdownAsZip(pages: OcrPageInfo[], baseName: string) {
    const zip = new JSZip();

    const md =
        pages.length <= 1
            ? (pages[0]?.markdown ?? '')
            : pages
                .map((p, i) => `<!-- Page ${i + 1} -->\n\n${p.markdown}`)
                .join('\n\n---\n\n');

    zip.file(`${baseName}.md`, md);

    const added = new Set<string>();
    pages.forEach((p) => {
        (p.markdown_images || []).forEach((img) => {
            if (!img?.path || !img?.image) return;
            const path = normalizeImagePath(img.path);
            if (added.has(path)) return;
            const bytes = dataUrlToBytes(img.image);
            if (!bytes) return;
            zip.file(path, bytes);
            added.add(path);
        });
    });

    const blob = await zip.generateAsync({ type: 'blob' });
    triggerBlobDownload(blob, `${baseName}.zip`);
}

export default function App() {
    const [files, setFiles] = useState<OcrFile[]>([]);
    const [selection, setSelection] = useState<Selection | null>(null);
    const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());
    const [isDragOver, setIsDragOver] = useState<boolean>(false);
    const [copyStatus, setCopyStatus] = useState<CopyStatus>('');
    const [previewMode, setPreviewMode] = useState<PreviewMode>('markdown');
    const [showBoxes, setShowBoxes] = useState<boolean>(true);
    const fileInputRef = useRef<HTMLInputElement>(null);



    const selectedFile: OcrFile | null =
        files.find((f) => f.id === selection?.fileId) || null;

    /** 화면에 표시할 페이지들 (단일 페이지 선택이면 그 페이지, 아니면 전체) */
    const selectedPages: OcrPageInfo[] = (() => {
        if (!selectedFile) return [];
        if (selection?.pageIndex != null && selectedFile.pages[selection.pageIndex]) {
            return [selectedFile.pages[selection.pageIndex]];
        }
        return selectedFile.pages;
    })();

    /** 현재 화면에 표시할 markdown (PDF + 단일 페이지 선택이면 그 페이지만, 아니면 전체 합본) */
    const currentMarkdown: string = (() => {
        if (!selectedFile) return '';
        if (
            selection?.pageIndex !== null &&
            selection?.pageIndex !== undefined &&
            selectedFile.pages[selection.pageIndex]
        ) {
            const page = selectedFile.pages[selection.pageIndex];
            return resolveMarkdownImages(page.markdown, page.markdown_images);
        }
        return joinPages(selectedFile.pages);
    })();

    /** 편집 가능한 페이지 인덱스
     *  - 특정 페이지 선택 → 그 페이지
     *  - 단일 이미지(페이지 1개) → 0
     *  - 다중 페이지 PDF 전체 보기 → null (합본은 편집 비활성) */
    const editablePageIndex: number | null = (() => {
        if (!selectedFile) return null;
        if (selection?.pageIndex != null) return selection.pageIndex;
        if (selectedFile.pages.length === 1) return 0;
        return null;
    })();

    /** 편집 결과를 해당 페이지 markdown에 반영 → 복사/다운로드/HTML이 자동으로 따라옴 */
    const handleMarkdownEdit = (newMarkdown: string) => {
        if (!selectedFile || editablePageIndex === null) return;
        const fileId = selectedFile.id;
        setFiles((prev) =>
            prev.map((f) =>
                f.id === fileId
                    ? {
                        ...f,
                        pages: f.pages.map((p, i) =>
                            i === editablePageIndex ? { ...p, markdown: newMarkdown } : p
                        ),
                    }
                    : f
            )
        );
    };

    /** 현재 표시 제목 (PDF 단일 페이지면 "파일명 — Page N") */
    const currentTitle: string = (() => {
        if (!selectedFile) return 'OCR 결과';
        if (
            selection?.pageIndex !== null &&
            selection?.pageIndex !== undefined &&
            isPdf(selectedFile)
        ) {
            return `${selectedFile.name} — Page ${selection.pageIndex + 1}`;
        }
        return selectedFile.name;
    })();

    /** HTML 모드일 때 변환된 HTML 본문 */
    const currentHtmlBody: string =
        previewMode === 'html' ? markdownToHtml(currentMarkdown) : '';

    /** 저장/표시용 완전한 HTML 문서 */
    const currentHtmlDocument: string =
        previewMode === 'html'
            ? wrapHtmlDocument(currentHtmlBody, currentTitle)
            : '';

    // ===== 파일 추가 =====
    const handleAddFiles = useCallback((fileList: FileList | File[]) => {
        const accepted = Array.from(fileList).filter(
            (f) => f.type.startsWith('image/') || f.type === 'application/pdf'
        );
        if (accepted.length === 0) return;

        const newItems: OcrFile[] = accepted.map((file) => ({
            id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
            file,
            name: file.name,
            type: file.type,
            size: file.size,
            status: 'pending',
            pages: [],
            error: '',
        }));

        setFiles((prev) => [...prev, ...newItems]);
        setSelection((prev) => prev ?? { fileId: newItems[0].id, pageIndex: null });

        newItems.forEach((item) => runOcr(item));
    }, []);

    // ===== OCR 호출 =====
    const runOcr = useCallback(async (item: OcrFile): Promise<void> => {
        setFiles((prev) =>
            prev.map((f) =>
                f.id === item.id ? { ...f, status: 'processing', error: '' } : f
            )
        );

        try {
            const formData = new FormData();
            formData.append('files', item.file);

            const response = await fetch('http://127.0.0.1:8082/ocr/run_ocr', {
                method: 'POST',
                body: formData,
            });
            if (!response.ok) {
                throw new Error(`Server responded with ${response.status}`);
            }
            const data: OcrResponse = await response.json();
            const result = data.results[0];
            console.log(data);

            const pages: OcrPageInfo[] = result?.fileinfo ?? [];

            setFiles((prev) =>
                prev.map((f) =>
                    f.id === item.id ? { ...f, status: 'done', pages } : f
                )
            );

            // PDF + 다중 페이지면 기본적으로 펼침
            if (pages.length > 1) {
                setExpandedIds((prev) => {
                    const next = new Set(prev);
                    next.add(item.id);
                    return next;
                });
            }
        } catch (err) {
            const message = err instanceof Error ? err.message : 'OCR 실패';
            setFiles((prev) =>
                prev.map((f) =>
                    f.id === item.id ? { ...f, status: 'error', error: message } : f
                )
            );
        }
    }, []);

    // ===== 이벤트 핸들러 =====
    const onInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        if (e.target.files) handleAddFiles(e.target.files);
        e.target.value = '';
    };

    const onDrop = (e: React.DragEvent<HTMLDivElement>) => {
        e.preventDefault();
        setIsDragOver(false);
        if (e.dataTransfer.files?.length) handleAddFiles(e.dataTransfer.files);
    };

    const onDragOver = (e: React.DragEvent<HTMLDivElement>) => {
        e.preventDefault();
        setIsDragOver(true);
    };

    const onDragLeave = () => setIsDragOver(false);

    const removeFile = (id: string) => {
        setFiles((prev) => {
            const next = prev.filter((f) => f.id !== id);
            if (selection?.fileId === id) {
                setSelection(next[0] ? { fileId: next[0].id, pageIndex: null } : null);
            }
            return next;
        });
        setExpandedIds((prev) => {
            const next = new Set(prev);
            next.delete(id);
            return next;
        });
    };

    const retryOcr = (id: string) => {
        const target = files.find((f) => f.id === id);
        if (target) runOcr(target);
    };

    const toggleExpand = (id: string) => {
        setExpandedIds((prev) => {
            const next = new Set(prev);
            if (next.has(id)) next.delete(id);
            else next.add(id);
            return next;
        });
    };

    // ===== 다운로드 =====
    /** 현재 선택된 항목(파일 전체 또는 PDF 단일 페이지) 다운로드
     *  - markdown: .md + img/ 폴더(실제 이미지 파일)를 zip으로 묶어서 다운로드
     *  - html: base64 인라인된 단일 .html 파일로 다운로드 */
    const downloadCurrent = () => {
        if (!selectedFile || selectedFile.status !== 'done') return;
        if (!currentMarkdown) return;

        const isSinglePage =
            selection?.pageIndex !== null &&
            selection?.pageIndex !== undefined &&
            isPdf(selectedFile);
        const baseName = stripExt(selectedFile.name);
        const suffix = isSinglePage ? `_page_${(selection!.pageIndex as number) + 1}` : '';

        if (previewMode === 'html') {
            triggerDownload(
                currentHtmlDocument,
                `${baseName}${suffix}.html`,
                'text/html;charset=utf-8'
            );
            return;
        }

        const pages = isSinglePage
            ? [selectedFile.pages[selection!.pageIndex as number]]
            : selectedFile.pages;
        void downloadMarkdownAsZip(pages, `${baseName}${suffix}`);
    };

    /** 업로드된 모든 파일을 개별 다운로드 (현재 미리보기 모드 기준으로 .md+img zip 또는 .html) */
    const downloadAll = () => {
        const ready = files.filter((f) => f.status === 'done' && f.pages.length > 0);
        if (ready.length === 0) return;

        const isHtml = previewMode === 'html';

        ready.forEach((f, i) => {
            const baseName = stripExt(f.name);
            // 브라우저가 동시 다운로드를 차단하는 것을 피하기 위해 약간의 지연
            setTimeout(() => {
                if (isHtml) {
                    const md = joinPages(f.pages);
                    const content = wrapHtmlDocument(markdownToHtml(md), baseName);
                    triggerDownload(content, `${baseName}.html`, 'text/html;charset=utf-8');
                } else {
                    void downloadMarkdownAsZip(f.pages, baseName);
                }
            }, i * 150);
        });
    };

    const copyMd = async () => {
        const text = previewMode === 'html' ? currentHtmlDocument : currentMarkdown;
        if (!text) return;
        try {
            await navigator.clipboard.writeText(text);
            setCopyStatus('copied');
        } catch {
            setCopyStatus('failed');
        }
        setTimeout(() => setCopyStatus(''), 1500);
    };

    useEffect(() => {
        const handlePaste = (e: ClipboardEvent) => {
            const items = e.clipboardData?.items;
            if (!items)
                return;

            const imageFiles: File[] = [];
            for (const item of Array.from(items)) {
                if (item.type.startsWith("image/")) {
                    const file = item.getAsFile();
                    if (file) {
                        const ext = item.type.split("/")[1] || 'png';
                        const named = new File(
                            [file],
                            `paste_${Date.now()}.${ext}`,
                            { type: item.type }
                        )
                        imageFiles.push(named);
                        break;
                    }
                }
            }

            if (imageFiles.length > 0) {
                e.preventDefault(); // 텍스트 붙여넣기 방지
                handleAddFiles(imageFiles);

            }
        };

        document.addEventListener('paste', handlePaste);
        return () => document.removeEventListener('paste', handlePaste);

    }, [handleAddFiles]);

    const doneCount = files.filter((f) => f.status === 'done').length;

    const canAct = !!selectedFile && selectedFile.status === 'done';

    // ===== 렌더링 =====
    return (
        <div className="flex h-screen w-full bg-white text-ink font-sans antialiased">
            {/* ===== 왼쪽 패널 ===== */}
            <aside className="w-[332px] min-w-[332px] shrink-0 flex flex-col pl-7 pr-[18px] py-7">
                {/* 로고 */}
                <div className="shrink-0">
                    <div className="flex items-center gap-2">
                        <LogoMark className="w-[21px] h-[21px]" />
                        <span className="text-[17px] font-bold tracking-tight leading-none">
                            TG OCR
                        </span>
                    </div>
                    <p className="mt-[8px] pl-[23px] text-[10px] leading-none text-muted">
                        이미지를 문자로, 빠르고 정확하게
                    </p>
                </div>

                {/* 파일 입력 */}
                <h2 className="mt-[26px] shrink-0 text-[13px] font-semibold">파일 업로드</h2>
                <div
                    onClick={() => fileInputRef.current?.click()}
                    onDrop={onDrop}
                    onDragOver={onDragOver}
                    onDragLeave={onDragLeave}
                    className={`
                        mt-[9px] h-[130px] shrink-0 cursor-pointer rounded-xl border border-dashed
                        flex flex-col items-center justify-center text-center transition-colors
                        ${isDragOver
                        ? 'border-brand bg-brand-tint'
                        : 'border-line bg-surface hover:border-brand/50 hover:bg-brand-tint/60'}
                    `}
                >
                    <UploadIcon className="w-[26px] h-[26px] text-muted" />
                    <p className="mt-[9px] text-[13px] font-medium text-muted">
                        클릭하거나 파일을 드래그하세요
                    </p>
                    <p className="mt-[5px] text-[11px] text-muted/70">
                        이미지(PNG, JPG 등) 또는 PDF
                    </p>
                </div>
                <input
                    ref={fileInputRef}
                    type="file"
                    accept="image/*,application/pdf"
                    multiple
                    onChange={onInputChange}
                    className="hidden"
                />

                {/* 리스트 헤더 + 전체 다운로드 */}
                <div className="mt-[38px] shrink-0 flex items-center justify-between">
                    <h2 className="text-[13px] font-semibold">
                        업로드된 파일({files.length})
                    </h2>
                    <button
                        onClick={downloadAll}
                        disabled={doneCount === 0}
                        className="h-6 px-2.5 rounded-lg border border-line bg-white text-[11px] text-ink hover:bg-surface disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                        title="완료된 모든 파일을 다운로드"
                    >
                        전체 다운로드
                    </button>
                </div>

                {/* 파일 리스트 */}
                <div className="mt-[5px] flex-1 min-h-0 overflow-y-auto">
                    {files.length === 0 ? (
                        <div className="h-14 rounded-xl border border-line bg-white flex items-center justify-center text-[11px] text-muted">
                            아직 업로드된 파일이 없습니다.
                        </div>
                    ) : (
                        <ul className="space-y-2">
                            {files.map((f) => {
                                const isExpanded = expandedIds.has(f.id);
                                const isPdfFile = isPdf(f);
                                const hasPages = f.pages.length > 1;
                                const isFileSelected = selection?.fileId === f.id;

                                return (
                                    <li key={f.id}>
                                        <div
                                            onClick={() =>
                                                setSelection({ fileId: f.id, pageIndex: null })
                                            }
                                            className={`
                                                rounded-xl border cursor-pointer transition-colors
                                                ${isFileSelected
                                                ? 'border-brand bg-brand-tint'
                                                : 'border-line bg-white hover:bg-surface'}
                                            `}
                                        >
                                            {/* 파일 행 */}
                                            <div className="h-14 flex items-center gap-[9px] pl-2 pr-3.5">
                                                {/* 확장자 뱃지 */}
                                                <div
                                                    className={`w-10 h-10 shrink-0 rounded-lg flex items-center justify-center text-[11px] font-bold uppercase ${extBadgeColor(f.name)}`}
                                                >
                                                    {getExt(f.name)}
                                                </div>

                                                {/* 정보 */}
                                                <div className="flex-1 min-w-0">
                                                    <p className="text-[13px] font-semibold truncate">
                                                        {f.name}
                                                    </p>
                                                    <div className="mt-[3px] flex items-center gap-1.5 flex-wrap">
                                                        <StatusBadge status={f.status} />
                                                        {isPdfFile && f.pages.length > 0 && (
                                                            <span className="text-[11px] text-muted">
                                                                {f.pages.length} pages
                                                            </span>
                                                        )}
                                                        <span className="text-[11px] text-muted">
                                                            {(f.size / 1024).toFixed(1)} KB
                                                        </span>
                                                    </div>
                                                </div>

                                                {/* 액션 */}
                                                <div className="shrink-0 self-stretch py-[13px] flex flex-col items-end justify-between">
                                                    <div className="flex items-center gap-2 text-muted">
                                                        {f.status === 'error' && (
                                                            <button
                                                                onClick={(e) => {
                                                                    e.stopPropagation();
                                                                    retryOcr(f.id);
                                                                }}
                                                                className="hover:text-brand transition-colors"
                                                                title="다시 시도"
                                                            >
                                                                <RetryIcon />
                                                            </button>
                                                        )}
                                                        <button
                                                            onClick={(e) => {
                                                                e.stopPropagation();
                                                                removeFile(f.id);
                                                            }}
                                                            className="hover:text-danger transition-colors"
                                                            title="삭제"
                                                        >
                                                            <CloseIcon />
                                                        </button>
                                                    </div>

                                                    {/* 펼치기 (PDF + 다중 페이지일 때만) */}
                                                    {hasPages && (
                                                        <button
                                                            onClick={(e) => {
                                                                e.stopPropagation();
                                                                toggleExpand(f.id);
                                                            }}
                                                            className="text-muted hover:text-ink transition-colors"
                                                            title={isExpanded ? '접기' : '펼치기'}
                                                        >
                                                            <ChevronIcon
                                                                className={`w-2 h-[5px] transition-transform ${isExpanded ? '' : '-rotate-90'}`}
                                                            />
                                                        </button>
                                                    )}
                                                </div>
                                            </div>

                                            {/* 페이지 리스트 (펼침 상태) */}
                                            {isExpanded && hasPages && (
                                                <ul className="border-t border-divide bg-surface rounded-b-xl px-[17px] py-2 space-y-[1px]">
                                                    {f.pages.map((p, i) => {
                                                        const isPageSelected =
                                                            selection?.fileId === f.id &&
                                                            selection?.pageIndex === i;
                                                        return (
                                                            <li
                                                                key={i}
                                                                onClick={(e) => {
                                                                    e.stopPropagation();
                                                                    setSelection({
                                                                        fileId: f.id,
                                                                        pageIndex: i,
                                                                    });
                                                                }}
                                                                className={`
                                                                    h-6 px-2 rounded-md flex items-center gap-2 text-[11px] cursor-pointer transition-colors
                                                                    ${isPageSelected
                                                                    ? 'bg-brand-soft text-brand'
                                                                    : 'hover:bg-chip'}
                                                                `}
                                                            >
                                                                <PageIcon
                                                                    className={`w-[7px] h-[9px] shrink-0 ${isPageSelected ? 'text-brand' : 'text-muted'}`}
                                                                />
                                                                <span className="font-medium">
                                                                    Page {i + 1}
                                                                </span>
                                                                <span
                                                                    className={`truncate ${isPageSelected ? 'text-brand/70' : 'text-muted'}`}
                                                                >
                                                                    · {p.markdown.length.toLocaleString()} chars
                                                                </span>
                                                            </li>
                                                        );
                                                    })}
                                                </ul>
                                            )}
                                        </div>
                                    </li>
                                );
                            })}
                        </ul>
                    )}
                </div>
            </aside>

            {/* ===== 오른쪽 패널 ===== */}
            <main className="flex-1 min-w-0 pt-7 pr-7 pb-7">
                <div className="h-full flex flex-col rounded-2xl border border-line bg-surface overflow-hidden">
                    {/* 헤더 */}
                    <header className="h-[66px] shrink-0 pl-5 pr-[18px] flex items-center justify-between gap-4 border-b border-divide">
                        <div className="min-w-0">
                            <h1 className="text-[15px] font-bold leading-none">OCR 결과</h1>
                            <p className="mt-[7px] text-[13px] leading-none text-muted truncate">
                                {selectedFile ? currentTitle : '왼쪽에서 파일을 선택하세요'}
                            </p>
                        </div>

                        <div className="shrink-0 flex items-center gap-3.5">
                            {selectedFile && <StatusPill status={selectedFile.status} />}
                            <div className="flex items-center gap-[7px]">
                                <IconButton
                                    label={
                                        copyStatus === 'copied'
                                            ? '복사됨'
                                            : copyStatus === 'failed'
                                                ? '복사 실패'
                                                : '복사'
                                    }
                                    onClick={copyMd}
                                    disabled={!canAct}
                                >
                                    {copyStatus === 'copied' ? <CheckIcon /> : <CopyIcon />}
                                </IconButton>
                                <IconButton
                                    label={previewMode === 'html' ? 'HTML저장' : 'MD저장'}
                                    onClick={downloadCurrent}
                                    disabled={!canAct}
                                    variant="primary"
                                >
                                    <DownloadIcon />
                                </IconButton>
                            </div>
                        </div>
                    </header>

                    {/* 결과 영역 */}
                    <div className="flex-1 min-h-0">
                        {!selectedFile && (
                            <EmptyState message="왼쪽에서 파일을 업로드하거나 선택해주세요" />
                        )}

                        {selectedFile?.status === 'pending' && (
                            <EmptyState message="대기 중..." />
                        )}

                        {selectedFile?.status === 'processing' && (
                            <div className="h-full flex flex-col items-center justify-center">
                                <div className="w-[46px] h-[46px] rounded-full border-[5px] border-brand-pale border-t-brand animate-spin" />
                                <p className="mt-[34px] text-[15px] font-medium">OCR 처리 중</p>
                            </div>
                        )}

                        {selectedFile?.status === 'error' && (
                            <div className="px-6 pt-[22px] flex justify-center">
                                <div className="w-full max-w-[386px] rounded-xl border border-danger bg-danger-surface px-6 py-[13px] flex gap-6">
                                    <AlertIcon className="w-6 h-6 shrink-0 text-danger" />
                                    <div className="min-w-0 text-[13px] leading-[18px]">
                                        <p className="font-bold text-danger">OCR 처리 실패</p>
                                        <p className="text-danger break-words">
                                            {selectedFile.error}
                                        </p>
                                        <button
                                            onClick={() => retryOcr(selectedFile.id)}
                                            className="block text-danger/70 hover:text-danger transition-colors"
                                        >
                                            다시 시도
                                        </button>
                                    </div>
                                </div>
                            </div>
                        )}

                        {selectedFile?.status === 'done' && (
                            <div className="flex h-full">
                                {/* Raw (원본 이미지 + OCR 블록 오버레이) */}
                                <div className="flex-1 flex flex-col min-w-0">
                                    <div className="h-14 shrink-0 px-5 flex items-center justify-between">
                                        <span className="text-[14px] font-bold">Source Image</span>
                                        <button
                                            onClick={() => setShowBoxes((v) => !v)}
                                            className={`h-6 px-3 rounded-lg border text-[12px] font-semibold transition-colors ${
                                                showBoxes
                                                    ? 'border-brand bg-brand-tint text-ink'
                                                    : 'border-line bg-white text-muted hover:text-ink'
                                            }`}
                                            title="OCR 블록 영역 표시/숨김"
                                        >
                                            Boxes
                                        </button>
                                    </div>
                                    <div className="flex-1 overflow-auto flex flex-col items-center gap-4 px-5 pt-2 pb-5 min-h-0">
                                        {selectedPages.length > 0 ? (
                                            selectedPages.map((page, idx) => (
                                                <ImageWithBoxes
                                                    key={idx}
                                                    src={page.source_image}
                                                    blocks={page.blocks ?? []}
                                                    showBoxes={showBoxes}
                                                />
                                            ))
                                        ) : (
                                            <div className="text-[13px] text-muted">이미지 로딩 중...</div>
                                        )}
                                    </div>
                                </div>

                                {/* Preview / Edit */}
                                <div className="flex-1 flex flex-col min-w-0 bg-white border-l border-divide">
                                    <div className="h-14 shrink-0 px-5 flex items-center justify-between border-b border-divide">
                                        <span className="text-[14px] font-bold">
                                            {previewMode === 'markdown' && editablePageIndex !== null
                                                ? 'Edit'
                                                : 'Preview'}
                                        </span>
                                        <div className="flex items-center gap-1 p-[3px] rounded-[10px] bg-track">
                                            {(['markdown', 'html'] as const).map((m) => (
                                                <button
                                                    key={m}
                                                    onClick={() => setPreviewMode(m)}
                                                    className={`h-6 px-3 rounded-lg text-[12px] transition-colors ${
                                                        previewMode === m
                                                            ? 'bg-white border border-brand font-semibold text-ink'
                                                            : 'font-medium text-muted hover:text-ink'
                                                    }`}
                                                >
                                                    {m === 'markdown' ? 'Markdown' : 'HTML'}
                                                </button>
                                            ))}
                                        </div>
                                    </div>
                                    <div className="flex-1 overflow-hidden bg-white">
                                        {previewMode === 'html' ? (
                                            <iframe
                                                srcDoc={currentHtmlDocument}
                                                sandbox="allow-same-origin"
                                                className="w-full h-full border-0"
                                                title="HTML Preview"
                                            />
                                        ) : editablePageIndex !== null ? (
                                            // ✅ WYSIWYG 편집 (preview + 수정 동시)
                                            // key를 selection에 묶어, 페이지/파일 전환 시 에디터 내용 갱신
                                            <div className="h-full overflow-y-auto">
                                                <MarkdownEditor
                                                    key={`${selectedFile.id}:${editablePageIndex}`}
                                                    markdown={resolveMarkdownImages(
                                                        selectedFile.pages[editablePageIndex].markdown,
                                                        selectedFile.pages[editablePageIndex].markdown_images
                                                    )}
                                                    onChange={handleMarkdownEdit}
                                                />
                                            </div>
                                        ) : (
                                            // 다중 페이지 합본은 읽기 전용 (개별 페이지 선택 시 편집)
                                            <div className="h-full overflow-y-auto">
                                                <div className="px-6 pt-4 text-[12px] text-warn">
                                                    여러 페이지 합본은 편집할 수 없습니다. 왼쪽에서 개별 페이지를 선택하면 편집할 수 있습니다.
                                                </div>
                                                <article className="prose prose-slate prose-sm max-w-none p-6 prose-pre:bg-chip prose-pre:text-ink prose-code:before:content-none prose-code:after:content-none prose-code:bg-chip prose-code:px-1 prose-code:py-0.5 prose-code:rounded">
                                                    <ReactMarkdown
                                                        remarkPlugins={[remarkGfm]}
                                                        rehypePlugins={[rehypeRaw, [rehypeSanitize,sanitizeSchema]]}
                                                        urlTransform={allowDataUrlTransform}
                                                    >
                                                        {currentMarkdown}
                                                    </ReactMarkdown>
                                                </article>
                                            </div>
                                        )}
                                    </div>
                                </div>
                            </div>
                        )}
                    </div>
                </div>
            </main>
        </div>
    );
}





/** 상태별 색상 토큰 (Figma: 대기=중립, 처리 중=앰버, 완료=브랜드, 실패=레드) */
const STATUS_STYLE: Record<
    FileStatus,
    { label: string; chip: string; dot: string }
> = {
    pending: { label: '대기', chip: 'bg-chip text-muted', dot: 'bg-muted' },
    processing: { label: '처리 중', chip: 'bg-warn-soft text-warn', dot: 'bg-warn' },
    done: { label: '완료', chip: 'bg-brand-soft text-brand', dot: 'bg-brand' },
    error: { label: '실패', chip: 'bg-danger-soft text-danger', dot: 'bg-danger' },
};

/** 파일 카드 안의 작은 상태 뱃지 */
function StatusBadge({ status }: { status: FileStatus }) {
    const { label, chip } = STATUS_STYLE[status];
    return (
        <span className={`inline-flex items-center h-[17px] px-1.5 rounded-md text-[10px] font-medium ${chip}`}>
            {label}
        </span>
    );
}

/** 결과 패널 헤더의 상태 필 (점 + 라벨) */
function StatusPill({ status }: { status: FileStatus }) {
    const { label, chip, dot } = STATUS_STYLE[status];
    return (
        <span className={`inline-flex items-center gap-1.5 h-[23px] px-2.5 rounded-full text-[11px] font-medium ${chip}`}>
            <span className={`w-2 h-2 rounded-full ${dot}`} />
            {label}
        </span>
    );
}

/** 헤더의 32x32 아이콘 버튼 (hover 시 아래에 라벨 툴팁) */
function IconButton({
                        label,
                        onClick,
                        disabled,
                        variant = 'ghost',
                        children,
                    }: {
    label: string;
    onClick: () => void;
    disabled?: boolean;
    variant?: 'ghost' | 'primary';
    children: React.ReactNode;
}) {
    return (
        <div className="relative group">
            <button
                type="button"
                onClick={onClick}
                disabled={disabled}
                aria-label={label}
                className={`w-8 h-8 rounded-[9px] flex items-center justify-center transition-colors disabled:opacity-40 disabled:cursor-not-allowed ${
                    variant === 'primary'
                        ? 'bg-brand text-white enabled:hover:bg-brand-hover'
                        : 'bg-white border border-line text-ink enabled:hover:bg-surface'
                }`}
            >
                {children}
            </button>
            {!disabled && (
                <span className="pointer-events-none absolute z-10 top-full left-1/2 -translate-x-1/2 mt-1.5 whitespace-nowrap rounded-md border border-line bg-white px-2 py-1 text-[11px] text-ink opacity-0 transition-opacity group-hover:opacity-100">
                    {label}
                </span>
            )}
        </div>
    );
}

/** 선택된 파일이 없을 때의 안내 화면 */
function EmptyState({ message }: { message: string }) {
    return (
        <div className="h-full flex flex-col items-center justify-center">
            <div className="w-[76px] h-[76px] rounded-full bg-brand-pale flex items-center justify-center">
                <DocumentIcon className="w-8 h-8 text-brand" />
            </div>
            <p className="mt-6 text-[15px] font-medium">{message}</p>
        </div>
    );
}

// ===== 유틸 함수 =====

function isPdf(f: OcrFile): boolean {
    return f.type === 'application/pdf' || /\.pdf$/i.test(f.name);
}

/** 페이지 markdown 합치기 (페이지 구분자로 결합, 이미지는 base64로 인라인 치환) */
function joinPages(pages: OcrPageInfo[]): string {
    if (pages.length === 0) return '';
    if (pages.length === 1) {
        return resolveMarkdownImages(pages[0].markdown, pages[0].markdown_images);
    }

    return pages
        .map((p, i) => `<!-- Page ${i + 1} -->\n\n${resolveMarkdownImages(p.markdown, p.markdown_images)}`)
        .join('\n\n---\n\n');
}

function getExt(name: string): string {
    const m = name.match(/\.([^.]+)$/);
    return m ? m[1] : 'FILE';
}

function stripExt(name: string): string {
    return name.replace(/\.[^.]+$/, '');
}

const IMAGE_EXTS = ['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'tif', 'tiff'];

/** 확장자 뱃지 색 (디자인: 이미지=브랜드 톤, 그 외=중립 톤) */
function extBadgeColor(name: string): string {
    const ext = getExt(name).toLowerCase();
    return IMAGE_EXTS.includes(ext)
        ? 'bg-brand-soft text-brand'
        : 'bg-chip text-muted';
}

function triggerDownload(content: string, filename: string, mime: string) {
    triggerBlobDownload(new Blob([content], { type: mime }), filename);
}

function triggerBlobDownload(blob: Blob, filename: string) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}