import { useCallback, useEffect, useRef, useState, useSyncExternalStore, type ReactNode } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

import { AppHeader } from '../components/AppHeader';
import { ApiError } from '../lib/http';
import { navigate, subscribeRoute } from '../lib/router';
import { FileList as RegisteredFileList } from './FileList';
import { GroupHome } from './GroupHome';
import { GroupInfoSidebar } from './GroupInfoSidebar';
import { ragApi } from './api';
import type { AskMode, AskSource, FileDetail, FileGroup, FileSummary, UploadResult } from './types';
import { AlertIcon, CloseIcon, DocumentIcon, UploadIcon } from '../components/icons';

/**
 * TG RAG 콘솔
 *
 * 문서 그룹을 만든 뒤 해당 그룹에 파일을 등록한다.
 * 질의응답은 상단 버튼으로 전환하며 대화와 입력 내용은 유지한다.
 */

const PREVIEW_LEN = 200;
let nextUploadDraftId = 0;

interface UploadDraft {
    id: string;
    file: File;
    description: string;
}

/** 업로드 가능한 확장자 (백엔드 parser/file_parser.py 의 SUPPORTED_EXTENSIONS 와 맞춘다) */
const UPLOAD_EXTENSIONS = [
    '.pdf', '.docx', '.pptx', '.xlsx', '.hwpx', '.hwp',
    '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp',
];

function fileExt(name: string): string {
    const i = name.lastIndexOf('.');
    return i < 0 ? '' : name.slice(i).toLowerCase();
}

function formatBytes(bytes: number): string {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 ** 2) return `${Math.round(bytes / 1024)} KB`;
    return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
}

function uploadOutcome(result: UploadResult): 'ready' | 'empty' | 'duplicate' | 'error' {
    if (result.error) return 'error';
    if (result.skipped === 'duplicate') return 'duplicate';
    if (result.num_chunks === 0) return 'empty';
    return 'ready';
}

function uploadCounts(results: UploadResult[]) {
    return results.reduce(
        (counts, result) => {
            counts[uploadOutcome(result)] += 1;
            return counts;
        },
        { ready: 0, empty: 0, duplicate: 0, error: 0 },
    );
}

function matchUploadResults(files: UploadDraft[], returned: UploadResult[]): UploadResult[] {
    const remaining = [...returned];
    return files.map(({ file }) => {
        const index = remaining.findIndex((result) => result.filename === file.name);
        if (index < 0) {
            return { filename: file.name, error: '처리 결과를 받지 못했습니다. 파일 목록에서 등록 여부를 확인해 주세요.' };
        }
        return remaining.splice(index, 1)[0];
    });
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

/** 아직 문서 그룹에 속하지 않은 기존 파일의 표시 이름 */
const UNGROUPED_LABEL = '미분류';

function fileViewKey(): string {
    const params = new URLSearchParams(window.location.search);
    if (params.get('unassigned') === '1') return 'unassigned';
    const groupId = params.get('group');
    return groupId ? `group:${groupId}` : 'groups';
}

function consoleViewKey(): string {
    const documentView = fileViewKey();
    return new URLSearchParams(window.location.search).get('qa') === '1'
        ? `qa|${documentView}`
        : documentView;
}

function viewPath(view: string, qa = false): string {
    const params = new URLSearchParams();
    if (view === 'unassigned') params.set('unassigned', '1');
    else if (view.startsWith('group:')) params.set('group', view.slice(6));
    if (qa) params.set('qa', '1');
    const query = params.toString();
    return query ? `/?${query}` : '/';
}

/* ================================================================== */
/*  최상위                                                             */
/* ================================================================== */

export function RagConsole() {
    const routeView = useSyncExternalStore(subscribeRoute, consoleViewKey);
    const workspaceOpen = routeView.startsWith('qa|');
    const view = workspaceOpen ? routeView.slice(3) : routeView;
    const [docs, setDocs] = useState<FileSummary[]>([]);
    const [groups, setGroups] = useState<FileGroup[]>([]);
    const [docsLoading, setDocsLoading] = useState(true);
    const [groupsLoading, setGroupsLoading] = useState(true);
    const [docsError, setDocsError] = useState('');
    const [groupsError, setGroupsError] = useState('');
    const [selectedDoc, setSelectedDoc] = useState<FileSummary | null>(null);
    const detailTriggerRef = useRef<HTMLElement | null>(null);
    const [lastUpload, setLastUpload] = useState<UploadResult[]>([]);
    const [lastUploadGroupId, setLastUploadGroupId] = useState<string | null>(null);
    const [uploadDrafts, setUploadDrafts] = useState<Record<string, UploadDraft[]>>({});
    const [uploadErrors, setUploadErrors] = useState<Record<string, string>>({});
    const [uploadingGroupId, setUploadingGroupId] = useState<string | null>(null);
    const [uploadNotice, setUploadNotice] = useState<{ groupId: string; message: string } | null>(null);
    const loadRequestRef = useRef(0);

    const loadDocs = useCallback(async () => {
        const requestId = ++loadRequestRef.current;
        const [filesResult, groupsResult] = await Promise.allSettled([ragApi.listFiles(), ragApi.listGroups()]);
        if (requestId !== loadRequestRef.current) return;
        if (filesResult.status === 'fulfilled') {
            setDocs(filesResult.value);
            setSelectedDoc((current) => filesResult.value.find((file) => file.file_id === current?.file_id) ?? null);
            setDocsError('');
        } else {
            setDocsError(errMessage(filesResult.reason));
        }
        if (groupsResult.status === 'fulfilled') {
            setGroups(groupsResult.value);
            setGroupsError('');
        } else {
            setGroupsError(errMessage(groupsResult.reason));
        }
        setDocsLoading(false);
        setGroupsLoading(false);
    }, []);

    const refreshDocs = useCallback(() => {
        setDocsLoading(true);
        setGroupsLoading(true);
        void loadDocs();
    }, [loadDocs]);

    useEffect(() => {
        // eslint-disable-next-line react-hooks/set-state-in-effect
        void loadDocs();
    }, [loadDocs]);

    const handleUploaded = (groupId: string, results: UploadResult[]) => {
        setLastUpload(results);
        setLastUploadGroupId(groupId);
        refreshDocs();
    };

    const updateUploadDraft = (groupId: string, update: (files: UploadDraft[]) => UploadDraft[]) => {
        setUploadDrafts((current) => ({ ...current, [groupId]: update(current[groupId] ?? []) }));
    };

    const uploadFiles = async (groupId: string) => {
        const submitted = [...(uploadDrafts[groupId] ?? [])];
        if (submitted.length === 0 || uploadingGroupId) return;
        setUploadingGroupId(groupId);
        setUploadErrors((current) => ({ ...current, [groupId]: '' }));
        setUploadNotice(null);
        setLastUpload([]);
        setLastUploadGroupId(null);
        try {
            const data = await ragApi.upload(
                submitted.map((draft) => draft.file),
                groupId,
                submitted.map((draft) => draft.description.trim()),
            );
            const results = matchUploadResults(submitted, data.results);
            setUploadDrafts((current) => ({
                ...current,
                [groupId]: submitted.filter((_, index) => uploadOutcome(results[index]) === 'error'),
            }));
            handleUploaded(groupId, results);
            if (consoleViewKey() !== `group:${groupId}`) {
                const counts = uploadCounts(results);
                setUploadNotice({ groupId, message: `파일 등록 결과: 완료 ${counts.ready}개 · 내용 없음 ${counts.empty}개 · 중복 ${counts.duplicate}개 · 실패 ${counts.error}개` });
            }
        } catch (e) {
            const message = errMessage(e);
            setUploadErrors((current) => ({ ...current, [groupId]: message }));
            if (consoleViewKey() !== `group:${groupId}`) {
                setUploadNotice({ groupId, message: `파일 등록 실패: ${message}` });
            }
        } finally {
            setUploadingGroupId(null);
        }
    };

    const createGroup = async (name: string, description: string) => {
        const created = await ragApi.createGroup(name, description);
        setGroups((current) => [...current, created]);
        refreshDocs();
        navigate(`/?group=${encodeURIComponent(created.id)}`);
    };

    const updateGroup = async (groupId: string, name: string, description: string) => {
        const updated = await ragApi.updateGroup(groupId, { name, description });
        setGroups((current) => current.map((group) => group.id === groupId ? updated : group));
        refreshDocs();
    };

    const updateGroupDescription = async (groupId: string, description: string) => {
        const updated = await ragApi.updateGroup(groupId, { description });
        setGroups((current) => current.map((group) => group.id === groupId ? updated : group));
        refreshDocs();
    };

    const activeGroupId = view.startsWith('group:') ? view.slice(6) : null;
    const activeGroup = groups.find((group) => group.id === activeGroupId) ?? null;
    const unassigned = view === 'unassigned';
    const visibleDocs = docs.filter((doc) => unassigned ? !doc.group_id : doc.group_id === activeGroupId);
    const unassignedCount = docs.filter((doc) => !doc.group_id).length;
    const otherUploadInProgress = uploadingGroupId !== null && (workspaceOpen || view !== `group:${uploadingGroupId}`);
    const otherUploadNotice = uploadNotice !== null && (workspaceOpen || view !== `group:${uploadNotice.groupId}`);
    const detailVisible = !!selectedDoc && !workspaceOpen
        && (unassigned ? !selectedDoc.group_id : !!activeGroup && selectedDoc.group_id === activeGroup.id);

    const openDetail = (doc: FileSummary) => {
        detailTriggerRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
        setSelectedDoc(doc);
    };

    const closeDetail = () => {
        setSelectedDoc(null);
        const trigger = detailTriggerRef.current;
        window.requestAnimationFrame(() => trigger?.focus());
    };

    useEffect(() => {
        // 다른 그룹으로 이동하면 이전 그룹의 파일 상세를 닫는다.
        // eslint-disable-next-line react-hooks/set-state-in-effect
        setSelectedDoc(null);
    }, [view]);

    useEffect(() => {
        if (!detailVisible) return;
        const previousOverflow = document.body.style.overflow;
        document.body.style.overflow = 'hidden';
        return () => { document.body.style.overflow = previousOverflow; };
    }, [detailVisible]);

    return (
        <div className="min-h-screen md:h-dvh md:overflow-hidden bg-white text-ink font-sans antialiased flex flex-col">
            <AppHeader
                current="rag"
                aside={
                    <button
                        type="button"
                        onClick={() => {
                            setSelectedDoc(null);
                            navigate(viewPath(view, !workspaceOpen));
                        }}
                        className="h-8 px-3 rounded-lg border border-line text-[12px] font-semibold hover:bg-surface"
                    >
                        {workspaceOpen ? '문서 관리' : '질의응답'}
                    </button>
                }
            >
                <span className="hidden sm:block text-[12px] text-muted truncate">{workspaceOpen ? '질의응답' : '문서 관리'}</span>
            </AppHeader>

            {(otherUploadInProgress || otherUploadNotice) && (
                <div role="status" className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-brand/20 bg-brand-tint px-4 py-2 text-[12px] text-ink sm:px-8">
                    {otherUploadInProgress ? (
                        <span>다른 문서 그룹의 파일을 등록하고 있습니다.</span>
                    ) : (
                        <span>{uploadNotice?.message}</span>
                    )}
                    <button
                        type="button"
                        onClick={() => {
                            const groupId = uploadingGroupId ?? uploadNotice?.groupId;
                            if (!groupId) return;
                            setUploadNotice(null);
                            navigate(viewPath(`group:${groupId}`));
                        }}
                        className="font-bold text-brand-hover underline"
                    >
                        해당 그룹 보기
                    </button>
                    {otherUploadNotice && !otherUploadInProgress && (
                        <button type="button" onClick={() => setUploadNotice(null)} className="ml-auto text-ink/70 underline">닫기</button>
                    )}
                </div>
            )}

            <div className={`${workspaceOpen ? 'hidden' : 'flex'} flex-1 min-h-0 flex-col`}>
                <main className="flex-1 min-h-0 overflow-y-auto">
                    {view === 'groups' ? (
                        <GroupHome
                            groups={groups}
                            ungroupedCount={unassignedCount}
                            loading={groupsLoading || docsLoading}
                            error={groupsError || docsError}
                            onCreate={createGroup}
                            onUpdate={updateGroup}
                            onOpenGroup={(id) => navigate(`/?group=${encodeURIComponent(id)}`)}
                            onOpenUngrouped={() => navigate('/?unassigned=1')}
                            onRefresh={refreshDocs}
                        />
                    ) : (
                        <div className="mx-auto w-full max-w-[1280px] px-4 pb-12 sm:px-6">
                            <div className="pt-6 pb-5">
                                <button type="button" onClick={() => navigate('/')} className="text-[12px] font-semibold text-brand-hover hover:underline focus-visible:outline-2 focus-visible:outline-brand">
                                    ← 문서 그룹
                                </button>
                                <h1 className="mt-3 break-words text-[22px] font-bold tracking-tight">{unassigned ? '미분류 파일' : activeGroup ? '파일 관리' : '문서 그룹'}</h1>
                                <p className="mt-1 text-[12.5px] leading-relaxed text-ink/70">
                                    {unassigned
                                        ? '기존 파일을 선택해 문서 그룹으로 옮길 수 있습니다.'
                                        : activeGroup ? `‘${activeGroup.name}’ 그룹에 파일을 등록하고 관리합니다.` : '문서 그룹을 확인하는 중입니다.'}
                                </p>
                            </div>
                            <div className={activeGroup ? 'lg:grid lg:grid-cols-[260px_minmax(0,1fr)] lg:items-start lg:gap-6' : ''}>
                                {activeGroup && <GroupInfoSidebar key={activeGroup.id} group={activeGroup} onSaveDescription={(description) => updateGroupDescription(activeGroup.id, description)} />}
                                <div className="min-w-0">
                                    {!unassigned && activeGroup && (
                                        <UploadPanel
                                            group={activeGroup}
                                            selected={uploadDrafts[activeGroup.id] ?? []}
                                            onSelectedChange={(update) => updateUploadDraft(activeGroup.id, update)}
                                            uploading={uploadingGroupId === activeGroup.id}
                                            busy={uploadingGroupId !== null}
                                            error={uploadErrors[activeGroup.id] ?? ''}
                                            onClearError={() => setUploadErrors((current) => ({ ...current, [activeGroup.id]: '' }))}
                                            onUpload={() => void uploadFiles(activeGroup.id)}
                                        />
                                    )}
                                    {!unassigned && !activeGroup && (
                                        groupsLoading ? <p role="status" className="py-6 text-[13px] text-muted">문서 그룹을 불러오는 중…</p>
                                            : <div role="alert" className="rounded-xl border border-line px-4 py-6 text-[13px]">
                                                <p>{groupsError || '문서 그룹을 찾을 수 없습니다.'}</p>
                                                {groupsError && <button type="button" onClick={refreshDocs} className="mt-2 font-bold text-brand-hover underline">다시 시도</button>}
                                            </div>
                                    )}
                                    {!unassigned && activeGroup && lastUploadGroupId === activeGroup.id && lastUpload.length > 0 && (
                                        <UploadResultPanel results={lastUpload} onDismiss={() => setLastUpload([])} />
                                    )}
                                    {unassigned && groupsError && (
                                        <div role="alert" className="mb-5 rounded-xl border border-danger/25 bg-danger-surface px-4 py-3 text-[12px] text-danger">
                                            문서 그룹을 불러오지 못해 파일을 이동할 수 없습니다: {groupsError}
                                            <button type="button" onClick={refreshDocs} className="ml-2 font-bold underline">다시 시도</button>
                                        </div>
                                    )}
                                    {(unassigned || activeGroup) && (
                                        <RegisteredFileList
                                            key={view}
                                            docs={visibleDocs}
                                            groups={groups}
                                            groupId={activeGroup?.id ?? null}
                                            loading={docsLoading}
                                            error={docsError}
                                            onRefresh={refreshDocs}
                                            onChanged={refreshDocs}
                                            onSelect={openDetail}
                                        />
                                    )}
                                </div>
                            </div>
                        </div>
                    )}
                </main>
            </div>
            {detailVisible && selectedDoc && (
                <div className="fixed inset-0 z-50 flex justify-end bg-ink/30" onMouseDown={(event) => { if (event.target === event.currentTarget) closeDetail(); }}>
                    <aside
                        role="dialog"
                        aria-modal="true"
                        aria-label={`${selectedDoc.original_name} 파일 상세`}
                        onKeyDown={(event) => {
                            if (event.key !== 'Tab') return;
                            const controls = Array.from(event.currentTarget.querySelectorAll<HTMLElement>('a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), iframe'))
                                .filter((control) => control.getClientRects().length > 0);
                            const first = controls[0];
                            const last = controls[controls.length - 1];
                            if (!first || !last) return;
                            if (event.shiftKey && document.activeElement === first) {
                                event.preventDefault();
                                last.focus();
                            } else if (!event.shiftKey && document.activeElement === last) {
                                event.preventDefault();
                                first.focus();
                            }
                        }}
                        className="flex h-dvh w-full min-w-0 flex-col bg-surface shadow-xl sm:w-[460px]"
                    >
                        <FileDetailPanel
                            key={selectedDoc.file_id}
                            doc={selectedDoc}
                            groups={groups}
                            onGroupChanged={() => { closeDetail(); refreshDocs(); }}
                            onDescriptionChanged={refreshDocs}
                            onClose={closeDetail}
                        />
                    </aside>
                </div>
            )}
            <div className={`${workspaceOpen ? 'flex' : 'hidden'} flex-1 min-w-0 min-h-0 flex-col`}>
                <Workspace docCount={docs.length} lastUpload={lastUpload} />
            </div>
        </div>
    );
}

/* ================================================================== */
/*  그룹별 파일 등록                                                    */
/* ================================================================== */

function UploadPanel({
    group,
    selected,
    onSelectedChange,
    uploading,
    busy,
    error,
    onClearError,
    onUpload,
}: {
    group: FileGroup;
    selected: UploadDraft[];
    onSelectedChange: (update: (files: UploadDraft[]) => UploadDraft[]) => void;
    uploading: boolean;
    busy: boolean;
    error: string;
    onClearError: () => void;
    onUpload: () => void;
}) {
    const [isDragOver, setIsDragOver] = useState(false);
    const [selectionNotice, setSelectionNotice] = useState('');
    const inputRef = useRef<HTMLInputElement>(null);

    const totalBytes = selected.reduce((sum, draft) => sum + draft.file.size, 0);

    /** 지원 형식만 대기 목록에 추가한다. 내용 중복은 서버가 판정한다. */
    const pickFiles = (list: FileList | File[]) => {
        if (busy) return;
        const accepted: File[] = [];
        let unsupported = 0;
        for (const file of Array.from(list)) {
            if (!UPLOAD_EXTENSIONS.includes(fileExt(file.name))) {
                unsupported += 1;
                continue;
            }
            accepted.push(file);
        }
        if (accepted.length > 0) {
            onSelectedChange((prev) => [
                ...prev,
                ...accepted.map((file) => ({ id: String(++nextUploadDraftId), file, description: '' })),
            ]);
        }
        setSelectionNotice(unsupported > 0 ? `지원하지 않는 형식 ${unsupported}개를 제외했습니다.` : '');
        onClearError();
    };

    const startUpload = () => {
        if (selected.length === 0 || busy) return;
        setIsDragOver(false);
        setSelectionNotice('');
        onUpload();
    };

    return (
        <section aria-labelledby="upload-title" aria-busy={uploading} className="mb-5 rounded-2xl border border-line bg-white shadow-[0_3px_12px_rgba(20,28,43,0.04)]">
            <div className="border-b border-divide px-4 py-3">
                <h2 id="upload-title" className="text-[14px] font-bold">파일 등록</h2>
                <p className="mt-1 text-[12px] text-ink/70">선택한 파일은 ‘{group.name}’ 그룹에 등록됩니다.</p>
            </div>
            <div className="px-4 py-4">
                <div>
                    <button
                        type="button"
                        onClick={() => { if (!busy) inputRef.current?.click(); }}
                        onDrop={(event) => {
                            event.preventDefault();
                            setIsDragOver(false);
                            if (!busy && event.dataTransfer.files.length > 0) pickFiles(event.dataTransfer.files);
                        }}
                        onDragOver={(event) => {
                            event.preventDefault();
                            event.dataTransfer.dropEffect = busy ? 'none' : 'copy';
                            if (!busy) setIsDragOver(true);
                        }}
                        onDragLeave={() => setIsDragOver(false)}
                        aria-disabled={busy}
                        aria-describedby="upload-formats"
                        className={`flex min-h-[96px] w-full flex-col items-center justify-center gap-1 rounded-xl border border-dashed px-3 py-3 text-center transition-colors focus-visible:outline-2 focus-visible:outline-brand aria-disabled:cursor-not-allowed aria-disabled:opacity-50 ${
                            isDragOver ? 'border-brand bg-brand-tint' : 'border-line bg-surface hover:border-brand/60 hover:bg-brand-tint'
                        }`}
                    >
                        <span className="mb-0.5 flex h-8 w-8 items-center justify-center rounded-lg bg-brand-pale text-brand">
                            <UploadIcon className="h-[18px] w-[18px]" />
                        </span>
                        <span className="text-[12.5px] font-semibold">파일을 끌어 놓거나 클릭해 선택</span>
                        <span className="text-[12px] text-ink/70">여러 파일을 한 번에 선택할 수 있습니다.</span>
                    </button>
                    <input
                        ref={inputRef}
                        type="file"
                        accept={UPLOAD_EXTENSIONS.join(',')}
                        multiple
                        disabled={busy}
                        onChange={(event) => {
                            if (event.target.files) pickFiles(event.target.files);
                            event.target.value = '';
                        }}
                        className="hidden"
                    />
                    <p id="upload-formats" className="mt-1.5 text-[11.5px] leading-relaxed text-ink/70">
                        지원 형식: PDF, DOCX, PPTX, XLSX, HWP/HWPX, 이미지(PNG, JPG, GIF, BMP, WEBP)
                    </p>
                </div>

                {selected.length > 0 && (
                    <div className="mt-4">
                        <div className="mb-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11.5px]">
                            <span className="font-bold">등록 대기 <span className="tabular-nums text-brand-hover">{selected.length}</span></span>
                            <span className="text-muted tabular-nums">총 {formatBytes(totalBytes)}</span>
                            <button
                                type="button"
                                onClick={() => onSelectedChange(() => [])}
                                disabled={busy}
                                className="ml-auto font-semibold text-muted hover:text-danger disabled:opacity-50"
                            >
                                전체 비우기
                            </button>
                        </div>
                        <ul className="max-h-64 divide-y divide-divide overflow-y-auto rounded-lg border border-divide px-2">
                            {selected.map(({ id, file, description }, index) => (
                                <li key={id} className="flex min-w-0 items-start gap-2 py-2">
                                    <span className="mt-1.5 w-9 shrink-0 text-center text-[9px] font-bold text-brand-hover">{fileExt(file.name).slice(1, 5).toUpperCase()}</span>
                                    <div className="min-w-0 flex-1">
                                        <div className="flex min-w-0 items-center gap-2">
                                            <span className="min-w-0 flex-1 truncate text-[11.5px] font-medium" title={file.name}>{file.name}</span>
                                            <span className="shrink-0 text-[11px] tabular-nums text-ink/70">{formatBytes(file.size)}</span>
                                        </div>
                                        <input
                                            type="text"
                                            value={description}
                                            onChange={(event) => {
                                                const value = event.target.value;
                                                onSelectedChange((current) => current.map((draft) => draft.id === id ? { ...draft, description: value } : draft));
                                                onClearError();
                                            }}
                                            disabled={busy}
                                            maxLength={500}
                                            aria-label={`${file.name} 파일 설명 ${index + 1}`}
                                            placeholder="이 파일의 간단한 설명 (선택)"
                                            className="mt-1.5 h-8 w-full rounded-md border border-line bg-white px-2 text-[11.5px] text-ink placeholder:text-muted focus:outline-none focus:border-brand disabled:opacity-50"
                                        />
                                    </div>
                                    <button
                                        type="button"
                                        onClick={() => onSelectedChange((current) => current.filter((draft) => draft.id !== id))}
                                        disabled={busy}
                                        aria-label={`${file.name} 대기 목록에서 제거`}
                                        className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-muted hover:bg-danger-surface hover:text-danger disabled:opacity-50"
                                    >
                                        <CloseIcon />
                                    </button>
                                </li>
                            ))}
                        </ul>
                    </div>
                )}

                {selectionNotice && <p role="status" className="mt-2 text-[11.5px] leading-relaxed text-warn">{selectionNotice}</p>}
                <button
                    type="button"
                    onClick={startUpload}
                    disabled={selected.length === 0 || busy}
                    className="mt-4 flex h-10 w-full items-center justify-center gap-2 rounded-xl bg-brand text-[12.5px] font-bold text-white transition-colors enabled:hover:bg-brand-hover disabled:cursor-not-allowed disabled:opacity-40"
                >
                    {uploading && <span className="h-3.5 w-3.5 rounded-full border-2 border-white/40 border-t-white animate-spin" />}
                    {uploading
                        ? '파일 분석·검색 반영 중…'
                        : busy
                            ? '다른 그룹의 파일 등록 중…'
                        : selected.length === 0
                            ? '파일을 선택해 주세요'
                            : `${selected.length}개 파일 등록`}
                </button>
                {selected.length > 0 && !uploading && <p className="mt-1.5 text-center text-[11.5px] text-ink/70">선택한 파일 모두가 ‘{group.name}’ 그룹에 들어갑니다.</p>}
                {uploading && <p role="status" className="mt-2 text-center text-[12px] text-ink/70">문서 내용을 추출하고 검색에 반영하고 있습니다. 완료될 때까지 기다려 주세요.</p>}
                {error && <InlineError>{error}</InlineError>}
            </div>
        </section>
    );
}

function UploadResultPanel({ results, onDismiss }: { results: UploadResult[]; onDismiss: () => void }) {
    const counts = uploadCounts(results);
    const summary = [
        counts.ready > 0 ? `검색 준비 완료 ${counts.ready}개` : '',
        counts.empty > 0 ? `내용 없음 ${counts.empty}개` : '',
        counts.duplicate > 0 ? `중복 ${counts.duplicate}개` : '',
        counts.error > 0 ? `실패 ${counts.error}개` : '',
    ].filter(Boolean).join(' · ');

    return (
        <section aria-label="파일 등록 결과" className="mb-5 rounded-xl border border-brand/25 bg-brand-tint px-3 py-3">
            <div className="flex items-start gap-2">
                <div role="status" aria-live="polite" className="min-w-0 flex-1">
                    <h2 className="text-[12.5px] font-bold">파일 등록 결과</h2>
                    <p className="mt-0.5 text-[11.5px] text-ink/80">{summary}</p>
                </div>
                <button type="button" onClick={onDismiss} aria-label="파일 등록 결과 닫기" className="flex h-6 w-6 shrink-0 items-center justify-center rounded text-muted hover:bg-white hover:text-ink">
                    <CloseIcon />
                </button>
            </div>
            <ul className="mt-2 max-h-32 divide-y divide-divide overflow-y-auto rounded-lg bg-white px-2">
                {results.map((result, index) => <UploadResultRow key={`${result.filename}-${index}`} result={result} />)}
            </ul>
        </section>
    );
}

/* ================================================================== */
/*  파일 상세 패널                                                      */
/* ================================================================== */

function FileDetailPanel({
    doc,
    groups,
    onGroupChanged,
    onDescriptionChanged,
    onClose,
}: {
    doc: FileSummary;
    groups: FileGroup[];
    onGroupChanged: () => void;
    onDescriptionChanged: () => void;
    onClose: () => void;
}) {
    const [detail, setDetail] = useState<FileDetail | null>(null);
    const [error, setError] = useState('');
    const [previewOpen, setPreviewOpen] = useState(false);
    const [groupSaving, setGroupSaving] = useState(false);
    const [groupError, setGroupError] = useState('');
    const [descriptionEditing, setDescriptionEditing] = useState(false);
    const [descriptionDraft, setDescriptionDraft] = useState('');
    const [descriptionSaving, setDescriptionSaving] = useState(false);
    const [descriptionError, setDescriptionError] = useState('');

    const visibleDescription = detail?.description ?? doc.description;

    const saveDescription = async () => {
        const description = descriptionDraft.trim();
        if (description === visibleDescription) {
            setDescriptionEditing(false);
            return;
        }
        setDescriptionSaving(true);
        setDescriptionError('');
        try {
            await ragApi.updateFileDescription(doc.file_id, description);
            setDetail((current) => current ? { ...current, description } : current);
            setDescriptionEditing(false);
            onDescriptionChanged();
        } catch (e) {
            setDescriptionError(`설명 저장 실패: ${errMessage(e)}`);
        } finally {
            setDescriptionSaving(false);
        }
    };

    const changeGroup = async (value: string) => {
        const next = value || null;
        if (next === (doc.group_id ?? null)) return;
        setGroupSaving(true);
        setGroupError('');
        try {
            await ragApi.setFileGroup(doc.file_id, next);
            onGroupChanged(); // 목록을 다시 불러오면 doc.group_id 가 바뀐 값으로 내려온다
        } catch (e) {
            setGroupError(`그룹 변경 실패: ${errMessage(e)}`);
        } finally {
            setGroupSaving(false);
        }
    };

    useEffect(() => {
        let ignore = false;
        void ragApi.getFileDetail(doc.file_id).then((result) => {
            if (!ignore) setDetail(result);
        }).catch((e: unknown) => {
            if (!ignore) setError(errMessage(e));
        });
        return () => { ignore = true; };
    }, [doc.file_id]);

    if (previewOpen) {
        return <PdfPreview doc={doc} onClose={() => setPreviewOpen(false)} />;
    }

    const size = detail?.size_bytes;
    const sizeLabel = size == null ? '—'
        : size < 1024 ? `${size} B`
        : size < 1024 ** 2 ? `${(size / 1024).toFixed(1)} KB`
        : `${(size / 1024 ** 2).toFixed(1)} MB`;
    const fields = [
        ['파일 형식', fileExt(doc.original_name).slice(1).toUpperCase() || '—'],
        ['파일 크기', sizeLabel],
        ['청크 수', detail?.chunk_count == null ? '—' : `${detail.chunk_count.toLocaleString()}개`],
        ['등록일', detail?.created_at?.replace('T', ' ').slice(0, 16) || '—'],
        ['수정일', detail?.updated_at?.replace('T', ' ').slice(0, 16) || '—'],
    ];

    return (
        <section className="flex-1 min-h-0 flex flex-col" onKeyDown={(event) => {
            if (event.key !== 'Escape') return;
            if (descriptionEditing) {
                if (!descriptionSaving) setDescriptionEditing(false);
                return;
            }
            onClose();
        }}>
            <div className="shrink-0 px-5 py-4 flex items-center justify-between border-b border-divide">
                <h2 className="text-[14px] font-bold">파일 상세</h2>
                <button type="button" onClick={onClose} autoFocus aria-label="파일 상세 닫기" className="w-7 h-7 rounded-lg flex items-center justify-center text-muted hover:text-ink hover:bg-chip">
                    <CloseIcon />
                </button>
            </div>
            <div className="flex-1 min-h-0 overflow-y-auto px-5 py-6">
                <div className="w-11 h-11 rounded-xl bg-white border border-line flex items-center justify-center">
                    <DocumentIcon className="w-6 h-6 text-brand" />
                </div>
                <h3 className="mt-4 text-[16px] font-bold leading-relaxed break-words">{doc.original_name}</h3>

                <div className="mt-5 rounded-xl border border-line bg-white p-3">
                    <div className="flex items-center justify-between gap-2">
                        <h4 className="text-[11.5px] font-semibold text-muted">파일 설명</h4>
                        {!descriptionEditing && (
                            <button
                                type="button"
                                onClick={() => {
                                    setDescriptionDraft(visibleDescription);
                                    setDescriptionError('');
                                    setDescriptionEditing(true);
                                }}
                                disabled={!detail}
                                className="text-[11.5px] font-bold text-brand-hover hover:underline disabled:cursor-wait disabled:opacity-50"
                            >
                                {visibleDescription ? '수정' : '추가'}
                            </button>
                        )}
                    </div>
                    {descriptionEditing ? (
                        <div className="mt-2">
                            <textarea
                                value={descriptionDraft}
                                onChange={(event) => setDescriptionDraft(event.target.value)}
                                disabled={descriptionSaving}
                                autoFocus
                                maxLength={500}
                                rows={3}
                                aria-label={`${doc.original_name} 파일 설명`}
                                placeholder="파일의 내용을 짧게 적어 주세요"
                                className="w-full resize-y rounded-lg border border-line px-2.5 py-2 text-[12px] leading-relaxed focus:outline-none focus:border-brand disabled:opacity-50"
                            />
                            {descriptionError && <InlineError>{descriptionError}</InlineError>}
                            <div className="mt-2 flex justify-end gap-2">
                                <button type="button" onClick={() => setDescriptionEditing(false)} disabled={descriptionSaving} className="h-8 rounded-lg px-2 text-[11.5px] font-semibold text-ink/70 hover:bg-surface disabled:opacity-50">취소</button>
                                <button type="button" onClick={() => void saveDescription()} disabled={descriptionSaving} className="h-8 rounded-lg bg-brand px-3 text-[11.5px] font-bold text-white hover:bg-brand-hover disabled:opacity-50">{descriptionSaving ? '저장 중…' : '저장'}</button>
                            </div>
                        </div>
                    ) : (
                        <p className="mt-2 break-words text-[12px] leading-relaxed text-ink/70">{visibleDescription || '아직 설명이 없습니다.'}</p>
                    )}
                </div>

                {groups.length > 0 && (
                    <div className="mt-5">
                        <label className="block text-[11.5px] font-semibold text-muted" htmlFor={`group-${doc.file_id}`}>
                            소속 문서 그룹
                        </label>
                        <select
                            id={`group-${doc.file_id}`}
                            value={doc.group_id ?? ''}
                            onChange={(e) => void changeGroup(e.target.value)}
                            disabled={groupSaving}
                            className="mt-1.5 w-full h-9 px-2.5 rounded-lg border border-line bg-white text-[12.5px] text-ink focus:outline-none focus:border-brand disabled:opacity-40"
                        >
                            <option value="">{UNGROUPED_LABEL}</option>
                            {groups.map((g) => (
                                <option key={g.id} value={g.id}>{g.name}</option>
                            ))}
                        </select>
                        <p className="mt-1.5 text-[12px] text-ink/70 leading-relaxed">
                            {groupSaving ? '파일을 이동하는 중…' : '다른 그룹을 선택하면 이 파일이 해당 그룹의 목록으로 이동합니다.'}
                        </p>
                        {groupError && <InlineError>{groupError}</InlineError>}
                    </div>
                )}

                {error ? <InlineError>{error}</InlineError> : !detail ? (
                    <p role="status" className="mt-6 text-[12px] text-muted">상세 정보를 불러오는 중…</p>
                ) : (
                    <dl className="mt-6 divide-y divide-divide">
                        {fields.map(([label, value]) => (
                            <div key={label} className="py-3 flex items-baseline justify-between gap-4 text-[12px]">
                                <dt className="text-muted shrink-0">{label}</dt>
                                <dd className="text-right break-words tabular-nums">{value}</dd>
                            </div>
                        ))}
                    </dl>
                )}
                {fileExt(doc.original_name) === '.pdf' && (
                    <button type="button" onClick={() => setPreviewOpen(true)} className="mt-6 h-9 w-full rounded-lg border border-line bg-white text-[12px] font-semibold hover:border-brand hover:text-brand">
                        PDF 미리보기
                    </button>
                )}
            </div>
        </section>
    );
}

/* ================================================================== */
/*  오른쪽 — PDF 원본 미리보기                                         */
/* ================================================================== */

function PdfPreview({ doc, onClose }: { doc: FileSummary; onClose: () => void }) {
    const [url, setUrl] = useState('');
    const [error, setError] = useState('');

    useEffect(() => {
        const controller = new AbortController();
        let objectUrl = '';

        void ragApi.previewPdf(doc.file_id, controller.signal).then((blob) => {
            if (controller.signal.aborted) return;
            objectUrl = URL.createObjectURL(blob);
            setUrl(objectUrl);
        }).catch((e: unknown) => {
            if (!controller.signal.aborted) setError(errMessage(e));
        });

        return () => {
            controller.abort();
            if (objectUrl) URL.revokeObjectURL(objectUrl);
        };
    }, [doc.file_id]);

    return (
        <section aria-label="PDF 미리보기" className="h-full min-h-0 flex flex-col" onKeyDown={(event) => { if (event.key === 'Escape') onClose(); }}>
            <div className="shrink-0 flex flex-wrap items-center gap-3 border-b border-divide px-4 py-3">
                <DocumentIcon className="w-5 h-5 shrink-0 text-brand" />
                <h2 className="flex-1 min-w-0 truncate text-[14px] font-semibold" title={doc.original_name}>
                    {doc.original_name}
                </h2>
                <a
                    href={ragApi.filePreviewUrl(doc.file_id)}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-[12px] font-semibold text-muted hover:text-ink"
                >
                    새 탭에서 열기
                </a>
                <button
                    type="button"
                    onClick={onClose}
                    autoFocus
                    className="h-8 px-3 rounded-lg border border-line text-[12px] font-semibold hover:bg-surface"
                >
                    상세 정보로 돌아가기
                </button>
            </div>
            {error ? (
                <div className="flex-1 flex items-center justify-center px-6">
                    <ErrorLine title="PDF를 열 수 없습니다" message={error} />
                </div>
            ) : url ? (
                <iframe title={`${doc.original_name} PDF 미리보기`} src={url} className="flex-1 min-h-0 w-full border-0 bg-surface" />
            ) : (
                <div role="status" className="flex-1 flex items-center justify-center gap-2 text-[13px] text-muted">
                    <span className="w-4 h-4 rounded-full border-2 border-brand-pale border-t-brand animate-spin" />
                    PDF를 불러오는 중…
                </div>
            )}
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
    const [mode, setMode] = useState<AskMode>('local');
    // 서버에 ANTHROPIC_API_KEY가 없으면 Claude 버튼을 잠근다.
    // GET /config로 먼저 확인하고, 그래도 Claude 모드 /ask가 503을 주면 그때 잠근다.
    const [claudeUnavailable, setClaudeUnavailable] = useState(false);

    useEffect(() => {
        ragApi
            .getConfig()
            .then((cfg) => setClaudeUnavailable(!cfg.claude_available))
            .catch(() => {
                /* /config가 없는 구버전 서버면 버튼을 그대로 둔다 */
            });
    }, []);
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
            if (mode === 'claude' && e instanceof ApiError && e.status === 503) {
                setClaudeUnavailable(true);
                setMode('local');
            }
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
                                    disabled={m === 'claude' && claudeUnavailable}
                                    title={
                                        m === 'claude' && claudeUnavailable
                                            ? '서버에 ANTHROPIC_API_KEY가 없어 사용할 수 없습니다'
                                            : undefined
                                    }
                                    className={`h-6 px-2.5 rounded-md text-[11.5px] font-semibold transition-colors disabled:opacity-40 disabled:cursor-not-allowed ${
                                        mode === m ? 'bg-white text-ink shadow-[0_1px_2px_rgba(20,28,43,0.10)]' : 'text-muted enabled:hover:text-ink'
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

/** 로그가 비었을 때: 직전 등록 결과가 있으면 그걸, 없으면 안내를 보여준다 */
function EmptyWorkspace({
    docCount,
    lastUpload,
}: {
    docCount: number;
    lastUpload: UploadResult[];
}) {
    if (lastUpload.length > 0) {
        const counts = uploadCounts(lastUpload);
        return (
            <div className="mx-auto w-full max-w-[760px] px-5 sm:px-10 pt-8 pb-4">
                <h2 className="text-[18px] font-bold">
                    {counts.ready > 0 ? '문서에 대해 질문해 보세요' : '등록 결과를 확인해 주세요'}
                </h2>
                <p className="mt-1 text-[12px] text-muted">
                    검색 준비 완료 {counts.ready}개 · 내용 없음 {counts.empty}개 · 중복 {counts.duplicate}개 · 실패 {counts.error}개
                </p>
                <ul className="mt-4 divide-y divide-divide">
                    {lastUpload.map((r, i) => (
                        <UploadResultRow key={`${r.filename}-${i}`} result={r} showPreview />
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
                                    {s.source.split(/[\\/]/).pop() || s.source} · {s.page}쪽
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

function UploadResultRow({ result, showPreview = false }: { result: UploadResult; showPreview?: boolean }) {
    const outcome = uploadOutcome(result);
    const status = {
        ready: { label: '완료', tone: 'bg-brand-pale text-brand-hover', message: '질의응답에서 검색할 수 있습니다.' },
        empty: { label: '내용 없음', tone: 'bg-warn-soft text-warn', message: '텍스트를 추출하지 못해 검색에 사용되지 않습니다.' },
        duplicate: { label: '중복', tone: 'bg-chip text-muted', message: '같은 내용의 파일이 이미 등록되어 있습니다. 필요한 경우 기존 파일을 이 그룹으로 옮겨 주세요.' },
        error: { label: '실패', tone: 'bg-danger-surface text-danger', message: result.error ?? '처리하지 못했습니다.' },
    }[outcome];
    return (
        <li className="py-2.5">
            <div className="flex items-start gap-2">
                <span className={`mt-0.5 w-[58px] shrink-0 rounded-md px-1 py-0.5 text-center text-[10px] font-bold ${status.tone}`}>{status.label}</span>
                <div className="min-w-0 flex-1">
                    <p className="break-all text-[11.5px] font-semibold">{result.filename || '(파일명 없음)'}</p>
                    <p className={`mt-0.5 break-words text-[11px] leading-relaxed ${outcome === 'error' ? 'text-danger' : 'text-muted'}`}>{status.message}</p>
                </div>
            </div>
            {showPreview && outcome === 'ready' && !!result.chunks?.length && (
                <details className="ml-[66px] mt-1.5">
                    <summary className="cursor-pointer text-[11.5px] font-semibold text-brand-hover hover:underline">추출 내용 미리보기</summary>
                    <ul className="mt-1 divide-y divide-divide">
                        {result.chunks.slice(0, 3).map((chunk) => (
                            <li key={chunk.id} className="py-1.5 text-[11.5px] leading-relaxed">
                                <span className="mr-1 text-muted tabular-nums">{chunk.page}쪽</span>
                                <span className="whitespace-pre-wrap break-words">{truncate(chunk.text)}</span>
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
