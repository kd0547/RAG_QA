import { useEffect, useState } from 'react';
import { AppHeader } from '../components/AppHeader';
import { CheckIcon, DocumentIcon, TrashIcon } from '../components/icons';
import { ApiError } from '../lib/http';
import { promptApi, type Prompt, type PromptInput } from './api';

// 백엔드 app/routers/prompt.py 와 같은 상한
const MAX_NAME_LENGTH = 100;
const MAX_CONTENT_LENGTH = 20_000;
const EMPTY_DRAFT: PromptInput = { name: '', content: '' };

type ActiveId = number | 'new' | null;

function errorMessage(e: unknown, fallback: string): string {
    if (e instanceof ApiError) return e.status === 0 ? '서버에 연결하지 못했습니다.' : e.message;
    return fallback;
}

function formatDate(value: string): string {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '';
    return new Intl.DateTimeFormat('ko-KR', { dateStyle: 'medium', timeStyle: 'short' }).format(date);
}

/** 선택된 프롬프트를 먼저 연다. 없으면 첫 번째. */
function initialId(prompts: Prompt[]): ActiveId {
    return (prompts.find((p) => p.is_selected) ?? prompts[0])?.id ?? null;
}

export function PromptSection() {
    const [prompts, setPrompts] = useState<Prompt[] | null>(null);
    const [loadError, setLoadError] = useState('');
    const [activeId, setActiveId] = useState<ActiveId>(null);
    const [draft, setDraft] = useState<PromptInput>(EMPTY_DRAFT);
    const [busy, setBusy] = useState<'save' | 'delete' | 'select' | null>(null);
    const [notice, setNotice] = useState('');
    const [error, setError] = useState('');

    const active = typeof activeId === 'number' ? prompts?.find((p) => p.id === activeId) : undefined;
    const isNew = activeId === 'new';
    const base: PromptInput = active ? { name: active.name, content: active.content } : EMPTY_DRAFT;
    const dirty = draft.name !== base.name || draft.content !== base.content;
    const trimmedName = draft.name.trim();
    const canSave = dirty && Boolean(trimmedName) && Boolean(draft.content.trim()) && !busy;
    const defaultPrompt = prompts?.find((p) => p.is_default);

    function open(id: ActiveId, list: Prompt[] | null = prompts) {
        const target = typeof id === 'number' ? list?.find((p) => p.id === id) : undefined;
        setActiveId(id);
        setDraft(target ? { name: target.name, content: target.content } : EMPTY_DRAFT);
    }

    function clearMessages() {
        setNotice('');
        setError('');
    }

    async function load() {
        setLoadError('');
        try {
            const list = await promptApi.list();
            setPrompts(list);
            return list;
        } catch (e) {
            setLoadError(errorMessage(e, '프롬프트 목록을 불러오지 못했습니다.'));
            return null;
        }
    }

    useEffect(() => {
        // 마운트 시 한 번만 불러온다. 화면을 빨리 떠나면 늦게 온 응답은 버린다.
        let cancelled = false;
        promptApi.list()
            .then((list) => {
                if (cancelled) return;
                setPrompts(list);
                open(initialId(list), list);
            })
            .catch((e) => { if (!cancelled) setLoadError(errorMessage(e, '프롬프트 목록을 불러오지 못했습니다.')); });
        return () => { cancelled = true; };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    /** 저장하지 않은 변경이 있으면 버릴지 묻는다 */
    function confirmDiscard(): boolean {
        return !dirty || window.confirm('저장하지 않은 변경 사항이 있습니다. 버리고 이동할까요?');
    }

    function switchTo(id: ActiveId) {
        if (id === activeId || !confirmDiscard()) return;
        open(id);
        clearMessages();
    }

    function updateDraft(patch: Partial<PromptInput>) {
        setDraft((current) => ({ ...current, ...patch }));
        clearMessages();
    }

    async function save() {
        if (!canSave) return;
        setBusy('save');
        clearMessages();
        const input = { name: trimmedName, content: draft.content };
        try {
            const saved = isNew || !active
                ? await promptApi.create(input)
                : await promptApi.update(active.id, input);
            setPrompts((list) => {
                const rest = (list ?? []).filter((p) => p.id !== saved.id);
                return [...rest, saved].sort((a, b) => a.id - b.id);
            });
            setActiveId(saved.id);
            setDraft({ name: saved.name, content: saved.content });
            setNotice(isNew ? `'${saved.name}' 프롬프트를 추가했습니다.` : '저장했습니다.');
        } catch (e) {
            setError(errorMessage(e, '저장하지 못했습니다.'));
        } finally {
            setBusy(null);
        }
    }

    async function remove() {
        if (!active || active.is_default || busy) return;
        const extra = active.is_selected ? '\n지금 사용 중인 프롬프트라서 삭제하면 기본 프롬프트를 사용합니다.' : '';
        if (!window.confirm(`'${active.name}' 프롬프트를 삭제할까요?${extra}`)) return;
        setBusy('delete');
        clearMessages();
        try {
            await promptApi.remove(active.id);
            // 선택된 프롬프트를 지우면 서버가 기본 프롬프트를 선택하므로 목록을 다시 받는다
            const list = await load();
            if (list) open(initialId(list), list);
            setNotice(`'${active.name}' 프롬프트를 삭제했습니다.`);
        } catch (e) {
            setError(errorMessage(e, '삭제하지 못했습니다.'));
        } finally {
            setBusy(null);
        }
    }

    async function select() {
        if (!active || active.is_selected || dirty || busy) return;
        setBusy('select');
        clearMessages();
        try {
            const selected = await promptApi.select(active.id);
            setPrompts((list) => (list ?? []).map((p) => (
                p.id === selected.id ? selected : { ...p, is_selected: false }
            )));
            setNotice(`이제 '${selected.name}' 프롬프트로 답변을 만듭니다.`);
        } catch (e) {
            setError(errorMessage(e, '프롬프트를 사용하도록 바꾸지 못했습니다.'));
        } finally {
            setBusy(null);
        }
    }

    function statusText(p: Prompt): string {
        if (typeof activeId === 'number' && p.id === activeId && dirty) return '저장하지 않은 변경';
        return [p.is_selected && '사용 중', p.is_default && '기본'].filter(Boolean).join(' · ') || formatDate(p.updated_at);
    }

    const title = isNew ? '새 프롬프트' : active?.name ?? '프롬프트';

    return (
        <div className="min-h-screen md:h-dvh md:overflow-hidden bg-white text-ink font-sans antialiased flex flex-col">
            <AppHeader current="prompt">
                <span className="hidden sm:block text-[12px] text-muted truncate">프롬프트 설정</span>
            </AppHeader>

            <div className="flex-1 min-h-0 flex flex-col md:flex-row">
                <aside className="md:w-[260px] lg:w-[280px] shrink-0 border-b md:border-b-0 md:border-r border-divide p-4 md:p-5 md:overflow-y-auto">
                    <h1 className="text-[16px] font-bold">프롬프트</h1>
                    <p className="mt-1 text-[12px] leading-5 text-muted">사용 중인 프롬프트가 문서 질의응답과 메일 답변에 함께 적용됩니다.</p>
                    <button
                        type="button"
                        onClick={() => switchTo('new')}
                        disabled={prompts === null}
                        aria-pressed={isNew}
                        className={`mt-4 w-full h-9 rounded-lg border text-[12px] font-semibold transition-colors focus-visible:outline-2 focus-visible:outline-brand disabled:opacity-40 disabled:cursor-not-allowed ${isNew ? 'border-brand/25 bg-brand-tint text-brand-hover' : 'border-line hover:bg-chip'}`}
                    >
                        + 새 프롬프트
                    </button>

                    <nav aria-label="프롬프트 목록" className="mt-3 flex md:flex-col gap-2 overflow-x-auto md:overflow-visible">
                        {prompts === null && !loadError && <p className="text-[12px] text-muted px-1 py-2">불러오는 중…</p>}
                        {prompts?.map((p) => {
                            const isActive = activeId === p.id;
                            const changed = isActive && dirty;
                            return (
                                <button
                                    key={p.id}
                                    type="button"
                                    aria-pressed={isActive}
                                    onClick={() => switchTo(p.id)}
                                    className={`shrink-0 min-w-[180px] md:min-w-0 flex items-center gap-3 rounded-xl border p-3 text-left transition-colors focus-visible:outline-2 focus-visible:outline-brand ${isActive ? 'border-brand/25 bg-brand-tint' : 'border-transparent hover:bg-chip'}`}
                                >
                                    <DocumentIcon className={`hidden sm:block w-5 h-5 shrink-0 ${isActive ? 'text-brand' : 'text-muted'}`} />
                                    <span className="min-w-0 flex-1">
                                        <span className="block text-[13px] font-semibold truncate">{p.name}</span>
                                        <span className={`block mt-0.5 text-[11px] truncate ${p.is_selected && !changed ? 'text-brand-hover font-semibold' : 'text-muted'}`}>
                                            {statusText(p)}
                                        </span>
                                    </span>
                                    {changed
                                        ? <span className="w-1.5 h-1.5 rounded-full bg-warn shrink-0" aria-hidden="true" />
                                        : p.is_selected && <CheckIcon className="w-3.5 h-3.5 shrink-0 text-brand" />}
                                </button>
                            );
                        })}
                    </nav>
                </aside>

                <main className="flex-1 min-w-0 md:overflow-y-auto bg-surface px-4 py-6 sm:p-8 lg:p-10">
                    <div className="mx-auto max-w-[920px]">
                        {loadError ? (
                            <div role="alert" className="rounded-xl border border-danger/20 bg-danger-surface px-4 py-3 text-[13px] text-danger flex flex-wrap items-center justify-between gap-2">
                                <span>{loadError}</span>
                                <button
                                    type="button"
                                    onClick={async () => { const list = await load(); if (list) open(initialId(list), list); }}
                                    className="h-8 rounded-lg border border-danger/30 bg-white px-3 text-[12px] font-semibold hover:bg-danger-soft focus-visible:outline-2 focus-visible:outline-danger"
                                >
                                    다시 시도
                                </button>
                            </div>
                        ) : prompts === null ? (
                            <p className="text-[13px] text-muted">프롬프트를 불러오는 중…</p>
                        ) : activeId === null ? (
                            <p className="text-[13px] text-muted">왼쪽에서 프롬프트를 고르거나 새 프롬프트를 추가하세요.</p>
                        ) : (
                            <>
                                <div className="flex flex-wrap items-center gap-2">
                                    <h2 className="text-[22px] font-bold tracking-tight break-all">{title}</h2>
                                    {active?.is_selected && <span className="rounded-full bg-brand px-2 py-0.5 text-[10px] font-semibold text-white">사용 중</span>}
                                    {active?.is_default && <span className="rounded-full border border-line bg-white px-2 py-0.5 text-[10px] font-semibold text-muted">기본</span>}
                                </div>
                                <p className="mt-2 text-[13px] leading-6 text-muted">
                                    {isNew
                                        ? '이름과 내용을 입력해 저장한 뒤 "이 프롬프트 사용"을 누르면 답변에 적용됩니다.'
                                        : active?.is_default
                                            ? '서버가 처음 만든 기본 프롬프트입니다. 수정할 수 있지만 삭제할 수는 없습니다.'
                                            : `${active ? formatDate(active.updated_at) : ''} 저장`}
                                </p>

                                <section aria-label="프롬프트 편집" className="mt-6 overflow-hidden rounded-2xl border border-divide bg-white">
                                    <div className="border-b border-divide px-5 py-4">
                                        <label htmlFor="prompt-name" className="text-[13px] font-semibold">이름</label>
                                        <input
                                            id="prompt-name"
                                            value={draft.name}
                                            onChange={(e) => updateDraft({ name: e.target.value })}
                                            maxLength={MAX_NAME_LENGTH}
                                            placeholder="예: 친절한 답변용"
                                            className="mt-2 block h-10 w-full rounded-lg border border-line bg-white px-3 text-[13px] text-ink placeholder:text-muted focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand/10"
                                        />
                                    </div>
                                    <div className="flex flex-wrap items-center justify-between gap-2 border-b border-divide px-5 py-4">
                                        <label htmlFor="prompt-content" className="text-[13px] font-semibold">프롬프트 내용</label>
                                        {isNew && defaultPrompt && (
                                            <button
                                                type="button"
                                                onClick={() => updateDraft({ content: defaultPrompt.content })}
                                                disabled={Boolean(draft.content.trim())}
                                                className="rounded-md text-[12px] font-medium text-brand-hover hover:underline disabled:text-muted disabled:no-underline disabled:cursor-not-allowed focus-visible:outline-2 focus-visible:outline-brand"
                                            >
                                                기본 프롬프트 불러오기
                                            </button>
                                        )}
                                    </div>
                                    <div className="p-4 sm:p-5">
                                        <textarea
                                            id="prompt-content"
                                            value={draft.content}
                                            onChange={(e) => updateDraft({ content: e.target.value })}
                                            maxLength={MAX_CONTENT_LENGTH}
                                            placeholder="역할, 답변 기준, 말투, 출력 형식 등을 자유롭게 입력하세요."
                                            aria-describedby="prompt-help"
                                            spellCheck={false}
                                            className="block min-h-[320px] md:min-h-[380px] w-full resize-y rounded-xl border border-line bg-white p-4 text-[13px] leading-7 text-ink placeholder:text-muted focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand/10"
                                        />
                                        <div className="mt-3 flex flex-wrap items-start justify-between gap-2 text-[11px] text-muted">
                                            <p id="prompt-help" className="leading-5">
                                                <code className="rounded bg-chip px-1 py-0.5 text-ink">$aliases</code> 자리에는 용어 별칭 목록이 들어갑니다. 지우면 별칭이 모델에 전달되지 않습니다.
                                            </p>
                                            <span className="tabular-nums shrink-0">
                                                {draft.content.length.toLocaleString('ko-KR')} / {MAX_CONTENT_LENGTH.toLocaleString('ko-KR')}자
                                            </span>
                                        </div>
                                    </div>
                                    <div className="flex flex-wrap items-center justify-between gap-3 border-t border-divide px-5 py-4">
                                        <div className="flex items-center gap-2">
                                            {active && (
                                                <button
                                                    type="button"
                                                    onClick={remove}
                                                    disabled={active.is_default || Boolean(busy)}
                                                    title={active.is_default ? '기본 프롬프트는 삭제할 수 없습니다' : undefined}
                                                    className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-line px-3.5 text-[12px] font-semibold text-danger hover:bg-danger-surface disabled:opacity-40 disabled:cursor-not-allowed focus-visible:outline-2 focus-visible:outline-danger"
                                                >
                                                    <TrashIcon />{busy === 'delete' ? '삭제 중…' : '삭제'}
                                                </button>
                                            )}
                                            {active && (
                                                <button
                                                    type="button"
                                                    onClick={select}
                                                    disabled={active.is_selected || dirty || Boolean(busy)}
                                                    title={dirty ? '변경 사항을 저장한 뒤 사용할 수 있습니다' : undefined}
                                                    className="h-9 rounded-lg border border-brand/30 px-3.5 text-[12px] font-semibold text-brand-hover hover:bg-brand-tint disabled:opacity-40 disabled:cursor-not-allowed focus-visible:outline-2 focus-visible:outline-brand"
                                                >
                                                    {active.is_selected ? '사용 중' : busy === 'select' ? '바꾸는 중…' : '이 프롬프트 사용'}
                                                </button>
                                            )}
                                        </div>
                                        <div className="flex items-center gap-2">
                                            <button
                                                type="button"
                                                disabled={!dirty || Boolean(busy)}
                                                onClick={() => { setDraft(base); clearMessages(); }}
                                                className="h-9 rounded-lg border border-line px-3.5 text-[12px] font-semibold hover:bg-chip disabled:opacity-40 disabled:cursor-not-allowed focus-visible:outline-2 focus-visible:outline-brand"
                                            >
                                                변경 취소
                                            </button>
                                            <button
                                                type="button"
                                                disabled={!canSave}
                                                onClick={save}
                                                className="inline-flex h-9 items-center gap-1.5 rounded-lg bg-brand px-4 text-[12px] font-semibold text-white hover:bg-brand-hover disabled:opacity-40 disabled:cursor-not-allowed focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand"
                                            >
                                                <CheckIcon />{busy === 'save' ? '저장 중…' : isNew ? '추가' : '저장'}
                                            </button>
                                        </div>
                                    </div>
                                </section>
                                {dirty && (!trimmedName || !draft.content.trim()) && (
                                    <p className="mt-3 text-[12px] text-muted">이름과 내용을 모두 입력해야 저장할 수 있습니다.</p>
                                )}
                                <p role="status" className="mt-3 min-h-5 text-[12px] text-brand-hover">{notice}</p>
                                {error && <p role="alert" className="mt-1 text-[12px] text-danger">{error}</p>}
                            </>
                        )}
                    </div>
                </main>
            </div>
        </div>
    );
}
