import { useState, type FormEvent } from 'react';

import { FolderIcon } from '../components/icons';
import type { FileGroup } from './types';

interface GroupHomeProps {
    groups: FileGroup[];
    ungroupedCount: number;
    loading: boolean;
    error: string;
    onCreate: (name: string, description: string) => Promise<void>;
    onUpdate: (groupId: string, name: string, description: string) => Promise<void>;
    onOpenGroup: (id: string) => void;
    onOpenUngrouped: () => void;
    onRefresh: () => void;
}

export function GroupHome({
    groups,
    ungroupedCount,
    loading,
    error,
    onCreate,
    onUpdate,
    onOpenGroup,
    onOpenUngrouped,
    onRefresh,
}: GroupHomeProps) {
    const [formOpen, setFormOpen] = useState(false);
    const [name, setName] = useState('');
    const [description, setDescription] = useState('');
    const [creating, setCreating] = useState(false);
    const [createError, setCreateError] = useState('');
    const [editingId, setEditingId] = useState<string | null>(null);
    const [editName, setEditName] = useState('');
    const [editDescription, setEditDescription] = useState('');
    const [updating, setUpdating] = useState(false);
    const [updateError, setUpdateError] = useState('');

    const closeForm = () => {
        setFormOpen(false);
        setName('');
        setDescription('');
        setCreateError('');
    };

    const submit = async (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        if (loading) return;
        const trimmedName = name.trim();
        if (!trimmedName) {
            setCreateError('문서 그룹 이름을 입력해 주세요.');
            return;
        }
        setCreating(true);
        setCreateError('');
        try {
            await onCreate(trimmedName, description.trim());
            closeForm();
        } catch (cause) {
            setCreateError(cause instanceof Error ? cause.message : '문서 그룹을 만들지 못했습니다. 다시 시도해 주세요.');
        } finally {
            setCreating(false);
        }
    };

    const startEditing = (group: FileGroup) => {
        if (updating) return;
        setEditingId(group.id);
        setEditName(group.name);
        setEditDescription(group.description);
        setUpdateError('');
    };

    const stopEditing = () => {
        setEditingId(null);
        setUpdateError('');
    };

    const saveGroup = async (event: FormEvent<HTMLFormElement>, groupId: string) => {
        event.preventDefault();
        const trimmedName = editName.trim();
        if (!trimmedName) {
            setUpdateError('문서 그룹 이름을 입력해 주세요.');
            return;
        }
        setUpdating(true);
        setUpdateError('');
        try {
            await onUpdate(groupId, trimmedName, editDescription.trim());
            stopEditing();
        } catch (cause) {
            setUpdateError(cause instanceof Error ? cause.message : '문서 그룹을 수정하지 못했습니다. 다시 시도해 주세요.');
        } finally {
            setUpdating(false);
        }
    };

    return (
        <div className="bg-white px-4 py-6 sm:px-8 lg:px-10">
            <div className="mx-auto w-full max-w-5xl">
                <header className="flex flex-wrap items-start justify-between gap-4">
                    <div>
                        <h1 className="text-[22px] font-bold tracking-tight text-ink">문서 그룹</h1>
                        <p className="mt-2 text-[13px] leading-relaxed text-ink/70">
                            관련 파일을 그룹으로 모으고, 그룹을 선택해 파일을 등록하세요.
                        </p>
                    </div>
                    {!formOpen && (
                        <button
                            type="button"
                            onClick={() => setFormOpen(true)}
                            disabled={loading}
                            className="inline-flex h-10 items-center justify-center gap-1.5 rounded-xl bg-brand px-4 text-[13px] font-bold text-white transition-colors hover:bg-brand-hover focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand disabled:opacity-50"
                        >
                            <span aria-hidden="true" className="text-[18px] leading-none">+</span>
                            새 문서 그룹
                        </button>
                    )}
                </header>

                {formOpen && (
                    <form
                        onSubmit={(event) => void submit(event)}
                        onKeyDown={(event) => { if (event.key === 'Escape' && !creating) closeForm(); }}
                        aria-labelledby="create-group-title"
                        className="mt-6 rounded-2xl border border-brand/30 bg-brand-tint p-4 sm:p-5"
                    >
                        <h2 id="create-group-title" className="text-[15px] font-bold text-ink">새 문서 그룹 만들기</h2>
                        <p className="mt-1 text-[12px] leading-relaxed text-ink/70">이름을 정한 뒤 그 안에 파일을 등록할 수 있습니다.</p>
                        <div className="mt-4 grid gap-4 sm:grid-cols-2">
                            <div>
                                <label htmlFor="new-group-name" className="block text-[12px] font-semibold text-ink">그룹 이름 <span className="text-danger">*</span></label>
                                <input
                                    id="new-group-name"
                                    value={name}
                                    onChange={(event) => setName(event.target.value)}
                                    disabled={creating}
                                    autoFocus
                                    required
                                    maxLength={80}
                                    placeholder="예: 제품 인증 자료"
                                    className="mt-1.5 h-10 w-full rounded-lg border border-line bg-white px-3 text-[13px] text-ink placeholder:text-muted focus:outline-none focus:border-brand focus:ring-2 focus:ring-brand/20 disabled:opacity-50"
                                />
                            </div>
                            <div>
                                <label htmlFor="new-group-description" className="block text-[12px] font-semibold text-ink">그룹 설명 <span className="font-normal text-ink/60">(선택)</span></label>
                                <textarea
                                    id="new-group-description"
                                    value={description}
                                    onChange={(event) => setDescription(event.target.value)}
                                    disabled={creating}
                                    maxLength={500}
                                    rows={2}
                                    placeholder="예: KC 안전확인·적합등록 인증서와 시험 자료"
                                    className="mt-1.5 w-full resize-y rounded-lg border border-line bg-white px-3 py-2 text-[13px] text-ink placeholder:text-muted focus:outline-none focus:border-brand focus:ring-2 focus:ring-brand/20 disabled:opacity-50"
                                />
                                <p className="mt-1 text-[11.5px] text-ink/60">AI가 관련 문서를 찾을 때 참고합니다.</p>
                            </div>
                        </div>
                        {createError && <p role="alert" className="mt-3 text-[12px] leading-relaxed text-danger">{createError}</p>}
                        <div className="mt-4 flex flex-wrap items-center justify-end gap-2">
                            <button
                                type="button"
                                onClick={closeForm}
                                disabled={creating}
                                className="h-9 rounded-lg px-3 text-[12px] font-semibold text-ink/70 hover:bg-white disabled:opacity-50"
                            >
                                취소
                            </button>
                            <button
                                type="submit"
                                disabled={creating || loading || !name.trim()}
                                className="h-9 rounded-lg bg-brand px-4 text-[12px] font-bold text-white enabled:hover:bg-brand-hover disabled:cursor-not-allowed disabled:opacity-40"
                            >
                                {creating ? '만드는 중…' : '그룹 만들기'}
                            </button>
                        </div>
                    </form>
                )}

                <section aria-labelledby="group-list-title" className="mt-8">
                    <div className="flex items-center justify-between gap-3">
                        <h2 id="group-list-title" className="text-[15px] font-bold text-ink">
                            문서 그룹 목록 <span className="ml-1 text-[13px] font-semibold tabular-nums text-ink/60">{groups.length}</span>
                        </h2>
                        <button
                            type="button"
                            onClick={onRefresh}
                            disabled={loading}
                            className="h-8 rounded-lg px-3 text-[12px] font-semibold text-ink/70 hover:bg-surface disabled:opacity-50"
                        >
                            {loading ? '불러오는 중…' : '새로고침'}
                        </button>
                    </div>

                    {error && (
                        <div role="alert" className="mt-4 rounded-xl border border-danger/30 bg-danger-surface px-4 py-3 text-[12px] leading-relaxed text-danger">
                            목록을 불러오지 못했습니다: {error}
                        </div>
                    )}
                    {loading && groups.length === 0 ? (
                        <p role="status" className="mt-4 rounded-xl border border-divide bg-surface px-4 py-10 text-center text-[13px] text-ink/70">문서 그룹을 불러오는 중…</p>
                    ) : groups.length > 0 ? (
                        <ul className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                            {groups.map((group) => (
                                <li key={group.id} className="flex min-h-44 flex-col rounded-2xl border border-line bg-white p-4">
                                    {editingId === group.id ? (
                                        <form
                                            onSubmit={(event) => void saveGroup(event, group.id)}
                                            onKeyDown={(event) => { if (event.key === 'Escape' && !updating) stopEditing(); }}
                                            className="flex h-full flex-col"
                                            aria-label={`${group.name} 그룹 수정`}
                                        >
                                            <h3 className="text-[14px] font-bold text-ink">문서 그룹 수정</h3>
                                            <label htmlFor={`edit-group-name-${group.id}`} className="mt-3 text-[11.5px] font-semibold text-ink">그룹 이름</label>
                                            <input
                                                id={`edit-group-name-${group.id}`}
                                                value={editName}
                                                onChange={(event) => setEditName(event.target.value)}
                                                disabled={updating}
                                                autoFocus
                                                required
                                                maxLength={80}
                                                className="mt-1 h-9 w-full rounded-lg border border-line px-2.5 text-[12px] focus:outline-none focus:border-brand disabled:opacity-50"
                                            />
                                            <label htmlFor={`edit-group-description-${group.id}`} className="mt-3 text-[11.5px] font-semibold text-ink">그룹 설명 <span className="font-normal text-ink/60">(선택)</span></label>
                                            <textarea
                                                id={`edit-group-description-${group.id}`}
                                                value={editDescription}
                                                onChange={(event) => setEditDescription(event.target.value)}
                                                disabled={updating}
                                                maxLength={500}
                                                rows={2}
                                                className="mt-1 w-full resize-y rounded-lg border border-line px-2.5 py-2 text-[12px] focus:outline-none focus:border-brand disabled:opacity-50"
                                            />
                                            {updateError && <p role="alert" className="mt-2 break-words text-[11.5px] text-danger">{updateError}</p>}
                                            <div className="mt-3 flex justify-end gap-2">
                                                <button type="button" onClick={stopEditing} disabled={updating} className="h-8 rounded-lg px-2 text-[11.5px] font-semibold text-ink/70 hover:bg-surface disabled:opacity-50">취소</button>
                                                <button type="submit" disabled={updating || !editName.trim()} className="h-8 rounded-lg bg-brand px-3 text-[11.5px] font-bold text-white hover:bg-brand-hover disabled:opacity-50">{updating ? '저장 중…' : '저장'}</button>
                                            </div>
                                        </form>
                                    ) : (
                                        <>
                                            <div className="flex items-start gap-2">
                                                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-brand-pale text-brand"><FolderIcon /></span>
                                                <span className="ml-auto rounded-full bg-chip px-2.5 py-1 text-[11px] font-semibold tabular-nums text-ink/70">파일 {group.file_count.toLocaleString('ko-KR')}개</span>
                                                <button
                                                    type="button"
                                                    onClick={() => startEditing(group)}
                                                    disabled={updating}
                                                    aria-label={`${group.name} 그룹 정보 수정`}
                                                    className="rounded-lg px-2 py-1 text-[11.5px] font-semibold text-ink/70 hover:bg-surface hover:text-brand-hover focus-visible:outline-2 focus-visible:outline-brand disabled:opacity-50"
                                                >
                                                    수정
                                                </button>
                                            </div>
                                            <button
                                                type="button"
                                                onClick={() => onOpenGroup(group.id)}
                                                aria-label={`${group.name} 그룹 열기, 파일 ${group.file_count}개`}
                                                className="mt-3 flex flex-1 flex-col rounded-lg text-left hover:text-brand-hover focus-visible:outline-2 focus-visible:outline-brand"
                                            >
                                                <h3 className="break-words text-[14px] font-bold text-ink">{group.name}</h3>
                                                <p className="mt-1 line-clamp-2 break-words text-[12px] leading-relaxed text-ink/70">
                                                    {group.description || '그룹에 대한 설명을 추가해 주세요.'}
                                                </p>
                                                <span className="mt-auto pt-4 text-[12px] font-semibold text-brand-hover">파일 관리하기 <span aria-hidden="true">→</span></span>
                                            </button>
                                        </>
                                    )}
                                </li>
                            ))}
                        </ul>
                    ) : !error && (
                        <div className="mt-4 rounded-2xl border border-dashed border-line bg-surface px-5 py-10 text-center">
                            <span className="mx-auto flex h-11 w-11 items-center justify-center rounded-xl bg-brand-pale text-brand"><FolderIcon className="h-6 w-6" /></span>
                            <p className="mt-3 text-[14px] font-bold text-ink">아직 문서 그룹이 없습니다.</p>
                            <p className="mt-1 text-[12px] leading-relaxed text-ink/70">그룹을 만들고 관련 파일을 등록해 보세요.</p>
                            {!formOpen && (
                                <button type="button" onClick={() => setFormOpen(true)} className="mt-4 text-[12px] font-bold text-brand-hover hover:underline focus-visible:outline-2 focus-visible:outline-brand">
                                    첫 문서 그룹 만들기 →
                                </button>
                            )}
                        </div>
                    )}
                </section>

                {ungroupedCount > 0 && (
                    <section aria-labelledby="ungrouped-title" className="mt-8 border-t border-divide pt-6">
                        <h2 id="ungrouped-title" className="text-[14px] font-bold text-ink">분류할 파일</h2>
                        <button
                            type="button"
                            onClick={onOpenUngrouped}
                            className="mt-3 flex w-full items-center gap-3 rounded-xl border border-line bg-surface px-4 py-3 text-left transition-colors hover:border-brand/60 hover:bg-brand-tint focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand"
                        >
                            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-warn-soft text-warn"><FolderIcon /></span>
                            <span className="min-w-0 flex-1">
                                <span className="block text-[13px] font-bold text-ink">미분류 파일 <span className="font-semibold tabular-nums text-warn">{ungroupedCount.toLocaleString('ko-KR')}</span></span>
                                <span className="mt-0.5 block text-[12px] leading-relaxed text-ink/70">기존 파일을 확인하고 문서 그룹으로 옮기세요.</span>
                            </span>
                            <span aria-hidden="true" className="shrink-0 text-brand-hover">→</span>
                        </button>
                    </section>
                )}
            </div>
        </div>
    );
}
