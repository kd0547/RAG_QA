import { useCallback, useEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

import { ApiError } from '../lib/http';
import { navigate } from '../lib/router';
import { ragApi } from './api';
import type { AskMode, AskSource, FileSummary, UploadResult } from './types';
import { AlertIcon, CloseIcon, DocumentIcon, LogoMark, TrashIcon, UploadIcon } from '../components/icons';

/**
 * RAG 콘솔 (기존 app/static/index.html 대체)
 *
 * 레이아웃: 좌측 사이드바(문서 관리) + 우측 질의응답 워크스페이스.
 *  - 좌: 업로드 + 업로드된 문서 목록 — 자체 스크롤
 *  - 우: 질문/답변 로그(스크롤) + 하단 고정 입력창
 * 페이지 전체는 스크롤되지 않고 각 패널이 독립적으로 스크롤한다.
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
    /** 직전 업로드 응답. 질의 로그가 비어 있을 때 워크스페이스에 요약으로 보여준다 */
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
        <div className="flex h-screen w-full bg-white text-ink font-sans antialiased">
            <aside className="w-[332px] min-w-[332px] shrink-0 flex flex-col border-r border-divide pl-7 pr-[18px] py-7">
                {/* 브랜드 + 다른 화면 이동 */}
                <div className="shrink-0">
                    <div className="flex items-center justify-between gap-2">
                        <div className="flex items-center gap-2">
                            <LogoMark className="w-[21px] h-[21px]" />
                            <span className="text-[17px] font-bold tracking-tight leading-none">
                                TG RAG
                            </span>
                        </div>
                        <nav className="flex items-center gap-1">
                            <NavButton label="메일" onClick={() => navigate('/mail')} />
                            <NavButton label="OCR" onClick={() => navigate('/ocr')} />
                        </nav>
                    </div>
                    <p className="mt-[8px] pl-[23px] text-[10px] leading-none text-muted">
                        문서를 근거로 답하는 RAG 콘솔
                    </p>
                </div>

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
    );
}

/** 사이드바의 다른 화면 이동 버튼 */
function NavButton({ label, onClick }: { label: string; onClick: () => void }) {
    return (
        <button
            type="button"
            onClick={onClick}
            className="h-[22px] px-2 rounded-md border border-line bg-white text-[11px] font-medium text-muted hover:text-ink hover:border-brand hover:bg-brand-tint transition-colors"
        >
            {label}
        </button>
    );
}

/* ================================================================== */
/*  사이드바 — 업로드                                                  */
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
        <section className="shrink-0">
            <h2 className="mt-[26px] text-[13px] font-semibold">문서 업로드</h2>

            <div
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
                className={`mt-[9px] h-[104px] cursor-pointer rounded-xl border border-dashed flex flex-col items-center justify-center text-center transition-colors ${
                    isDragOver
                        ? 'border-brand bg-brand-tint'
                        : 'border-line bg-surface hover:border-brand/50 hover:bg-brand-tint/60'
                }`}
            >
                <UploadIcon className="w-[22px] h-[22px] text-muted" />
                <p className="mt-[7px] text-[12px] font-medium text-muted">
                    클릭 또는 드래그해서 추가
                </p>
                <p className="mt-[3px] text-[10px] text-muted/70">PDF · Word · PowerPoint · Excel · 한글(hwp·hwpx) · 이미지</p>
            </div>
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
                    <ul className="mt-2 max-h-[132px] overflow-y-auto space-y-1">
                        {selected.map((f, i) => (
                            <li
                                key={`${f.name}-${i}`}
                                className="h-8 flex items-center gap-1.5 rounded-lg border border-line bg-white pl-2.5 pr-2"
                            >
                                <span
                                    className="flex-1 min-w-0 truncate text-[11px] font-medium"
                                    title={f.name}
                                >
                                    {f.name}
                                </span>
                                <span className="shrink-0 text-[10px] text-muted tabular-nums">
                                    {(f.size / 1024).toFixed(0)}KB
                                </span>
                                <button
                                    type="button"
                                    onClick={() => setSelected((p) => p.filter((_, x) => x !== i))}
                                    disabled={uploading}
                                    aria-label="선택 해제"
                                    className="shrink-0 text-muted hover:text-danger disabled:opacity-40 transition-colors"
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
                        className="mt-2 w-full h-8 rounded-[9px] bg-brand text-white text-[12px] font-semibold inline-flex items-center justify-center gap-2 enabled:hover:bg-brand-hover disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                    >
                        {uploading && (
                            <span className="w-3.5 h-3.5 rounded-full border-2 border-white/40 border-t-white animate-spin" />
                        )}
                        {uploading ? '처리 중...' : `${selected.length}개 업로드`}
                    </button>
                </>
            )}

            {error && (
                <p className="mt-2 rounded-lg border border-danger bg-danger-surface px-2.5 py-1.5 text-[11px] leading-[15px] text-danger break-words">
                    {error}
                </p>
            )}
        </section>
    );
}

/* ================================================================== */
/*  사이드바 — 문서 목록                                               */
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
        <section className="mt-[30px] flex-1 min-h-0 flex flex-col">
            <div className="shrink-0 flex items-center justify-between gap-2">
                <h2 className="text-[13px] font-semibold">업로드된 문서 ({docs.length})</h2>
                <button
                    type="button"
                    onClick={onRefresh}
                    disabled={loading}
                    className="h-6 px-2 rounded-lg border border-line bg-white text-[11px] text-muted hover:text-ink hover:border-brand disabled:opacity-40 transition-colors"
                >
                    {loading ? '불러오는 중' : '새로고침'}
                </button>
            </div>

            {error && (
                <p className="shrink-0 mt-2 rounded-lg border border-danger bg-danger-surface px-2.5 py-1.5 text-[11px] leading-[15px] text-danger break-words">
                    목록을 불러오지 못했습니다: {error}
                </p>
            )}
            {deleteError && (
                <p className="shrink-0 mt-2 rounded-lg border border-danger bg-danger-surface px-2.5 py-1.5 text-[11px] leading-[15px] text-danger break-words">
                    {deleteError}
                </p>
            )}

            <div className="mt-[7px] flex-1 min-h-0 overflow-y-auto">
                {docs.length === 0 ? (
                    <div className="h-14 rounded-xl border border-line bg-white flex items-center justify-center text-[11px] text-muted">
                        {loading ? '불러오는 중...' : '아직 업로드된 문서가 없습니다.'}
                    </div>
                ) : (
                    <ul className="space-y-1.5">
                        {docs.map((d) => (
                            <li
                                key={d.file_id}
                                className="rounded-xl border border-line bg-white px-2.5 py-2 hover:border-brand/50 transition-colors"
                            >
                                <div className="flex items-center gap-2">
                                    <div className="w-[26px] h-[26px] shrink-0 rounded-md bg-chip text-muted flex items-center justify-center text-[9px] font-bold">
                                        {fileExt(d.original_name).slice(1, 5).toUpperCase() || 'FILE'}
                                    </div>
                                    {/* 한 줄로 두고, 넘치면 오른쪽 끝을 흐리게 (전체 이름은 title로) */}
                                    <p
                                        className="flex-1 min-w-0 overflow-hidden whitespace-nowrap text-[12px] font-semibold leading-[16px] [mask-image:linear-gradient(to_right,black_calc(100%-28px),transparent)]"
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
                                        className="w-6 h-6 shrink-0 rounded-md flex items-center justify-center text-muted hover:text-danger hover:bg-danger-surface disabled:opacity-40 transition-colors"
                                    >
                                        {deletingId === d.file_id ? (
                                            <span className="w-3 h-3 rounded-full border-2 border-line border-t-danger animate-spin" />
                                        ) : (
                                            <TrashIcon />
                                        )}
                                    </button>
                                </div>
                            </li>
                        ))}
                    </ul>
                )}
            </div>
        </section>
    );
}

/* ================================================================== */
/*  워크스페이스 — 질의응답                                            */
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

    // 입력창 높이를 내용에 맞춰 늘린다 (최대 120px)
    useEffect(() => {
        const el = inputRef.current;
        if (!el) return;
        el.style.height = 'auto';
        el.style.height = `${Math.min(el.scrollHeight, 120)}px`;
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
        <main className="flex-1 min-w-0 pt-7 pr-7 pb-7 pl-[18px]">
            <div className="h-full flex flex-col rounded-2xl border border-line bg-surface overflow-hidden">
                {/* 헤더 */}
                <header className="h-[66px] shrink-0 px-5 flex items-center justify-between gap-4 border-b border-divide">
                    <div className="min-w-0">
                        <h1 className="text-[15px] font-bold leading-none">질의응답</h1>
                        <p className="mt-[7px] text-[13px] leading-none text-muted truncate">
                            {turns.length > 0
                                ? `${turns.length}개 질문 · 문서 ${docCount}건`
                                : '업로드된 문서를 근거로 에이전트가 답변합니다'}
                        </p>
                    </div>
                    {turns.length > 0 && (
                        <button
                            type="button"
                            onClick={() => setTurns([])}
                            disabled={busy}
                            className="shrink-0 h-7 px-3 rounded-lg border border-line bg-white text-[12px] text-muted hover:text-ink hover:border-brand disabled:opacity-40 transition-colors"
                        >
                            기록 지우기
                        </button>
                    )}
                </header>

                {/* 로그 */}
                <div ref={logRef} className="flex-1 min-h-0 overflow-y-auto px-5 py-5">
                    {turns.length === 0 ? (
                        <EmptyWorkspace docCount={docCount} lastUpload={lastUpload} />
                    ) : (
                        <div className="space-y-7">
                            {turns.map((t) => (
                                <TurnView key={t.id} turn={t} />
                            ))}
                        </div>
                    )}
                </div>

                {/* 입력 (하단 고정) */}
                <div className="shrink-0 border-t border-divide bg-white px-5 py-3.5">
                    <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
                        <div className="flex items-center gap-1 p-[3px] rounded-[10px] bg-track">
                            {(['claude', 'local'] as const).map((m) => (
                                <button
                                    key={m}
                                    type="button"
                                    onClick={() => setMode(m)}
                                    className={`h-6 px-3 rounded-lg text-[12px] transition-colors ${
                                        mode === m
                                            ? 'bg-white border border-brand font-semibold text-ink'
                                            : 'font-medium text-muted hover:text-ink'
                                    }`}
                                >
                                    {MODE_LABEL[m]}
                                </button>
                            ))}
                        </div>
                        <NumberField
                            label="검색"
                            hint="query_top_n"
                            value={queryTopN}
                            onChange={setQueryTopN}
                        />
                        <NumberField
                            label="리랭킹"
                            hint="rerank_top_n"
                            value={rerankTopN}
                            onChange={setRerankTopN}
                            invalid={paramInvalid}
                        />
                        {paramInvalid && (
                            <span className="text-[11px] text-warn">
                                ⚠ 리랭킹은 검색 개수보다 작거나 같아야 합니다
                            </span>
                        )}
                    </div>

                    <div className="mt-2.5 flex items-end gap-2">
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
                            placeholder="문서에 대해 질문하세요"
                            className="flex-1 min-w-0 resize-none px-3 py-2 rounded-lg border border-line bg-white text-[13px] leading-[20px] placeholder:text-muted focus:border-brand focus:outline-none transition-colors"
                        />
                        <button
                            type="button"
                            onClick={ask}
                            disabled={!canSend}
                            className="h-9 px-4 shrink-0 rounded-[9px] bg-brand text-white text-[12px] font-semibold enabled:hover:bg-brand-hover disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                        >
                            {busy ? '생성 중' : '질문'}
                        </button>
                    </div>
                    <p className="mt-1.5 text-[10px] text-muted">
                        Enter 전송 · Shift+Enter 줄바꿈
                    </p>
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
            <div>
                <h2 className="text-[13px] font-semibold">
                    업로드 완료 · {ok.length}/{lastUpload.length}건
                </h2>
                <p className="mt-[5px] text-[11px] text-muted">
                    아래에서 청크를 확인하고, 하단 입력창으로 질문해보세요.
                </p>
                <ul className="mt-3 space-y-2.5">
                    {lastUpload.map((r, i) => (
                        <UploadResultCard key={`${r.filename}-${i}`} result={r} />
                    ))}
                </ul>
            </div>
        );
    }

    return (
        <div className="h-full flex flex-col items-center justify-center text-center">
            <div className="w-[76px] h-[76px] rounded-full bg-brand-pale flex items-center justify-center">
                <DocumentIcon className="w-8 h-8 text-brand" />
            </div>
            <p className="mt-6 text-[15px] font-medium">
                {docCount > 0 ? '무엇이든 물어보세요' : '왼쪽에서 문서를 업로드하세요'}
            </p>
            <p className="mt-2 text-[12px] text-muted max-w-[320px]">
                {docCount > 0
                    ? '하단 입력창에 질문을 적으면 문서를 검색해 근거와 함께 답합니다.'
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
            <div className="flex justify-end">
                <p className="max-w-[80%] rounded-2xl rounded-br-md bg-brand px-4 py-2.5 text-[13px] leading-[19px] text-white whitespace-pre-wrap break-words">
                    {turn.question}
                </p>
            </div>
            <div className="mt-1.5 flex justify-end items-center gap-2 text-[10px] text-muted tabular-nums">
                <span>{MODE_LABEL[turn.mode]}</span>
                <span>·</span>
                <span>
                    top {turn.queryTopN}/{turn.rerankTopN}
                </span>
                <span>·</span>
                <span>{fmtTime(turn.askedAt)}</span>
            </div>

            {/* 답변 */}
            <div className="mt-3">
                {turn.status === 'pending' && (
                    <div className="flex items-center gap-2.5 text-[13px] text-muted">
                        <span className="w-4 h-4 rounded-full border-2 border-brand-pale border-t-brand animate-spin" />
                        답변 생성 중...
                    </div>
                )}

                {turn.status === 'error' && (
                    <ErrorBox title="답변 생성 실패" message={turn.error ?? ''} />
                )}

                {turn.status === 'done' && (
                    <>
                        <div className="rounded-xl border border-line bg-white px-5 py-4">
                            {turn.answer ? (
                                <div className="prose prose-slate prose-sm max-w-none prose-pre:bg-chip prose-pre:text-ink prose-code:before:content-none prose-code:after:content-none prose-code:bg-chip prose-code:px-1 prose-code:py-0.5 prose-code:rounded">
                                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                                        {turn.answer}
                                    </ReactMarkdown>
                                </div>
                            ) : (
                                <p className="text-[13px] text-muted">(답변이 비어 있습니다)</p>
                            )}
                        </div>
                        {!!turn.sources?.length && <SourceList sources={turn.sources} />}
                    </>
                )}
            </div>
        </article>
    );
}

/** 참고한 청크. 긴 청크는 클릭해서 펼친다 */
function SourceList({ sources }: { sources: AskSource[] }) {
    const [expanded, setExpanded] = useState<Set<number>>(new Set());

    const toggle = (i: number) =>
        setExpanded((prev) => {
            const next = new Set(prev);
            if (next.has(i)) next.delete(i);
            else next.add(i);
            return next;
        });

    return (
        <details className="mt-2 rounded-xl border border-line bg-white px-4 py-2.5">
            <summary className="cursor-pointer text-[12px] font-medium text-brand hover:text-brand-hover list-none">
                참고한 청크 ({sources.length}개)
            </summary>
            <ul className="mt-1.5 divide-y divide-divide">
                {sources.map((s, i) => {
                    const isLong = s.text.length > PREVIEW_LEN;
                    const isOpen = expanded.has(i);
                    return (
                        <li
                            key={`${s.source}-${s.page}-${i}`}
                            onClick={() => isLong && toggle(i)}
                            title={isLong ? (isOpen ? '접기' : '전체 보기') : undefined}
                            className={`py-1.5 text-[12px] leading-[17px] rounded transition-colors ${
                                isLong ? 'cursor-pointer hover:bg-brand-tint' : ''
                            }`}
                        >
                            <span className="mr-1.5 text-muted">
                                {s.source} p{s.page}
                            </span>
                            <span className="whitespace-pre-wrap">
                                {isOpen ? s.text : truncate(s.text)}
                            </span>
                        </li>
                    );
                })}
            </ul>
        </details>
    );
}

/* ================================================================== */
/*  공용 조각                                                          */
/* ================================================================== */

function UploadResultCard({ result }: { result: UploadResult }) {
    if (result.error) {
        return (
            <li className="rounded-xl border border-danger bg-danger-surface px-4 py-3">
                <p className="text-[13px] font-semibold truncate">
                    {result.filename || '(파일명 없음)'}
                </p>
                <p className="mt-1 text-[12px] text-danger break-words">{result.error}</p>
            </li>
        );
    }

    return (
        <li className="rounded-xl border border-line bg-white px-4 py-3">
            <p className="text-[13px] font-semibold truncate">{result.filename}</p>
            <p className="mt-1 text-[11px] text-muted">
                청크 {result.num_chunks ?? 0}개 · 저장 위치: {result.chunks_saved_to ?? '—'}
            </p>
            {!!result.chunks?.length && (
                <details className="mt-2">
                    <summary className="cursor-pointer text-[12px] font-medium text-brand hover:text-brand-hover list-none">
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
        <label className="flex items-center gap-1.5 text-[11px] text-muted" title={hint}>
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
                className={`w-14 h-7 px-2 rounded-lg border bg-white text-[12px] text-ink tabular-nums focus:outline-none transition-colors ${
                    invalid ? 'border-warn' : 'border-line focus:border-brand'
                }`}
            />
        </label>
    );
}

function ErrorBox({ title, message }: { title: string; message: string }) {
    return (
        <div className="rounded-xl border border-danger bg-danger-surface px-5 py-3 flex gap-4">
            <AlertIcon className="w-5 h-5 shrink-0 text-danger" />
            <div className="min-w-0 text-[13px] leading-[18px]">
                <p className="font-bold text-danger">{title}</p>
                <p className="text-danger break-words">{message}</p>
            </div>
        </div>
    );
}
