import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

import { AppHeader } from '../components/AppHeader';
import { ApiError } from '../lib/http';
import { ragApi } from './api';
import type { AskMode, AskSource, FileSummary, UploadResult } from './types';
import { AlertIcon, CloseIcon, DocumentIcon, TrashIcon, UploadIcon } from '../components/icons';

/**
 * TG RAG 콘솔
 *
 * 레이아웃: 상단 공통 바 아래로 왼쪽 문서 열 + 오른쪽 질의응답 캔버스. 큰 상자 없이 구분선 하나로 나눈다.
 *  - 왼쪽: 업로드 + 업로드된 문서 목록 — 자체 스크롤
 *  - 오른쪽: 가운데 읽기 폭으로 놓인 질문/답변(스크롤) + 하단에 떠 있는 입력창
 */

const PREVIEW_LEN = 200;

/** 업로드 가능한 확장자 (백엔드 parser/file_parser.py 의 SUPPORTED_EXTENSIONS 와 맞춘다) */
const UPLOAD_EXTENSIONS = [
    '.pdf', '.docx', '.pptx', '.xlsx', '.hwpx', '.hwp',
    '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp',
];

function fileExt(name: string): string {
    const i = name.lastIndexOf('.');
    return i < 0 ? '' : name.slice(i).toLowerCase();
}

const MODE_LABEL: Record<AskMode, string> = {
    claude: 'Claude API',
    local: '로컬 모델',
};

const timeFmt = new Intl.DateTimeFormat('ko-KR', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
});

function fmtTime(iso: string): string {
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? '—' : timeFmt.format(d);
}

function errMessage(e: unknown): string {
    if (e instanceof ApiError) {
        return e.code === 'network' ? `서버에 연결할 수 없습니다 (${e.message})` : e.message;
    }
    return e instanceof Error ? e.message : '알 수 없는 오류';
}

function truncate(text: string): string {
    return text.length > PREVIEW_LEN ? `${text.slice(0, PREVIEW_LEN)}…` : text;
}

/* ================================================================== */
/*  최상위                                                             */
/* ================================================================== */

export function RagConsole() {
    // 문서 목록은 서버(GET /files)가 기준이다. 업로드가 끝나면 다시 불러온다
    const [docs, setDocs] = useState<FileSummary[]>([]);
    const [docsLoading, setDocsLoading] = useState(true);
    const [docsError, setDocsError] = useState('');
    /** 직전 업로드 응답. 질의 로그가 비어 있을 때 캔버스에 요약으로 보여준다 */
    const [lastUpload, setLastUpload] = useState<UploadResult[]>([]);

    // setState는 모두 await 이후에 실행된다. 로딩 표시는 호출하는 쪽(refreshDocs)에서 켠다
    const loadDocs = useCallback(async () => {
        try {
            setDocs(await ragApi.listFiles());
            setDocsError('');
        } catch (e) {
            setDocsError(errMessage(e));
        } finally {
            setDocsLoading(false);
        }
    }, []);

    const refreshDocs = useCallback(() => {
        setDocsLoading(true);
        void loadDocs();
    }, [loadDocs]);

    useEffect(() => {
        // eslint-disable-next-line react-hooks/set-state-in-effect
        void loadDocs();
    }, [loadDocs]);

    const handleUploaded = useCallback(
        (results: UploadResult[]) => {
            setLastUpload(results);
            refreshDocs();
        },
        [refreshDocs],
    );

    return (
        <div className="min-h-screen md:h-dvh md:overflow-hidden bg-white text-ink font-sans antialiased flex flex-col">
            <AppHeader current="rag">
                <span className="hidden sm:block text-[12px] text-muted truncate">문서를 근거로 답하는 RAG 콘솔</span>
            </AppHeader>

            <div className="flex-1 min-h-0 flex flex-col md:flex-row">
                <aside className="md:w-[300px] xl:w-[320px] shrink-0 min-h-0 max-h-[45vh] md:max-h-none flex flex-col border-b md:border-b-0 md:border-r border-divide">
                    <UploadPanel onUploaded={handleUploaded} />
                    <DocumentList
                        docs={docs}
                        loading={docsLoading}
                        error={docsError}
                        onRefresh={refreshDocs}
                        onDeleted={refreshDocs}
                    />
                </aside>

                <Workspace docCount={docs.length} lastUpload={lastUpload} />
            </div>
        </div>
    );
}

/* ================================================================== */
/*  왼쪽 — 업로드                                                      */
/* ================================================================== */

function UploadPanel({ onUploaded }: { onUploaded: (results: UploadResult[]) => void }) {
    const [selected, setSelected] = useState<File[]>([]);
    const [isDragOver, setIsDragOver] = useState(false);
    const [uploading, setUploading] = useState(false);
    const [error, setError] = useState('');
    const inputRef = useRef<HTMLInputElement>(null);

    /** 지원 확장자만 받는다 (백엔드도 같은 목록 외에는 거부한다) */
    const pickFiles = useCallback((list: FileList | File[]) => {
        const all = Array.from(list);
        const accepted = all.filter((f) => UPLOAD_EXTENSIONS.includes(fileExt(f.name)));
        const skipped = all.length - accepted.length;
        setError(skipped > 0 ? `지원하지 않는 형식 ${skipped}개는 제외했습니다.` : '');
        if (accepted.length === 0) return;
        setSelected((prev) => [...prev, ...accepted]);
    }, []);

    const upload = async () => {
        if (selected.length === 0) return;
        setUploading(true);
        setError('');
        try {
            const data = await ragApi.upload(selected);
            setSelected([]);
            onUploaded(data.results);
        } catch (e) {
            setError(errMessage(e));
        } finally {
            setUploading(false);
        }
    };

    return (
        <section className="shrink-0 px-4 pt-4 pb-3">
            <button
                type="button"
                onClick={() => inputRef.current?.click()}
                onDrop={(e) => {
                    e.preventDefault();
                    setIsDragOver(false);
                    if (e.dataTransfer.files?.length) pickFiles(e.dataTransfer.files);
                }}
                onDragOver={(e) => {
                    e.preventDefault();
                    setIsDragOver(true);
                }}
                onDragLeave={() => setIsDragOver(false)}
                className={`w-full rounded-xl border border-dashed px-3.5 py-3 flex items-center gap-3 text-left transition-colors focus-visible:outline-2 focus-visible:outline-brand ${
                    isDragOver ? 'border-brand bg-brand-tint' : 'border-line hover:border-brand/50 hover:bg-brand-tint/60'
                }`}
            >
                <span className="w-9 h-9 shrink-0 rounded-lg bg-brand-pale text-brand flex items-center justify-center">
                    <UploadIcon className="w-[18px] h-[18px]" />
                </span>
                <span className="min-w-0">
                    <span className="block text-[13px] font-semibold">문서 추가</span>
                    <span className="block text-[11px] text-muted truncate">끌어다 놓거나 클릭 · PDF·Office·한글·이미지</span>
                </span>
            </button>
            <input
                ref={inputRef}
                type="file"
                accept={UPLOAD_EXTENSIONS.join(',')}
                multiple
                onChange={(e) => {
                    if (e.target.files) pickFiles(e.target.files);
                    e.target.value = '';
                }}
                className="hidden"
            />

            {selected.length > 0 && (
                <>
                    <ul className="mt-2 max-h-[132px] overflow-y-auto">
                        {selected.map((f, i) => (
                            <li key={`${f.name}-${i}`} className="h-8 flex items-center gap-2 px-1.5 rounded-lg hover:bg-surface">
                                <span className="flex-1 min-w-0 truncate text-[12px] font-medium" title={f.name}>
                                    {f.name}
                                </span>
                                <span className="shrink-0 text-[10px] text-muted tabular-nums">{(f.size / 1024).toFixed(0)}KB</span>
                                <button
                                    type="button"
                                    onClick={() => setSelected((p) => p.filter((_, x) => x !== i))}
                                    disabled={uploading}
                                    aria-label="선택 해제"
                                    className="shrink-0 w-5 h-5 rounded flex items-center justify-center text-muted hover:text-danger disabled:opacity-40 transition-colors"
                                >
                                    <CloseIcon />
                                </button>
                            </li>
                        ))}
                    </ul>

                    <button
                        type="button"
                        onClick={upload}
                        disabled={uploading}
                        className="mt-2 w-full h-9 rounded-xl bg-brand text-white text-[12.5px] font-bold inline-flex items-center justify-center gap-2 enabled:hover:bg-brand-hover disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                    >
                        {uploading && <span className="w-3.5 h-3.5 rounded-full border-2 border-white/40 border-t-white animate-spin" />}
                        {uploading ? '처리 중…' : `${selected.length}개 업로드`}
                    </button>
                </>
            )}

            {error && <InlineError>{error}</InlineError>}
        </section>
    );
}

/* ================================================================== */
/*  왼쪽 — 문서 목록                                                   */
/* ================================================================== */

function DocumentList({
    docs,
    loading,
    error,
    onRefresh,
    onDeleted,
}: {
    docs: FileSummary[];
    loading: boolean;
    error: string;
    onRefresh: () => void;
    onDeleted: () => void;
}) {
    const [deletingId, setDeletingId] = useState<string | null>(null);
    const [deleteError, setDeleteError] = useState('');

    const remove = async (doc: FileSummary) => {
        if (!window.confirm(`'${doc.original_name}'을(를) 삭제할까요?
검색에 쓰이는 임베딩도 함께 삭제됩니다.`)) {
            return;
        }
        setDeletingId(doc.file_id);
        setDeleteError('');
        try {
            await ragApi.deleteFile(doc.file_id);
            onDeleted();
        } catch (e) {
            setDeleteError(`삭제 실패: ${errMessage(e)}`);
        } finally {
            setDeletingId(null);
        }
    };

    return (
        <section className="flex-1 min-h-0 flex flex-col border-t border-divide">
            <div className="shrink-0 px-4 pt-3.5 pb-2 flex items-center justify-between gap-2">
                <h2 className="text-[13px] font-bold">
                    업로드된 문서 <span className="text-muted tabular-nums">{docs.length}</span>
                </h2>
                <button
                    type="button"
                    onClick={onRefresh}
                    disabled={loading}
                    className="h-7 px-2.5 rounded-lg text-[12px] font-semibold text-muted hover:text-ink hover:bg-chip disabled:opacity-40 transition-colors"
                >
                    {loading ? '불러오는 중' : '새로고침'}
                </button>
            </div>

            {(error || deleteError) && (
                <div className="shrink-0 px-4">
                    {error && <InlineError>목록을 불러오지 못했습니다: {error}</InlineError>}
                    {deleteError && <InlineError>{deleteError}</InlineError>}
                </div>
            )}

            <div className="flex-1 min-h-0 overflow-y-auto px-2 pb-3">
                {docs.length === 0 ? (
                    <p className="px-3 py-8 text-center text-[12px] text-muted">
                        {loading ? '불러오는 중…' : '아직 업로드된 문서가 없습니다.'}
                    </p>
                ) : (
                    <ul>
                        {docs.map((d) => (
                            <li key={d.file_id} className="group flex items-center gap-2.5 px-2 py-2 rounded-xl hover:bg-surface transition-colors">
                                <span className="w-8 h-8 shrink-0 rounded-lg bg-chip text-muted flex items-center justify-center text-[9px] font-bold">
                                    {fileExt(d.original_name).slice(1, 5).toUpperCase() || 'FILE'}
                                </span>
                                {/* 한 줄로 두고, 넘치면 오른쪽 끝을 흐리게 (전체 이름은 title로) */}
                                <p
                                    className="flex-1 min-w-0 overflow-hidden whitespace-nowrap text-[12.5px] font-semibold leading-[16px] [mask-image:linear-gradient(to_right,black_calc(100%-24px),transparent)]"
                                    title={d.original_name}
                                >
                                    {d.original_name}
                                </p>
                                <button
                                    type="button"
                                    onClick={() => void remove(d)}
                                    disabled={deletingId !== null}
                                    aria-label={`${d.original_name} 삭제`}
                                    title="삭제"
                                    className={`w-7 h-7 shrink-0 rounded-lg flex items-center justify-center text-muted hover:text-danger hover:bg-danger-surface disabled:opacity-40 transition focus-visible:opacity-100 ${
                                        deletingId === d.file_id ? 'opacity-100' : 'opacity-0 group-hover:opacity-100'
                                    }`}
                                >
                                    {deletingId === d.file_id ? (
                                        <span className="w-3 h-3 rounded-full border-2 border-line border-t-danger animate-spin" />
                                    ) : (
                                        <TrashIcon />
                                    )}
                                </button>
                            </li>
                        ))}
                    </ul>
                )}
            </div>
        </section>
    );
}

/* ================================================================== */
/*  오른쪽 — 질의응답                                                  */
/* ================================================================== */

interface QaTurn {
    id: string;
    question: string;
    mode: AskMode;
    queryTopN: number;
    rerankTopN: number;
    askedAt: string;
    status: 'pending' | 'done' | 'error';
    answer?: string;
    sources?: AskSource[];
    error?: string;
}

function Workspace({
    docCount,
    lastUpload,
}: {
    docCount: number;
    lastUpload: UploadResult[];
}) {
    const [turns, setTurns] = useState<QaTurn[]>([]);
    const [question, setQuestion] = useState('');
    const [mode, setMode] = useState<AskMode>('claude');
    const [queryTopN, setQueryTopN] = useState(5);
    const [rerankTopN, setRerankTopN] = useState(3);

    const logRef = useRef<HTMLDivElement>(null);
    const inputRef = useRef<HTMLTextAreaElement>(null);

    // 리랭킹은 검색 결과의 부분집합이므로 rerank_top_n <= query_top_n 이어야 한다
    const paramInvalid = rerankTopN > queryTopN;
    const busy = turns.some((t) => t.status === 'pending');
    const canSend = !!question.trim() && !paramInvalid && !busy;

    // 새 턴이 붙거나 답이 도착하면 로그를 맨 아래로
    useEffect(() => {
        logRef.current?.scrollTo({ top: logRef.current.scrollHeight, behavior: 'smooth' });
    }, [turns]);

    // 입력창 높이를 내용에 맞춰 늘린다 (최대 160px)
    useEffect(() => {
        const el = inputRef.current;
        if (!el) return;
        el.style.height = 'auto';
        el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
    }, [question]);

    const ask = async () => {
        const q = question.trim();
        if (!q || paramInvalid || busy) return;

        const turn: QaTurn = {
            id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
            question: q,
            mode,
            queryTopN,
            rerankTopN,
            askedAt: new Date().toISOString(),
            status: 'pending',
        };
        setTurns((prev) => [...prev, turn]);
        setQuestion('');

        const patch = (fields: Partial<QaTurn>) =>
            setTurns((prev) => prev.map((t) => (t.id === turn.id ? { ...t, ...fields } : t)));

        try {
            const res = await ragApi.ask({
                question: q,
                mode,
                query_top_n: queryTopN,
                rerank_top_n: rerankTopN,
            });
            patch({ status: 'done', answer: res.answer, sources: res.sources });
        } catch (e) {
            patch({ status: 'error', error: errMessage(e) });
        }
    };

    return (
        <main className="flex-1 min-w-0 min-h-0 flex flex-col">
            {/* 대화 로그 */}
            <div ref={logRef} className="flex-1 min-h-0 overflow-y-auto">
                {turns.length === 0 ? (
                    <EmptyWorkspace docCount={docCount} lastUpload={lastUpload} />
                ) : (
                    <div className="mx-auto w-full max-w-[760px] px-5 sm:px-10 pt-6 pb-4">
                        <div className="flex items-center gap-3 text-[12px] text-muted">
                            <span>
                                질문 {turns.length}개 · 문서 {docCount}건
                            </span>
                            <button
                                type="button"
                                onClick={() => setTurns([])}
                                disabled={busy}
                                className="ml-auto h-7 px-2.5 rounded-lg font-semibold hover:text-ink hover:bg-chip disabled:opacity-40 transition-colors"
                            >
                                기록 지우기
                            </button>
                        </div>
                        <div className="mt-4 flex flex-col gap-10">
                            {turns.map((t) => (
                                <TurnView key={t.id} turn={t} />
                            ))}
                        </div>
                    </div>
                )}
            </div>

            {/* 떠 있는 입력창 */}
            <div className="shrink-0 px-4 pb-4 pt-1">
                <div className="mx-auto w-full max-w-[760px] rounded-2xl bg-white border border-divide shadow-[0_8px_30px_rgba(20,28,43,0.10)] focus-within:border-brand/50 transition-colors">
                    <textarea
                        ref={inputRef}
                        rows={1}
                        value={question}
                        onChange={(e) => setQuestion(e.target.value)}
                        onKeyDown={(e) => {
                            // Enter 전송 · Shift+Enter 줄바꿈 (IME 조합 중에는 무시)
                            if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                                e.preventDefault();
                                void ask();
                            }
                        }}
                        placeholder={docCount > 0 ? '문서에 대해 질문하세요' : '문서를 올리거나, 서버에 있는 문서로 바로 질문하세요'}
                        className="block w-full resize-none bg-transparent px-4 pt-3.5 pb-1 text-[14px] leading-[22px] placeholder:text-muted focus:outline-none"
                    />
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-2 px-2.5 pb-2.5 pt-1">
                        <div className="flex p-0.5 rounded-lg bg-chip">
                            {(['claude', 'local'] as const).map((m) => (
                                <button
                                    key={m}
                                    type="button"
                                    onClick={() => setMode(m)}
                                    className={`h-6 px-2.5 rounded-md text-[11.5px] font-semibold transition-colors ${
                                        mode === m ? 'bg-white text-ink shadow-[0_1px_2px_rgba(20,28,43,0.10)]' : 'text-muted hover:text-ink'
                                    }`}
                                >
                                    {MODE_LABEL[m]}
                                </button>
                            ))}
                        </div>
                        <NumberField label="검색" hint="query_top_n" value={queryTopN} onChange={setQueryTopN} />
                        <NumberField
                            label="리랭킹"
                            hint="rerank_top_n"
                            value={rerankTopN}
                            onChange={setRerankTopN}
                            invalid={paramInvalid}
                        />
                        {paramInvalid && <span className="text-[11px] text-warn">리랭킹은 검색 개수 이하여야 합니다</span>}
                        <span className="hidden sm:inline ml-auto text-[10px] text-muted">Enter 전송 · Shift+Enter 줄바꿈</span>
                        <button
                            type="button"
                            onClick={ask}
                            disabled={!canSend}
                            className="ml-auto sm:ml-0 h-8 px-4 shrink-0 rounded-xl bg-brand text-white text-[12.5px] font-bold enabled:hover:bg-brand-hover disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                        >
                            {busy ? '생성 중…' : '질문'}
                        </button>
                    </div>
                </div>
            </div>
        </main>
    );
}

/** 로그가 비었을 때: 직전 업로드 결과가 있으면 그걸, 없으면 안내를 보여준다 */
function EmptyWorkspace({
    docCount,
    lastUpload,
}: {
    docCount: number;
    lastUpload: UploadResult[];
}) {
    if (lastUpload.length > 0) {
        const ok = lastUpload.filter((r) => !r.error);
        return (
            <div className="mx-auto w-full max-w-[760px] px-5 sm:px-10 pt-8 pb-4">
                <h2 className="text-[18px] font-bold">
                    업로드 완료 <span className="text-muted tabular-nums">{ok.length}/{lastUpload.length}</span>
                </h2>
                <p className="mt-1 text-[12px] text-muted">청크를 확인하고, 아래 입력창으로 질문해보세요.</p>
                <ul className="mt-4 divide-y divide-divide">
                    {lastUpload.map((r, i) => (
                        <UploadResultRow key={`${r.filename}-${i}`} result={r} />
                    ))}
                </ul>
            </div>
        );
    }

    return (
        <div className="h-full min-h-[280px] flex flex-col items-center justify-center text-center px-6">
            <div className="w-14 h-14 rounded-2xl bg-brand-pale flex items-center justify-center">
                <DocumentIcon className="w-7 h-7 text-brand" />
            </div>
            <p className="mt-5 text-[20px] font-bold tracking-tight">
                {docCount > 0 ? '무엇이든 물어보세요' : '문서를 올리고 질문해보세요'}
            </p>
            <p className="mt-2 text-[13px] text-muted max-w-[360px] leading-relaxed">
                {docCount > 0
                    ? `업로드된 문서 ${docCount}건을 검색해 근거와 함께 답합니다.`
                    : '업로드한 문서를 근거로 답변합니다. 이미 서버에 문서가 있다면 바로 질문해도 됩니다.'}
            </p>
        </div>
    );
}

/** 질문 1건 + 그 답변 */
function TurnView({ turn }: { turn: QaTurn }) {
    return (
        <article>
            {/* 질문 */}
            <div className="flex flex-col items-end">
                <p className="max-w-[85%] rounded-2xl rounded-br-md bg-chip px-4 py-2.5 text-[14px] leading-[21px] whitespace-pre-wrap break-words">
                    {turn.question}
                </p>
                <span className="mt-1.5 text-[10.5px] text-muted tabular-nums">
                    {MODE_LABEL[turn.mode]} · top {turn.queryTopN}/{turn.rerankTopN} · {fmtTime(turn.askedAt)}
                </span>
            </div>

            {/* 답변 */}
            <div className="mt-4 flex gap-3">
                <span className="w-8 h-8 shrink-0 rounded-full bg-brand text-white text-[10px] font-extrabold flex items-center justify-center">
                    AI
                </span>
                <div className="min-w-0 flex-1 pt-1">
                    {turn.status === 'pending' && (
                        <div className="flex items-center gap-2.5 text-[13px] text-muted">
                            <span className="w-4 h-4 rounded-full border-2 border-brand-pale border-t-brand animate-spin" />
                            문서를 찾아 답변을 만드는 중…
                        </div>
                    )}

                    {turn.status === 'error' && <ErrorLine title="답변 생성 실패" message={turn.error ?? ''} />}

                    {turn.status === 'done' && (
                        <>
                            {turn.answer ? (
                                <div className="prose prose-slate max-w-none text-[15px] leading-[1.8] prose-pre:bg-chip prose-pre:text-ink prose-code:before:content-none prose-code:after:content-none prose-code:bg-chip prose-code:px-1 prose-code:py-0.5 prose-code:rounded">
                                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{turn.answer}</ReactMarkdown>
                                </div>
                            ) : (
                                <p className="text-[13px] text-muted">(답변이 비어 있습니다)</p>
                            )}
                            {!!turn.sources?.length && <SourceList sources={turn.sources} />}
                        </>
                    )}
                </div>
            </div>
        </article>
    );
}

/** 참고한 청크. 접어 두고, 긴 청크는 클릭해서 펼친다 */
function SourceList({ sources }: { sources: AskSource[] }) {
    const [open, setOpen] = useState(false);
    const [expanded, setExpanded] = useState<Set<number>>(new Set());

    const toggle = (i: number) =>
        setExpanded((prev) => {
            const next = new Set(prev);
            if (next.has(i)) next.delete(i);
            else next.add(i);
            return next;
        });

    return (
        <div className="mt-3">
            <button
                type="button"
                onClick={() => setOpen((v) => !v)}
                aria-expanded={open}
                className="h-7 -ml-2 px-2 rounded-lg inline-flex items-center gap-1.5 text-[12px] font-semibold text-muted hover:text-ink hover:bg-chip transition-colors"
            >
                <DocumentIcon className="w-3.5 h-3.5" />
                참고한 청크 {sources.length}개
                <span aria-hidden className={`transition-transform ${open ? 'rotate-90' : ''}`}>
                    ›
                </span>
            </button>
            {open && (
                <ul className="mt-1 divide-y divide-divide">
                    {sources.map((s, i) => {
                        const isLong = s.text.length > PREVIEW_LEN;
                        const isOpen = expanded.has(i);
                        return (
                            <li
                                key={`${s.source}-${s.page}-${i}`}
                                onClick={() => isLong && toggle(i)}
                                title={isLong ? (isOpen ? '접기' : '전체 보기') : undefined}
                                className={`py-2.5 text-[12.5px] leading-[19px] ${isLong ? 'cursor-pointer' : ''}`}
                            >
                                <span className="block text-[11px] font-semibold text-muted truncate">
                                    {s.source} · p.{s.page}
                                </span>
                                <span className="mt-0.5 block whitespace-pre-wrap text-ink/80">{isOpen ? s.text : truncate(s.text)}</span>
                            </li>
                        );
                    })}
                </ul>
            )}
        </div>
    );
}

/* ================================================================== */
/*  공용 조각                                                          */
/* ================================================================== */

function UploadResultRow({ result }: { result: UploadResult }) {
    if (result.error) {
        return (
            <li className="py-3">
                <p className="text-[13px] font-semibold truncate">{result.filename || '(파일명 없음)'}</p>
                <p className="mt-0.5 text-[12px] text-danger break-words">{result.error}</p>
            </li>
        );
    }

    return (
        <li className="py-3">
            <p className="text-[13px] font-semibold truncate">{result.filename}</p>
            <p className="mt-0.5 text-[11px] text-muted">
                청크 {result.num_chunks ?? 0}개 · 저장 위치: {result.chunks_saved_to ?? '—'}
            </p>
            {!!result.chunks?.length && (
                <details className="mt-1.5">
                    <summary className="cursor-pointer text-[12px] font-semibold text-brand-hover hover:underline list-none">
                        청크 미리보기 ({result.chunks.length}개)
                    </summary>
                    <ul className="mt-1.5 divide-y divide-divide">
                        {result.chunks.map((c) => (
                            <li key={c.id} className="py-1.5 text-[12px] leading-[17px]">
                                <span className="mr-1.5 text-muted tabular-nums">
                                    [{c.id}] p{c.page}
                                </span>
                                <span className="whitespace-pre-wrap">{truncate(c.text)}</span>
                            </li>
                        ))}
                    </ul>
                </details>
            )}
        </li>
    );
}

function NumberField({
    label,
    hint,
    value,
    onChange,
    invalid = false,
}: {
    label: string;
    hint: string;
    value: number;
    onChange: (v: number) => void;
    invalid?: boolean;
}) {
    return (
        <label className="flex items-center gap-1.5 text-[11.5px] text-muted" title={hint}>
            <span>{label}</span>
            <input
                type="number"
                min={1}
                max={50}
                value={value}
                onChange={(e) => {
                    // 입력 중 빈 값은 최소값으로 고정해 NaN이 API로 넘어가지 않게 한다
                    const n = Number(e.target.value);
                    onChange(Number.isFinite(n) && n >= 1 ? Math.min(Math.trunc(n), 50) : 1);
                }}
                className={`w-12 h-6 px-1.5 rounded-md bg-chip text-[12px] text-ink tabular-nums focus:outline-none focus:bg-white focus:ring-2 transition ${
                    invalid ? 'ring-2 ring-warn/60' : 'focus:ring-brand/30'
                }`}
            />
        </label>
    );
}

function InlineError({ children }: { children: ReactNode }) {
    return (
        <p role="alert" className="mt-2 text-[11.5px] leading-[16px] text-danger break-words">
            {children}
        </p>
    );
}

function ErrorLine({ title, message }: { title: string; message: string }) {
    return (
        <div role="alert" className="flex gap-2.5 text-[13px] leading-[19px]">
            <AlertIcon className="w-[18px] h-[18px] shrink-0 mt-px text-danger" />
            <div className="min-w-0">
                <p className="font-bold text-danger">{title}</p>
                <p className="text-danger/90 break-words">{message}</p>
            </div>
        </div>
    );
}
