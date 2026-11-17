import { useEffect, useMemo, useRef, useState } from 'react';
import type { KeyboardEvent, MouseEvent } from 'react';

import { AlertIcon, CheckIcon, DocumentIcon } from '../components/icons';
import { ApiError } from '../lib/http';
import { navigate } from '../lib/router';
import { ragApi } from './api';
import { PageMarkdown, PageTextEditor } from './PageTextEditor';
import { PAGE_PROSE_CLASS } from './pageProse';
import type { FilePage, FilePagesResponse } from './types';

/**
 * 파일 검수 (/review?file_id=…&return=…)
 *
 * 왼쪽에는 페이지 목록(썸네일 레일), 가운데에는 선택한 페이지를 보여준다.
 * 가운데는 [텍스트 / 원본 / 나란히]로 바꿔 본다. 원본(PDF 페이지)은 서버가 PDF만 내려주므로
 * 다른 형식은 텍스트만 볼 수 있다. 텍스트는 업로드 때 파싱해 DB에 저장한 그 페이지의 내용이고, 누르면 그 자리에서 고친다.
 *
 * 업로드한 파일은 검수 대기(pending)로 시작한다. 이때는 고쳐 저장해도 텍스트만 바뀌고,
 * [검수 완료]를 눌러야 서버가 전체 페이지를 청킹·임베딩해 검색에 넣고 그래프 추출을 건다.
 * 검수가 끝난 파일은 텍스트를 고쳐 저장하면 서버가 그 페이지만 다시 청킹·임베딩한다.
 * 업로드 원본 파일과 처음 파싱 결과(original_text)는 서버가 바꾸지 않는다.
 *
 * "이 페이지 확인" 표시는 검수하는 사람의 진행 표시일 뿐이라 서버에 저장하지 않고 이 브라우저(localStorage)에만 둔다.
 * 확인하지 않은 페이지가 있어도 [검수 완료]는 막지 않고 확인 창에서 알려 준다.
 */

type ViewMode = 'text' | 'orig' | 'both';

const VIEW_KEY = 'rag-review-view';
const checkedKey = (fileId: string) => `rag-review-checked:${fileId}`;

/** URL에서 검수할 파일과 돌아갈 경로를 읽는다. 다른 사이트로 나가는 경로는 무시한다. */
function readReviewTarget(): { fileId: string; returnPath: string } | null {
    const params = new URLSearchParams(window.location.search);
    const fileId = params.get('file_id');
    if (!fileId) return null;
    const back = params.get('return') ?? '/';
    const returnPath = back.startsWith('/') && !back.startsWith('//') ? back : '/';
    return { fileId, returnPath };
}

function readView(): ViewMode {
    try {
        const saved = window.localStorage.getItem(VIEW_KEY);
        if (saved === 'text' || saved === 'orig' || saved === 'both') return saved;
    } catch {
        // 저장소를 못 쓰면 기본값
    }
    return 'both';
}

function readChecked(fileId: string): Set<number> {
    try {
        const saved = JSON.parse(window.localStorage.getItem(checkedKey(fileId)) ?? '[]');
        if (Array.isArray(saved)) return new Set(saved.filter((n): n is number => typeof n === 'number'));
    } catch {
        // 저장소를 못 쓰거나 값이 깨졌으면 빈 상태로
    }
    return new Set();
}

function errorText(e: unknown): string {
    if (e instanceof ApiError) {
        return e.code === 'network' ? `서버에 연결할 수 없습니다 (${e.message})` : e.message;
    }
    return e instanceof Error ? e.message : '알 수 없는 오류가 발생했습니다.';
}

/** 썸네일에 보일 첫 몇 글자. 마크다운 기호와 표 구분선은 뺀다 */
function snippet(text: string): string {
    return text.replace(/[#*|>`_~]+|-{3,}/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 70);
}

/** 입력 중인 곳에서 누른 화살표 키는 페이지 이동으로 쓰지 않는다 */
function isTypingTarget(target: EventTarget | null): boolean {
    if (!(target instanceof HTMLElement)) return false;
    return target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName);
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
    const [editingIds, setEditingIds] = useState<Set<number>>(new Set());
    const [completing, setCompleting] = useState(false);
    const [completeError, setCompleteError] = useState('');
    const [completeNotice, setCompleteNotice] = useState('');
    const [view, setView] = useState<ViewMode>(readView);
    const [checked, setChecked] = useState<Set<number>>(() => (target ? readChecked(target.fileId) : new Set()));

    const fileId = target?.fileId ?? '';
    const pending = data?.review_status === 'pending';
    const isPdf = /\.pdf$/i.test(data?.original_name ?? '');
    // 원본이 없는 형식은 텍스트만 볼 수 있다
    const shownView: ViewMode = isPdf ? view : 'text';

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
    const checkedCount = pageNumbers.filter((p) => checked.has(p)).length;
    const editingLock = editingIds.size > 0;

    // ← → 로 페이지 이동 (수정 중이거나 입력 칸에 있을 때는 쓰지 않는다)
    const pageMoveRef = useRef<(step: number) => void>(() => {});
    const editingIdsRef = useRef(editingIds);
    useEffect(() => {
        editingIdsRef.current = editingIds;
        pageMoveRef.current = (step: number) => {
            const next = pageNumbers[pagePos + step];
            if (next !== undefined) setSelectedPage(next);
        };
    });
    useEffect(() => {
        const onKey = (e: globalThis.KeyboardEvent) => {
            if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
            if (e.altKey || e.ctrlKey || e.metaKey || e.shiftKey || isTypingTarget(e.target)) return;
            if (editingIdsRef.current.size > 0) return;
            e.preventDefault();
            pageMoveRef.current(e.key === 'ArrowLeft' ? -1 : 1);
        };
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
    }, []);

    const changeView = (next: ViewMode) => {
        setView(next);
        try {
            window.localStorage.setItem(VIEW_KEY, next);
        } catch {
            // 저장하지 못해도 이번 화면에서는 바뀐다
        }
    };

    const toggleChecked = (page: number) => {
        setChecked((current) => {
            const next = new Set(current);
            if (next.has(page)) next.delete(page);
            else next.add(page);
            try {
                window.localStorage.setItem(checkedKey(fileId), JSON.stringify([...next]));
            } catch {
                // 저장하지 못해도 이번 화면에서는 표시된다
            }
            return next;
        });
    };

    const onSaved = (updated: FilePage) => {
        setData((current) => current && {
            ...current,
            pages: current.pages.map((p) => (p.page_id === updated.page_id ? updated : p)),
        });
    };

    const setEditing = (pageId: number, editing: boolean) => {
        setEditingIds((current) => {
            if (current.has(pageId) === editing) return current;
            const next = new Set(current);
            if (editing) next.add(pageId);
            else next.delete(pageId);
            return next;
        });
    };

    const completeReview = async () => {
        if (!data || completing || editingLock) return;
        const unchecked = pageNumbers.length - checkedCount;
        const warning = unchecked > 0 ? `\n\n확인 표시를 하지 않은 페이지가 ${unchecked}개 있습니다.` : '';
        if (!window.confirm(`'${data.original_name}' 검수를 마치고 질의응답 검색에 반영할까요?\n지금 저장된 페이지 텍스트로 청크를 만들고 그래프를 추출합니다.${warning}`)) return;
        setCompleting(true);
        setCompleteError('');
        try {
            const result = await ragApi.completeReview(fileId);
            setData((current) => current && { ...current, review_status: 'done', error_message: null });
            setCompleteNotice(`검수 완료: 청크 ${result.chunk_count.toLocaleString()}개를 검색에 반영했습니다. 그래프 추출은 뒤에서 이어집니다.`);
            try {
                window.localStorage.removeItem(checkedKey(fileId));
            } catch {
                // 지우지 못해도 화면 동작에는 영향이 없다
            }
        } catch (e) {
            // 서버 메시지가 이미 "검색 반영 실패: …"로 시작한다
            setCompleteError(`${errorText(e)} — 다시 눌러 재시도할 수 있습니다.`);
        } finally {
            setCompleting(false);
        }
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

    const failure = pending ? (completeError || (data?.error_message ? `지난 시도 — ${data.error_message}` : '')) : '';

    return (
        <div className="flex h-screen w-full gap-5 bg-surface p-5 text-ink font-sans antialiased">
            {/* 페이지 레일 */}
            {rows.length > 0 && (
                <nav aria-label="페이지 목록" className="w-[92px] shrink-0 flex flex-col">
                    <div className="flex-1 min-h-0 overflow-y-auto space-y-2 p-1">
                        {pageNumbers.map((p) => {
                            const blocks = rows.filter((r) => r.page === p);
                            const edited = blocks.some((r) => r.edited);
                            const active = p === currentPage;
                            return (
                                <button
                                    key={p}
                                    type="button"
                                    onClick={() => setSelectedPage(p)}
                                    aria-current={active ? 'page' : undefined}
                                    aria-label={`${p}쪽${pending && checked.has(p) ? ', 확인함' : ''}${edited ? ', 수정됨' : ''}`}
                                    className={`relative block h-[84px] w-full overflow-hidden rounded-lg bg-white px-2 pt-2 pb-5 text-left transition-shadow ${
                                        active ? 'ring-2 ring-brand' : 'ring-1 ring-divide hover:ring-line'
                                    }`}
                                >
                                    <span className="line-clamp-4 text-[9.5px] leading-[1.35] text-ink/55 break-all">
                                        {snippet(blocks.map((r) => r.text).join(' ')) || '(빈 페이지)'}
                                    </span>
                                    <span className={`absolute left-2 bottom-1.5 text-[11px] font-semibold ${active ? 'text-brand' : 'text-muted'}`}>{p}</span>
                                    <span className="absolute right-1.5 bottom-1.5 flex items-center gap-1">
                                        {edited && <PencilIcon className="w-3 h-3 text-brand" />}
                                        {pending && checked.has(p) && <CheckIcon className="w-3 h-3 text-emerald-600" />}
                                    </span>
                                </button>
                            );
                        })}
                    </div>
                    {pending && (
                        <p className="shrink-0 pt-2 text-center text-[11px] text-muted">
                            확인 <span className="font-semibold text-ink">{checkedCount}</span> / {pageNumbers.length}
                        </p>
                    )}
                </nav>
            )}

            <main className="flex-1 min-w-0 flex flex-col">
                {/* 위: 돌아가기 · 상태 */}
                <div className="shrink-0 flex items-center justify-between gap-4">
                    <button
                        type="button"
                        onClick={() => navigate(target?.returnPath ?? '/')}
                        className="h-8 -ml-2 px-2 rounded-lg text-[12px] font-semibold text-muted hover:bg-white hover:text-ink transition-colors"
                    >
                        ← 파일 관리
                    </button>
                    {data && (pending ? (
                        <div className="inline-flex items-center gap-2.5 rounded-full bg-ink py-1 pl-3.5 pr-1 text-[12px] text-white">
                            <span className="h-1.5 w-1.5 rounded-full bg-warn" aria-hidden="true" />
                            <span>검수 대기 · 아직 검색에 안 쓰임</span>
                            <button
                                type="button"
                                onClick={() => void completeReview()}
                                disabled={completing || editingLock}
                                title={editingLock ? '수정 중인 페이지를 저장하거나 취소해야 누를 수 있습니다' : undefined}
                                className="h-7 inline-flex items-center gap-1.5 rounded-full bg-brand px-3.5 font-bold hover:bg-brand-hover disabled:cursor-not-allowed disabled:opacity-50"
                            >
                                {completing && <span className="h-3 w-3 rounded-full border-2 border-white/40 border-t-white animate-spin" />}
                                {completing ? '반영하는 중…' : '검수 완료'}
                            </button>
                        </div>
                    ) : (
                        <span className="h-8 inline-flex items-center gap-1.5 rounded-full bg-white px-3 text-[12px] font-semibold text-emerald-700 ring-1 ring-divide">
                            <CheckIcon className="w-3 h-3" /> 검수 완료됨
                        </span>
                    ))}
                </div>

                {/* 파일 이름 · 보기 방식 */}
                <div className="shrink-0 mt-3 mb-3 flex flex-wrap items-end justify-between gap-3">
                    <div className="min-w-0">
                        <h1 className="text-[16px] font-bold truncate" title={data?.original_name}>
                            {data?.original_name ?? (loadError ? '파일을 불러오지 못했습니다' : '불러오는 중...')}
                        </h1>
                        {rows.length > 0 && currentPage !== null && (
                            <p className="mt-1 text-[12px] text-muted">
                                {currentPage}쪽 / {pageNumbers[pageNumbers.length - 1]}쪽
                                {editedCount > 0 && ` · 고친 곳 ${editedCount}`}
                                {' · '}
                                {pending ? '고친 내용은 [검수 완료] 때 검색에 반영됩니다' : '저장하면 그 페이지만 다시 청킹·임베딩합니다'}
                            </p>
                        )}
                    </div>
                    {rows.length > 0 && (
                        <div role="group" aria-label="보기 방식" className="inline-flex rounded-full bg-white p-0.5 ring-1 ring-divide">
                            {([['text', '텍스트'], ['orig', '원본'], ['both', '나란히']] as const).map(([mode, name]) => (
                                <button
                                    key={mode}
                                    type="button"
                                    onClick={() => changeView(mode)}
                                    disabled={!isPdf && mode !== 'text'}
                                    aria-pressed={shownView === mode}
                                    title={!isPdf && mode !== 'text' ? '원본 미리보기는 PDF만 지원합니다' : undefined}
                                    className={`h-7 rounded-full px-3.5 text-[12px] transition-colors disabled:cursor-not-allowed disabled:text-muted/60 ${
                                        shownView === mode ? 'bg-chip font-bold text-ink' : 'text-muted hover:text-ink'
                                    }`}
                                >
                                    {name}
                                </button>
                            ))}
                        </div>
                    )}
                </div>

                {/* 알림 */}
                {failure && <p role="alert" className="shrink-0 mb-3 rounded-lg bg-danger-surface px-3 py-2 break-words text-[12px] text-danger">{failure}</p>}
                {pending && editingLock && (
                    <p className="shrink-0 mb-3 text-[12px] text-muted">수정 중인 페이지를 저장하거나 취소해야 [검수 완료]를 누를 수 있습니다.</p>
                )}
                {completeNotice && (
                    <p role="status" className="shrink-0 mb-3 rounded-lg bg-brand-pale px-3 py-2 text-[12.5px] font-semibold text-brand-hover">{completeNotice}</p>
                )}

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
                        <div className={`grid h-full gap-4 ${shownView === 'both' ? 'grid-cols-2' : 'grid-cols-1'}`}>
                            {/* 원본 */}
                            {shownView !== 'text' && (
                                <section aria-label="원본" className="min-w-0 min-h-0 overflow-hidden rounded-xl bg-white ring-1 ring-divide">
                                    {pdfError ? (
                                        <CenterMessage error>{`PDF를 열 수 없습니다: ${pdfError}`}</CenterMessage>
                                    ) : pdfUrl ? (
                                        // 페이지가 바뀌면 다시 그려야 해당 페이지로 이동한다
                                        <iframe
                                            key={currentPage}
                                            title={`${data.original_name} ${currentPage}페이지`}
                                            src={`${pdfUrl}#page=${currentPage}`}
                                            className="h-full w-full"
                                        />
                                    ) : (
                                        <CenterMessage>PDF를 불러오는 중...</CenterMessage>
                                    )}
                                </section>
                            )}

                            {/* 저장된 페이지 텍스트. 원본만 볼 때도 숨기기만 해서 고치던 내용이 사라지지 않게 한다 */}
                            <section
                                aria-label="페이지 텍스트"
                                className={`min-w-0 min-h-0 flex-col overflow-hidden rounded-xl bg-white ring-1 ring-divide ${shownView === 'orig' ? 'hidden' : 'flex'}`}
                            >
                                <div className="flex-1 min-h-0 overflow-y-auto divide-y divide-divide">
                                    {pageRows.map((row, i) => (
                                        <PageCard
                                            key={row.page_id}
                                            fileId={fileId}
                                            row={row}
                                            label={pageRows.length > 1 ? `블록 ${i + 1}` : ''}
                                            pending={pending}
                                            locked={completing}
                                            onSaved={onSaved}
                                            onEditingChange={(editing) => setEditing(row.page_id, editing)}
                                        />
                                    ))}
                                </div>
                                <div className="shrink-0 h-12 px-4 flex items-center justify-between gap-3 border-t border-divide">
                                    <span className="text-[11.5px] text-muted">← → 페이지 이동</span>
                                    {pending && currentPage !== null && (
                                        <button
                                            type="button"
                                            onClick={() => toggleChecked(currentPage)}
                                            aria-pressed={checked.has(currentPage)}
                                            className={`h-8 inline-flex items-center gap-1.5 rounded-lg px-3 text-[12px] font-semibold transition-colors ${
                                                checked.has(currentPage)
                                                    ? 'bg-emerald-50 text-emerald-700 hover:bg-emerald-100'
                                                    : 'ring-1 ring-line text-ink hover:bg-surface'
                                            }`}
                                            title={checked.has(currentPage) ? '다시 누르면 확인 표시를 지웁니다' : undefined}
                                        >
                                            <CheckIcon className="w-3 h-3" />
                                            {checked.has(currentPage) ? '확인함' : '이 페이지 확인'}
                                        </button>
                                    )}
                                </div>
                            </section>
                        </div>
                    )}
                </div>
            </main>
        </div>
    );
}

function PageCard({
    fileId,
    row,
    label,
    pending,
    locked,
    onSaved,
    onEditingChange,
}: {
    fileId: string;
    row: FilePage;
    /** 한 페이지에 블록이 여럿일 때(xlsx 등)만 "블록 n" */
    label: string;
    /** 검수 대기 파일이면 저장해도 텍스트만 바뀐다 (색인은 [검수 완료] 때) */
    pending: boolean;
    /** [검수 완료] 처리 중에는 수정을 시작하지 못하게 한다 */
    locked: boolean;
    onSaved: (row: FilePage) => void;
    onEditingChange: (editing: boolean) => void;
}) {
    const [editing, setEditingState] = useState(false);
    const setEditing = (value: boolean) => {
        setEditingState(value);
        onEditingChange(value);
    };
    // 수정 중에 다른 페이지로 넘어가 카드가 사라지면 [검수 완료]가 계속 잠기지 않게 풀어 준다
    const editingChangeRef = useRef(onEditingChange);
    useEffect(() => {
        editingChangeRef.current = onEditingChange;
    });
    useEffect(() => () => editingChangeRef.current(false), []);
    const [draft, setDraft] = useState('');
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState('');
    const [status, setStatus] = useState('');
    const [showOriginal, setShowOriginal] = useState(false);
    const [tableOpen, setTableOpen] = useState(false);
    const editLabel = label ? `Page ${row.page} · ${label}` : `Page ${row.page}`;
    // 처음 파싱 결과를 보는 중에는 누른다고 고치지 않는다 (현재 텍스트를 고치는 것이라 헷갈린다)
    const canEdit = !locked && !showOriginal;

    const startEdit = () => {
        if (!canEdit) return;
        setDraft(row.text);
        setError('');
        setStatus('');
        setShowOriginal(false);
        setEditing(true);
    };

    // 텍스트를 누르면 그 자리에서 고친다. 글자를 드래그해 고르거나 링크를 누른 것은 빼고
    const onTextClick = (e: MouseEvent<HTMLElement>) => {
        if (window.getSelection()?.toString()) return;
        if ((e.target as HTMLElement).closest('a')) return;
        startEdit();
    };
    const onTextKey = (e: KeyboardEvent<HTMLElement>) => {
        if (e.key === 'Enter' && e.target === e.currentTarget) {
            e.preventDefault();
            startEdit();
        }
    };

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
            if (pending) setStatus('저장했습니다. [검수 완료]를 누르면 검색에 반영됩니다.');
            else if (result.chunk_count !== null) setStatus(`저장했습니다. 검색용 청크 ${result.chunk_count}개를 다시 만들었습니다.`);
        } catch (e) {
            setError(`저장 실패: ${errorText(e)}`);
        } finally {
            setSaving(false);
        }
    };

    return (
        <section className="px-5 py-4">
            <div className="mb-2 flex min-h-6 items-center justify-between gap-2">
                <div className="flex items-center gap-2 text-[12px]">
                    {label && <span className="font-semibold">{label}</span>}
                    <span className="text-muted">{row.text.length.toLocaleString()}자</span>
                    {row.edited && <span className="h-[17px] px-1.5 inline-flex items-center rounded-md bg-brand-soft text-brand text-[10px] font-medium">수정됨</span>}
                    {showOriginal && <span className="text-[11.5px] font-semibold text-warn">처음 파싱 결과 (읽기 전용)</span>}
                </div>
                {!editing && (
                    <div className="flex items-center gap-3">
                        {row.edited && (
                            <button type="button" onClick={() => setShowOriginal((v) => !v)} className="text-[12px] font-semibold text-muted hover:text-ink">
                                {showOriginal ? '현재 텍스트 보기' : '처음 파싱 결과 보기'}
                            </button>
                        )}
                        <button
                            type="button"
                            onClick={startEdit}
                            disabled={!canEdit}
                            className="inline-flex items-center gap-1 text-[12px] font-semibold text-muted hover:text-brand-hover disabled:opacity-40"
                        >
                            <PencilIcon className="w-3 h-3" /> 수정
                        </button>
                    </div>
                )}
            </div>
            {editing ? (
                <div>
                    <PageTextEditor
                        value={draft}
                        onChange={setDraft}
                        disabled={saving}
                        label={editLabel}
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
                    <article
                        tabIndex={canEdit ? 0 : undefined}
                        onClick={canEdit ? onTextClick : undefined}
                        onKeyDown={canEdit ? onTextKey : undefined}
                        title={canEdit ? '누르면 고칠 수 있습니다' : undefined}
                        aria-label={canEdit ? `${editLabel} 텍스트, Enter를 누르면 수정` : undefined}
                        className={`${PAGE_PROSE_CLASS} -mx-2 rounded-lg px-2 py-1 ${
                            canEdit ? 'cursor-text transition-colors hover:bg-brand-tint focus:outline-none focus-visible:ring-2 focus-visible:ring-brand/40' : ''
                        }`}
                    >
                        {(showOriginal ? row.original_text : row.text).trim()
                            ? <PageMarkdown text={showOriginal ? row.original_text : row.text} />
                            : <p className="text-muted">(빈 페이지)</p>}
                    </article>
                    {status && <p role="status" className="mt-2 text-[12px] text-brand-hover">{status}</p>}
                </>
            )}
        </section>
    );
}

function PencilIcon({ className = 'w-3 h-3' }: { className?: string }) {
    return (
        <svg className={className} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M10.5 2.5l3 3L5 14H2v-3z" />
            <path d="M9 4l3 3" />
        </svg>
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
