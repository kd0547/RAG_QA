import { useState } from 'react';

import { AlertIcon, DocumentIcon, TrashIcon } from '../components/icons';
import { ApiError } from '../lib/http';
import { linkProps } from '../lib/router';
import { ragApi, reviewPath } from './api';
import type { FileGroup, FileSummary } from './types';

const UNGROUPED_TARGET = '__ungrouped__';

export interface FileListProps {
    /** 현재 문서 그룹에 속한 파일만 전달한다. */
    docs: FileSummary[];
    groups: FileGroup[];
    /** null이면 기존 미분류 파일을 보는 화면이다. */
    groupId: string | null;
    loading: boolean;
    error: string;
    onRefresh: () => void;
    onChanged: () => void;
    onSelect: (doc: FileSummary) => void;
}

function errorMessage(error: unknown): string {
    if (error instanceof ApiError) {
        return error.code === 'network' ? `서버에 연결할 수 없습니다 (${error.message})` : error.message;
    }
    return error instanceof Error ? error.message : '알 수 없는 오류가 발생했습니다.';
}

function extension(name: string): string {
    const index = name.lastIndexOf('.');
    return index < 0 ? 'FILE' : name.slice(index + 1, index + 5).toUpperCase();
}

/** 그룹이 바뀌면 체크 상태와 이동 대상이 남지 않도록 내용 컴포넌트를 다시 시작한다. */
export function FileList(props: FileListProps) {
    return <FileListContent key={props.groupId ?? UNGROUPED_TARGET} {...props} />;
}

function FileListContent({
    docs,
    groups,
    groupId,
    loading,
    error,
    onRefresh,
    onChanged,
    onSelect,
}: FileListProps) {
    const [checked, setChecked] = useState<Set<string>>(new Set());
    const [moveTo, setMoveTo] = useState('');
    const [moving, setMoving] = useState(false);
    const [deletingId, setDeletingId] = useState<string | null>(null);
    const [actionError, setActionError] = useState('');
    const [actionStatus, setActionStatus] = useState('');

    const targets = groups.filter((group) => group.id !== groupId);
    const canMoveFiles = targets.length > 0 || groupId !== null;
    const selectedIds = docs.filter((doc) => checked.has(doc.file_id)).map((doc) => doc.file_id);
    const allChecked = docs.length > 0 && selectedIds.length === docs.length;
    const someChecked = selectedIds.length > 0 && !allChecked;
    const validTarget = targets.some((group) => group.id === moveTo)
        || (groupId !== null && moveTo === UNGROUPED_TARGET);
    const busy = moving || deletingId !== null;

    const toggleOne = (fileId: string) => {
        setChecked((current) => {
            const next = new Set(current);
            if (next.has(fileId)) next.delete(fileId);
            else next.add(fileId);
            return next;
        });
    };

    const toggleAll = () => {
        setChecked((current) => {
            const next = new Set(current);
            for (const doc of docs) {
                if (allChecked) next.delete(doc.file_id);
                else next.add(doc.file_id);
            }
            return next;
        });
    };

    const moveSelected = async () => {
        if (busy || selectedIds.length === 0 || !validTarget) return;
        const targetId = moveTo === UNGROUPED_TARGET ? null : moveTo;
        const targetName = targetId === null
            ? '미분류'
            : targets.find((group) => group.id === targetId)?.name ?? '다른 문서 그룹';
        setMoving(true);
        setActionError('');
        setActionStatus('');
        try {
            const result = await ragApi.setFilesGroup(selectedIds, targetId);
            setChecked(new Set());
            setMoveTo('');
            setActionStatus(`${result.updated}개 파일을 ${targetName}(으)로 이동했습니다.`);
            onChanged();
        } catch (moveError) {
            setActionError(`파일 이동 실패: ${errorMessage(moveError)}`);
        } finally {
            setMoving(false);
        }
    };

    const deleteFile = async (doc: FileSummary) => {
        if (busy) return;
        if (!window.confirm(`'${doc.original_name}' 파일을 삭제할까요?\n검색에 쓰이는 내용도 함께 삭제됩니다.`)) return;
        setDeletingId(doc.file_id);
        setActionError('');
        setActionStatus('');
        try {
            await ragApi.deleteFile(doc.file_id);
            setChecked((current) => {
                const next = new Set(current);
                next.delete(doc.file_id);
                return next;
            });
            setActionStatus(`${doc.original_name} 파일을 삭제했습니다.`);
            onChanged();
        } catch (deleteError) {
            setActionError(`파일 삭제 실패: ${errorMessage(deleteError)}`);
        } finally {
            setDeletingId(null);
        }
    };

    return (
        <section aria-labelledby="registered-files-title" className="min-w-0">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                    <h2 id="registered-files-title" className="text-[16px] font-bold text-ink">
                        등록된 파일 <span className="ml-1 tabular-nums text-brand-hover">{docs.length}</span>
                    </h2>
                    <p className="mt-1 text-[12px] text-ink/70">파일을 선택해 설명을 수정하고 등록 정보를 확인할 수 있습니다.</p>
                </div>
                <button
                    type="button"
                    onClick={onRefresh}
                    disabled={loading}
                    className="h-8 rounded-lg border border-line px-3 text-[12px] font-semibold text-ink/70 hover:border-brand hover:text-brand-hover disabled:opacity-50"
                >
                    {loading ? '불러오는 중…' : '새로고침'}
                </button>
            </div>

            {error && (
                <div role="alert" className="mt-4 flex flex-wrap items-start gap-2 rounded-xl border border-danger/20 bg-danger-surface p-3 text-[12px] text-danger">
                    <AlertIcon className="mt-0.5 h-4 w-4 shrink-0" />
                    <p className="min-w-0 flex-1 break-words">파일 목록을 불러오지 못했습니다: {error}</p>
                    <button type="button" onClick={onRefresh} className="font-bold underline hover:no-underline">다시 시도</button>
                </div>
            )}
            {actionError && <p role="alert" className="mt-3 break-words text-[12px] text-danger">{actionError}</p>}
            {actionStatus && <p role="status" className="mt-3 break-words text-[12px] text-brand-hover">{actionStatus}</p>}

            {canMoveFiles && selectedIds.length > 0 && (
                <div className="mt-4 flex flex-wrap items-center gap-2 rounded-xl border border-brand/20 bg-brand-pale p-3">
                    <span className="shrink-0 text-[12px] font-bold text-ink">{selectedIds.length}개 선택</span>
                    <label className="min-w-[160px] flex-1">
                        <span className="sr-only">이동할 문서 그룹</span>
                        <select
                            value={moveTo}
                            onChange={(event) => setMoveTo(event.target.value)}
                            disabled={busy}
                            className="h-9 w-full rounded-lg border border-line bg-white px-2.5 text-[12px] text-ink focus:outline-none focus:border-brand focus:ring-2 focus:ring-brand/20 disabled:opacity-50"
                        >
                            <option value="">이동할 문서 그룹 선택</option>
                            {targets.map((group) => <option key={group.id} value={group.id}>{group.name}</option>)}
                            {groupId !== null && <option value={UNGROUPED_TARGET}>미분류 파일로 이동</option>}
                        </select>
                    </label>
                    <button
                        type="button"
                        onClick={() => void moveSelected()}
                        disabled={busy || !validTarget}
                        className="h-9 rounded-lg bg-brand px-4 text-[12px] font-bold text-white hover:bg-brand-hover disabled:cursor-not-allowed disabled:opacity-50"
                    >
                        {moving ? '이동 중…' : '이동'}
                    </button>
                    <button
                        type="button"
                        onClick={() => { setChecked(new Set()); setMoveTo(''); }}
                        disabled={busy}
                        className="h-9 rounded-lg px-2 text-[12px] font-semibold text-ink/70 hover:bg-white disabled:opacity-50"
                    >
                        선택 해제
                    </button>
                </div>
            )}

            {docs.length === 0 ? (
                <div className="mt-4 flex min-h-44 flex-col items-center justify-center rounded-2xl border border-dashed border-line bg-surface px-4 py-8 text-center">
                    <DocumentIcon className="h-7 w-7 text-muted" />
                    {loading ? (
                        <p role="status" className="mt-3 text-[13px] text-ink/70">파일 목록을 불러오는 중…</p>
                    ) : error ? (
                        <p className="mt-3 text-[13px] text-ink/70">목록을 확인할 수 없습니다. 다시 시도해 주세요.</p>
                    ) : (
                        <>
                            <p className="mt-3 text-[13px] font-semibold text-ink">
                                {groupId === null ? '미분류 파일이 없습니다.' : '아직 등록된 파일이 없습니다.'}
                            </p>
                            <p className="mt-1 text-[12px] text-ink/70">
                                {groupId === null ? '다른 문서 그룹의 파일은 해당 그룹에서 확인할 수 있습니다.' : '위에서 이 문서 그룹에 파일을 추가해 주세요.'}
                            </p>
                        </>
                    )}
                </div>
            ) : (
                <div className="mt-4 overflow-hidden rounded-xl border border-line bg-white">
                    {canMoveFiles && (
                        <div className="flex items-center gap-2 border-b border-divide bg-surface px-3 py-2">
                            <input
                                type="checkbox"
                                checked={allChecked}
                                ref={(element) => { if (element) element.indeterminate = someChecked; }}
                                onChange={toggleAll}
                                disabled={busy}
                                aria-label="등록된 파일 전체 선택"
                                className="h-4 w-4 shrink-0 accent-brand"
                            />
                            <span className="text-[12px] font-semibold text-ink/70">전체 선택</span>
                        </div>
                    )}
                    <ul className="divide-y divide-divide">
                        {docs.map((doc) => (
                            <li key={doc.file_id} className="group flex min-w-0 items-center gap-2 px-3 py-2 hover:bg-brand-tint">
                                {canMoveFiles && (
                                    <input
                                        type="checkbox"
                                        checked={checked.has(doc.file_id)}
                                        onChange={() => toggleOne(doc.file_id)}
                                        disabled={busy}
                                        aria-label={`${doc.original_name} 선택`}
                                        className="h-4 w-4 shrink-0 accent-brand"
                                    />
                                )}
                                <button
                                    type="button"
                                    onClick={() => onSelect(doc)}
                                    className="flex min-w-0 flex-1 items-center gap-3 rounded-lg px-1 py-1 text-left focus-visible:outline-2 focus-visible:outline-brand"
                                >
                                    <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-brand-pale text-[9px] font-bold text-brand-hover">
                                        {extension(doc.original_name)}
                                    </span>
                                    <span className="min-w-0 flex-1">
                                        <span className="block break-all text-[12.5px] font-semibold leading-relaxed text-ink">{doc.original_name}</span>
                                        {doc.description && <span className="mt-0.5 block break-words text-[11.5px] leading-relaxed text-ink/70">{doc.description}</span>}
                                    </span>
                                </button>
                                <a
                                    {...linkProps(reviewPath(doc.file_id))}
                                    title="저장된 내용을 원본과 비교하며 검수합니다"
                                    className="shrink-0 h-8 inline-flex items-center rounded-lg border border-line bg-white px-2.5 text-[11.5px] font-semibold text-ink/70 hover:border-brand hover:text-brand-hover focus-visible:outline-2 focus-visible:outline-brand"
                                >
                                    파일 검수
                                </a>
                                <button
                                    type="button"
                                    onClick={() => void deleteFile(doc)}
                                    disabled={busy}
                                    aria-label={`${doc.original_name} 삭제`}
                                    title="파일 삭제"
                                    className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-muted hover:bg-danger-surface hover:text-danger focus-visible:outline-2 focus-visible:outline-brand disabled:opacity-50"
                                >
                                    {deletingId === doc.file_id
                                        ? <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-danger/30 border-t-danger" />
                                        : <TrashIcon />}
                                </button>
                            </li>
                        ))}
                    </ul>
                </div>
            )}
        </section>
    );
}
