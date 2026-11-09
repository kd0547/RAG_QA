import { useEffect, useMemo, useState } from 'react';

import { AlertIcon, DocumentIcon } from '../components/icons';
import { ApiError } from '../lib/http';
import { navigate } from '../lib/router';
import { ragApi } from './api';
import { PageMarkdown, PageTextEditor } from './PageTextEditor';
import { PAGE_PROSE_CLASS } from './pageProse';
import type { FilePage, FilePagesResponse } from './types';

/**
 * 파일 검수 (/review?file_id=…&return=…)
 *
 * OCR 도구와 같은 배치로, 왼쪽에는 원본(PDF 페이지), 오른쪽에는 업로드 때 파싱해 DB에 저장한 그 페이지의 텍스트를 보여준다.
 * 텍스트를 고쳐 저장하면 서버가 그 페이지만 다시 청킹·임베딩한다.
 * 업로드 원본 파일과 처음 파싱 결과(original_text)는 서버가 바꾸지 않는다.
 * 원본 미리보기는 서버가 PDF만 내려주므로, 다른 형식은 텍스트 검수만 할 수 있다.
 */

/** URL에서 검수할 파일과 돌아갈 경로를 읽는다. 다른 사이트로 나가는 경로는 무시한다. */
function readReviewTarget(): { fileId: string; returnPath: string } | null {
    const params = new URLSearchParams(window.location.search);
    const fileId = params.get('file_id');
    if (!fileId) return null;
    const back = params.get('return') ?? '/';
    const returnPath = back.startsWith('/') && !back.startsWith('//') ? back : '/';
    return { fileId, returnPath };
}

function errorText(e: unknown): string {
    if (e instanceof ApiError) {
        return e.code === 'network' ? `서버에 연결할 수 없습니다 (${e.message})` : e.message;
    }
    return e instanceof Error ? e.message : '알 수 없는 오류가 발생했습니다.';
}

export function FileReview() {
    const [target] = useState(readReviewTarget);
    const [data, setData] = useState<FilePagesResponse | null>(null);
    const [loadError, setLoadError] = useState(target ? '' : '검수할 파일이 지정되지 않았습니다.');
    const [selectedPage, setSelectedPage] = useState<number | null>(null);
    const [importing, setImporting] = useState(false);
    const [importError, setImportError] = useState('');
    const [pdfUrl, setPdfUrl] = useState('');
    const [pdfError, setPdfError] = useState('');

    const fileId = target?.fileId ?? '';
    const isPdf = /\.pdf$/i.test(data?.original_name ?? '');

    // 저장된 페이지 텍스트
    useEffect(() => {
        if (!fileId) return;
        let ignore = false;
        ragApi.listFilePages(fileId).then((result) => {
            if (!ignore) setData(result);
        }).catch((e: unknown) => {
            if (!ignore) setLoadError(errorText(e));
        });
        return () => { ignore = true; };
    }, [fileId]);

    // 원본 PDF (PDF일 때만)
    useEffect(() => {
        if (!fileId || !isPdf) return;
        const controller = new AbortController();
        let objectUrl = '';
        ragApi.previewPdf(fileId, controller.signal).then((blob) => {
            if (controller.signal.aborted) return;
            objectUrl = URL.createObjectURL(blob);
            setPdfUrl(objectUrl);
        }).catch((e: unknown) => {
            if (!controller.signal.aborted) setPdfError(errorText(e));
        });
        return () => {
            controller.abort();
            if (objectUrl) URL.revokeObjectURL(objectUrl);
        };
    }, [fileId, isPdf]);

    const rows = useMemo(() => data?.pages ?? [], [data]);
    const pageNumbers = useMemo(() => [...new Set(rows.map((r) => r.page))].sort((a, b) => a - b), [rows]);
    const currentPage = selectedPage ?? pageNumbers[0] ?? null;
    const pageRows = rows.filter((r) => r.page === currentPage);
    const pagePos = currentPage === null ? -1 : pageNumbers.indexOf(currentPage);
    const editedCount = rows.filter((r) => r.edited).length;

    const onSaved = (updated: FilePage) => {
        setData((current) => current && {
            ...current,
            pages: current.pages.map((p) => (p.page_id === updated.page_id ? updated : p)),
        });
    };

    const importPages = async () => {
        setImporting(true);
        setImportError('');
        try {
            setData(await ragApi.importFilePages(fileId));
        } catch (e) {
            setImportError(errorText(e));
        } finally {
            setImporting(false);
        }
    };

    return (
        <div className="flex h-screen w-full bg-white text-ink font-sans antialiased p-7">
            <div className="h-full w-full flex flex-col rounded-2xl border border-line bg-surface overflow-hidden">
                {/* 헤더 */}
                <header className="h-[66px] shrink-0 pl-5 pr-[18px] flex items-center justify-between gap-4 border-b border-divide">
                    <div className="min-w-0 flex items-center gap-3">
                        <button
                            type="button"
                            onClick={() => navigate(target?.returnPath ?? '/')}
                            className="shrink-0 h-8 px-3 rounded-lg border border-line bg-white text-[12px] font-semibold text-ink hover:border-brand hover:text-brand transition-colors"
                        >
                            ← 파일 관리
                        </button>
                        <div className="min-w-0">
                            <h1 className="text-[15px] font-bold leading-none">파일 검수</h1>
                            <p className="mt-[7px] text-[13px] leading-none text-muted truncate" title={data?.original_name}>
                                {data?.original_name ?? (loadError ? '파일을 불러오지 못했습니다' : '불러오는 중...')}
                            </p>
                        </div>
                    </div>

                    {pageNumbers.length > 0 && currentPage !== null && (
                        <div className="shrink-0 flex items-center gap-2">
                            {editedCount > 0 && (
                                <span className="h-[23px] px-2.5 inline-flex items-center rounded-full bg-brand-soft text-brand text-[11px] font-medium">
                                    {editedCount}개 페이지 수정됨
                                </span>
                            )}
                            <button
                                type="button"
                                onClick={() => setSelectedPage(pageNumbers[pagePos - 1])}
                                disabled={pagePos <= 0}
                                aria-label="이전 페이지"
                                className="h-8 w-8 rounded-lg border border-line bg-white text-[13px] hover:bg-surface disabled:opacity-40"
                            >
                                ‹
                            </button>
                            <select
                                value={currentPage}
                                onChange={(e) => setSelectedPage(Number(e.target.value))}
                                aria-label="검수할 페이지"
                                className="h-8 rounded-lg border border-line bg-white px-2 text-[12px] text-ink focus:outline-none focus:border-brand"
                            >
                                {pageNumbers.map((p) => (
                                    <option key={p} value={p}>
                                        Page {p} / {pageNumbers[pageNumbers.length - 1]}
                                        {rows.some((r) => r.page === p && r.edited) ? ' · 수정됨' : ''}
                                    </option>
                                ))}
                            </select>
                            <button
                                type="button"
                                onClick={() => setSelectedPage(pageNumbers[pagePos + 1])}
                                disabled={pagePos >= pageNumbers.length - 1}
                                aria-label="다음 페이지"
                                className="h-8 w-8 rounded-lg border border-line bg-white text-[13px] hover:bg-surface disabled:opacity-40"
                            >
                                ›
                            </button>
                        </div>
                    )}
                </header>

                {/* 본문 */}
                <div className="flex-1 min-h-0">
                    {loadError ? (
                        <CenterMessage error>{loadError}</CenterMessage>
                    ) : !data ? (
                        <CenterMessage>저장된 내용을 불러오는 중...</CenterMessage>
                    ) : rows.length === 0 ? (
                        <div className="h-full flex flex-col items-center justify-center px-6 text-center">
                            <DocumentIcon className="w-7 h-7 text-muted" />
                            <p className="mt-3 text-[13px] font-semibold">이 파일은 검수용 페이지 텍스트가 없습니다.</p>
                            <p className="mt-1 max-w-md text-[12px] leading-relaxed text-ink/70">
                                이 기능이 생기기 전에 올린 파일입니다. 보관된 원본을 다시 파싱해 페이지 텍스트를 만듭니다.
                                검색에 쓰는 내용은 페이지를 고쳐 저장할 때만 바뀝니다. 스캔 문서는 OCR 때문에 시간이 걸릴 수 있습니다.
                            </p>
                            {importError && <p role="alert" className="mt-3 max-w-md break-words text-[12px] text-danger">{importError}</p>}
                            <button
                                type="button"
                                onClick={() => void importPages()}
                                disabled={importing}
                                className="mt-4 h-9 rounded-lg bg-brand px-4 text-[12px] font-bold text-white hover:bg-brand-hover disabled:opacity-50"
                            >
                                {importing ? '원본을 파싱하는 중…' : '페이지 텍스트 만들기'}
                            </button>
                        </div>
                    ) : (
                        <div className="flex h-full">
                            {/* 원본 */}
                            <div className="flex-1 flex flex-col min-w-0">
                                <div className="h-14 shrink-0 px-5 flex items-center">
                                    <span className="text-[14px] font-bold">원본</span>
                                </div>
                                <div className="flex-1 min-h-0 px-5 pb-5">
                                    {!isPdf ? (
                                        <CenterMessage>원본 미리보기는 PDF만 지원합니다. 오른쪽에서 저장된 텍스트만 검수할 수 있습니다.</CenterMessage>
                                    ) : pdfError ? (
                                        <CenterMessage error>{`PDF를 열 수 없습니다: ${pdfError}`}</CenterMessage>
                                    ) : pdfUrl ? (
                                        // 페이지가 바뀌면 다시 그려야 해당 페이지로 이동한다
                                        <iframe
                                            key={currentPage}
                                            title={`${data.original_name} ${currentPage}페이지`}
                                            src={`${pdfUrl}#page=${currentPage}`}
                                            className="h-full w-full rounded-xl border border-line bg-white"
                                        />
                                    ) : (
                                        <CenterMessage>PDF를 불러오는 중...</CenterMessage>
                                    )}
                                </div>
                            </div>

                            {/* 저장된 페이지 텍스트 */}
                            <div className="flex-1 flex flex-col min-w-0 bg-white border-l border-divide">
                                <div className="h-14 shrink-0 px-5 flex items-center justify-between border-b border-divide">
                                    <span className="text-[14px] font-bold">페이지 텍스트</span>
                                    <span className="text-[12px] text-muted">저장하면 이 페이지만 다시 청킹·임베딩합니다</span>
                                </div>
                                <div className="flex-1 min-h-0 overflow-y-auto p-5 space-y-4">
                                    {pageRows.map((row, i) => (
                                        <PageCard
                                            key={row.page_id}
                                            fileId={fileId}
                                            row={row}
                                            label={pageRows.length > 1 ? `Page ${row.page} · 블록 ${i + 1}` : `Page ${row.page}`}
                                            onSaved={onSaved}
                                        />
                                    ))}
                                </div>
                            </div>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}

function PageCard({
    fileId,
    row,
    label,
    onSaved,
}: {
    fileId: string;
    row: FilePage;
    label: string;
    onSaved: (row: FilePage) => void;
}) {
    const [editing, setEditing] = useState(false);
    const [draft, setDraft] = useState('');
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState('');
    const [status, setStatus] = useState('');
    const [showOriginal, setShowOriginal] = useState(false);
    const [tableOpen, setTableOpen] = useState(false);

    const save = async () => {
        if (draft === row.text) {
            setEditing(false);
            return;
        }
        setSaving(true);
        setError('');
        setStatus('');
        try {
            const result = await ragApi.updatePageText(fileId, row.page_id, draft);
            onSaved(result.page);
            setEditing(false);
            if (result.chunk_count !== null) setStatus(`저장했습니다. 검색용 청크 ${result.chunk_count}개를 다시 만들었습니다.`);
        } catch (e) {
            setError(`저장 실패: ${errorText(e)}`);
        } finally {
            setSaving(false);
        }
    };

    return (
        <section className="rounded-xl border border-line bg-white">
            <div className="h-10 px-4 flex items-center justify-between gap-2 border-b border-divide">
                <div className="flex items-center gap-2 text-[12px]">
                    <span className="font-semibold">{label}</span>
                    <span className="text-muted">{row.text.length.toLocaleString()}자</span>
                    {row.edited && <span className="h-[17px] px-1.5 inline-flex items-center rounded-md bg-brand-soft text-brand text-[10px] font-medium">수정됨</span>}
                </div>
                <div className="flex items-center gap-3">
                    {row.edited && !editing && (
                        <button type="button" onClick={() => setShowOriginal((v) => !v)} className="text-[12px] font-semibold text-muted hover:text-ink">
                            {showOriginal ? '현재 텍스트 보기' : '처음 파싱 결과 보기'}
                        </button>
                    )}
                    {!editing && (
                        <button
                            type="button"
                            onClick={() => {
                                setDraft(row.text);
                                setError('');
                                setStatus('');
                                setShowOriginal(false);
                                setEditing(true);
                            }}
                            className="text-[12px] font-bold text-brand-hover hover:underline"
                        >
                            수정
                        </button>
                    )}
                </div>
            </div>
            {editing ? (
                <div className="p-4">
                    <PageTextEditor
                        value={draft}
                        onChange={setDraft}
                        disabled={saving}
                        label={label}
                        onTableEditingChange={setTableOpen}
                    />
                    {error && <p role="alert" className="mt-2 break-words text-[12px] text-danger">{error}</p>}
                    <div className="mt-2 flex items-center justify-end gap-2">
                        {row.edited && (
                            <button
                                type="button"
                                onClick={() => setDraft(row.original_text)}
                                disabled={saving || tableOpen}
                                className="mr-auto h-8 rounded-lg px-2 text-[12px] font-semibold text-muted hover:bg-surface hover:text-ink disabled:opacity-50"
                                title="편집 칸을 처음 파싱 결과로 바꿉니다. 저장해야 반영됩니다"
                            >
                                처음 파싱 결과로 되돌리기
                            </button>
                        )}
                        {tableOpen && <span className="text-[11.5px] text-muted">표 편집을 적용하거나 취소한 뒤 저장할 수 있습니다</span>}
                        <button type="button" onClick={() => setEditing(false)} disabled={saving || tableOpen} className="h-8 rounded-lg px-3 text-[12px] font-semibold text-ink/70 hover:bg-surface disabled:opacity-50">
                            취소
                        </button>
                        <button type="button" onClick={() => void save()} disabled={saving || tableOpen} className="h-8 rounded-lg bg-brand px-3 text-[12px] font-bold text-white hover:bg-brand-hover disabled:opacity-50">
                            {saving ? '저장 중…' : '저장'}
                        </button>
                    </div>
                </div>
            ) : (
                <>
                    {showOriginal && (
                        <p className="px-4 pt-3 text-[11.5px] font-semibold text-warn">처음 파싱 결과 (읽기 전용)</p>
                    )}
                    <article className={`${PAGE_PROSE_CLASS} px-4 py-3`}>
                        {(showOriginal ? row.original_text : row.text).trim()
                            ? <PageMarkdown text={showOriginal ? row.original_text : row.text} />
                            : <p className="text-muted">(빈 페이지)</p>}
                    </article>
                    {status && <p role="status" className="px-4 pb-3 text-[12px] text-brand-hover">{status}</p>}
                </>
            )}
        </section>
    );
}

function CenterMessage({ children, error = false }: { children: string; error?: boolean }) {
    return (
        <div className="h-full flex flex-col items-center justify-center px-6 text-center">
            {error
                ? <AlertIcon className="w-7 h-7 text-danger" />
                : <DocumentIcon className="w-7 h-7 text-muted" />}
            <p role={error ? 'alert' : 'status'} className={`mt-3 max-w-md break-words text-[13px] ${error ? 'text-danger' : 'text-ink/70'}`}>
                {children}
            </p>
        </div>
    );
}
